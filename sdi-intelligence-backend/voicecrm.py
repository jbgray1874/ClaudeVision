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

import auth

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
        "writes_enabled": False,
        "write_note": ("Read-only by design. Writing requires the confirm-and-journal "
                       "loop and a separate approval."),
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
