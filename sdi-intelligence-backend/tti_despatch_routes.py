"""Sue's TTI despatch question, read-only, for named Customer Services people.

Phase one of the TTI app: "what is due to leave SDI on Thursday?", answered
from the Despatch Plan with the sheet and row it came from.

── WHAT THIS CANNOT DO, BY CONSTRUCTION ─────────────────────────────────────
There is no writer here. Nothing in this module opens Completed Orders, sends
mail, or changes a cell in either tracker. The transfer half of the pilot
(sue_despatch.propose_completed_transfer) is deliberately not mounted: it can
only describe a transfer, Completed Orders could not even be read when the
pilot was written, and what counts as "dispatched" is still Sue's to define.

── THE CALLER NEVER NAMES A FILE ────────────────────────────────────────────
The workbook is configuration (SDI_TTI_DESPATCH_PLAN), not a parameter. A
request carries a date and nothing else, so this is one question about one
known workbook rather than a spreadsheet reader pointed wherever a URL says.
"""
import os
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse

import auth
import tti_plan_source as plan
from sue_despatch import going_out
from tracker_snapshot import load_schedule_snapshot, read_schedule_bytes

PREFIX = "/api/tti"
PAGE = "tti-despatch.html"
_PAGE_HEADERS = {"Cache-Control": "no-store"}


def plan_path() -> str:
    return (os.getenv("SDI_TTI_DESPATCH_PLAN", "") or "").strip()


def allowed(request) -> bool:
    """Named Customer Services people, by Entra object ID. Never a shared key:
    this reads a live commercial tracker, so every read is attributable."""
    named = {v.strip().lower() for v in
             os.getenv("SDI_TTI_OIDS", "").split(",") if v.strip()}
    user = auth.current_user(request) if auth.ENABLED else None
    return bool(named and user and user.get("kind") == "user"
                and str(user.get("oid") or "").lower() in named)


def make_router(page_dir=None):
    router = APIRouter(prefix=PREFIX)
    page = Path(page_dir or Path(__file__).parent) / "appportal" / PAGE
    if not page.is_file():
        raise RuntimeError(f"{PAGE} must be deployed with the code; looked in {page.parent}")

    def who(request):
        if not allowed(request):
            raise HTTPException(403, "The TTI despatch view is for named Customer "
                                     "Services people. Ask IT to be added.")

    @router.get("/despatch")
    def despatch(request: Request):
        who(request)
        return FileResponse(str(page), headers=_PAGE_HEADERS)

    @router.get("/despatch/day")
    def leaving_on(request: Request, day: str = Query(..., max_length=10)):
        who(request)
        try:
            asked = date.fromisoformat(day)
        except ValueError:
            raise HTTPException(400, "A date is needed, as YYYY-MM-DD.")
        # SharePoint is the verified source. A local snapshot path stays
        # supported for a machine with no Graph access, and is never the
        # default: a file of unknown freshness answering a despatch question
        # is worse than no answer.
        where = plan_path()
        if plan.configured():
            try:
                data, saved, version = plan.fetch_plan(auth.graph_token(request))
            except plan.PlanUnavailable as exc:
                raise HTTPException(503, str(exc))
            try:
                digest, rows = read_schedule_bytes(data)
            except ValueError as exc:
                raise HTTPException(409, f"The Despatch Plan could not be read: {exc}")
        elif where:
            try:
                digest, rows = load_schedule_snapshot(where)
            except ValueError as exc:
                raise HTTPException(409, f"The Despatch Plan could not be read: {exc}")
            except OSError:
                raise HTTPException(503, "The Despatch Plan is not reachable from "
                                         "this service just now.")
            # The file's own last-modified time, not the hour this ran.
            try:
                saved = datetime.fromtimestamp(Path(where).stat().st_mtime, timezone.utc)
            except OSError:
                saved = datetime.now(timezone.utc)
            version = ""
        else:
            raise HTTPException(503, "The Despatch Plan has not been configured. Set "
                                     "SDI_TTI_PLAN_SITE and SDI_TTI_PLAN_PATH for the "
                                     "SharePoint workbook.")
        answer = going_out(rows, day=asked, as_of=saved.date())
        answer["plan_saved"] = saved.isoformat()
        answer["plan_version"] = (version or digest)[:16]
        answer["rows_read"] = len(rows)
        return JSONResponse(answer, headers=_PAGE_HEADERS)

    return router


def install(app, env=None):
    """Mounted only when switched on, like the private assistant."""
    env = os.environ if env is None else env
    if env.get("SDI_TTI_ENABLED", "").lower() != "yes":
        return None
    app.include_router(make_router())
    return True
