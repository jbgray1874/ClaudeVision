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

from fastapi import APIRouter, Body, Header, HTTPException, Request

import config
try:
    from service_config import the_service_config
except ImportError:                    # loaded by path, without this folder on sys.path
    import importlib.util as _ilu
    import pathlib as _pl
    _scs = _ilu.spec_from_file_location("service_config", _pl.Path(__file__).with_name("service_config.py"))
    _scm = _ilu.module_from_spec(_scs)
    _scs.loader.exec_module(_scm)
    the_service_config = _scm.the_service_config
config = the_service_config(config)   # this service's, even where the engine's holds the name
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
    try:
        return hr_blip.run_blip()
    except RuntimeError as exc:
        # e.g. BrightHR's staff list could not be read: the portal prints the
        # reason rather than a bare 500.
        raise HTTPException(status_code=502, detail=str(exc))


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
    who = auth.current_user(request) or {}
    by = "intranet portal" + (f" ({who['email']})" if who.get("email") else "")
    try:
        return hr_onsite_push.run_push(apply=apply, force=force, source=source, by=by)
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
# One job running at a time, and the last result of each kind kept, so a data
# issues report does not replace the last check on screen.
_app_state = {"running": None, "last": {}}
_APP_KINDS = ("check", "update", "issues")


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


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


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


def _run_app_job(kind: str, user: dict):
    import hr_history
    import hr_inventry_api as api
    who = f"HRInventry Anywhere ({user.get('email') or user.get('name')})"
    result, error = {}, None
    try:
        if kind == "issues":
            staff = hr_blip._current_staff(hr_blip._get_token())
            result["issues"] = hr_onsite_push.data_issues(staff, api.InVentryAPI().get_personnel())
        else:
            blip = hr_blip.run_blip()
            result["blip"] = {k: blip.get(k) for k in
                              ("timestamp", "status", "on_site", "employees_checked",
                               "query_failures", "warnings")}
            if blip.get("status") != "busy":
                result["clocked_in"] = _clocked_in_now()
            if kind == "check":
                hr_history.record({"time": _now_iso(), "kind": "check", "by": who,
                                   "status": blip.get("status"),
                                   "brighthr_on_site": blip.get("on_site"),
                                   "staff_checked": blip.get("employees_checked")})
            elif blip.get("status") == "busy":
                result["not_updated"] = (blip.get("warnings") or ["BrightHR check busy"])[0]
            else:
                # The push applies its own guards: a degraded or stale check is
                # refused there, with the reason in its warnings. It also writes
                # its own history line.
                result["push"] = hr_onsite_push.run_push(apply=True, by=who)
    except Exception as exc:             # reported to the app, not lost in a thread
        error = str(exc) or exc.__class__.__name__
    with _app_lock:
        job = dict(_app_state["running"] or {}, kind=kind)
        job.update(state="error" if error else "done", error=error, result=result,
                   finished=_now_iso())
        _app_state["last"][kind] = job
        _app_state["running"] = None


def _start_app_job(kind: str, user: dict) -> dict:
    with _app_lock:
        running = _app_state["running"]
        if running:
            raise HTTPException(status_code=409, detail=(
                f"{running.get('by') or 'Someone'} started a {running.get('kind')} at "
                f"{(running.get('started') or '')[11:16]} UTC. Wait for it to finish."))
        _app_state["running"] = {"state": "running", "kind": kind, "by": user.get("name", ""),
                                 "started": _now_iso()}
    # Who pressed what, in the same log as the runs themselves.
    hr_blip._log(f"APP {kind} started by {user.get('email') or user.get('name')}")
    threading.Thread(target=_run_app_job, args=(kind, user), daemon=True).start()
    return _app_status_payload(user)


def _app_status_payload(user: dict) -> dict:
    with _app_lock:
        return {"user": user.get("name", ""),
                "running": dict(_app_state["running"]) if _app_state["running"] else None,
                "last": {k: dict(v) for k, v in _app_state["last"].items()}}


@router.get("/app/status")
def app_status(request: Request):
    """Who is signed in, any job running, and the last result of each kind."""
    return _app_status_payload(_app_user(request))


@router.post("/app/check")
def app_check(request: Request):
    """Ask BrightHR who is clocked in. Changes nothing in InVentry."""
    return _start_app_job("check", _app_user(request))


@router.post("/app/update")
def app_update(request: Request):
    """Ask BrightHR, then sign people in and out of InVentry to match."""
    return _start_app_job("update", _app_user(request))


@router.post("/app/issues")
def app_issues(request: Request):
    """Duplicates, shared emails and unmatched staff between BrightHR and
    InVentry, for whoever tidies the data. Changes nothing."""
    return _start_app_job("issues", _app_user(request))


def _inventry_on_site():
    """Who InVentry shows on site now, or (None, reason) if it is not answering."""
    import hr_inventry_api as api
    try:
        people = api.InVentryAPI().get_personnel()
    except api.InVentryAPIError as exc:
        return None, f"InVentry did not answer ({exc}), so this list is from BrightHR only."
    return [{"name": f"{api._field(r, 'FirstName')} {api._field(r, 'Surname')}".strip() or "?",
             "since": str(api._field(r, "LastActivityDate") or ""),
             "by": "sync" if api.signed_in_by_us(r) else "reception"}
            for r in people if api.is_on_site(r)], None


def _rollcall_payload() -> dict:
    import hr_rollcall
    on_site, inventry_problem = _inventry_on_site()
    try:
        snap = json.loads((Path(cfg.HR_SNAPSHOT_DIR) / "blip_latest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        snap = None
    people, forgotten = hr_rollcall.build(on_site, snap)
    st = hr_rollcall.state()
    for p in people:
        p["ticked"] = st["ticks"].get(p["key"])
    return {"time": _now_iso(), "people": people, "count": len(people),
            "accounted": sum(1 for p in people if p["ticked"]),
            "started": st.get("started"), "started_by": st.get("started_by"),
            "inventry_problem": inventry_problem,
            "brighthr_checked": ((snap or {}).get("summary") or {}).get("timestamp"),
            "forgotten_left_out": forgotten}


@router.get("/app/rollcall")
def app_rollcall(request: Request):
    """The fire roll call: InVentry's on-site list and BrightHR's clocked-in
    list merged, with the shared ticks. Answers directly, in seconds: in an
    evacuation nobody waits for a job. Read-only towards InVentry and BrightHR."""
    _app_user(request)
    return _rollcall_payload()


@router.post("/app/rollcall/tick")
def app_rollcall_tick(request: Request, payload: dict = Body(...)):
    """Tick (or untick) one person as accounted for. Shared by every phone."""
    user = _app_user(request)
    import hr_rollcall
    key = str(payload.get("key") or "").strip()
    if not key:
        raise HTTPException(status_code=400, detail="Which person? No key was sent.")
    st = hr_rollcall.tick(key, bool(payload.get("ticked")), user.get("name") or user.get("email", ""))
    return {"key": key, "ticked": st["ticks"].get(key)}


@router.post("/app/rollcall/new")
def app_rollcall_new(request: Request):
    """Clear every tick and start a new roll call."""
    user = _app_user(request)
    import hr_rollcall
    hr_rollcall.start_new(user.get("name") or user.get("email", ""))
    hr_blip._log(f"APP roll call started by {user.get('email') or user.get('name')}")
    return _rollcall_payload()


@router.get("/app/history")
def app_history(request: Request, n: int = 30):
    """The latest checks and updates: who, when, and who was signed in or out."""
    _app_user(request)
    import hr_history
    return {"entries": hr_history.recent(max(1, min(n, 200)))}
