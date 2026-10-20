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

from fastapi import APIRouter, Header, HTTPException, Request

import config
import auth              # Entra SSO — a signed-in person counts as authorised
import hr_config as cfg
import hr_pull
import hr_load_inventry

router = APIRouter(prefix="/api/hr", tags=["hr"])


def _check_key(key, request=None):
    """A signed-in person, or a machine presenting the shared key.

    These endpoints write the InVentry CSV, so once the scheduled task has its
    own identity, SDI_ALLOW_API_KEY=no closes the shared-key route.
    """
    if request is not None and auth.ENABLED and auth.current_user(request) is not None:
        return
    if config.API_KEY and key != config.API_KEY:
        raise HTTPException(status_code=401, detail="Sign in, or present a valid X-SDI-Key")


@router.post("/pull")
def pull(request: Request, x_sdi_key: str | None = Header(default=None)):
    _check_key(x_sdi_key, request)
    return hr_pull.run_pull()


@router.post("/load")
def load(request: Request, x_sdi_key: str | None = Header(default=None)):
    _check_key(x_sdi_key, request)
    return hr_load_inventry.run_load()


@router.post("/sync")
def sync(request: Request, x_sdi_key: str | None = Header(default=None)):
    """On demand: pull -> store -> load into InVentry. The COO button."""
    _check_key(x_sdi_key, request)
    pull_summary = hr_pull.run_pull()
    if pull_summary["status"] == "aborted":
        return {"pull": pull_summary,
                "load": {"status": "skipped", "reason": "pull aborted by safety guard"}}
    load_summary = hr_load_inventry.run_load()
    return {"pull": pull_summary, "load": load_summary}


@router.get("/status")
def status(request: Request, x_sdi_key: str | None = Header(default=None)):
    _check_key(x_sdi_key, request)
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
def blip(request: Request, x_sdi_key: str | None = Header(default=None)):
    """Query current Blip clockings — who is on site right now."""
    _check_key(x_sdi_key, request)
    return hr_blip.run_blip()


@router.get("/blip/latest")
def blip_latest(request: Request, x_sdi_key: str | None = Header(default=None)):
    """Return the latest Blip snapshot without re-querying BrightHR."""
    _check_key(x_sdi_key, request)
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
def blip_load(request: Request, force: bool = False, dry_run: bool = False, source: str = "latest",
              x_sdi_key: str | None = Header(default=None)):
    """Write the current on-site list to the InVentry watched folder.

    source: "latest" (snapshot, keeps emails), "output" (the on-site JSON the
    portal Files view exposes, emails recovered from the roster), or a path.
    dry_run writes the CSV beside the snapshot instead of into the watched
    folder — use it until InVentry confirm the presence import.
    """
    _check_key(x_sdi_key, request)
    return hr_blip_inventry.run_blip_load(force=force, dry_run=dry_run, source=source)


@router.post("/blip/sync")
def blip_sync(request: Request, force: bool = False, dry_run: bool = False, source: str = "latest",
              x_sdi_key: str | None = Header(default=None)):
    """Query Blip then load the result into InVentry — the COO's one click."""
    _check_key(x_sdi_key, request)
    blip_summary = hr_blip.run_blip()
    if blip_summary.get("status") not in ("ok", "degraded"):
        return {"blip": blip_summary,
                "load": {"status": "skipped", "reason": "Blip query failed"}}
    load_summary = hr_blip_inventry.run_blip_load(force=force, dry_run=dry_run, source=source)
    return {"blip": blip_summary, "load": load_summary}


# ── Blip -> InVentry presence push over the Partner API (stage 3, API route) ──
import hr_onsite_push


@router.get("/inventry/check")
def inventry_check(request: Request, x_sdi_key: str | None = Header(default=None)):
    """Read-only check of the InVentry Partner API. Writes nothing.

    Confirms the base URL, credentials and TLS setup work, and reports how many
    personnel records already carry our PersonID.
    """
    _check_key(x_sdi_key, request)
    import hr_inventry_api
    try:
        return hr_inventry_api.InVentryAPI().check()
    except hr_inventry_api.InVentryAPIError as exc:
        return {"status": "error", "detail": str(exc)}


@router.post("/blip/push")
def blip_push(request: Request, apply: bool = False, force: bool = False, source: str = "latest",
              x_sdi_key: str | None = Header(default=None)):
    """Push the current on-site list into InVentry via the Partner API.

    Defaults to a dry run: the plan is logged and returned, nothing is sent.
    Pass apply=true to write. source is as for /blip/load.
    """
    _check_key(x_sdi_key, request)
    try:
        return hr_onsite_push.run_push(apply=apply, force=force, source=source)
    except RuntimeError as exc:
        # "No Blip snapshot — run the Blip query first" and its kind: a reason the portal
        # can print, not a 500 the button reports as a bare status code.
        return {"status": "error", "detail": str(exc), "dry_run": not apply,
                "warnings": [str(exc)]}


# ── HRInventry Anywhere (app portal, reachable from outside the office) ─────
#
# A BrightHR check takes minutes and the App Proxy cuts a request off after
# about 85 seconds, so the app starts a job here and polls for it. One job at a
# time in this process; the Blip lock still keeps it apart from a scheduled run.
#
# Who is in the building is personal data, and an update writes to the fire
# roll call, so these need a signed-in person on SDI_HR_APP_USERS: not the
# shared key, and not the office network's unsigned access.
import datetime
import threading

_app_lock = threading.Lock()
_app_job = {"state": "idle"}


def _app_user(request: Request) -> dict:
    user = auth.current_user(request)
    if user is None or user.get("kind") != "user":
        raise HTTPException(status_code=401,
                            detail="Sign in with your SDI Microsoft account to use this app.")
    if str(user.get("email", "")).strip().lower() not in cfg.HR_APP_USERS:
        raise HTTPException(status_code=403,
                            detail="Your account is not on this app's list. Ask IT to add you "
                                   "to SDI_HR_APP_USERS.")
    return user


def _clocked_in_now() -> list:
    """Names and clock-in times from the snapshot the check just wrote."""
    p = Path(cfg.HR_SNAPSHOT_DIR) / "blip_latest.json"
    try:
        snap = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    people = [{"name": f"{r.get('first_name', '')} {r.get('surname', '')}".strip() or "?",
               "clocked_in": (r.get("clocking") or {}).get("start", "")}
              for r in snap.get("on_site") or []]
    return sorted(people, key=lambda x: x["name"].lower())


def _run_app_job(kind: str):
    result, error = {}, None
    try:
        blip = hr_blip.run_blip()
        result["blip"] = {k: blip.get(k) for k in
                          ("timestamp", "status", "on_site", "employees_checked",
                           "query_failures", "warnings")}
        if blip.get("status") != "busy":
            result["clocked_in"] = _clocked_in_now()
        if kind == "update":
            if blip.get("status") == "busy":
                result["not_updated"] = (blip.get("warnings") or ["BrightHR check busy"])[0]
            else:
                # The push applies its own guards: a degraded or stale check is
                # refused there, with the reason in its warnings.
                result["push"] = hr_onsite_push.run_push(apply=True)
    except Exception as exc:             # reported to the app, not lost in a thread
        error = str(exc) or exc.__class__.__name__
    with _app_lock:
        _app_job.update(state="error" if error else "done", error=error, result=result,
                        finished=datetime.datetime.now(datetime.timezone.utc).isoformat())


def _start_app_job(kind: str, user: dict) -> dict:
    with _app_lock:
        if _app_job.get("state") == "running":
            raise HTTPException(status_code=409, detail=(
                f"{_app_job.get('by') or 'Someone'} started a {_app_job.get('kind')} at "
                f"{(_app_job.get('started') or '')[11:16]} UTC. Wait for it to finish."))
        _app_job.clear()
        _app_job.update(state="running", kind=kind, by=user.get("name", ""),
                        started=datetime.datetime.now(datetime.timezone.utc).isoformat())
    # Who pressed what, in the same log as the runs themselves.
    hr_blip._log(f"APP {kind} started by {user.get('email') or user.get('name')}")
    threading.Thread(target=_run_app_job, args=(kind,), daemon=True).start()
    return _app_status_payload(user)


def _app_status_payload(user: dict) -> dict:
    with _app_lock:
        job = dict(_app_job)
    return {"user": user.get("name", ""), "job": job}


@router.get("/app/status")
def app_status(request: Request):
    """Who is signed in, and the current or last job with its result."""
    return _app_status_payload(_app_user(request))


@router.post("/app/check")
def app_check(request: Request):
    """Ask BrightHR who is clocked in. Changes nothing in InVentry."""
    return _start_app_job("check", _app_user(request))


@router.post("/app/update")
def app_update(request: Request):
    """Ask BrightHR, then sign people in and out of InVentry to match."""
    return _start_app_job("update", _app_user(request))
