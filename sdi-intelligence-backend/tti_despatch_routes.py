"""The TTI tracker's six questions, read-only, for named Customer Services people.

Phase one answered one: "what is due to leave SDI on Thursday?". This adds the
five Selina Kuddus, Lee Merril and Sue Rogers asked for next - search, the
chase list, overdue-undated rows, the morning summary and data quality - all
from the same workbook, with no ERP integration behind any of them.

── WHAT THIS CANNOT DO, BY CONSTRUCTION ─────────────────────────────────────
There is no writer here. Nothing in this module opens Completed Orders, sends
mail, or changes a cell in either tracker. The transfer half of the pilot
(sue_despatch.propose_completed_transfer) is deliberately not mounted: it can
only describe a transfer, Completed Orders could not even be read when the
pilot was written, and what counts as "dispatched" is still Sue's to define.
The morning summary is produced as text and is NOT emailed: which mailbox it
leaves from, and who is on it, is Sue and Selina's decision, not this code's.

── THE CALLER NEVER NAMES A FILE ────────────────────────────────────────────
The workbook is configuration (SDI_TTI_PLAN_SITE / SDI_TTI_PLAN_PATH), not a
parameter. A request carries a date, or words to search for, and nothing that
is a location - so this is six questions about one known workbook rather than
a spreadsheet reader pointed wherever a URL says.
"""
import os
from datetime import date
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

import auth
import tti_data
import tti_files
from sue_despatch import going_out, going_out_week
from tti_search import (chase, data_quality, find, morning, overdue_undated,
                        summary_text)

PREFIX = "/api/tti"
PAGE = "tti-despatch.html"
_PAGE_HEADERS = {"Cache-Control": "no-store"}

# A search term is words, not a path. Long enough for an order number and a
# part code together, short enough that nobody pastes a file into it.
MAX_QUERY = 80


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

    def read(request) -> tti_data.Plan:
        """One reading of the plan, as the person asking. Their access decides."""
        try:
            return tti_data.rows_for(auth.graph_token(request))
        except tti_data.Unavailable as exc:
            # The reason travels as a header so the page can offer the next
            # step ("Find TTi files works without it") for an access answer.
            raise HTTPException(503, str(exc),
                                headers={"X-TTI-Reason": exc.reason} if exc.reason else None)

    def day_asked(day: str) -> date:
        try:
            return date.fromisoformat(day)
        except ValueError:
            raise HTTPException(400, "A date is needed, as YYYY-MM-DD.")

    def answered(plan: tti_data.Plan, answer: dict) -> JSONResponse:
        answer.update(plan.provenance())
        answer["source_version_date"] = plan.saved.date().isoformat()
        return JSONResponse(answer, headers=_PAGE_HEADERS)

    @router.get("/despatch")
    def despatch(request: Request):
        who(request)
        return FileResponse(str(page), headers=_PAGE_HEADERS)

    @router.get("/despatch/day")
    def leaving_on(request: Request, day: str = Query(..., max_length=10)):
        who(request)
        asked = day_asked(day)
        plan = read(request)
        return answered(plan, going_out(plan.rows, day=asked, as_of=plan.saved.date()))

    @router.get("/despatch/week")
    def leaving_this_week(request: Request, day: str = Query(..., max_length=10)):
        """Monday to Friday of the week `day` falls in, from one reading of the plan."""
        who(request)
        asked = day_asked(day)
        plan = read(request)
        return answered(plan, going_out_week(plan.rows, day=asked, as_of=plan.saved.date()))

    @router.get("/despatch/search")
    def search(request: Request, q: str = Query(..., max_length=MAX_QUERY)):
        who(request)
        if not q.strip():
            raise HTTPException(400, "Type an order number, customer PO, part code "
                                     "or TTI account to search for.")
        plan = read(request)
        return answered(plan, find(plan.rows, q, as_of=plan.saved.date()))

    @router.get("/despatch/chase")
    def chase_list(request: Request, horizon: int = Query(7, ge=0, le=90)):
        who(request)
        plan = read(request)
        return answered(plan, chase(plan.rows, as_of=plan.saved.date(),
                                    horizon=horizon))

    @router.get("/despatch/overdue")
    def overdue(request: Request):
        who(request)
        plan = read(request)
        return answered(plan, overdue_undated(plan.rows, as_of=plan.saved.date()))

    @router.get("/despatch/morning")
    def morning_summary(request: Request, day: str = Query("", max_length=10)):
        who(request)
        plan = read(request)
        asked = day_asked(day) if day.strip() else plan.saved.date()
        answer = morning(plan.rows, day=asked, as_of=plan.saved.date())
        answer["as_text"] = summary_text(answer)
        return answered(plan, answer)

    @router.get("/despatch/morning.txt", response_class=PlainTextResponse)
    def morning_as_text(request: Request, day: str = Query("", max_length=10)):
        """The same summary as plain text, to paste into an email.

        Deliberately not sent from here. The decision about which mailbox a
        daily despatch email leaves from, and who is on it, belongs to Sue and
        Selina - so this hands them the words and stops.
        """
        who(request)
        plan = read(request)
        asked = day_asked(day) if day.strip() else plan.saved.date()
        answer = morning(plan.rows, day=asked, as_of=plan.saved.date())
        return PlainTextResponse(summary_text(answer), headers=_PAGE_HEADERS)

    @router.get("/despatch/quality")
    def quality(request: Request):
        who(request)
        plan = read(request)
        return answered(plan, data_quality(plan.rows, as_of=plan.saved.date()))

    # ── Liam's TTi folders: Design, Production, Prototype ──────────────────
    # A search of an index of names, built on a schedule. Like everything
    # above it only reads, and the folders are configuration: a search
    # carries words, and opening carries only a path a search returned.
    @router.get("/despatch/files")
    def find_files(request: Request, q: str = Query(..., max_length=MAX_QUERY),
                   folder: str = Query("", max_length=40), kind: str = Query("", max_length=20)):
        who(request)
        try:
            answer = tti_files.search(q, folder=folder, kind=kind)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        except tti_files.NotReady as exc:
            raise HTTPException(503, str(exc))
        return JSONResponse(answer, headers=_PAGE_HEADERS)

    # Open one file a search found: a drawing on a phone, off site. Opened in a
    # new tab, so a person not signed in is sent to sign in and brought back,
    # rather than shown a 401. Only a file the index lists inside the three
    # folders; tti_files.locate says why anything else is refused.
    @router.get("/despatch/files/open")
    def open_file(request: Request, path: str = Query(..., max_length=1000)):
        if auth.ENABLED and auth.current_user(request) is None:
            return auth.login_redirect(request)
        who(request)
        try:
            found = tti_files.locate(path)
        except tti_files.NotFound as exc:
            raise HTTPException(404, str(exc))
        except tti_files.NotReady as exc:
            raise HTTPException(503, str(exc))
        user = auth.current_user(request) or {}
        print(f"[tti-files] opened by {user.get('email') or user.get('oid') or '?'}: "
              f"{path[:300]} ({found['size']} bytes)", flush=True)
        return FileResponse(found["unc"], media_type=found["media_type"], filename=found["name"],
                            content_disposition_type="inline" if found["inline"] else "attachment",
                            headers={"Cache-Control": "private, no-store",
                                     "X-Content-Type-Options": "nosniff"})

    @router.get("/despatch/files/status")
    def files_status(request: Request):
        who(request)
        try:
            return JSONResponse(tti_files.status(), headers=_PAGE_HEADERS)
        except tti_files.NotReady as exc:
            raise HTTPException(503, str(exc))

    return router


def install(app, env=None):
    """Mounted only when switched on, like the private assistant."""
    env = os.environ if env is None else env
    if env.get("SDI_TTI_ENABLED", "").lower() != "yes":
        return None
    app.include_router(make_router())
    return True
