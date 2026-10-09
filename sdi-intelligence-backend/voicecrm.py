"""
SDI Intelligence — Voice-Activated CRM (sandbox pilot) backend.

Read-only, deliberately. This reads Nick's sandbox project records from a
SharePoint List through Microsoft Graph, as the signed-in user, so the app
portal can show the real records rather than a description of them.

It does NOT write. Writing needs the full confirm-and-journal loop from the
architecture — validate, read back, obtain explicit confirmation, re-check the
owner and the record version, record the outcome durably so a retry cannot
repeat a saved change — and that is a separately approved step. An endpoint
that wrote without those controls would be worse than no endpoint.

Everything here degrades honestly. If the List is not configured, or consent
was never granted, or Graph returns an error, the response says exactly that.
Nothing is invented to make the screen look finished.

Configuration (.env):

    SDI_VOICECRM_SITE      SharePoint site, "hostname:/sites/SiteName"
                           e.g. sdidisplays.sharepoint.com:/sites/NickGarrish-...
    SDI_VOICECRM_LIST      Display name or ID of the List
    SDI_VOICECRM_OWNER     Owner value to filter on, default "NG"
    SDI_VOICECRM_OWNER_FIELD  Internal field name of the owner column,
                           default "AMOwner"

The delegated scope Sites.Read.All (or Sites.Selected, scoped to this one site)
must be in SDI_GRAPH_SCOPES and consented, or every call returns no_token.
"""

import json
import re
import os
import time
from collections import Counter
from datetime import date
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import auth
import journal
import voicecrm_excel
import voicecrm_speech

GRAPH = "https://graph.microsoft.com/v1.0"


def _opt(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


# ── Storage backend ──────────────────────────────────────────────────────────
# "list"  — a SharePoint List (the original design)
# "excel" — a workbook in the site's document library (what Nick's sandbox
#           actually is). Same propose/confirm/journal loop either way; only
#           how a record is fetched, versioned and written differs.
STORE = _opt("SDI_VOICECRM_STORE", "list").lower()
EXCEL = voicecrm_excel.ExcelStore() if STORE == "excel" else None

SITE = _opt("SDI_VOICECRM_SITE")
LIST = _opt("SDI_VOICECRM_LIST")
OWNER = _opt("SDI_VOICECRM_OWNER", "NG")
# A List column has an internal name ("AMOwner"); a sheet header is the
# literal text in the cell ("AM Owner").
OWNER_FIELD = _opt("SDI_VOICECRM_OWNER_FIELD",
                   "AM Owner" if STORE == "excel" else "AMOwner")

CONFIGURED = EXCEL.configured if EXCEL else bool(SITE and LIST)

router = APIRouter()


def _status_payload() -> dict[str, Any]:
    if EXCEL:
        missing = list(EXCEL.missing)
    else:
        missing = []
        if not SITE:
            missing.append("SDI_VOICECRM_SITE")
        if not LIST:
            missing.append("SDI_VOICECRM_LIST")
    scopes_ok = any(s.lower().startswith(("sites.", "files."))
                    for s in auth.GRAPH_SCOPES)
    return {
        "configured": CONFIGURED,
        "store": STORE,
        "workbook": EXCEL.xlsx if EXCEL else "",
        "interpret_ready": _interpret_ready(),
        **voicecrm_speech.status(),
        "missing_settings": missing,
        "sso_enabled": auth.ENABLED,
        "graph_scopes": auth.GRAPH_SCOPES,
        "site_scope_granted": scopes_ok,
        "owner_filter": OWNER,
        "owner_field": OWNER_FIELD,
        "writes_enabled": WRITE_ENABLED,
        "approved_by": APPROVED_BY,
        "editable_fields": EDITABLE,
        "editable_label": _editable_label(),
        "write_note": ("Writing runs propose -> read back -> confirm, with an owner and "
                       "version re-check and a durable journal. Off until the List exists "
                       "and the pilot is approved."),
    }


@router.get("/api/voicecrm/status")
def status(request: Request, user: dict = Depends(auth.require_user)):
    """What is wired up and what is not — used by the app screen to explain itself."""
    user = auth.current_user(request)
    return {**_status_payload(), "sso_enabled": auth.sso_applies(request),
            "writes_enabled": WRITE_ENABLED and _may_write(user or {}),
            "writers_restricted": True,
            "signed_in": bool(user) and user.get("kind") == "user",
            "user": (user or {}).get("name", "")}


@router.get("/api/voicecrm/projects")
def projects(request: Request, user: dict = Depends(auth.require_user)):
    """The signed-in user's sandbox project records, filtered to the owner value.

    Returns {"state": ...} describing exactly why there is no data, rather than
    an empty list that looks like "no projects".
    """
    if not CONFIGURED:
        return {"state": "not_configured", "detail": _status_payload(), "items": []}

    if not auth.ENABLED:
        return {"state": "sso_disabled", "items": [],
                "detail": "Graph is called as the signed-in user. Configure Entra SSO first."}
    if not auth.sso_applies(request):
        public = sorted(auth.PUBLIC_HOSTS)
        return {"state": "sign_in_elsewhere", "items": [],
                "public_url": f"https://{public[0]}/app/voice-crm.html" if public else "",
                "detail": ("These records are read as the signed-in person, and signing "
                           "in only works on the published address.")}

    token = auth.graph_token(request)
    if not token:
        return {"state": "no_token", "items": [],
                "detail": ("No Microsoft Graph token for this session. Sign in again, and "
                           "check that a Sites.* scope is in SDI_GRAPH_SCOPES and has been "
                           "consented for this application.")}

    if EXCEL:
        data = EXCEL.rows(token)
        if data.get("state") == "graph_error" and data.get("status") in (403, 404):
            # Graph answers 403 - or 404, refusing even to confirm the file
            # exists - to someone who cannot open the sandbox site. For anyone
            # but the pilot's own users that is the correct outcome; say so
            # rather than "not found", which reads as a fault.
            return {"state": "no_access", "items": [], "status": data.get("status"),
                    "workbook": EXCEL.xlsx, "detail": data.get("detail", "")}
        if data.get("state") != "ok":
            return data
        rows, skipped = [], 0
        for item in data["items"]:
            owner = str(item["fields"].get(OWNER_FIELD, "")).strip()
            if OWNER and owner.upper() != OWNER.upper():
                skipped += 1
                continue
            rows.append(item)
        out = {"state": "ok", "items": rows, "owner_filter": OWNER,
               "skipped_other_owner": skipped, "sheet": data.get("sheet", ""),
               "owner_field_found": OWNER_FIELD in data.get("headers", []),
               "columns": data.get("headers", [])}
        if not rows:
            # Say what WAS there, so the fix is one look rather than a guess.
            counts = Counter(str(i["fields"].get(OWNER_FIELD, "")).strip() or "(blank)"
                             for i in data["items"])
            out.update({"sheets": data.get("sheets", []),
                        "header_row": data.get("header_row"),
                        "headers_seen": data.get("headers", [])[:40],
                        "owner_values": counts.most_common(8)})
        return out

    headers = {"Authorization": f"Bearer {token}"}
    try:
        with httpx.Client(timeout=20) as client:
            site = client.get(f"{GRAPH}/sites/{SITE}", headers=headers)
            if site.status_code != 200:
                return {"state": "graph_error", "items": [], "status": site.status_code,
                        "detail": _graph_detail(site)}
            site_id = site.json().get("id", "")

            items = client.get(
                f"{GRAPH}/sites/{site_id}/lists/{LIST}/items",
                params={"expand": "fields", "$top": "100"},
                headers=headers,
            )
            if items.status_code != 200:
                return {"state": "graph_error", "items": [], "status": items.status_code,
                        "detail": _graph_detail(items)}
    except httpx.HTTPError as exc:
        return {"state": "unreachable", "items": [],
                "detail": f"Could not reach Microsoft Graph: {exc}"}

    rows = []
    skipped_other_owner = 0
    for entry in items.json().get("value", []):
        fields = entry.get("fields", {}) or {}
        owner = str(fields.get(OWNER_FIELD, "")).strip()
        if OWNER and owner.upper() != OWNER.upper():
            skipped_other_owner += 1
            continue
        rows.append({
            "id": entry.get("id"),
            # eTag carries the version — the write path will need it to detect
            # a record someone else changed mid-conversation.
            "etag": entry.get("eTag", ""),
            "modified": entry.get("lastModifiedDateTime", ""),
            "fields": fields,
        })

    return {"state": "ok", "items": rows, "owner_filter": OWNER,
            "skipped_other_owner": skipped_other_owner,
            "owner_field_found": any(OWNER_FIELD in r["fields"] for r in rows) if rows else None}


def _graph_detail(response: httpx.Response) -> str:
    """Graph's own error message, which is usually the actionable one."""
    try:
        err = response.json().get("error", {})
        return f"{err.get('code', '')}: {err.get('message', '')}"[:400]
    except Exception:  # noqa: BLE001 — a non-JSON error body is still worth showing
        return response.text[:400]


# ═══════════════════════════════════════════════════════════════════════════
# Write path — propose, read back, confirm, journal.
#
# OFF by default. Two independent gates must both be open:
#   SDI_VOICECRM_WRITE=yes        the switch
#   SDI_VOICECRM_APPROVED_BY=...  who approved the pilot to write, recorded
#                                 in every journal entry
#
# Nothing writes to the live tracker. This only ever touches the List named by
# SDI_VOICECRM_SITE / SDI_VOICECRM_LIST, and only records whose owner matches.
# ═══════════════════════════════════════════════════════════════════════════

WRITE_ENABLED = _opt("SDI_VOICECRM_WRITE", "no").lower() in ("1", "yes", "true", "on")
APPROVED_BY = _opt("SDI_VOICECRM_APPROVED_BY")

# Which columns may be written. For the Excel sandbox the default is "*":
# every column of the tracker, because a call update can touch any of them -
# EXCEPT the owner column (changing it would hand the record away and defeats
# the owner check), the sheet's helper columns (AM_Upper, Budget_Num, Contact
# Key... restate other columns), and any cell holding a formula (checked per
# cell at propose time, so a calculated cell is never overwritten with a value).
# A comma list in SDI_VOICECRM_EDITABLE narrows it back to named columns.
_EDITABLE_DEFAULT = "*" if STORE == "excel" else "Status,NextAction,NextActionDate"
EDITABLE = [f.strip() for f in
            _opt("SDI_VOICECRM_EDITABLE", _EDITABLE_DEFAULT).split(",")
            if f.strip()]
ALL_COLUMNS = EDITABLE == ["*"]
# Columns that identify the tracker's header row (not a write list).
_KEY_COLUMNS = ["Status", "NEXT STEPS", "KEY DATES FOR NEXT STEPS", "Commercial Status",
                "Confidence to Order", "Last Client Contact Date", "BUDGET COST"]
if EXCEL:
    EXCEL.key_columns = [OWNER_FIELD, *(_KEY_COLUMNS if ALL_COLUMNS else EDITABLE)]

_HELPER_COLUMN = re.compile(r"_upper$|_num$|clean|key$|^stat$|^(id|row|#)$", re.I)


def _protected(field: str) -> bool:
    """Never written, whatever the editable setting says."""
    return (" ".join(field.split()).lower() == " ".join(OWNER_FIELD.split()).lower()
            or bool(_HELPER_COLUMN.search(field.strip())))


def _editable(field: str, columns=None) -> bool:
    """May this column be written? `columns` = the sheet's actual headers."""
    if not field or _protected(field):
        return False
    if ALL_COLUMNS:
        return columns is None or field in columns
    return field in EDITABLE


def _editable_label() -> str:
    return ("any column except " + OWNER_FIELD + " and calculated columns"
            if ALL_COLUMNS else ", ".join(EDITABLE))

_journal = journal.UpdateJournal()


class ProposeIn(BaseModel):
    item_id: str
    field: str
    new_value: str


class ConfirmIn(BaseModel):
    proposal_id: str
    confirmed: bool


# Who may change records through the app, by sign-in email. Required: with
# writing on and no list, nobody can write. Read access to the sandbox site
# (or membership of it) is deliberately not enough - colleagues are given the
# site to SEE the pilot, and must not be able to change Nick's records by voice.
WRITERS = {e.strip().lower() for e in _opt("SDI_VOICECRM_WRITERS").split(",") if e.strip()}


def _may_write(user: dict) -> bool:
    return bool(user) and str(user.get("email", "")).strip().lower() in WRITERS


def _is_money(field: str) -> bool:
    return any(w in field.upper() for w in ("BUDGET", "COST", "VALUE", "PRICE"))


def _money_value(raw: str) -> str | None:
    """A spoken or typed amount as a plain number for the cell, or None.

    The sheet holds budgets as numbers (its Budget_Num helper and any totals
    calculate from them). Written as "£50,000.00" Excel may keep it as text and
    silently break those, so currency signs, commas and spaces are removed and
    anything that is not then a plain number is refused, not guessed at.
    """
    cleaned = re.sub(r"[£$€,\s]", "", str(raw or ""))
    if cleaned.lower().endswith("k") and re.fullmatch(r"-?\d+(\.\d+)?k", cleaned.lower()):
        cleaned = str(float(cleaned[:-1]) * 1000)
    if not re.fullmatch(r"-?\d+(\.\d+)?", cleaned):
        return None
    value = float(cleaned)
    return str(int(value)) if value == int(value) else f"{value:.2f}"


def _write_gate(user: dict | None = None) -> dict | None:
    """The reason writing is refused, or None if it is permitted."""
    if WRITE_ENABLED and user is not None and not _may_write(user):
        who = (user or {}).get("email") or "this account"
        return {"state": "not_a_writer",
                "detail": (f"Updates in this pilot are limited to named people, and {who} "
                           f"is not one of them. You can still ask questions.")}
    if not WRITE_ENABLED:
        return {"state": "writes_disabled",
                "detail": ("updates aren't switched on for this pilot yet, so nothing was "
                           "saved. You can still ask about your records.")}
    if not APPROVED_BY:
        return {"state": "not_approved",
                "detail": ("SDI_VOICECRM_APPROVED_BY is empty. Record who approved the pilot "
                           "to write — it is stamped on every journal entry.")}
    if not CONFIGURED:
        return {"state": "not_configured", "detail": _status_payload()}
    return None


def _fetch_item(token: str, item_id: str) -> tuple[dict | None, dict | None]:
    """One record with its fields, or (None, error-payload)."""
    if EXCEL:
        return EXCEL.fetch(token, item_id)
    headers = {"Authorization": f"Bearer {token}"}
    try:
        with httpx.Client(timeout=20) as client:
            site = client.get(f"{GRAPH}/sites/{SITE}", headers=headers)
            if site.status_code != 200:
                return None, {"state": "graph_error", "status": site.status_code,
                              "detail": _graph_detail(site)}
            site_id = site.json().get("id", "")
            item = client.get(f"{GRAPH}/sites/{site_id}/lists/{LIST}/items/{item_id}",
                              params={"expand": "fields"}, headers=headers)
            if item.status_code != 200:
                return None, {"state": "graph_error", "status": item.status_code,
                              "detail": _graph_detail(item)}
            data = item.json()
            data["_site_id"] = site_id
            return data, None
    except httpx.HTTPError as exc:
        return None, {"state": "unreachable", "detail": f"Could not reach Microsoft Graph: {exc}"}


def _owner_ok(fields: dict) -> bool:
    return not OWNER or str(fields.get(OWNER_FIELD, "")).strip().upper() == OWNER.upper()


def _project_ref(fields: dict) -> str:
    # Excel headers first (Nick's tracker — Project codes are currently blank,
    # so Client + Project is the spoken reference), then List internal names.
    if fields.get("ACCOUNT"):
        parts = [fields.get("ACCOUNT"), fields.get("BUSINESS UNIT"),
                 str(fields.get("OVERVIEW / DESCRIPTION / DELIVERABLES") or "").split("\n")[0][:60]]
        return " — ".join(str(p).strip() for p in parts if p and str(p).strip())
    if fields.get("Client") or fields.get("Project"):
        return " — ".join(str(fields[k]) for k in ("Client", "Project") if fields.get(k))
    for key in ("Project code", "ProjectID", "ProjectId", "Project_x0020_ID", "Title"):
        if fields.get(key):
            return str(fields[key])
    return ""


@router.post("/api/voicecrm/propose")
def propose(body: ProposeIn, request: Request, user: dict = Depends(auth.require_user)):
    """Validate a change and read it back. Nothing is written by this call."""
    blocked = _write_gate(user)
    if blocked:
        return blocked

    if not _editable(body.field):
        return {"state": "field_not_editable", "field": body.field, "editable": EDITABLE,
                "detail": (f"{body.field} can't be changed from here. "
                           f"You can change {_editable_label()}.")}

    if _is_money(body.field):
        amount = _money_value(body.new_value)
        if amount is None:
            return {"state": "invalid_value", "field": body.field,
                    "detail": (f"'{body.new_value}' isn't a clear amount for {body.field}. "
                               f"Say it as a number, e.g. fifteen thousand five hundred.")}
        body.new_value = amount

    token = auth.graph_token(request)
    if not token:
        return {"state": "no_token", "detail": "No Microsoft Graph token for this session."}

    item, err = _fetch_item(token, body.item_id)
    if err:
        return err

    fields = item.get("fields", {}) or {}
    if not _owner_ok(fields):
        # The owner check is enforced here, not by the view the records came from.
        return {"state": "not_your_record",
                "detail": f"That record's {OWNER_FIELD} is not {OWNER}."}
    if body.field not in fields:
        return {"state": "field_not_editable", "field": body.field,
                "detail": f"There is no column called {body.field} in the tracker."}
    if EXCEL and EXCEL.is_formula(token, item, body.field):
        return {"state": "field_not_editable", "field": body.field,
                "detail": (f"{body.field} is calculated by a formula in the sheet, "
                           f"so it can't be typed over.")}

    old_value = fields.get(body.field)
    if str(old_value or "") == body.new_value:
        return {"state": "no_change",
                "detail": f"{body.field} is already '{body.new_value}'. Nothing to confirm."}

    etag = item.get("eTag", "")
    ref = _project_ref(fields)
    pid = _journal.propose(user=user, item_id=body.item_id, project_ref=ref,
                           field=body.field, old_value=old_value,
                           new_value=body.new_value, etag=etag)

    return {
        "state": "proposed",
        "proposal_id": pid,
        # What the voice agent reads back, verbatim, before taking a yes.
        "readback": (f"On {ref or 'item ' + body.item_id}, change {body.field} "
                     f"from '{old_value or 'blank'}' to '{body.new_value}'. Is that right?"),
        # The parts, so the app can read several changes back as one.
        "item_id": body.item_id, "project_ref": ref, "field": body.field,
        "old_value": old_value or "", "new_value": body.new_value,
        "expires_in_seconds": journal.PROPOSAL_TTL_SECONDS,
    }


def _only_own_changes(item: dict, entry: dict) -> bool:
    """True when the row differs from the read-back only by changes this same
    person has saved to it since - e.g. "end date today, status completed" is
    two saves to one row, and the second must not see the first as someone
    else's edit. Those cells are put back to their earlier values and the row
    re-stamped: if that matches the stamp taken at the read-back, nothing
    else changed. Excel rows only; a SharePoint List keeps its strict check."""
    cells, cols = item.get("_cells"), item.get("_col")
    if not (EXCEL and cells is not None and cols):
        return False
    own = _journal.applied_to(entry["item_id"], entry["user_oid"], entry["created"],
                              exclude=entry["proposal_id"])
    if not own:
        return False
    cells = list(cells)
    for change in reversed(own):                    # newest first, back to the start
        j = cols.get(change["field"])
        if j is None or j >= len(cells):
            return False
        cells[j] = change["old_value"] or ""
    return voicecrm_excel.fingerprint(cells) == entry["etag"]


@router.post("/api/voicecrm/confirm")
def confirm(body: ConfirmIn, request: Request, user: dict = Depends(auth.require_user)):
    """Apply a proposal, once. A repeated confirm returns the first outcome."""
    blocked = _write_gate(user)
    if blocked:
        return blocked

    entry = _journal.get(body.proposal_id)
    if not entry:
        return {"state": "unknown_proposal", "detail": "No such proposal."}

    # Idempotency: the whole point of the journal. A second confirm never writes.
    if entry["state"] != "proposed":
        return {"state": entry["state"], "already_resolved": True,
                "proposal_id": body.proposal_id, "outcome": entry["outcome"],
                "detail": "This proposal was already resolved; nothing was written again."}

    if not body.confirmed:
        _journal.finish(body.proposal_id, "failed", "Declined by the user.")
        return {"state": "declined", "proposal_id": body.proposal_id}

    if entry["user_oid"] and entry["user_oid"] != user.get("oid"):
        _journal.finish(body.proposal_id, "failed", "Confirmed by a different user.")
        return {"state": "wrong_user",
                "detail": "A proposal can only be confirmed by the person who made it."}

    token = auth.graph_token(request)
    if not token:
        return {"state": "no_token", "detail": "No Microsoft Graph token for this session."}

    item, err = _fetch_item(token, entry["item_id"])
    if err:
        _journal.finish(body.proposal_id, "failed", str(err.get("detail", ""))[:300])
        return err

    fields = item.get("fields", {}) or {}
    if not _owner_ok(fields):
        _journal.finish(body.proposal_id, "failed", "Owner changed since the proposal.")
        return {"state": "not_your_record", "detail": "That record is no longer yours."}

    # Someone else edited the record while we were talking about it. Abandon the
    # proposal rather than overwrite their change. Changes this person saved to
    # the same row a moment ago (the earlier parts of one "yes") don't count.
    if (entry["etag"] and item.get("eTag") and item["eTag"] != entry["etag"]
            and not _only_own_changes(item, entry)):
        _journal.finish(body.proposal_id, "conflict",
                        "The record changed between proposal and confirmation.")
        return {"state": "conflict",
                "detail": ("Someone changed that record while we were talking. Nothing was "
                           "written. Read it again and re-propose.")}

    if EXCEL:
        # A workbook write cannot carry If-Match; the fingerprint comparison
        # above is the version check. voicecrm_excel.py documents the residual
        # read-to-write window this leaves open.
        err = EXCEL.apply(token, item, entry["field"], entry["new_value"])
        if err:
            _journal.finish(body.proposal_id, "failed",
                            f"{err.get('state')}: {str(err.get('detail', ''))[:300]}")
            return err
    else:
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        if item.get("eTag"):
            headers["If-Match"] = item["eTag"]  # belt and braces alongside the check above
        url = f"{GRAPH}/sites/{item['_site_id']}/lists/{LIST}/items/{entry['item_id']}/fields"
        try:
            with httpx.Client(timeout=20) as client:
                res = client.patch(url, headers=headers,
                                   json={entry["field"]: entry["new_value"]})
        except httpx.HTTPError as exc:
            _journal.finish(body.proposal_id, "failed", f"Graph unreachable: {exc}")
            return {"state": "unreachable", "detail": f"Could not reach Microsoft Graph: {exc}"}

        if res.status_code == 412:
            _journal.finish(body.proposal_id, "conflict", "Precondition failed on write.")
            return {"state": "conflict",
                    "detail": "The record changed as we wrote. Nothing was saved."}

        if res.status_code >= 300:
            detail = _graph_detail(res)
            _journal.finish(body.proposal_id, "failed", f"HTTP {res.status_code}: {detail}")
            # Never report success for a write that did not happen.
            return {"state": "failed", "status": res.status_code, "detail": detail}

    _journal.finish(body.proposal_id, "applied",
                    f"{entry['field']}: '{entry['old_value']}' -> '{entry['new_value']}' "
                    f"(approved by {APPROVED_BY})")
    return {"state": "applied", "proposal_id": body.proposal_id,
            "project_ref": entry["project_ref"], "field": entry["field"],
            "old_value": entry["old_value"], "new_value": entry["new_value"]}


@router.post("/api/voicecrm/transcribe")
async def transcribe(request: Request, user: dict = Depends(auth.require_user)):
    """One recorded sentence (16 kHz mono WAV, the request body) to text, via
    Azure AI Speech. Used on iPhones, where the browser's own recognition
    stops when the page scrolls. Writes nothing; the words then go through
    /interpret like any spoken or typed request."""
    started = time.monotonic()
    audio = await request.body()
    if len(audio) > voicecrm_speech.MAX_AUDIO_BYTES:
        return {"state": "too_long", "detail": "That was longer than a minute — please say it in shorter parts."}
    out = voicecrm_speech.transcribe(audio)
    print(f"[voicecrm.transcribe] user={(user or {}).get('email', '')} bytes={len(audio)} "
          f"state={out.get('state')} chars={len(out.get('text', ''))} parts={out.get('parts', 0)} "
          f"secs={time.monotonic() - started:.1f}", flush=True)
    return out


class SpeakIn(BaseModel):
    text: str


@router.post("/api/voicecrm/speak")
def speak(body: SpeakIn, request: Request, user: dict = Depends(auth.require_user)):
    """A reply as MP3 in the configured Azure neural voice. The page falls back
    to the phone's own voice if this is off or fails."""
    audio, err = voicecrm_speech.synthesize(body.text)
    if err:
        return err
    return Response(content=audio, media_type="audio/mpeg",
                    headers={"Cache-Control": "no-store"})


class ClientLogIn(BaseModel):
    reason: str = Field("", max_length=40)
    ua: str = Field("", max_length=400)
    events: list[str] = Field(default_factory=list, max_length=80)


# Control characters would let a caller forge extra log lines.
_CTRL = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")


@router.post("/api/voicecrm/clientlog")
def client_log(body: ClientLogIn, request: Request, user: dict = Depends(auth.require_user)):
    """What a phone's mic and speech engine did, so voice problems on someone
    else's phone can be diagnosed from the server log. The page sends event
    names, error codes and lengths only - never what was said."""
    clean = lambda v, n: _CTRL.sub(" ", str(v))[:n]          # noqa: E731
    events = " | ".join(clean(e, 90) for e in body.events[-60:])
    print(f"[voicecrm.client] user={(user or {}).get('email', '')} reason={clean(body.reason, 30)!r} "
          f"ua={clean(body.ua, 200)!r} events={events[:4000]}", flush=True)
    return {"state": "ok"}


@router.get("/api/voicecrm/journal")
def journal_view(request: Request, limit: int = 25, user: dict = Depends(auth.require_user)):
    """The audit trail: every proposal and what actually happened to it."""
    return {"writes_enabled": WRITE_ENABLED, "approved_by": APPROVED_BY,
            "writers": sorted(WRITERS),
            "editable_fields": EDITABLE, "counts": _journal.counts(),
            "entries": _journal.recent(limit)}


# ═══════════════════════════════════════════════════════════════════════════
# Interpret — one spoken sentence in, one structured instruction out.
#
# The browser does the listening (Web Speech API) and the talking
# (speechSynthesis); this endpoint only turns the transcript into either a
# proposal the normal propose/confirm loop can run, an answer to read aloud,
# or a clarifying question. It never writes anything itself — every update
# still goes through /propose and /confirm with all their checks.
# ═══════════════════════════════════════════════════════════════════════════

INTERPRET_MODEL = _opt("SDI_VOICECRM_MODEL", "claude-opus-5-5")
# How hard the model thinks per spoken request. Voice turns are short
# (match a record, read or propose one change), so "low" keeps the reply
# quick; raise to "medium" (the model's default) if answers to broad
# questions ("what's at risk?") get thinner. Every write is still checked by
# this code and confirmed by the person, whatever the setting.
INTERPRET_EFFORT = _opt("SDI_VOICECRM_EFFORT", "low").lower()


def _interpret_ready() -> bool:
    if not os.getenv("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401 — availability probe
        return True
    except ImportError:
        return False


def _canonical_id(raw, known_ids: set) -> str:
    """The model's record reference as one of the ids it was given, or "".

    It is handed ids like "xl8" but sometimes returns "8", "XL8" or "row 8".
    Each still names exactly one row; anything that does not resolve to an id
    it was given is still discarded.
    """
    text = str(raw or "").strip().lower()
    if text in known_ids:
        return text
    digits = re.sub(r"\D", "", text)
    if digits and f"xl{digits}" in known_ids:
        return f"xl{digits}"
    return ""


def _canonical_field(raw, columns=None) -> str:
    """The model's column name as the real column it means, or as given."""
    wanted = " ".join(str(raw or "").replace("_", " ").split()).lower()
    for f in (columns if ALL_COLUMNS and columns else EDITABLE):
        if " ".join(f.split()).lower() == wanted:
            return f
    return str(raw or "")


class InterpretIn(BaseModel):
    transcript: str
    # The records the screen is currently showing, trimmed by the browser to
    # {id, ref, fields-of-interest}. The model matches against these only.
    projects: list[dict] = []
    # Every column of the sheet, including ones blank on every record shown.
    columns: list[str] = []
    # The last few turns of this conversation, oldest first: [{"who": "you"|"app",
    # "text": ...}]. Lets "Tesco Mobile's" answer the question the model just
    # asked, and "it" mean the job being discussed.
    history: list[dict] = []


_INTERPRET_SYSTEM = """You are the voice of an account manager's project tracker. You receive one
spoken sentence (a voice transcript, so expect recognition errors), today's
date, the columns that may be changed, and their records. You either answer a
question about the records, propose changes, or ask one question back.

Reply with ONLY a JSON object, no prose, no code fences, with the keys in
this order (the start of "say" is spoken while the rest is still arriving):
  {"action": "read" | "update" | "clarify",
   "say": "<what to speak to the person>",
   "changes": [{"item_id": "<id of the record>",
                "field": "<an editable column, spelled exactly as given>",
                "new_value": "<the value to set>"}]}
"changes" is [] unless action is "update".

How the tracker is laid out:
Speech recognition misspells names. Match by SOUND and meaning, not exact
spelling: "barber" is Barbour, "tesco's bank" is TESCO BANK, "the perfume
shop" is TPS, "sofa dell" is SOFIDEL, "hurb ladder" is Herb Ladder. When one
record is a clear sound-alike match, use it - every update is read back with
the record's real name before anything is saved, so the person catches a
wrong match. Ask only when two or more records are equally plausible.

- ACCOUNT is the client company (e.g. TESCO; TPS is The Perfume Shop).
- BUSINESS UNIT is the part of that client, or the store/site (e.g. TESCO BANK,
  TESCO MOBILE, Swansea). A name the person says - "Tesco Bank", "Morrisons",
  "Swansea" - may be an ACCOUNT, a BUSINESS UNIT or words in the description,
  in any letter case. Look in all three.
- OVERVIEW / DESCRIPTION / DELIVERABLES is the job itself.
- Status and NEXT STEPS are the latest position; KEY DATES FOR NEXT STEPS is
  when the next step is due; START and END are the job dates.
- Commercial Status (Quoted, Awaiting PO, Ordered, At Risk, On Hold, Verbal /
  Likely) and Confidence to Order describe the deal; BUDGET COST is its value.
- AM / PM Owner are initials of the account and project managers.

"read" - any question about the records, about one job or a group: "what's
happening with Tesco Bank", "what's at risk", "what's due this week", "read me
my records". Answer across EVERY matching record; never ask them to pick one
just to answer a question. Lead with how many match, then what matters most:
due soonest or overdue (compare with today), at risk, highest value. Name jobs
by business unit and job, e.g. "Tesco Bank's Digital Gift Card Gatepost". At
most five short sentences - it is spoken aloud, so no lists, symbols or
markdown; say amounts as words a person would say ("about fifty thousand
pounds"). If there are more than you can say, say how many more there are.

"update" - they want to change one or more values. A single sentence often
carries several: "spoke to Tesco Bank today, they want a revised quote by
Friday, confidence 80 percent" is three changes - Last Client Contact Date,
NEXT STEPS (and its KEY DATES FOR NEXT STEPS), Confidence to Order. Put every
change in "changes", one entry per cell (at most 8). Each must name exactly one
record, an editable column and a clear value. item_id must be an id you were
given; never invent one. When they add to notes-like text (NEXT STEPS, Status,
descriptions) and say "add" or "also", new_value is the existing text plus the
new words; otherwise it replaces it. In "say", briefly confirm what you
understood; the changes are read back and confirmed before saving.

"clarify" - an update whose record, column or value is ambiguous, or a request
you genuinely cannot match. Ask ONE specific question, naming the candidates
(at most three).

"conversation_so_far" holds the last few turns, oldest first. Use it: when the
person answers a question you asked ("Tesco Mobile's", "the first one", "yes,
that one"), combine the answer with their earlier request and act on it -
never ask them to repeat what they already said. "It" and "that job" mean the
job being discussed. A change that was read back and not confirmed was NOT
saved; if they ask again, propose it again. Do not claim anything was saved:
only the app's own "Updated" lines confirm a save.

Money (BUDGET COST): new_value is a plain number - no currency sign, no
commas: "fifty thousand" is "50000", "fifteen and a half k" is "15500". If you
are not sure of the amount you heard, ask; never guess a figure.

Dates: resolve relative dates ("next Tuesday", "end of the month") against
"today", and write new values as YYYY-MM-DD. Never guess the year or swap day
and month; ask if unclear. The sheet shows dates month-first (9/4/2026 is
4 September 2026) - say dates in words when speaking ("the fourth of September").

If they ask you to report a problem or an error, say that every failed or
partly saved update is already recorded automatically for James to look at,
so there is nothing else they need to do, then carry on helping.

Never invent facts that are not in the records. Interpreting a misheard name
as the job it plainly sounds like is not guessing; making up a value, date or
status is."""


def _interpret_prepare(body: InterpretIn):
    """The request to the model for one transcript, or a reply needing no model."""
    if not _interpret_ready():
        return None, {"state": "interpret_unavailable",
                      "detail": ("Voice interpretation needs ANTHROPIC_API_KEY in the service "
                                 "environment and the 'anthropic' package installed.")}
    transcript = body.transcript.strip()
    if not transcript:
        return None, {"state": "clarify", "say": "I didn't catch that. Say it again?"}

    columns = [c for c in body.columns if c and _editable(c)] if ALL_COLUMNS else EDITABLE
    # The records go first, marked for caching: within a conversation they are
    # the same from one question to the next, so the model reuses its reading
    # of them instead of processing ~80 records again each time. Only the
    # sentence and the date follow the cache point.
    records_block = json.dumps({
        "editable_fields": columns or _editable_label(),
        "records": body.projects[:150],
    }, ensure_ascii=False, sort_keys=True)
    history = [{"who": "person" if str(h.get("who")) == "you" else "assistant",
                "text": str(h.get("text") or "")[:400]}
               for h in body.history[-8:] if isinstance(h, dict) and h.get("text")]
    question_block = json.dumps({
        "conversation_so_far": history,
        "transcript": transcript,
        "today": date.today().isoformat(),
    }, ensure_ascii=False)
    return dict(
        model=INTERPRET_MODEL,
        max_tokens=4000,
        thinking={"type": "adaptive"},
        output_config={"effort": INTERPRET_EFFORT},
        system=_INTERPRET_SYSTEM,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": records_block, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": question_block},
        ]}],
    ), None


def _interpret_result(text: str, stop_reason, cached, body: InterpretIn, user: dict,
                      started: float, streamed: bool = False, first_say=None) -> dict:
    """The model's reply checked and turned into update / read / clarify."""
    transcript = body.transcript.strip()
    if stop_reason == "max_tokens":
        return {"state": "clarify",
                "say": "That needed a longer answer than I can give. Could you narrow it down?"}
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").removeprefix("json").strip()
    try:
        parsed = json.loads(text)
        action = parsed.get("action")
        if action not in ("update", "read", "clarify"):
            raise ValueError(f"unknown action {action!r}")
    except (ValueError, json.JSONDecodeError, AttributeError):
        return {"state": "clarify",
                "say": "I couldn't make sense of that. Could you rephrase it?"}

    say = str(parsed.get("say") or "")[:900]
    raw_changes = parsed.get("changes")
    if not isinstance(raw_changes, list):
        raw_changes = []
    if not raw_changes and parsed.get("item_id"):        # the older one-change shape
        raw_changes = [{k: parsed.get(k) for k in ("item_id", "field", "new_value")}]
    # One line per request in the service log: what was heard, how many
    # records the model was given, and what it decided. No record contents.
    print(f"[voicecrm.interpret] user={user.get('email','')} records={len(body.projects)} "
          f"heard={transcript[:120]!r} action={action} "
          f"changes={[(c.get('item_id'), c.get('field')) for c in raw_changes if isinstance(c, dict)]!r} "
          f"say={say[:120]!r} effort={INTERPRET_EFFORT} secs={time.monotonic() - started:.1f} "
          f"cached={cached or 0}{' streamed' if streamed else ''}"
          f"{f' first_say={first_say:.1f}' if first_say is not None else ''}",
          flush=True)

    if action == "update":
        known_ids = {str(p.get("id")) for p in body.projects}
        sheet_cols = body.columns or sorted({k for p in body.projects
                                             for k in (p.get("fields") or {})})
        changes = []
        # The model proposes; this code decides. An id or column it was not
        # given is discarded, not trusted.
        for c in raw_changes[:8]:
            if not isinstance(c, dict):
                continue
            item_id = _canonical_id(c.get("item_id"), known_ids)
            field = _canonical_field(c.get("field"), sheet_cols)
            new_value = str(c.get("new_value") or "")
            if item_id not in known_ids:
                return {"state": "clarify",
                        "say": say or "I couldn't match that to one of your records. Which client was it?"}
            if not _editable(field, sheet_cols if ALL_COLUMNS else None):
                return {"state": "clarify",
                        "say": (f"I can't change {field or 'that column'} from here. "
                                f"I can change {_editable_label()}.")}
            if not new_value:
                return {"state": "clarify", "say": f"What should {field} be set to?"}
            changes.append({"item_id": item_id, "field": field, "new_value": new_value})
        if not changes:
            return {"state": "clarify", "say": say or "What would you like to change?"}
        first = changes[0]
        return {"state": "update", "changes": changes, "say": say,
                # single-change fields kept for older copies of the page
                "item_id": first["item_id"], "field": first["field"],
                "new_value": first["new_value"]}

    return {"state": action, "say": say or "Sorry, I have nothing useful to say about that."}


@router.post("/api/voicecrm/interpret")
def interpret(body: InterpretIn, request: Request, user: dict = Depends(auth.require_user)):
    """Parse a transcript into update/read/clarify. Writes nothing."""
    params, early = _interpret_prepare(body)
    if early:
        return early
    import anthropic
    started = time.monotonic()
    try:
        resp = anthropic.Anthropic().messages.create(**params)
    except anthropic.APIError as exc:
        return {"state": "interpret_failed",
                "detail": f"The language model refused the request: {exc}"[:400]}
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    cached = getattr(getattr(resp, "usage", None), "cache_read_input_tokens", 0)
    return _interpret_result(text, resp.stop_reason, cached, body, user, started)


class _SayScanner:
    """Reads the model's JSON reply as it streams in and hands back each
    finished sentence of "say", once "action" shows it is an answer to speak
    (read / clarify). An update's words are not spoken early: the change is
    read back from the sheet instead. Anything it can't follow (a different
    key order, an odd escape) just means nothing is spoken early - the full
    reply still arrives at the end as usual."""

    _ACTION = re.compile(r'"action"\s*:\s*"(\w+)"')
    _SAY = re.compile(r'"say"\s*:\s*"')
    _END = re.compile(r'[.!?](?=\s)')

    def __init__(self):
        self.buf = ""
        self.action = None
        self.say_at = -1          # where the say string's text starts in buf
        self.spoken = 0           # characters of the say text already handed out
        self.closed = False

    def _say_text(self) -> str:
        out, i, s = [], self.say_at, self.buf
        while i < len(s):
            ch = s[i]
            if ch == '"':
                self.closed = True
                break
            if ch == "\\":
                if i + 1 >= len(s):
                    break                       # escape split across chunks: wait
                nxt = s[i + 1]
                if nxt == "u":
                    if i + 6 > len(s):
                        break
                    try:
                        out.append(chr(int(s[i + 2:i + 6], 16)))
                    except ValueError:
                        pass
                    i += 6
                    continue
                out.append({"n": " ", "t": " ", "r": " "}.get(nxt, nxt))
                i += 2
                continue
            out.append(ch)
            i += 1
        return "".join(out)

    def feed(self, chunk: str) -> list[str]:
        self.buf += chunk
        if self.action is None:
            m = self._ACTION.search(self.buf)
            if m:
                self.action = m.group(1)
        if self.say_at < 0:
            m = self._SAY.search(self.buf)
            if not m:
                return []
            self.say_at = m.end()
        if self.action not in ("read", "clarify"):
            return []
        text = self._say_text()
        rest = text[self.spoken:]
        cuts = [m.end() for m in self._END.finditer(rest)]
        if self.closed and (not cuts or cuts[-1] < len(rest)):
            cuts.append(len(rest))
        out, prev = [], 0
        for cut in cuts:                         # one sentence at a time
            piece = rest[prev:cut].strip()
            if piece:
                out.append(piece)
            prev = cut
        self.spoken += prev
        return out


@router.post("/api/voicecrm/interpret/stream")
def interpret_stream(body: InterpretIn, request: Request, user: dict = Depends(auth.require_user)):
    """The same as /interpret, as lines of JSON: {"type": "say", "text": ...}
    for each sentence of an answer as soon as it is written, then
    {"type": "result", ...the /interpret reply...}. Lets the phone start
    speaking the first sentence while the rest is still being written."""
    params, early = _interpret_prepare(body)

    def lines():
        if early:
            yield json.dumps({"type": "result", **early}) + "\n"
            return
        import anthropic
        started = time.monotonic()
        scanner = _SayScanner()
        parts, said, first_say = [], [], None
        try:
            with anthropic.Anthropic().messages.stream(**params) as stream:
                for text in stream.text_stream:
                    parts.append(text)
                    for sentence in scanner.feed(text):
                        if not said:
                            first_say = time.monotonic() - started
                        said.append(sentence)
                        yield json.dumps({"type": "say", "text": sentence}) + "\n"
                final = stream.get_final_message()
        except anthropic.APIError as exc:
            yield json.dumps({"type": "result", "state": "interpret_failed",
                              "detail": f"The language model refused the request: {exc}"[:400]}) + "\n"
            return
        cached = getattr(getattr(final, "usage", None), "cache_read_input_tokens", 0)
        result = _interpret_result("".join(parts), final.stop_reason, cached, body, user,
                                   started, streamed=True, first_say=first_say)
        # Whether what was already spoken is the whole answer; if not (a
        # reply that failed its checks, say), the page speaks the result too.
        norm = lambda t: " ".join(str(t or "").split())
        result["say_streamed"] = bool(said) and norm(" ".join(said)) == norm(result.get("say"))
        yield json.dumps({"type": "result", **result}) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


# ═══════════════════════════════════════════════════════════════════════════
# Morning review — the same review the scheduled 7:50 job emails, on demand.
# Read-only. Preview for anyone signed in who can see the sandbox; sending is
# limited to the pilot writers. See morning_review.py.
# ═══════════════════════════════════════════════════════════════════════════

def _review_for(request: Request) -> tuple[dict | None, dict | None]:
    import morning_review
    if not EXCEL:
        return None, {"state": "not_excel", "detail": "The review reads the Excel tracker."}
    if not auth.sso_applies(request):
        return None, {"state": "sign_in_elsewhere",
                      "detail": "Open the app on its published address to run the review."}
    token = auth.graph_token(request)
    if not token:
        return None, {"state": "no_token", "detail": "No Microsoft Graph token for this session."}
    data = EXCEL.rows(token)
    if data.get("state") != "ok":
        return None, data
    return morning_review.compose([i["fields"] for i in data["items"]], data.get("headers", []),
                                  OWNER_FIELD, OWNER or "NG"), None


@router.get("/api/voicecrm/review")
def review_preview(request: Request, user: dict = Depends(auth.require_user)):
    """Today's morning review, built now from the sheet. Nothing is sent or saved."""
    import morning_review
    composed, err = _review_for(request)
    if err:
        return err
    r = composed["review"]
    return {"state": "ok", "counts": r["counts"], "previous_date": r["previous_date"],
            "subject": composed["email"]["subject"], "text": composed["email"]["text"],
            "html": composed["email"]["html"], "recipients": morning_review.recipients(),
            "can_send": _may_write(user)}


@router.get("/api/voicecrm/briefing")
def briefing(request: Request, user: dict = Depends(auth.require_user)):
    """The spoken briefing: changes saved in the last 24 hours, movement in the
    sheet since the last review, the headline counts and the top three.
    Rule-based only (no model call), so it starts speaking in a second or two."""
    import morning_review
    if not EXCEL:
        return {"state": "not_excel", "detail": "The briefing reads the Excel tracker."}
    if not auth.sso_applies(request):
        return {"state": "sign_in_elsewhere",
                "detail": "Open the app on its published address to hear the briefing."}
    token = auth.graph_token(request)
    if not token:
        return {"state": "no_token", "detail": "No Microsoft Graph token for this session."}
    data = EXCEL.rows(token)
    if data.get("state") != "ok":
        return data
    today = date.today()
    review = morning_review.build_review([i["fields"] for i in data["items"]],
                                         data.get("headers", []), OWNER_FIELD, OWNER or "NG",
                                         today, morning_review.last_snapshot(today))
    changes = _journal.applied_since(time.time() - 24 * 3600)
    first = str((user or {}).get("name") or "").split(" ")[0] or "there"
    return {"state": "ok", "say": morning_review.spoken_briefing(review, changes, first),
            "changes": len(changes), "counts": review["counts"]}


@router.post("/api/voicecrm/review/send")
def review_send(request: Request, user: dict = Depends(auth.require_user)):
    """Build the review now and email it to SDI_REVIEW_TO. Pilot writers only."""
    import morning_review
    if not _may_write(user):
        return {"state": "not_a_writer", "detail": "Only the pilot's named people can send the review."}
    if not morning_review.recipients():
        return {"state": "no_recipients", "detail": "SDI_REVIEW_TO is empty in the service .env."}
    composed, err = _review_for(request)
    if err:
        return err
    result = morning_review.send(composed)
    return {"state": "sent" if result.get("sent") else "not_sent", **result,
            "subject": composed["email"]["subject"]}
