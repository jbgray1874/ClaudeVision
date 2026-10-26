"""SDI Remote Control Intelligence - phase one: the service, from a phone.

Every check this answers was a trip to the laptop on 26 October 2026: which
commit is running, is the service up, can it reach the shares, which apps
mounted, and what does the log say. None of those needs a shell, so none is
given one.

── READ ONLY, AND THAT IS THE DESIGN NOT A GAP ──────────────────────────────
There is no restart here, no command, no path a caller can name. An
authenticated "run anything" endpoint on the public address would be the
highest-value target in the estate, and it would undo the boundaries the rest
of this service spends its time holding. If a real shell is needed on the
server, Remote Desktop already exists, is already gated and is already audited.

A later phase may add a small, fixed set of named actions - restart this one
service, and nothing else. Until that is designed and agreed it is absent
rather than half-present.

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
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse

import auth

PREFIX = "/api/ops"
PAGE = "sdi-remote-control.html"
_HEADERS = {"Cache-Control": "no-store"}
STARTED = time.time()

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
    named = {v.strip().lower() for v in
             os.getenv("SDI_OPS_OIDS", "").split(",") if v.strip()}
    user = auth.current_user(request) if auth.ENABLED else None
    return bool(named and user and user.get("kind") == "user"
                and str(user.get("oid") or "").lower() in named)


def log_path() -> Path:
    named = (os.getenv("SDI_OPS_LOG", "") or "").strip()
    return Path(named) if named else Path(__file__).with_name("service_out.log")


def make_router(page_dir=None):
    router = APIRouter(prefix=PREFIX)
    page = Path(page_dir or Path(__file__).parent) / "appportal" / PAGE
    if not page.is_file():
        raise RuntimeError(f"{PAGE} must be deployed with the code; looked in {page.parent}")

    def who(request):
        if not allowed(request):
            raise HTTPException(403, "SDI Remote Control is for named people "
                                     "(SDI_OPS_OIDS). Check which account you are "
                                     "signed in as at /api/me.")

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
            "configured": {name: bool((os.getenv(name) or "").strip()) for name in (
                "SDI_API_KEY", "SDI_ESTIMATOR_OIDS", "SDI_TTI_OIDS", "SDI_OPS_OIDS",
                "SDI_PRIVATE_ENABLED", "SDI_TTI_ENABLED", "SDI_TTI_PLAN_SITE",
                "SDI_GRAPH_SCOPES", "SDI_PUBLIC_HOSTS", "SDI_FILE_ROOTS")},
            "log": {"path": str(log), "exists": log.is_file(),
                    "size_bytes": log.stat().st_size if log.is_file() else 0},
            "backend_folder": str(here),
        }, headers=_HEADERS)

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


def install(app, env=None):
    env = os.environ if env is None else env
    if env.get("SDI_OPS_ENABLED", "").lower() != "yes":
        return None
    app.include_router(make_router())
    return True
