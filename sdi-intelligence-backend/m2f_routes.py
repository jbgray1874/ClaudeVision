"""
Monday2Friday endpoints and pages.

Mount in app.py with two lines:
    from m2f_routes import router as m2f_router
    app.include_router(m2f_router)

Pages (no key needed: they hold no data, and fetch it with the key):
    GET /m2f                 the workspace
    GET /m2f/architecture    how it is built
    GET /m2f/guide           user guide

API (every call needs header  X-SDI-Key: <SDI_API_KEY>  when a key is set):
    GET  /api/m2f/status                 tracker source, load time, reconciliation
    PUT  /api/m2f/tracker                upload a tracker .xlsx (request body = the file)
    GET  /api/m2f/dashboard?asof=YYYY-MM director dashboard
    GET  /api/m2f/am/{name}              AM workspace
    GET  /api/m2f/pm/{name}              PM overview
    GET  /api/m2f/projects               all projects (?hidden=false for live only)
    GET  /api/m2f/projects/{pid}         one project with its forecast, issues, variations
    GET  /api/m2f/accounts               accounts and brands
    GET  /api/m2f/people                 people named in the tracker, with owners and deputies
    PUT  /api/m2f/assignments            set an owner, alias or deputy
    GET  /api/m2f/freezes                forecast freezes
    POST /api/m2f/freezes                freeze the forecast now
    GET  /api/m2f/review/{freeze_id}     weekly review: what moved since a freeze
    PUT  /api/m2f/review/{freeze_id}/notes/{pid}   reason and next action for a movement
    GET  /api/m2f/variations             variations register
    POST /api/m2f/variations             add a variation
    PATCH /api/m2f/variations/{id}       update a variation
    GET  /api/m2f/questions              open questions for Kayleigh, with evidence and answers
    PUT  /api/m2f/questions/{id}         record an answer
    GET  /api/m2f/issues                 everything the importer flagged

Settings (.env): M2F_TRACKER_PATH = UNC path of the tracker workbook;
M2F_DATA_DIR = folder for the pilot store and uploaded trackers.
"""
from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, Body, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse

import config
from m2f.service import Workspace

router = APIRouter(tags=["monday2friday"])
_HERE = Path(__file__).resolve().parent
_PAGES = _HERE / "m2f" / "web"
_MAX_UPLOAD = 25 * 1024 * 1024
_workspace: Workspace | None = None


def workspace() -> Workspace:
    global _workspace
    if _workspace is None:
        data_dir = os.getenv("M2F_DATA_DIR", "").strip() or str(_HERE / "m2f_data")
        _workspace = Workspace(os.getenv("M2F_TRACKER_PATH", "").strip() or None, data_dir)
    return _workspace


def set_workspace(ws: Workspace | None) -> None:
    """Used by tests to point the router at a temporary workspace."""
    global _workspace
    _workspace = ws


def _check_key(key: str | None) -> None:
    if config.API_KEY and key != config.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-SDI-Key")


def _ready(key: str | None) -> Workspace:
    _check_key(key)
    ws = workspace()
    if not ws.ready():
        raise HTTPException(status_code=409, detail=ws.error or "No tracker loaded yet.")
    return ws


def _page(name: str):
    path = _PAGES / name
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{name} is missing from m2f/web")
    return FileResponse(str(path), media_type="text/html")


# ── Pages ───────────────────────────────────────────────────────────────────
@router.get("/m2f", include_in_schema=False)
def page_app():
    return _page("index.html")


@router.get("/m2f/architecture", include_in_schema=False)
def page_architecture():
    return _page("architecture.html")


@router.get("/m2f/guide", include_in_schema=False)
def page_guide():
    return _page("guide.html")


# ── Tracker ─────────────────────────────────────────────────────────────────
@router.get("/api/m2f/status")
def status(x_sdi_key: str | None = Header(default=None)):
    _check_key(x_sdi_key)
    return workspace().status()


@router.put("/api/m2f/tracker")
async def upload_tracker(request: Request, x_sdi_key: str | None = Header(default=None)):
    _check_key(x_sdi_key)
    data = await request.body()
    if not data:
        raise HTTPException(status_code=400, detail="Send the .xlsx file as the request body.")
    if len(data) > _MAX_UPLOAD:
        raise HTTPException(status_code=413, detail="Tracker is larger than 25 MB.")
    ws = workspace()
    try:
        ws.save_upload(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if ws.error:
        raise HTTPException(status_code=422, detail=ws.error)
    return ws.status()


# ── Views ───────────────────────────────────────────────────────────────────
@router.get("/api/m2f/dashboard")
def dashboard(asof: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
              x_sdi_key: str | None = Header(default=None)):
    return _ready(x_sdi_key).dashboard(asof)


@router.get("/api/m2f/am/{name}")
def am_workspace(name: str, asof: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
                 x_sdi_key: str | None = Header(default=None)):
    return _ready(x_sdi_key).am_workspace(name, asof)


@router.get("/api/m2f/pm/{name}")
def pm_overview(name: str, asof: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
                x_sdi_key: str | None = Header(default=None)):
    return _ready(x_sdi_key).pm_overview(name, asof)


@router.get("/api/m2f/projects")
def projects(hidden: bool = True, x_sdi_key: str | None = Header(default=None)):
    return {"projects": _ready(x_sdi_key).project_rows(include_hidden=hidden)}


@router.get("/api/m2f/projects/{pid}")
def project(pid: str, x_sdi_key: str | None = Header(default=None)):
    detail = _ready(x_sdi_key).project_detail(pid)
    if detail is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return detail


@router.get("/api/m2f/accounts")
def accounts(asof: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
             x_sdi_key: str | None = Header(default=None)):
    return _ready(x_sdi_key).accounts(asof)


@router.get("/api/m2f/people")
def people(x_sdi_key: str | None = Header(default=None)):
    ws = _ready(x_sdi_key)
    return {"people": ws.people(), "assignments": ws.assignments()}


@router.put("/api/m2f/assignments")
def set_assignment(payload: dict = Body(...), x_sdi_key: str | None = Header(default=None)):
    ws = _ready(x_sdi_key)
    try:
        ws.set_assignment(payload.get("kind", ""), str(payload.get("subject", "")).strip(),
                          payload.get("person"), payload.get("by"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"assignments": ws.assignments()}


# ── Weekly review ───────────────────────────────────────────────────────────
@router.get("/api/m2f/freezes")
def freezes(x_sdi_key: str | None = Header(default=None)):
    return {"freezes": _ready(x_sdi_key).freezes()}


@router.post("/api/m2f/freezes")
def freeze(payload: dict = Body(default={}), x_sdi_key: str | None = Header(default=None)):
    return _ready(x_sdi_key).freeze(str(payload.get("label", "")), payload.get("by"))


@router.get("/api/m2f/review/{freeze_id}")
def review(freeze_id: int, asof: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$"),
           x_sdi_key: str | None = Header(default=None)):
    ws = _ready(x_sdi_key)
    result = ws.review(freeze_id, asof)
    if result["freeze"] is None:
        raise HTTPException(status_code=404, detail="Freeze not found")
    return result


@router.put("/api/m2f/review/{freeze_id}/notes/{pid}")
def review_note(freeze_id: int, pid: str, payload: dict = Body(...), x_sdi_key: str | None = Header(default=None)):
    ws = _ready(x_sdi_key)
    ws.save_note(freeze_id, pid, payload.get("reason"), payload.get("next_action"), payload.get("owner"),
                 payload.get("by"))
    return {"saved": True}


# ── Variations ──────────────────────────────────────────────────────────────
@router.get("/api/m2f/variations")
def variations(open_only: bool = False, x_sdi_key: str | None = Header(default=None)):
    return {"variations": _ready(x_sdi_key).variations(open_only)}


@router.post("/api/m2f/variations", status_code=201)
def add_variation(payload: dict = Body(...), x_sdi_key: str | None = Header(default=None)):
    try:
        return _ready(x_sdi_key).save_variation(payload, payload.get("by"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/api/m2f/variations/{vid}")
def update_variation(vid: int, payload: dict = Body(...), x_sdi_key: str | None = Header(default=None)):
    try:
        return _ready(x_sdi_key).save_variation(payload, payload.get("by"), vid)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except KeyError:
        raise HTTPException(status_code=404, detail="Variation not found")


# ── Open questions and issues ───────────────────────────────────────────────
@router.get("/api/m2f/questions")
def questions(x_sdi_key: str | None = Header(default=None)):
    return {"questions": _ready(x_sdi_key).questions()}


@router.put("/api/m2f/questions/{qid}")
def answer(qid: str, payload: dict = Body(...), x_sdi_key: str | None = Header(default=None)):
    ws = _ready(x_sdi_key)
    try:
        ws.record_decision(qid, payload.get("choice"), payload.get("answer"), payload.get("by"))
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown question")
    return {"questions": ws.questions()}


@router.get("/api/m2f/issues")
def issues(code: str | None = None, x_sdi_key: str | None = Header(default=None)):
    ws = _ready(x_sdi_key)
    return {"issues": [asdict(i) for i in ws.result.issues if code is None or i.code == code]}
