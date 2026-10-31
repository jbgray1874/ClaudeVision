"""SDI Remote Control Intelligence: the service, from a phone.

Every check this answers was a trip to the laptop on 26 October 2026: which
commit is running, is the service up, can it reach the shares, which apps
mounted, and what does the log say. None of those needs a shell, so none is
given one.

── ONE ACTION, AND IT IS NOT A COMMAND ──────────────────────────────────────
There is no command here and no path a caller can name. An authenticated "run
anything" endpoint on the public address would be the highest-value target in
the estate, and it would undo the boundaries the rest of this service spends
its time holding. If a real shell is needed on the server, Remote Desktop
already exists, is already gated and is already audited.

Phase two (agreed 30 October 2026) adds exactly one action: restart THIS
service. It is not a command either - the process ends itself, and the Windows
service manager (NSSM, AppExit Default Restart) starts it again, which is when
.env is read. So it can do nothing a crash could not, and it needs no rights a
crash would not have. It has its own switch, SDI_OPS_RESTART=yes, and with the
switch off the route does not exist. It refuses while an estimate is queued or
running (those are held in memory and a restart would lose them), and within
three minutes of the last start, so two phones cannot bounce it.

Phase two also answers the question Ready-For-People.ps1 answered from the
laptop: what will AM CRM do for this person? Yes or no about an address the
asker typed - never the lists themselves.

── THE LOG IS REDACTED BEFORE IT LEAVES THE MACHINE ─────────────────────────
uvicorn's access log records whole request lines, and this service's own
sign-in callback carries an OAuth authorization code in its query string. They
are single-use and short-lived, and they still have no business on a web page.
Query strings are stripped and anything token-shaped is replaced, here, before
the text is sent anywhere.
"""
import os
import platform
import re
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

import access
import auth

PREFIX = "/api/ops"
PAGE = "sdi-remote-control.html"
_HEADERS = {"Cache-Control": "no-store"}
STARTED = time.time()

# Named, never shown: whether each is set, not what it is set to. The AM CRM
# ones are what Ready-For-People.ps1 checked from the laptop on 30 October.
SETTINGS = (
    "SDI_API_KEY", "SDI_ESTIMATOR_OIDS", "SDI_TTI_OIDS", "SDI_OPS_OIDS",
    "SDI_OPS_RESTART", "SDI_PRIVATE_ENABLED", "SDI_TTI_ENABLED",
    "SDI_TTI_PLAN_SITE", "SDI_GRAPH_SCOPES", "SDI_PUBLIC_HOSTS", "SDI_FILE_ROOTS",
    "SDI_VOICECRM_SITE", "SDI_VOICECRM_XLSX", "SDI_VOICECRM_OWNERS",
    "SDI_VOICECRM_WRITERS", "SDI_VOICECRM_WRITE", "SDI_VOICECRM_APPROVED_BY")

# ── THE RESTART ──────────────────────────────────────────────────────────────
RESTART_SETTING = "SDI_OPS_RESTART"
# Any exit restarts under AppExit Default Restart. Non-zero, so the service's
# own event log records an exit that was asked for rather than a clean stop.
RESTART_EXIT_CODE = 75
# A second restart this soon after a start is a double tap or a second phone,
# not a second problem.
SETTLE_SECONDS = 180

# A query string can carry an authorization code, and a bare token can appear in
# an exception. Neither survives this.
_QUERY = re.compile(r"(\?)\S+")
_TOKENISH = re.compile(r"\b[A-Za-z0-9_\-]{40,}\b")
_NAMED = re.compile(r"((?:code|token|secret|key|password|pwd|sig)\s*[=:]\s*)\S+", re.I)


def redact(line: str) -> str:
    """A log line fit to leave the server."""
    out = _QUERY.sub(r"\1[query removed]", str(line or ""))
    out = _NAMED.sub(r"\1[removed]", out)
    return _TOKENISH.sub("[removed]", out)


def allowed(request) -> bool:
    """Named people, by Entra object ID. Never a shared key."""
    user = auth.current_user(request) if auth.ENABLED else None
    return access.may_use("SDI_OPS_OIDS", user)


def log_path() -> Path:
    named = (os.getenv("SDI_OPS_LOG", "") or "").strip()
    return Path(named) if named else Path(__file__).with_name("service_out.log")


# ── WHAT AM CRM WILL DO FOR A PERSON ────────────────────────────────────────
def amcrm_person(email: str) -> dict:
    """The answers Ready-For-People.ps1 gave, for one typed address.

    Read from the module the service is RUNNING, never from .env: a setting
    changed since the last start is not in force yet, and the running answer
    is the one the person will meet. Not imported if it is not loaded -
    importing it here would build a second tracker client to answer a
    question about the first.
    """
    asked = str(email or "").strip().lower()
    crm = sys.modules.get("voicecrm")
    if crm is None:
        return {"email": asked, "checked": False,
                "why": "AM CRM is not loaded in this service."}
    user = {"email": asked}
    out = {"email": asked, "checked": True,
           # No map means the old single-owner rule: everyone sees one set.
           "per_person": bool(crm.OWNERS),
           "sees": crm.owner_for(user),
           "may_write": crm._may_write(user),
           "writes_switched_on": bool(crm.WRITE_ENABLED),
           "elsewhere": []}
    # ── THE SIGN-IN NAME IS NOT ALWAYS THE MAILBOX ──────────────────────────
    # Nick's mailbox is @wearesdi.com and he signs in as @sdidisplays.co.uk;
    # checked under the mailbox he looked unmapped. The same name on another
    # domain is said, because "not set up" and "set up under the other
    # address" are fixed by different people.
    local = asked.split("@", 1)[0]
    if local:
        known = set(crm.OWNERS) | set(crm.WRITERS)
        out["elsewhere"] = sorted(k for k in known
                                  if k != asked and k.split("@", 1)[0] == local)
    return out


# ── WHAT A RESTART WOULD LOSE ────────────────────────────────────────────────
def work_in_hand() -> list:
    """Estimates queued or running. They live in the service's memory, so a
    restart would lose track of them. Not imported if estimating is not
    loaded: then there is nothing in hand to lose."""
    estimating = sys.modules.get("estimate_routes")
    if estimating is None or not hasattr(estimating, "work_in_hand"):
        return []
    return estimating.work_in_hand()


def restart_switched_on(env=None) -> bool:
    env = os.environ if env is None else env
    return str(env.get(RESTART_SETTING, "")).strip().lower() == "yes"


def why_not_restart(up_for: float, busy: list, switched_on: bool):
    """None when a restart may go ahead; otherwise the sentence that says why
    not, written for the person holding the phone."""
    if not switched_on:
        return (f"Restart is not switched on. {RESTART_SETTING}=yes in the server's "
                ".env turns it on, at the next restart from the laptop.")
    if up_for < SETTLE_SECONDS:
        return (f"It restarted {int(up_for)} seconds ago. Give it "
                f"{int(SETTLE_SECONDS - up_for)} more seconds - a second restart "
                "this soon is usually a double tap.")
    if busy:
        jobs = "; ".join(f"{b.get('client') or '?'} {b.get('drawing_number') or ''}"
                         f" ({b.get('status')})".replace("  ", " ") for b in busy[:3])
        return (f"Not while an estimate is in hand: {jobs}. Runs are held in the "
                "service's memory, so a restart would lose track of them. Try again "
                "when they have finished.")
    return None


def _exit_soon(delay: float = 1.5) -> None:
    """End this process once the answer has gone back. NSSM starts it again.

    os._exit, not sys.exit: sys.exit in a worker thread ends only the thread.
    The delay lets the response reach the phone, so it is told what happened
    rather than seeing the connection drop."""
    def end():
        time.sleep(delay)
        os._exit(RESTART_EXIT_CODE)
    threading.Thread(target=end, name="ops-restart", daemon=True).start()


class RestartAsk(BaseModel):
    # Typed on the page by the person, so a stray POST cannot be a restart.
    confirm: str = ""


def make_router(page_dir=None, env=None, exit_soon=None, in_hand=None):
    router = APIRouter(prefix=PREFIX)
    page = Path(page_dir or Path(__file__).parent) / "appportal" / PAGE
    if not page.is_file():
        raise RuntimeError(f"{PAGE} must be deployed with the code; looked in {page.parent}")
    # Settled when the router is built, as .env is: the route either exists or
    # it does not, and changing that takes a restart from the laptop.
    restart_on = restart_switched_on(env)
    exit_soon = exit_soon or _exit_soon
    in_hand = in_hand or work_in_hand

    def who(request):
        if not allowed(request):
            raise HTTPException(403, access.why_refused(
                "SDI_OPS_OIDS", auth.current_user(request) if auth.ENABLED else None))

    def restart_state():
        busy = in_hand()
        return {"switched_on": restart_on, "work_in_hand": busy,
                "refusal": why_not_restart(time.time() - STARTED, busy, restart_on)}

    @router.get("")
    def console(request: Request):
        who(request)
        return FileResponse(str(page), headers=_HEADERS)

    @router.get("/status")
    def status(request: Request):
        who(request)
        import app as host                      # already imported; this is the live one
        here = Path(__file__).parent
        # Which apps actually mounted, rather than which are configured - the
        # difference is a whole afternoon when app.py did not reach the server.
        routes = {getattr(r, "path", "") for r in request.app.routes}
        mounted = {
            "private assistant": any(p.startswith("/api/private-email") for p in routes),
            "TTI despatch": any(p.startswith("/api/tti") for p in routes),
            "estimating": any(p.startswith("/api/estimate") for p in routes),
            "AM CRM": any(p.startswith("/api/voicecrm") for p in routes),
            "HR": any(p.startswith("/api/hr") for p in routes),
            "remote control": True,
        }
        log = log_path()
        return JSONResponse({
            "commit": getattr(host, "SDI_COMMIT", "unknown"),
            "started": datetime.fromtimestamp(STARTED, timezone.utc).isoformat(),
            "up_for_seconds": int(time.time() - STARTED),
            "python": sys.version.split()[0],
            "host": platform.node(),
            "mounted": mounted,
            # Named settings only, never their values: this says whether the
            # service was configured, not what it was configured with.
            "configured": {name: bool((os.getenv(name) or "").strip()) for name in SETTINGS},
            "log": {"path": str(log), "exists": log.is_file(),
                    "size_bytes": log.stat().st_size if log.is_file() else 0},
            "backend_folder": str(here),
            "restart": restart_state(),
        }, headers=_HEADERS)

    @router.get("/person")
    def person(request: Request, email: str = Query(..., min_length=3, max_length=254)):
        """What AM CRM will do for this sign-in name. Yes or no about the
        address typed; the lists themselves never leave the server."""
        who(request)
        if "@" not in email:
            raise HTTPException(400, "Type the whole sign-in address, with the @.")
        return JSONResponse(amcrm_person(email), headers=_HEADERS)

    if restart_on:
        @router.post("/restart")
        def restart(request: Request, ask: RestartAsk):
            """End this process so the service manager starts it again.

            Same-origin and a header a plain form cannot send, as the other
            writes on this address are; then the typed word; then the three
            refusals in why_not_restart. Who asked goes in the log first, so
            the line is there even though the process is about to end."""
            who(request)
            here = request.headers.get("host", "").lower()
            origin = request.headers.get("origin", "").lower().rstrip("/")
            if (origin not in ("https://" + here, "http://" + here)
                    or request.headers.get("x-sdi-ops-action") != "1"):
                raise HTTPException(403, "Same-origin confirmation required.")
            if ask.confirm.strip().lower() != "restart":
                raise HTTPException(400, 'Type "restart" to confirm.')
            state = restart_state()
            if state["refusal"]:
                raise HTTPException(409, state["refusal"])
            asker = (auth.current_user(request) if auth.ENABLED else None) or {}
            print(f"[ops] restart asked by {asker.get('name') or '?'} "
                  f"<{asker.get('email') or '?'}> after {int(time.time() - STARTED)}s up",
                  flush=True)
            exit_soon()
            return JSONResponse({"restarting": True,
                                 "was_started": datetime.fromtimestamp(
                                     STARTED, timezone.utc).isoformat()},
                                headers=_HEADERS)

    @router.get("/health")
    def health(request: Request):
        """The same answer /api/health gives, without needing the office."""
        who(request)
        import app as host
        return JSONResponse(host.health(request, os.getenv("SDI_API_KEY")),
                            headers=_HEADERS)

    @router.get("/log")
    def tail(request: Request, lines: int = Query(default=40, ge=1, le=200),
             find: str = Query(default="", max_length=120)):
        who(request)
        log = log_path()
        if not log.is_file():
            raise HTTPException(404, f"No log at {log}.")
        try:
            # The tail only: a service log runs to hundreds of megabytes.
            with log.open("rb") as stream:
                stream.seek(0, os.SEEK_END)
                size = stream.tell()
                stream.seek(max(0, size - 400_000))
                text = stream.read().decode("utf-8", "replace")
        except OSError as exc:
            raise HTTPException(503, f"The log could not be read ({type(exc).__name__}).")
        found = [redact(l) for l in text.splitlines() if l.strip()]
        if find:
            found = [l for l in found if find.lower() in l.lower()]
        return JSONResponse({"path": str(log), "matched": len(found),
                             "lines": found[-lines:]}, headers=_HEADERS)

    return router


def _not_switched_on() -> APIRouter:
    """Something at the path that says why there is nothing at the path.

    ── "NOT FOUND" IS THE WRONG ANSWER TO "IS IT ON?" ────────────────────────
    With the switch off, nothing was mounted, so the portal card opened and
    the browser showed {"detail":"Not Found"}. That reads as broken - a card
    for an app that does not exist - when the truth is that it exists and has
    not been turned on. The two need different people to fix them, and the
    page cannot tell you which it is if nothing answers.

    It names the settings and nothing else: no values, no state, and none of
    the console's own routes. An unconfigured app saying so is not a leak.
    """
    router = APIRouter(prefix=PREFIX)

    @router.get("/{rest:path}")
    def off(rest: str = ""):
        return JSONResponse(
            status_code=503, headers={"Cache-Control": "no-store"},
            content={"detail": "SDI Remote Control Intelligence is built but not "
                               "switched on. Set SDI_OPS_ENABLED=yes and "
                               "SDI_OPS_OIDS to the Entra object IDs of the people "
                               "who may use it, in the server's .env, then restart "
                               "the service. (.env is read once, at startup.)"})
    return router


def install(app, env=None):
    env = os.environ if env is None else env
    if env.get("SDI_OPS_ENABLED", "").lower() != "yes":
        app.include_router(_not_switched_on())
        return None
    app.include_router(make_router(env=env))
    return True
