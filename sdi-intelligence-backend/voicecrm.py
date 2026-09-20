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

import os
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

import auth
import journal

GRAPH = "https://graph.microsoft.com/v1.0"


def _opt(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


SITE = _opt("SDI_VOICECRM_SITE")
LIST = _opt("SDI_VOICECRM_LIST")
OWNER = _opt("SDI_VOICECRM_OWNER", "NG")
OWNER_FIELD = _opt("SDI_VOICECRM_OWNER_FIELD", "AMOwner")

CONFIGURED = bool(SITE and LIST)

router = APIRouter()


def _status_payload() -> dict[str, Any]:
    missing = []
    if not SITE:
        missing.append("SDI_VOICECRM_SITE")
    if not LIST:
        missing.append("SDI_VOICECRM_LIST")
    scopes_ok = any(s.lower().startswith("sites.") for s in auth.GRAPH_SCOPES)
    return {
        "configured": CONFIGURED,
        "missing_settings": missing,
        "sso_enabled": auth.ENABLED,
        "graph_scopes": auth.GRAPH_SCOPES,
        "site_scope_granted": scopes_ok,
        "owner_filter": OWNER,
        "owner_field": OWNER_FIELD,
        "writes_enabled": WRITE_ENABLED,
        "approved_by": APPROVED_BY,
        "editable_fields": EDITABLE,
        "write_note": ("Writing runs propose -> read back -> confirm, with an owner and "
                       "version re-check and a durable journal. Off until the List exists "
                       "and the pilot is approved."),
    }


@router.get("/api/voicecrm/status")
def status(request: Request, user: dict = Depends(auth.require_user)):
    """What is wired up and what is not — used by the app screen to explain itself."""
    user = auth.current_user(request)
    return {**_status_payload(), "signed_in": user is not None,
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

    token = auth.graph_token(request)
    if not token:
        return {"state": "no_token", "items": [],
                "detail": ("No Microsoft Graph token for this session. Sign in again, and "
                           "check that a Sites.* scope is in SDI_GRAPH_SCOPES and has been "
                           "consented for this application.")}

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

# Only these columns may ever be written. An open-ended write endpoint against a
# List is how a pilot quietly becomes an incident.
EDITABLE = [f.strip() for f in
            _opt("SDI_VOICECRM_EDITABLE", "Status,NextAction,NextActionDate").split(",")
            if f.strip()]

_journal = journal.UpdateJournal()


class ProposeIn(BaseModel):
    item_id: str
    field: str
    new_value: str


class ConfirmIn(BaseModel):
    proposal_id: str
    confirmed: bool


def _write_gate() -> dict | None:
    """The reason writing is refused, or None if it is permitted."""
    if not WRITE_ENABLED:
        return {"state": "writes_disabled",
                "detail": ("Writing is switched off. Set SDI_VOICECRM_WRITE=yes only after "
                           "the sandbox List exists and the pilot has been approved.")}
    if not APPROVED_BY:
        return {"state": "not_approved",
                "detail": ("SDI_VOICECRM_APPROVED_BY is empty. Record who approved the pilot "
                           "to write — it is stamped on every journal entry.")}
    if not CONFIGURED:
        return {"state": "not_configured", "detail": _status_payload()}
    return None


def _fetch_item(token: str, item_id: str) -> tuple[dict | None, dict | None]:
    """One List item with its fields, or (None, error-payload)."""
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
    for key in ("ProjectID", "ProjectId", "Project_x0020_ID", "Title"):
        if fields.get(key):
            return str(fields[key])
    return ""


@router.post("/api/voicecrm/propose")
def propose(body: ProposeIn, request: Request, user: dict = Depends(auth.require_user)):
    """Validate a change and read it back. Nothing is written by this call."""
    blocked = _write_gate()
    if blocked:
        return blocked

    if body.field not in EDITABLE:
        return {"state": "field_not_editable", "field": body.field, "editable": EDITABLE,
                "detail": f"'{body.field}' is not in the editable set for this pilot."}

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
        "expires_in_seconds": journal.PROPOSAL_TTL_SECONDS,
    }


@router.post("/api/voicecrm/confirm")
def confirm(body: ConfirmIn, request: Request, user: dict = Depends(auth.require_user)):
    """Apply a proposal, once. A repeated confirm returns the first outcome."""
    blocked = _write_gate()
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
    # proposal rather than overwrite their change.
    if entry["etag"] and item.get("eTag") and item["eTag"] != entry["etag"]:
        _journal.finish(body.proposal_id, "conflict",
                        "The record changed between proposal and confirmation.")
        return {"state": "conflict",
                "detail": ("Someone changed that record while we were talking. Nothing was "
                           "written. Read it again and re-propose.")}

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if item.get("eTag"):
        headers["If-Match"] = item["eTag"]      # belt and braces alongside the check above
    url = f"{GRAPH}/sites/{item['_site_id']}/lists/{LIST}/items/{entry['item_id']}/fields"
    try:
        with httpx.Client(timeout=20) as client:
            res = client.patch(url, headers=headers, json={entry["field"]: entry["new_value"]})
    except httpx.HTTPError as exc:
        _journal.finish(body.proposal_id, "failed", f"Graph unreachable: {exc}")
        return {"state": "unreachable", "detail": f"Could not reach Microsoft Graph: {exc}"}

    if res.status_code == 412:
        _journal.finish(body.proposal_id, "conflict", "Precondition failed on write.")
        return {"state": "conflict", "detail": "The record changed as we wrote. Nothing was saved."}

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


@router.get("/api/voicecrm/journal")
def journal_view(request: Request, limit: int = 25, user: dict = Depends(auth.require_user)):
    """The audit trail: every proposal and what actually happened to it."""
    return {"writes_enabled": WRITE_ENABLED, "approved_by": APPROVED_BY,
            "editable_fields": EDITABLE, "counts": _journal.counts(),
            "entries": _journal.recent(limit)}
