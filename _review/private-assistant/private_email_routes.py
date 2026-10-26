"""Optional portal adapter. No routes mounted until explicitly integrated.

Uses only the host's verified session; never accepts user identity from JSON.
"""
from pathlib import Path
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


def make_router(auth, policy, database, origin, drafts_enabled=False):
    router = APIRouter(prefix="/api/private-email")
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
                if response.status_code >= 300:
                    raise HTTPException(502, f"Microsoft Graph returned {response.status_code}; no automatic write retry")
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
        page = "private-email.html" if drafts_enabled else "private-email-readonly.html"
        return FileResponse(Path(__file__).with_name(page), headers={"Cache-Control": "no-store"})

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
