"""
SDI Intelligence — AM CRM tracker connector (ChatGPT / Claude app).

A Model Context Protocol (MCP) server that lets a voice assistant Nick
already uses - ChatGPT, or the Claude app - read and change his tracker
through the SAME code the AM CRM web app uses (voicecrm.py): the owner check,
the writers list, formula and locked columns, the read-back, the version check
before every save, save-once, and the journal. The assistant only ever asks;
this server decides.

    look up   get_records      the owner's records, read as the signed-in person
    propose   propose_changes  checks and read-back, saves nothing
    confirm   confirm_changes  saves only on a plain yes, once, journalled
    history   recent_changes   what was proposed and what happened (writers only)

Each also shows a card in the conversation (connector_cards.py).

Who is calling: every request carries a Microsoft Entra access token for this
API (scope tracker.access), obtained when the person connected the app and
signed in with their SDI account and MFA. It is checked here - signature,
tenant, audience, scope and (optionally) which client app asked for it - and
then exchanged on-behalf-of for a Microsoft Graph token, so SharePoint is read
and written with that person's own rights, exactly as in the web app.

OFF unless SDI_CONNECTOR_ENABLED=yes. Runs as its own small service beside the
main app (default port 8073), published through Entra Application Proxy with
pass-through pre-authentication, because the caller is ChatGPT's or Claude's
cloud presenting a token rather than a browser with a cookie. See
CONNECTOR_SETUP.md.
"""
from __future__ import annotations

import asyncio
import os
import re
import threading
import time
from datetime import date

import config  # noqa: F401  (loads .env before the modules below read it)
import auth
import voicecrm
import connector_cards as cards

import jwt
import uvicorn
from mcp.server.apps import Apps
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field


def _opt(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


ENABLED = _opt("SDI_CONNECTOR_ENABLED", "no").lower() in ("1", "yes", "true", "on")
HOST = _opt("SDI_CONNECTOR_HOST", "0.0.0.0")
PORT = int(_opt("SDI_CONNECTOR_PORT", "8073") or 8073)
# The address ChatGPT / Claude use, e.g. https://sdi-tracker-sdidisplays.msappproxy.net/mcp
PUBLIC_URL = _opt("SDI_CONNECTOR_URL").rstrip("/")
SCOPE = _opt("SDI_CONNECTOR_SCOPE", "tracker.access")
# Optional: only tokens requested by these client apps (the "SDI Tracker for
# ChatGPT" / "for Claude" registrations), by application (client) id.
CLIENTS = {c.strip().lower() for c in _opt("SDI_CONNECTOR_CLIENTS").split(",") if c.strip()}
TENANT = auth.TENANT_ID
API_ID = auth.CLIENT_ID                   # the SDI Intelligence app exposes the scope
AUDIENCES = [a for a in (API_ID, f"api://{API_ID}" if API_ID else "",
                         _opt("SDI_CONNECTOR_AUDIENCE")) if a]
ISSUERS = [f"https://login.microsoftonline.com/{TENANT}/v2.0", f"https://sts.windows.net/{TENANT}/"]
JWKS_URL = _opt("SDI_CONNECTOR_JWKS_URL",
                f"https://login.microsoftonline.com/{TENANT}/discovery/v2.0/keys")


# ── Who is calling ────────────────────────────────────────────────────────────
class EntraTokenVerifier:
    """Accepts only Entra access tokens issued by SDI's tenant for this API,
    carrying the tracker scope. Anything else is refused before a tool runs."""

    def __init__(self):
        self._jwks = jwt.PyJWKClient(JWKS_URL, cache_keys=True, lifespan=3600)

    def _check(self, token: str) -> AccessToken | None:
        try:
            key = self._jwks.get_signing_key_from_jwt(token).key
            claims = jwt.decode(token, key, algorithms=["RS256"], audience=AUDIENCES,
                                options={"require": ["exp", "iss", "aud"]})
        except Exception as exc:                          # noqa: BLE001 - any doubt is a refusal
            print(f"[connector.auth] refused: {type(exc).__name__}: {str(exc)[:160]}", flush=True)
            return None
        scopes = str(claims.get("scp", "")).split()
        client = str(claims.get("azp") or claims.get("appid") or "").lower()
        why = ("issuer" if claims.get("iss") not in ISSUERS else
               "tenant" if claims.get("tid") != TENANT else
               "scope" if SCOPE not in scopes else
               "client" if CLIENTS and client not in CLIENTS else
               "user" if not claims.get("oid") else "")
        if why:
            print(f"[connector.auth] refused: wrong {why} (client={client})", flush=True)
            return None
        return AccessToken(token=token, client_id=client, scopes=scopes,
                           expires_at=int(claims["exp"]), subject=claims["oid"],
                           claims={k: claims.get(k) for k in
                                   ("iss", "oid", "tid", "name", "preferred_username", "upn")})

    async def verify_token(self, token: str) -> AccessToken | None:
        return await asyncio.to_thread(self._check, token)


def _caller() -> tuple[dict, str]:
    """The signed-in person (shaped like a web-app user) and their API token."""
    tok = get_access_token()
    if tok is None:                                       # the auth middleware stops this first
        raise PermissionError("Not signed in.")
    c = tok.claims or {}
    email = c.get("preferred_username") or c.get("upn") or ""
    return {"name": c.get("name") or email, "email": email, "oid": c.get("oid", ""),
            "tid": c.get("tid", ""), "kind": "user"}, tok.token


_obo_lock = threading.Lock()
_obo_app = None


def _graph_token(api_token: str) -> str | None:
    """This person's Microsoft Graph token, on behalf of the token ChatGPT /
    Claude presented: the same delegated scopes and SharePoint rights the web
    app's sign-in has. MSAL caches it until it nears expiry."""
    global _obo_app
    with _obo_lock:
        if _obo_app is None:
            _obo_app = auth._msal_app()
        result = _obo_app.acquire_token_on_behalf_of(api_token, scopes=auth.GRAPH_SCOPES)
    if "access_token" not in result:
        print(f"[connector.obo] no Graph token: {result.get('error')}: "
              f"{str(result.get('error_description', ''))[:200]}", flush=True)
        return None
    return result["access_token"]


# ── The tracker, as the connector shows it ────────────────────────────────────
_DATE_LIKE = re.compile(r"^(\d{4}-\d{1,2}-\d{1,2}|\d{1,2}/\d{1,2}/\d{4})$")
_COLUMNS: dict[str, tuple[float, list[str]]] = {}         # oid -> (when, sheet headers)


def _iso(value) -> str:
    """A cell's date as YYYY-MM-DD (the sheet shows dates month-first), or ""."""
    text = str(value or "").strip()
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", text)
    if m:
        y, mo, d = (int(g) for g in m.groups())
    else:
        m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", text)
        if not m:
            return ""
        mo, d, y = (int(g) for g in m.groups())
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return ""


def _record(item: dict) -> dict:
    f = item.get("fields", {}) or {}
    row = {"id": str(item.get("id", "")), "name": voicecrm._project_ref(f)}
    for k, v in f.items():
        if v in (None, "") or k.startswith("_") or voicecrm._protected(k) and k != voicecrm.OWNER_FIELD:
            continue
        # Whole cells, never shortened: "add to the next steps" sends the old
        # text back with the new words, so a cut-off cell would lose its end.
        text = str(v)
        row[k] = text
        if _DATE_LIKE.match(text.strip()):
            row[f"{k} (spoken)"] = voicecrm._spoken_value(text)
    row["_due_iso"] = _iso(f.get("KEY DATES FOR NEXT STEPS"))
    return row


def _field_for(user: dict, raw: str) -> str:
    """The sheet's own spelling of a column the assistant named."""
    cols = _COLUMNS.get(user["oid"], (0, []))[1]
    return voicecrm._canonical_field(raw, cols or None)


_NO = re.compile(r"\b(no|nope|not|never|cancel|stop|don'?t|do not|wrong|incorrect|wait|hold on|later)\b")
_YES = re.compile(r"^(?:(?:uh|um|er|oh|ok|okay)\s+)*(?:yes|yeah|yep|yup|correct|confirm|go ahead|do it|"
                  r"write it|save it)(?:\s+(?:please|thanks|thank you|go ahead|do it|save it|write it|"
                  r"that'?s right))?$")


def plain_yes(reply: str) -> bool:
    """The web app's rule: a yes only when the whole reply is a plain yes, and
    any refusal word wins ("no, don't do it" is a no)."""
    n = re.sub(r"\s+", " ", re.sub(r"[^a-z' ]+", " ", str(reply or "").lower().replace("’", "'"))).strip()
    return 0 < len(n.split()) <= 6 and not _NO.search(n) and bool(_YES.match(n))


def _timed(tool: str, started: float, user: dict, note: str = "") -> None:
    print(f"[connector] tool={tool} user={user.get('email', '')} "
          f"secs={time.monotonic() - started:.1f} {note}", flush=True)


INSTRUCTIONS = """You are connected to SDI's account tracker: the account manager's
own project records (client, job, status, next steps and dates, commercial
status, confidence, value). Changes are limited to named people; others can
only ask.

Looking things up: call get_records, with a search word when the person names a
client or job. Speech recognition misspells names, so match by sound ("barber"
is Barbour, "the perfume shop" is TPS). Answer from what it returns in short
spoken sentences, leading with what's overdue, due soonest, at risk or highest
value. Never invent values. Dates have a "(spoken)" form; use it.

Changing things - always in this order, never skipping a step:
1. Call propose_changes with every change the person asked for (several in one
   sentence go in one call). It saves nothing. Dates as YYYY-MM-DD, amounts as
   plain numbers; to add to text such as NEXT STEPS, send the old text plus the
   new words.
2. Read its read_back to the person, word for word, and ask if it's right.
3. Wait for their answer. Then call confirm_changes with the proposal_id and
   their reply exactly as they said it. Only a plain yes saves; anything else
   cancels. Never call confirm_changes before they have answered, never answer
   for them, and never say something is saved unless confirm_changes says so.
4. Tell them what confirm_changes reports, including anything not saved.
If they correct something, start again at step 1."""

apps = Apps()
UI_RECORDS, UI_CHANGE, UI_RECENT = "ui://sdi/records.html", "ui://sdi/change.html", "ui://sdi/recent.html"
READS = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)
SAVES = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True,
                        open_world_hint=False)


def _ui(uri: str, working: str, done: str) -> dict:
    return {"openai/outputTemplate": uri, "openai/widgetAccessible": True,
            "openai/toolInvocation/invoking": working, "openai/toolInvocation/invoked": done}


class Change(BaseModel):
    record_id: str = Field(description="The record's id from get_records")
    field: str = Field(description="Column to change, spelled as in get_records")
    new_value: str = Field(description="New value. Amounts as plain numbers (15500); dates as YYYY-MM-DD; "
                                       "to add to text, send the old text plus the new words")


@apps.tool(resource_uri=UI_RECORDS, meta=_ui(UI_RECORDS, "Checking the tracker…", "Checked the tracker"),
           annotations=READS,
           description="Look up the account manager's tracker records. Leave search empty for all of "
                       "them, or give a client, business unit or job word. Each record has its id, its "
                       "name and its filled-in columns; dates come with a spoken form.")
def get_records(search: str = "") -> dict:
    started = time.monotonic()
    user, api = _caller()
    token = _graph_token(api)
    if not token:
        return {"state": "no_token", "records": [],
                "detail": "Couldn't reach the tracker as you. Reconnect SDI Tracker and sign in again."}
    data = voicecrm.records_for(token)
    if data.get("state") != "ok":
        _timed("get_records", started, user, f"state={data.get('state')}")
        return {"state": data.get("state"), "records": [], "detail": str(data.get("detail", ""))[:300]}
    _COLUMNS[user["oid"]] = (time.time(), list(data.get("columns") or []))
    rows = [_record(i) for i in data["items"]]
    words = [w for w in re.findall(r"[a-z0-9]+", search.lower()) if len(w) > 1]
    found = [r for r in rows if not words or
             any(w in " ".join(str(v) for v in r.values()).lower() for w in words)]
    note = ""
    if words and not found:                     # a misheard name: give everything, match by sound
        found, note = rows, "No record matched that word; these are all the records. Match by sound."
    _timed("get_records", started, user, f"search={search!r} n={len(found)}")
    return {"state": "ok", "today": voicecrm._spoken_value(date.today().isoformat()),
            "today_iso": date.today().isoformat(), "count": len(found), "records": found, "note": note}


@apps.tool(resource_uri=UI_CHANGE, meta=_ui(UI_CHANGE, "Preparing the read-back…", "Read-back ready"),
           annotations=READS,
           description="Prepare one or more changes and get the read-back. SAVES NOTHING. Read the "
                       "read_back to the person and wait for their answer before confirm_changes.")
def propose_changes(changes: list[Change]) -> dict:
    started = time.monotonic()
    user, api = _caller()
    token_box: dict = {}

    def get_token():                            # one on-behalf-of exchange for the whole call
        if "t" not in token_box:
            token_box["t"] = _graph_token(api)
        return token_box["t"]

    pids, items, lines, problems = [], [], [], []
    for c in changes[:8]:
        field = _field_for(user, c.field)
        r = voicecrm.propose_change(user, get_token, c.record_id, field, c.new_value, source="connector")
        if r.get("state") != "proposed":
            if r.get("state") in ("not_a_writer", "writes_disabled", "not_approved", "not_configured",
                                  "no_token"):
                _timed("propose_changes", started, user, f"refused={r.get('state')}")
                return {"state": "nothing_to_save", "problems": [str(r.get("detail", r.get("state")))]}
            problems.append(f"{c.field}: {r.get('detail') or r.get('state')}")
            continue
        pids.append(r["proposal_id"])
        name = r["project_ref"] or f"record {r['item_id']}"
        items.append({"name": name, "field": r["field"],
                      "old_spoken": r["old_spoken"] or "blank", "new_spoken": r["new_spoken"]})
        lines.append(f"{name}: {r['field']} from {r['old_spoken'] or 'blank'} to {r['new_spoken']}")
    if not pids:
        _timed("propose_changes", started, user, "nothing to propose")
        return {"state": "nothing_to_save", "problems": problems}
    read_back = (("One change. " if len(pids) == 1 else f"{len(pids)} changes. ")
                 + ". ".join(lines) + ". Shall I save " + ("it?" if len(pids) == 1 else "them?"))
    _timed("propose_changes", started, user, f"n={len(pids)} problems={len(problems)}")
    # The journal holds each proposal; the id given back names them all, so a
    # confirm still works after a restart and only the proposer can use it.
    return {"state": "awaiting_yes", "proposal_id": "+".join(pids), "read_back": read_back,
            "items": items, "not_included": problems, "saved": False}


@apps.tool(resource_uri=UI_CHANGE, meta=_ui(UI_CHANGE, "Saving…", "Done"), annotations=SAVES,
           description="Save a proposal ONLY after the person has heard its read_back and answered. "
                       "Pass their reply exactly as they said it; only a plain yes saves.")
def confirm_changes(proposal_id: str, user_reply: str) -> dict:
    started = time.monotonic()
    user, api = _caller()
    pids = [p for p in re.split(r"[+,\s]+", proposal_id or "") if re.fullmatch(r"[0-9a-f]{32}", p)][:8]
    if not pids:
        return {"state": "unknown_proposal", "saved": False,
                "detail": "No such proposal. Propose the changes again."}
    yes = plain_yes(user_reply)
    token_box: dict = {}

    def get_token():
        if "t" not in token_box:
            token_box["t"] = _graph_token(api)
        return token_box["t"]

    saved, not_saved, states, repeat = [], [], [], False
    for pid in pids:
        r = voicecrm.confirm_change(user, get_token, pid, yes)
        state = r.get("state")
        repeat = repeat or bool(r.get("already_resolved"))
        if state == "applied" and not r.get("already_resolved"):
            saved.append(f"{r['project_ref']}: {r['field']} is now {r['new_spoken']}")
        elif r.get("already_resolved"):
            entry = voicecrm._journal.get(pid) or {}
            if entry.get("state") == "applied":
                state = "applied"
                saved.append(f"{entry.get('project_ref')}: {entry.get('field')} is now "
                             f"{voicecrm._spoken_value(entry.get('new_value'))}")
            else:
                state = entry.get("state") or state
                not_saved.append(f"{entry.get('project_ref', '')}: {entry.get('field', '')} not saved"
                                 f" ({entry.get('outcome') or state})")
        elif state != "declined":
            entry = voicecrm._journal.get(pid) or {}
            not_saved.append(f"{entry.get('project_ref') or ''}: {entry.get('field') or ''} not saved, "
                             f"{str(r.get('detail') or state).rstrip('.')}.".lstrip(": "))
        states.append(state)
    if not yes:
        out = {"state": "declined", "saved": False,
               "detail": f"Not saved: '{user_reply}' is not a plain yes."}
    else:
        overall = ("saved" if saved and not not_saved else "partly_saved" if saved else
                   "conflict" if "conflict" in states else "failed")
        out = {"state": overall, "saved": bool(saved), "saved_lines": saved, "not_saved": not_saved}
    if repeat:
        out["repeat"] = True
    _timed("confirm_changes", started, user, f"{out['state']} n={len(pids)} reply={user_reply[:40]!r}")
    return out


_LABEL = {"applied": "saved", "conflict": "conflict", "expired": "expired", "proposed": "proposed"}


@apps.tool(resource_uri=UI_RECENT, meta=_ui(UI_RECENT, "Checking recent activity…", "Recent activity"),
           annotations=READS,
           description="What has been proposed, saved, cancelled or refused recently, newest first. "
                       "Writers only.")
def recent_changes(limit: int = 10) -> dict:
    user, _ = _caller()
    if not voicecrm._may_write(user):
        return {"state": "not_a_writer", "entries": [],
                "detail": "Recent activity is for the people who can make changes."}
    out = []
    for e in voicecrm._journal.recent(max(1, min(int(limit or 10), 30))):
        outcome = e.get("outcome") or ""
        state = ("declined" if e["state"] == "failed" and outcome.startswith("Declined") else
                 _LABEL.get(e["state"], "conflict"))
        old, new = voicecrm._spoken_value(e.get("old_value")), voicecrm._spoken_value(e.get("new_value"))
        line = f"{e.get('project_ref') or e.get('item_id')}: {e['field']}"
        entry = {"proposal": e["proposal_id"], "state": state, "source": e.get("source") or "app",
                 "who": e.get("user_name", ""),
                 "when": time.strftime("%d %b %H:%M", time.localtime(e.get("applied") or e["created"])),
                 "lines": [f"{line} from {old or 'blank'} to {new or 'blank'}"]}
        if state == "saved":
            entry["saved_lines"] = [f"{line} is now {new or 'blank'}"]
        elif state not in ("proposed", "declined"):
            entry["reply"] = outcome[:120]
        out.append(entry)
    return {"state": "ok", "entries": out}


apps.add_html_resource(UI_RECORDS, cards.RECORDS_HTML, title="Records")
apps.add_html_resource(UI_CHANGE, cards.CHANGE_HTML, title="Read-back")
apps.add_html_resource(UI_RECENT, cards.RECENT_HTML, title="Recent activity")


def build_server() -> MCPServer:
    return MCPServer(
        name="SDI Tracker", instructions=INSTRUCTIONS, extensions=[apps],
        token_verifier=EntraTokenVerifier(),
        # Tells ChatGPT / Claude where to sign in (Entra) and which scope to ask
        # for; the token's audience is checked by the verifier above.
        auth=AuthSettings(issuer_url=ISSUERS[0], resource_server_url=PUBLIC_URL,
                          required_scopes=[SCOPE], validate_token_resource=False))


def build_app():
    problems = [n for n, v in (("SDI_CONNECTOR_URL", PUBLIC_URL), ("SDI_TENANT_ID", TENANT),
                               ("SDI_CLIENT_ID", API_ID), ("SDI_CLIENT_SECRET", auth.CLIENT_SECRET)) if not v]
    if problems:
        raise SystemExit("Connector not started - missing: " + ", ".join(problems))
    path = "/" + PUBLIC_URL.split("://", 1)[-1].split("/", 1)[-1] if "/" in PUBLIC_URL.split("://", 1)[-1] else "/mcp"
    return build_server().streamable_http_app(
        streamable_http_path=path, stateless_http=True, json_response=True, host=HOST,
        # Reached through App Proxy under its public name; the bearer token is
        # the lock, so the localhost-only Host check does not apply.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))


if __name__ == "__main__":
    if not ENABLED:
        raise SystemExit("The tracker connector is off. Set SDI_CONNECTOR_ENABLED=yes to start it.")
    print(f"[connector] starting on {HOST}:{PORT} for {PUBLIC_URL} (scope {SCOPE}; "
          f"writers {sorted(voicecrm.WRITERS)}; writes {'on' if voicecrm.WRITE_ENABLED else 'off'})", flush=True)
    uvicorn.run(build_app(), host=HOST, port=PORT)
