"""Optional portal adapter. No routes mounted until explicitly integrated.

Uses only the host's verified session; never accepts user identity from JSON.
"""
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from private_email import Denied, DraftStore, GraphMailbox


class Proposal(BaseModel):
    message_id: str = Field(min_length=1, max_length=2048)
    body: str = Field(min_length=1, max_length=20000)


class Confirmation(BaseModel):
    proposal_id: str
    digest: str


READONLY_PAGE = "private-email-readonly.html"
DRAFT_PAGE = "private-email.html"


def make_router(auth, policy, database, origin, drafts_enabled=False, page_dir=None):
    router = APIRouter(prefix="/api/private-email")
    # ── THE PAGE IS CHECKED AT STARTUP, NOT AT THE FIRST REQUEST ────────────────
    # Which page is served is the difference between a reader and a screen with a
    # Save Draft button, so it is settled when the router is built: a page that was
    # not deployed alongside the code stops the service starting, rather than
    # mounting the routes and failing later at a 404 that looks like a bad URL.
    # page_dir exists so the draft tests can supply a stub page without one being
    # shipped. Production never passes it: the page lives beside this module.
    page = Path(page_dir or Path(__file__).parent) / (DRAFT_PAGE if drafts_enabled else READONLY_PAGE)
    if not page.is_file():
        raise RuntimeError(
            f"{page.name} is not beside private_email_routes.py. "
            + ("Draft saving is not part of this release: deploy with drafts_enabled=False."
               if drafts_enabled else "The read-only page must be deployed with the code."))
    store = DraftStore(database) if drafts_enabled else None

    def context(request, mutation=False):
        user = auth.current_user(request)
        try:
            policy.check(user)
        except Denied as exc:
            raise HTTPException(403, str(exc))
        if mutation and (not origin.startswith("https://") or
                         request.headers.get("origin") != origin or
                         request.headers.get("x-sdi-private-action") != "1"):
            raise HTTPException(403, "Same-origin confirmation required")
        token = auth.graph_token(request)
        if not token:
            raise HTTPException(403, "Mailbox consent required; ask the administrator before changing scopes")

        def transport(method, url, **kwargs):
            try:
                with httpx.Client(timeout=30, follow_redirects=False) as client:
                    response = client.request(method, url, headers={"Authorization": "Bearer " + token}, **kwargs)
                # A REFUSAL IS NOT AN OUTAGE. 401 and 403 are what a missing consent, a
                # withdrawn permission or an expired token look like, and calling that
                # "Graph unavailable" sends somebody to check the network when the answer
                # is in Entra. Said plainly here, and in no more detail than that: Graph's
                # own body can carry request ids and tenant detail, so it goes to the
                # service log for the administrator, never to the browser.
                if response.status_code in (401, 403):
                    print(f"[private-email] Graph refused {method} {urlsplit(url).path}: "
                          f"{response.status_code} {response.text[:300]}", flush=True)
                    raise HTTPException(403, "Microsoft refused access to the mailbox. Sign in "
                                             "again; if it keeps happening the private app's "
                                             "Mail.Read consent needs checking.")
                if response.status_code >= 300:
                    print(f"[private-email] Graph {method} {urlsplit(url).path} returned "
                          f"{response.status_code}", flush=True)
                    raise HTTPException(502, "Microsoft Graph could not be read; no automatic write retry")
                return response.json()
            except httpx.HTTPError:
                raise HTTPException(502, "Microsoft Graph unavailable; write outcome may need checking")
        return user, GraphMailbox(transport, policy.owner)

    def run(fn):
        try:
            return fn()
        except Denied as exc:
            raise HTTPException(409, str(exc))

    @router.get("/workspace")
    def workspace(request: Request):
        try:
            policy.check(auth.current_user(request))
        except Denied as exc:
            raise HTTPException(403, str(exc))
        return FileResponse(page, headers={"Cache-Control": "no-store"})

    @router.get("/review")
    def review(request: Request):
        _, mailbox = context(request)
        from fastapi.responses import JSONResponse
        return JSONResponse(run(mailbox.review), headers={"Cache-Control": "no-store"})

    @router.post("/proposals")
    def propose(request: Request, data: Proposal):
        if not drafts_enabled:
            raise HTTPException(403, "Draft saving is disabled in this read-only release")
        user, mailbox = context(request, True)
        return run(lambda: store.propose(user["oid"], mailbox.source(data.message_id), data.body))

    @router.post("/confirm")
    def confirm(request: Request, data: Confirmation):
        if not drafts_enabled:
            raise HTTPException(403, "Draft saving is disabled in this read-only release")
        user, mailbox = context(request, True)
        return run(lambda: store.confirm(user["oid"], data.proposal_id, data.digest, mailbox))

    return router
