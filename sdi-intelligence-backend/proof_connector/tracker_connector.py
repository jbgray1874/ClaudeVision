"""AM CRM connector: two-day proof on MADE-UP data.

A Model Context Protocol (MCP) server that lets a voice assistant you already
use (ChatGPT, or the Claude app) look up and change records in a tracker, with
the same rules as the AM CRM web app: every change is read back, saved only on
a plain yes, checked against the record's version, saved once, and journalled.

Everything here is fictional and held in memory. It never touches SharePoint,
Microsoft Graph, Entra or the real tracker, and it forgets everything when it
restarts. Its only job is to find out how talking to the tracker through
ChatGPT's (or Claude's) own voice feels, and how long the pauses are.

Run:   pip install -r requirements.txt
       PROOF_KEY=<long random string> python tracker_connector.py
Then add  https://<host>/<PROOF_KEY>/mcp  as a connector (no authentication).
The key in the address is the only lock, which is acceptable for made-up data
and nothing else. A version for real data signs in through Entra instead.
"""
from __future__ import annotations

import os
import re
import secrets
import threading
import time
from datetime import date, timedelta

import uvicorn
from mcp.server.apps import Apps
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import HTMLResponse, PlainTextResponse
from starlette.routing import Route

import cards

KEY = os.getenv("PROOF_KEY", "").strip()
OWNER = "NG"
PROPOSAL_MINUTES = 15

# ── Made-up records ───────────────────────────────────────────────────────────
# Shaped like Nick's tracker (same columns), dated relative to today so "what's
# due this week" and "what's overdue" always have answers. Some names are
# deliberately awkward to hear (Castellano, Aldermoor, DX2041).
TODAY = date.today()
D = lambda days: (TODAY + timedelta(days=days)).isoformat()

COLUMNS = ["ACCOUNT", "BUSINESS UNIT", "OVERVIEW / DESCRIPTION / DELIVERABLES", "Status",
           "NEXT STEPS", "KEY DATES FOR NEXT STEPS", "START", "END", "Commercial Status",
           "Confidence to Order", "BUDGET COST", "Last Client Contact Date", "AM Owner", "PM Owner"]
LOCKED = {"AM Owner"}                                  # as in the web app: never changed by voice
MONEY = {"BUDGET COST"}
DATES = {"KEY DATES FOR NEXT STEPS", "START", "END", "Last Client Contact Date"}


def _r(rid, account, unit, job, status, nxt, key, start, end, commercial, conf, budget, contact, pm="JB"):
    return rid, dict(zip(COLUMNS, [account, unit, job, status, nxt, key, start, end, commercial,
                                   conf, budget, contact, OWNER, pm]))


RECORDS = dict([
    _r("r1", "NORTHWAY", "NORTHWAY MOBILE", "Digital Gatepost DX2041", "In production",
       "Confirm install slots with the store team", D(2), D(-30), D(9), "Ordered", "100%", "18500", D(-3)),
    _r("r2", "NORTHWAY", "NORTHWAY BANK", "Digital Gatepost, branch pilot", "Quoted",
       "Chase revised quote", D(-2), "", "", "Quoted", "60%", "42000", D(-16)),
    _r("r3", "NORTHWAY", "NORTHWAY EXPRESS", "Counter display refresh, 40 stores", "Awaiting PO",
       "Send artwork proofs", D(4), "", "", "Awaiting PO", "80%", "9800", D(-5)),
    _r("r4", "CASTELLANO", "CASTELLANO UK", "Always-on window unit SP2210", "In production",
       "Delivery booked", D(1), D(-45), D(3), "Ordered", "100%", "142000", D(-2)),
    _r("r5", "CASTELLANO", "CASTELLANO IRELAND", "Shelf-edge tables and graphic ends", "Delivered",
       "Raise invoice", D(-6), D(-60), D(-8), "Ordered", "100%", "15200", D(-9)),
    _r("r6", "KESTREL BEAUTY", "KESTREL STORES", "Fragrance tester gondola", "Design",
       "Prototype review with client", D(6), "", "", "Verbal / Likely", "70%", "27500", D(-1)),
    _r("r7", "ALDERMOOR", "ALDERMOOR GARDEN", "Seasonal bay kit, 120 sites", "On hold",
       "Client to confirm budget", D(-10), "", "", "On Hold", "30%", "64000", D(-21)),
    _r("r8", "THE CANDLE HOUSE", "TCH RETAIL", "H2 forecast and China prototypes", "Completed",
       "Await forecast sign-off", D(3), D(-90), D(-14), "Ordered", "100%", "38000", D(-4)),
    _r("r9", "BRIGHTWATER", "BRIGHTWATER HOMEWARE", "Cushion and throw rack, week 33", "Quoted",
       "Follow up on quote", D(-1), "", "", "At Risk", "40%", "12400", D(-18)),
    _r("r10", "BRIGHTWATER", "BRIGHTWATER KITCHEN", "Utensil wall, 25 stores", "Awaiting PO",
       "PO expected", D(5), "", "", "Awaiting PO", "90%", "21000", D(-2)),
    _r("r11", "HALDEN FOODS", "HALDEN CONVENIENCE", "Chiller header boards", "Survey",
       "Site survey Tuesday", D(8), "", "", "Quoted", "50%", "7600", D(-7)),
    _r("r12", "HALDEN FOODS", "HALDEN BAKERY", "Bread bay graphics refresh", "Quoted",
       "Price check against last year", D(12), "", "", "Quoted", "65%", "11300", D(-11)),
])
VERSION = {rid: 1 for rid in RECORDS}                  # bumped by every save
PROPOSALS: dict[str, dict] = {}
JOURNAL: list[dict] = []
LOCK = threading.Lock()

# ── Helpers (same rules as the web app) ───────────────────────────────────────
_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December")


def spoken(value: str) -> str:
    """Dates in words ("Monday 12 October") so a wrong day is easy to hear."""
    text = str(value or "").strip()
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", text)
    if not m:
        return text or "blank"
    try:
        when = date(*(int(g) for g in m.groups()))
    except ValueError:
        return text
    words = f"{_DAYS[when.weekday()]} {when.day} {_MONTHS[when.month - 1]}"
    return words if when.year == TODAY.year else f"{words} {when.year}"


def name(rid: str) -> str:
    """How a record is named aloud: business unit, then the job."""
    f = RECORDS[rid]
    unit = " ".join(w if len(w) <= 3 else w.title() for w in f["BUSINESS UNIT"].split())
    return f"{unit}, {f['OVERVIEW / DESCRIPTION / DELIVERABLES']}"


# A reply counts as yes only when the whole reply is a plain yes; any refusal
# word wins ("no, don't do it" is a no). The same rule as the web app.
_NO = re.compile(r"\b(no|nope|not|never|cancel|stop|don'?t|do not|wrong|incorrect|wait|hold on|later)\b")
_YES = re.compile(r"^(?:(?:uh|um|er|oh|ok|okay)\s+)*(?:yes|yeah|yep|yup|correct|confirm|go ahead|do it|"
                  r"write it|save it)(?:\s+(?:please|thanks|thank you|go ahead|do it|save it|write it|"
                  r"that'?s right))?$")


def plain_yes(reply: str) -> bool:
    n = re.sub(r"\s+", " ", re.sub(r"[^a-z' ]+", " ", str(reply or "").lower().replace("’", "'"))).strip()
    return len(n.split()) <= 6 and not _NO.search(n) and bool(_YES.match(n))


def field_named(raw: str) -> str | None:
    want = " ".join(str(raw or "").replace("_", " ").split()).lower()
    for c in COLUMNS:
        if c.lower() == want:
            return c
    return None


def clean_value(field: str, raw: str) -> tuple[str | None, str]:
    value = str(raw or "").strip()
    if field in MONEY:
        v = value.replace("£", "").replace(",", "").strip().lower()
        mult = 1000 if v.endswith("k") else 1
        try:
            n = float(v.rstrip("k")) * mult
        except ValueError:
            return None, f"{field} must be an amount in pounds, e.g. 15500."
        return (str(int(n)) if n == int(n) else f"{n:.2f}"), ""
    if field in DATES and value:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", value):
            return None, f"{field} must be a date written as YYYY-MM-DD."
        try:
            date.fromisoformat(value)
        except ValueError:
            return None, f"{value} is not a real date."
    return value, ""


def timed(tool: str, started: float, note: str = "") -> None:
    print(f"[proof] tool={tool} ms={(time.monotonic() - started) * 1000:.0f} {note}", flush=True)


# ── The connector ─────────────────────────────────────────────────────────────
INSTRUCTIONS = f"""You are connected to an account manager's project tracker (made-up
proof data). Today is {spoken(TODAY.isoformat())}.

Looking things up: call get_records, with a search word when the person names a
client or job; speech recognition misspells names, so match by sound ("castle
anno" is Castellano). Answer from what it returns, in short spoken sentences,
leading with what's overdue, due soonest, at risk or highest value. Never
invent values.

Changing things - always in this order, never skipping a step:
1. Call propose_changes with every change the person asked for. It saves nothing.
2. Read its read_back to the person, word for word, and ask if it's right.
3. Wait for their answer. Then call confirm_changes with the proposal_id and
   their reply exactly as they said it. Only a plain yes saves; anything else
   cancels. Never call confirm_changes before they have answered, never answer
   for them, and never say something is saved unless confirm_changes says so.
4. Tell them what confirm_changes reports, including anything not saved.
If they correct something, start again at step 1."""

# Each action shows one of three cards in the app (cards.py). The ui:// address
# is given twice: once for the MCP Apps standard (Claude and others, via
# Apps), once under ChatGPT's own key. widgetAccessible lets the Read-back
# card's Yes / No buttons call confirm_changes.
apps = Apps()
UI_RECORDS, UI_CHANGE, UI_RECENT = "ui://sdi/records.html", "ui://sdi/change.html", "ui://sdi/recent.html"


def ui(uri: str, working: str, done: str) -> dict:
    return {"openai/outputTemplate": uri, "openai/widgetAccessible": True,
            "openai/toolInvocation/invoking": working, "openai/toolInvocation/invoked": done}


# Marked so the apps know which actions only read (no approval prompt needed)
# and that the one save is safe to repeat: a second confirm never saves twice.
READS = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)
SAVES = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True,
                        open_world_hint=False)


class Change(BaseModel):
    record_id: str = Field(description="The record's id from get_records, e.g. r4")
    field: str = Field(description="Column to change, spelled as in get_records")
    new_value: str = Field(description="New value. Amounts as plain numbers (15500); dates as YYYY-MM-DD; "
                                       "to add to text, send the old text plus the new words")


@apps.tool(resource_uri=UI_RECORDS, meta=ui(UI_RECORDS, "Checking the tracker…", "Checked the tracker"),
           annotations=READS, description="Look up tracker records. Leave search empty for all of them, or give a client, "
                      "business unit or job word. Each record has its id, its name and every column; "
                      "dates come with a spoken form.")
def get_records(search: str = "") -> dict:
    started = time.monotonic()
    words = [w for w in re.findall(r"[a-z0-9]+", search.lower()) if len(w) > 1]
    out = []
    for rid, f in RECORDS.items():
        hay = " ".join(str(v) for v in f.values()).lower()
        if words and not any(w in hay for w in words):
            continue
        row = {"id": rid, "name": name(rid), **{k: v for k, v in f.items() if v}}
        for k in DATES:
            if f.get(k):
                row[f"{k} (spoken)"] = spoken(f[k])
        out.append(row)
    note = ""
    if words and not out:                  # a misheard name: give everything rather than nothing
        out = get_records("")["records"]
        note = "No record matched that word; these are all the records. Match by sound."
    timed("get_records", started, f"search={search!r} n={len(out)}")
    return {"today": spoken(TODAY.isoformat()), "today_iso": TODAY.isoformat(), "count": len(out),
            "records": out, "note": note}


@apps.tool(resource_uri=UI_CHANGE, meta=ui(UI_CHANGE, "Preparing the read-back…", "Read-back ready"),
           annotations=READS, description="Prepare one or more changes and get the read-back. SAVES NOTHING. Read the "
                      "read_back to the person and wait for their answer before confirm_changes.")
def propose_changes(changes: list[Change]) -> dict:
    started = time.monotonic()
    lines, ok, problems, items = [], [], [], []
    for c in changes[:8]:
        if c.record_id not in RECORDS:
            problems.append(f"There's no record {c.record_id}.")
            continue
        field = field_named(c.field)
        if not field or field in LOCKED:
            problems.append(f"{c.field} can't be changed from here.")
            continue
        if RECORDS[c.record_id]["AM Owner"] != OWNER:
            problems.append(f"{name(c.record_id)} belongs to another account manager.")
            continue
        value, why = clean_value(field, c.new_value)
        if value is None:
            problems.append(why)
            continue
        old = RECORDS[c.record_id].get(field, "")
        if old == value:
            problems.append(f"{field} on {name(c.record_id)} is already {spoken(value)}.")
            continue
        ok.append({"record_id": c.record_id, "field": field, "old": old, "new": value,
                   "version": VERSION[c.record_id]})
        items.append({"name": name(c.record_id), "field": field,
                      "old_spoken": spoken(old), "new_spoken": spoken(value)})
        lines.append(f"{name(c.record_id)}: {field} from {spoken(old)} to {spoken(value)}")
    if not ok:
        timed("propose_changes", started, "nothing to propose")
        return {"state": "nothing_to_save", "problems": problems}
    pid = "p" + secrets.token_hex(4)
    PROPOSALS[pid] = {"changes": ok, "created": time.time(), "outcome": None}
    read_back = (("One change. " if len(ok) == 1 else f"{len(ok)} changes. ")
                 + ". ".join(lines) + ". Shall I save " + ("it?" if len(ok) == 1 else "them?"))
    JOURNAL.append({"when": time.time(), "proposal": pid, "state": "proposed", "lines": lines})
    timed("propose_changes", started, f"{pid} n={len(ok)}")
    return {"state": "awaiting_yes", "proposal_id": pid, "read_back": read_back, "items": items,
            "not_included": problems, "saved": False}


@apps.tool(resource_uri=UI_CHANGE, meta=ui(UI_CHANGE, "Saving…", "Done"),
           annotations=SAVES, description="Save a proposal ONLY after the person has heard its read_back and answered. "
                      "Pass their reply exactly as they said it; only a plain yes saves.")
def confirm_changes(proposal_id: str, user_reply: str) -> dict:
    started = time.monotonic()
    with LOCK:
        p = PROPOSALS.get(proposal_id)
        if not p:
            return {"state": "unknown_proposal", "saved": False,
                    "detail": "No such proposal. Propose the changes again."}
        if p["outcome"]:                         # asked twice: same answer, never a second save
            timed("confirm_changes", started, f"{proposal_id} repeat")
            return {**p["outcome"], "repeat": True}
        if time.time() - p["created"] > PROPOSAL_MINUTES * 60:
            p["outcome"] = {"state": "expired", "saved": False,
                            "detail": "That proposal expired. Propose the changes again."}
        elif not plain_yes(user_reply):
            p["outcome"] = {"state": "declined", "saved": False,
                            "detail": f"Not saved: '{user_reply}' is not a plain yes."}
        else:
            saved, not_saved = [], []
            # Versions are checked for the whole proposal before anything is
            # saved, so two changes to one record in the same sentence don't
            # trip over each other; each record's version moves on once.
            changed = {c["record_id"] for c in p["changes"] if VERSION[c["record_id"]] != c["version"]}
            for c in p["changes"]:
                rid = c["record_id"]
                if rid in changed:
                    not_saved.append(f"{name(rid)}: {c['field']} not saved, the record changed "
                                     f"since the read-back.")
                    continue
                RECORDS[rid][c["field"]] = c["new"]
                saved.append(f"{name(rid)}: {c['field']} is now {spoken(c['new'])}")
            for rid in {c["record_id"] for c in p["changes"]} - changed:
                VERSION[rid] += 1
            p["outcome"] = {"state": "saved" if saved and not not_saved else "partly_saved" if saved else "conflict",
                            "saved": bool(saved), "saved_lines": saved, "not_saved": not_saved}
        JOURNAL.append({"when": time.time(), "proposal": proposal_id, "state": p["outcome"]["state"],
                        "reply": user_reply, "lines": p["outcome"].get("saved_lines", [])})
    timed("confirm_changes", started, f"{proposal_id} {p['outcome']['state']} reply={user_reply!r}")
    return p["outcome"]


@apps.tool(resource_uri=UI_RECENT, meta=ui(UI_RECENT, "Checking recent activity…", "Recent activity"),
           annotations=READS, description="What has been proposed, saved or declined recently, newest first.")
def recent_changes(limit: int = 10) -> dict:
    # One entry per proposal, as it stands now: what was proposed, its latest
    # outcome, and the reply that decided it. Newest first.
    latest: dict[str, dict] = {}
    for e in JOURNAL:
        cur = latest.setdefault(e["proposal"], {"proposal": e["proposal"], "lines": e["lines"],
                                                "state": e["state"], "when": e["when"]})
        if e["state"] != "proposed":
            cur.update(state=e["state"], when=e["when"], reply=e.get("reply", ""),
                       saved_lines=e.get("lines", []))
    entries = sorted(latest.values(), key=lambda e: e["when"], reverse=True)[:limit]
    return {"entries": [{**e, "when": time.strftime("%H:%M", time.localtime(e["when"]))} for e in entries]}


apps.add_html_resource(UI_RECORDS, cards.RECORDS_HTML, title="Records")
apps.add_html_resource(UI_CHANGE, cards.CHANGE_HTML, title="Read-back")
apps.add_html_resource(UI_RECENT, cards.RECENT_HTML, title="Recent activity")
mcp = MCPServer(name="SDI Tracker (proof)", instructions=INSTRUCTIONS, extensions=[apps])


# ── A page to watch the proof from a laptop: what was asked, saved, and how fast ─
async def journal_page(request: Request):
    rows = "".join(f"<tr><td>{time.strftime('%H:%M:%S', time.localtime(e['when']))}</td><td>{e['state']}</td>"
                   f"<td>{'<br>'.join(e.get('lines') or [])}</td><td>{e.get('reply', '')}</td></tr>"
                   for e in reversed(JOURNAL))
    return HTMLResponse("<!doctype html><meta name=viewport content='width=device-width'>"
                        "<meta http-equiv=refresh content=5><title>Tracker proof</title>"
                        "<body style='font-family:system-ui;margin:16px'><h2>Tracker proof: journal</h2>"
                        "<p>Made-up data. Refreshes every 5 seconds.</p><table border=1 cellpadding=6 "
                        "style='border-collapse:collapse'><tr><th>Time</th><th>Outcome</th><th>Changes</th>"
                        f"<th>Reply</th></tr>{rows}</table>")


def build_app():
    if len(KEY) < 24:
        raise SystemExit("Set PROOF_KEY to a long random string (24+ characters) first.")
    app = mcp.streamable_http_app(
        streamable_http_path=f"/{KEY}/mcp", stateless_http=True, json_response=True, host="0.0.0.0",
        # A public server reached by OpenAI's or Anthropic's cloud: the Host check
        # is meant for servers on localhost, so it is off; the key is the lock.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))
    app.router.routes.append(Route(f"/{KEY}/journal", journal_page))
    app.router.routes.append(Route("/", lambda r: PlainTextResponse("ok")))   # host health check
    return app


if __name__ == "__main__":
    uvicorn.run(build_app(), host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
