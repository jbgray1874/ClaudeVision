"""
Monday2Friday endpoints and pages.

Mount in app.py with two lines:
    from m2f_routes import router as m2f_router
    app.include_router(m2f_router)

Pages (sign-in required, like every other SDI Intelligence page):
    GET /m2f                 the workspace
    GET /m2f/architecture    how it is built
    GET /m2f/guide           user guide

API (a signed-in person, or a machine with X-SDI-Key while the key is allowed;
see auth.py). Changes are recorded under the signed-in person's name.
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

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse

import auth
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


_PAGE_HEADERS = {"Cache-Control": "no-store, must-revalidate"}
Who = Depends(auth.require_user)
Month = Query(default=None, pattern=r"^\d{4}-\d{2}$")


def _by(user: dict, payload: dict) -> str | None:
    """The signed-in person's name. Only when nobody is signed in (SSO off, or the
    office network) does the name typed into the page stand in for it."""
    if user.get("kind") == "user":
        return user.get("name")
    typed = str(payload.get("by") or "").strip()
    return typed or user.get("name")


def _ready() -> Workspace:
    ws = workspace()
    if not ws.ready():
        raise HTTPException(status_code=409, detail=ws.error or "No tracker loaded yet.")
    return ws


def _page(request: Request, name: str):
    if auth.current_user(request) is None:
        return auth.login_redirect(request)
    path = _PAGES / name
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{name} is missing from m2f/web")
    return FileResponse(str(path), media_type="text/html", headers=_PAGE_HEADERS)


# ── Pages ───────────────────────────────────────────────────────────────────
@router.get("/m2f", include_in_schema=False)
def page_app(request: Request):
    return _page(request, "index.html")


@router.get("/m2f/architecture", include_in_schema=False)
def page_architecture(request: Request):
    return _page(request, "architecture.html")


@router.get("/m2f/guide", include_in_schema=False)
def page_guide(request: Request):
    return _page(request, "guide.html")


# ── Tracker ─────────────────────────────────────────────────────────────────
@router.get("/api/m2f/status")
def status(user: dict = Who):
    return {**workspace().status(), "user": user.get("name")}


@router.put("/api/m2f/tracker")
async def upload_tracker(request: Request, user: dict = Who):
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
def dashboard(asof: str | None = Month, user: dict = Who):
    return _ready().dashboard(asof)


@router.get("/api/m2f/am/{name}")
def am_workspace(name: str, asof: str | None = Month, user: dict = Who):
    return _ready().am_workspace(name, asof)


@router.get("/api/m2f/pm/{name}")
def pm_overview(name: str, asof: str | None = Month, user: dict = Who):
    return _ready().pm_overview(name, asof)


@router.get("/api/m2f/projects")
def projects(hidden: bool = True, user: dict = Who):
    return {"projects": _ready().project_rows(include_hidden=hidden)}


@router.get("/api/m2f/projects/{pid}")
def project(pid: str, user: dict = Who):
    detail = _ready().project_detail(pid)
    if detail is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return detail


@router.get("/api/m2f/accounts")
def accounts(asof: str | None = Month, user: dict = Who):
    return _ready().accounts(asof)


@router.get("/api/m2f/people")
def people(user: dict = Who):
    ws = _ready()
    return {"people": ws.people(), "assignments": ws.assignments()}


@router.put("/api/m2f/assignments")
def set_assignment(payload: dict = Body(...), user: dict = Who):
    ws = _ready()
    try:
        ws.set_assignment(payload.get("kind", ""), str(payload.get("subject", "")).strip(),
                          payload.get("person"), _by(user, payload))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"assignments": ws.assignments()}


# ── Weekly review ───────────────────────────────────────────────────────────
@router.get("/api/m2f/freezes")
def freezes(user: dict = Who):
    return {"freezes": _ready().freezes()}


@router.post("/api/m2f/freezes")
def freeze(payload: dict = Body(default={}), user: dict = Who):
    return _ready().freeze(str(payload.get("label", "")), _by(user, payload))


@router.get("/api/m2f/review/{freeze_id}")
def review(freeze_id: int, asof: str | None = Month, user: dict = Who):
    ws = _ready()
    result = ws.review(freeze_id, asof)
    if result["freeze"] is None:
        raise HTTPException(status_code=404, detail="Freeze not found")
    return result


@router.put("/api/m2f/review/{freeze_id}/notes/{pid}")
def review_note(freeze_id: int, pid: str, payload: dict = Body(...), user: dict = Who):
    ws = _ready()
    ws.save_note(freeze_id, pid, payload.get("reason"), payload.get("next_action"), payload.get("owner"),
                 _by(user, payload))
    return {"saved": True}


# ── Variations ──────────────────────────────────────────────────────────────
@router.get("/api/m2f/variations")
def variations(open_only: bool = False, user: dict = Who):
    return {"variations": _ready().variations(open_only)}


@router.post("/api/m2f/variations", status_code=201)
def add_variation(payload: dict = Body(...), user: dict = Who):
    try:
        return _ready().save_variation(payload, _by(user, payload))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/api/m2f/variations/{vid}")
def update_variation(vid: int, payload: dict = Body(...), user: dict = Who):
    try:
        return _ready().save_variation(payload, _by(user, payload), vid)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except KeyError:
        raise HTTPException(status_code=404, detail="Variation not found")


# ── Open questions and issues ───────────────────────────────────────────────
@router.get("/api/m2f/questions")
def questions(user: dict = Who):
    return {"questions": _ready().questions()}


@router.put("/api/m2f/questions/{qid}")
def answer(qid: str, payload: dict = Body(...), user: dict = Who):
    ws = _ready()
    try:
        ws.record_decision(qid, payload.get("choice"), payload.get("answer"), _by(user, payload))
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown question")
    return {"questions": ws.questions()}


@router.get("/api/m2f/issues")
def issues(code: str | None = None, user: dict = Who):
    ws = _ready()
    return {"issues": [asdict(i) for i in ws.result.issues if code is None or i.code == code]}
