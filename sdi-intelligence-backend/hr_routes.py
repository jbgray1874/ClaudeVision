"""
HR endpoints for the intranet (BrightHR -> InVentry).

Mount in app.py with two lines:
    from hr_routes import router as hr_router
    app.include_router(hr_router)

Endpoints (all require header  X-SDI-Key: <SDI_API_KEY>):
    POST /api/hr/pull     pull from BrightHR -> store snapshot on disk
    POST /api/hr/load     load latest good snapshot -> InVentry CSV
    POST /api/hr/sync     pull then load (the COO's one-click button)
    GET  /api/hr/status   last pull + load summary (for the portal panel)
"""
import json
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException

import config            # backend config (for the shared API key)
import hr_config as cfg
import hr_pull
import hr_load_inventry

router = APIRouter(prefix="/api/hr", tags=["hr"])


def _check_key(key):
    if config.API_KEY and key != config.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-SDI-Key")


@router.post("/pull")
def pull(x_sdi_key: str | None = Header(default=None)):
    _check_key(x_sdi_key)
    return hr_pull.run_pull()


@router.post("/load")
def load(x_sdi_key: str | None = Header(default=None)):
    _check_key(x_sdi_key)
    return hr_load_inventry.run_load()


@router.post("/sync")
def sync(x_sdi_key: str | None = Header(default=None)):
    """On demand: pull -> store -> load into InVentry. The COO button."""
    _check_key(x_sdi_key)
    pull_summary = hr_pull.run_pull()
    if pull_summary["status"] == "aborted":
        return {"pull": pull_summary,
                "load": {"status": "skipped", "reason": "pull aborted by safety guard"}}
    load_summary = hr_load_inventry.run_load()
    return {"pull": pull_summary, "load": load_summary}


@router.get("/status")
def status(x_sdi_key: str | None = Header(default=None)):
    _check_key(x_sdi_key)
    p = Path(cfg.HR_SNAPSHOT_DIR) / "hr_status.json"
    if not p.exists():
        return {"pull": None, "load": None}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return {"error": "status file unreadable"}


# ── Blip attendance endpoints ─────────────────────────────────────────────────
import hr_blip

@router.post("/blip")
def blip(x_sdi_key: str | None = Header(default=None)):
    """Query current Blip clockings — who is on site right now."""
    _check_key(x_sdi_key)
    return hr_blip.run_blip()


@router.get("/blip/latest")
def blip_latest(x_sdi_key: str | None = Header(default=None)):
    """Return the latest Blip snapshot without re-querying BrightHR."""
    _check_key(x_sdi_key)
    p = Path(cfg.HR_SNAPSHOT_DIR) / "blip_latest.json"
    if not p.exists():
        return {"on_site": [], "summary": None,
                "note": "No Blip snapshot yet — POST /api/hr/blip to run"}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return {"error": "blip_latest.json unreadable"}


# ── Blip -> InVentry presence load (stage 3) ─────────────────────────────────
import hr_blip_inventry


@router.post("/blip/load")
def blip_load(force: bool = False, dry_run: bool = False,
              x_sdi_key: str | None = Header(default=None)):
    """Write the latest on-site list to the InVentry watched folder.

    dry_run writes the CSV beside the snapshot instead of into the watched
    folder — use it until InVentry confirm the presence import.
    """
    _check_key(x_sdi_key)
    return hr_blip_inventry.run_blip_load(force=force, dry_run=dry_run)


@router.post("/blip/sync")
def blip_sync(force: bool = False, dry_run: bool = False,
              x_sdi_key: str | None = Header(default=None)):
    """Query Blip then load the result into InVentry — the COO's one click."""
    _check_key(x_sdi_key)
    blip_summary = hr_blip.run_blip()
    if blip_summary.get("status") not in ("ok", "degraded"):
        return {"blip": blip_summary,
                "load": {"status": "skipped", "reason": "Blip query failed"}}
    load_summary = hr_blip_inventry.run_blip_load(force=force, dry_run=dry_run)
    return {"blip": blip_summary, "load": load_summary}
