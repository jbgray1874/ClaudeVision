"""Optional portal adapter. No routes mounted until explicitly integrated.

Uses only the host's verified session; never accepts user identity from JSON.
"""
from pathlib import Path
from urllib.parse import quote, urlsplit
import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from private_email import OCTET, Denied, DraftStore, GraphMailbox

try:
    import private_draft_writer as writer
except Exception as _missing:                                      # noqa: BLE001
    # ── A SIDE FEATURE MUST NEVER TAKE THE HOST DOWN ───────────────────────────
    # app.py imports this module as the service starts, so an import error here
    # stops the WHOLE portal - HR, estimating, the AM CRM, the app portal. On
    # 26 October 2026 a new module was added here and left out of the deploy's
    # file list, and App Proxy answered BadGateway for everything.
    #
    # Failing closed is right for anything that guards the mailbox; suggested
    # wording guards nothing. So this one degrades: no suggestions, everything
    # else as it was, and the reason in the log.
    print(f"[private-email] suggestions unavailable - {type(_missing).__name__}: "
          f"{_missing}. The mailbox still works; replies must be written by hand.",
          flush=True)

    class writer:                                                  # noqa: N801
        """Stands in for the writer when it could not be imported."""
        unavailable = True

        @staticmethod
        def available():
            return False

        @staticmethod
        def compose(message, instruction="", client=None):
            return {"summary": "", "asks": [], "draft": "", "gaps": []}


class Proposal(BaseModel):
    message_id: str = Field(min_length=1, max_length=2048)
    body: str = Field(min_length=1, max_length=20000)


class Confirmation(BaseModel):
    proposal_id: str
    digest: str


class Suggestion(BaseModel):
    message_id: str = Field(min_length=1, max_length=2048)
    # "say yes but push the date to the 14th". Steers the wording; it is not a
    # fact James has checked, so the no-invention rules still apply to it.
    instruction: str = Field(default="", max_length=1000)


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
            # A session can pre-date a consent change, or its refresh token may no
            # longer be usable. Neither case proves that tenant consent is absent.
            raise HTTPException(401, "Mail connection needs renewal. Sign in to the Private Assistant again; if it still fails, ask IT to check the app's delegated Mail.ReadWrite consent.")

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
                                             "delegated Mail.ReadWrite consent needs checking.")
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
    def review(request: Request, when: str = "", sender: str = "",
               unread: bool = False, attachments: bool = False):
        _, mailbox = context(request)
        from fastapi.responses import JSONResponse
        return JSONResponse(
            run(lambda: mailbox.review(when=when[:60], sender=sender[:200],
                                       unread_only=unread,
                                       with_attachments=attachments)),
            headers={"Cache-Control": "no-store"})

    @router.post("/suggest")
    def suggest(request: Request, data: Suggestion):
        """What the message says, and a reply to it - for reading, not for saving.

        Nothing is written anywhere by this route. It reads one message and
        returns wording; putting wording into Drafts is still /proposals and
        /confirm, which show it to you first. So a wrong suggestion costs the
        time it takes to read it.
        """
        _, mailbox = context(request)
        message = run(lambda: mailbox.full(data.message_id))
        drafted = writer.compose(message, data.instruction)
        from fastapi.responses import JSONResponse
        return JSONResponse(
            {**drafted, "wrote_it": bool(drafted["draft"]),
             # Said plainly, because an empty box with no explanation reads as a
             # broken screen rather than a model that could not be reached.
             "why_not": "" if drafted["draft"] else
                        ("Suggestions are switched off for this app."
                         if not writer.available() else
                         "Claude could not be reached just now - write the reply "
                         "yourself, or try again.")},
            headers={"Cache-Control": "no-store"})

    @router.get("/attachments/{message_id}")
    def attachments(request: Request, message_id: str):
        _, mailbox = context(request)
        from fastapi.responses import JSONResponse
        return JSONResponse(run(lambda: mailbox.attachments(message_id)),
                            headers={"Cache-Control": "no-store"})

    @router.get("/attachments/{message_id}/{attachment_id}")
    def attachment(request: Request, message_id: str, attachment_id: str):
        """One attachment, as a download.

        ── NEVER RENDERED ON THIS ORIGIN ──────────────────────────────────────
        The sender chose the file and the content type. Serving it inline would
        let an HTML or SVG attachment run as a page on the address that holds
        the mailbox session. So every attachment leaves as a download, with the
        sender's type replaced by a neutral one, sniffing turned off and scripts
        forbidden - a picture is opened by the viewer's own device, not by us.
        The cost is a click; the alternative is a mailbox that opens whatever it
        is sent.
        """
        from fastapi.responses import Response
        _, mailbox = context(request)
        got = run(lambda: mailbox.attachment(message_id, attachment_id))
        # RFC 6266: a plain filename for anything ASCII, filename* for the rest.
        name = got["name"]
        ascii_name = name.encode("ascii", "replace").decode().replace('"', "_")
        return Response(
            content=got["content"],
            media_type=OCTET,
            headers={
                "Content-Disposition":
                    f'attachment; filename="{ascii_name}"; '
                    f"filename*=UTF-8''{quote(name, safe='')}",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "default-src 'none'; sandbox",
                "Cache-Control": "no-store",
                # What the sender claimed it was, for the page to show. It is a
                # label, never a decision.
                "X-Sdi-Stated-Type": got["contentType"][:120],
            })

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
