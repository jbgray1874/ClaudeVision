"""
SDI Intelligence — backend API service.

Runs on the LOCAL Windows server, next to the file shares and the database.
The portal (front-end) calls these endpoints; the browser never touches the
shares, the VPN or the DB directly — only this service does, server-side.

Endpoints
  GET /api/health           service + DB health (for the monitoring tile)
  GET /api/roots            the configured file roots (names only)
  GET /api/files?path=...   list a folder that sits under an allowed root
  GET /api/file?path=...    download/stream one allowed file
  GET /api/db/ping          quick DB connectivity check

Security
  * Every request must carry header  X-SDI-Key: <SDI_API_KEY>  (if a key is set)
  * Files are only served from UNDER the configured UNC roots (no traversal)
  * Only the configured file extensions are returned
  * CORS is restricted to the configured portal origin(s)
"""

import os
import logging
import mimetypes
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

import config

config.validate()


def _resolve_commit() -> str:
    """The git commit this service is running, resolved ONCE at startup and stamped onto every
    response as X-SDI-Commit. It is the answer to 'which version is the box on?' without an SSH
    and a git log — hit any endpoint (or read /api/health) and the commit is there. This session
    hit that question repeatedly (a stale extract, a box behind the tip); a version the running
    service reports about itself ends the guessing. Env SDI_COMMIT wins for deploys with no
    working tree; else the short hash from git; else 'unknown' — never an exception at import."""
    import shutil
    import subprocess
    env = os.getenv("SDI_COMMIT", "").strip()
    if env:
        return env[:40]
    # RUN AS A WINDOWS SERVICE, git IS NOT ON THE PATH. The service starts uvicorn from its own
    # virtualenv under NT AUTHORITY\\SYSTEM, whose PATH has no git, so a bare "git" was never
    # found and the header reported "unknown" on a perfectly current service — the one question
    # it exists to answer. Resolve the executable explicitly, and ask about the REPO ROOT rather
    # than this folder, so the answer does not depend on where the service was launched from.
    _git = shutil.which("git") or r"C:\Program Files\Git\cmd\git.exe"
    for _where in (Path(__file__).resolve().parent.parent, Path(__file__).resolve().parent):
        try:
            out = subprocess.run([_git, "-C", str(_where), "rev-parse", "--short", "HEAD"],
                                 capture_output=True, text=True, timeout=3)
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.strip()
        except Exception:                                        # noqa: BLE001
            continue
    # A DEPLOYED COPY IS NOT A WORKING TREE. SDI-APP01 has no git AND no .git directory -- it
    # is not a clone, it is files copied onto it -- so neither branch above can ever answer
    # there, and /api/health reported "unknown" on a server that was perfectly current.
    #
    # push-to-server.ps1 runs on the laptop, which has both, and leaves the short hash in
    # .sdi-commit beside the code it copied. Read here rather than only in the start script,
    # because a service that can name its build ONLY when launched one particular way loses
    # it the moment anything else starts it -- which is exactly what happened: the stamp was
    # in place, correct, and the answer was still "unknown".
    #
    # AFTER git, deliberately. On a real checkout HEAD is the truth and a stale stamp beside
    # it is not; this is the fallback for machines where there is nothing to ask.
    for _where in (Path(__file__).resolve().parent.parent, Path(__file__).resolve().parent):
        try:
            stamp = _where / ".sdi-commit"
            if stamp.is_file():
                written = stamp.read_text(encoding="utf-8").strip().splitlines()
                if written and written[0].strip():
                    return written[0].strip()[:40]
        except Exception:                                        # noqa: BLE001
            continue
    return "unknown"


SDI_COMMIT = _resolve_commit()

# Must match wb_populate.CELL_MAP["template_path"] and the runner's WB_TEMPLATE_DEFAULT.
# A health check reporting a different file than the engine opens would say ok on a machine
# that cannot run an estimate, which is worse than not checking. A test pins all three.
# The double space in the filename is real.
_WB_TEMPLATE_DEFAULT = (r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed"
                        r"\AI Estimating\AISheets\Blank Estimate Sheet  WB 2026.xlsx")

app = FastAPI(title="SDI Intelligence — Backend", version="0.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    # POST is required by /api/estimate. With GET only, the browser's preflight
    # fails and the run is refused before any handler sees it — which reads as
    # "the button does nothing" rather than as a permissions error.
    allow_methods=["GET", "POST"],
    allow_headers=["X-SDI-Key", "Content-Type"],
    # So browser JS on the portal can READ the version header, not just devtools/curl.
    expose_headers=["X-SDI-Commit"],
)


@app.middleware("http")
async def _stamp_version(request, call_next):
    """Every response carries the running commit, errors included — so a 500 or a 415 still
    tells you which version produced it."""
    response = await call_next(request)
    response.headers["X-SDI-Commit"] = SDI_COMMIT
    return response


# ── Access gate ─────────────────────────────────────────────────────────────
def check_key(x_sdi_key: str | None) -> None:
    if config.API_KEY and x_sdi_key != config.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-SDI-Key")


# ── Path safety: only ever serve from inside an allowed root ─────────────────
def _within_a_root(target: str) -> Path | None:
    """Return the resolved path if it sits inside an allowed root, else None."""
    t = os.path.normcase(os.path.normpath(target))
    for root in config.FILE_ROOTS:
        r = os.path.normcase(os.path.normpath(root))
        if t == r or t.startswith(r + os.sep):
            return Path(os.path.normpath(target))
    return None


def _allowed_ext(p: Path) -> bool:
    return p.suffix.lower() in config.ALLOWED_EXTENSIONS


# WHAT WE WILL SERVE AND WHAT WE WILL STAGE ARE DIFFERENT QUESTIONS.
#
# ALLOWED_EXTENSIONS is a DOCUMENT list — .pdf, .xlsx, .html, .json, images — and it answers
# "may this file be sent to a browser". The folder listing below reused it to decide what to
# DISPLAY, and that listing is also the drawing picker on the estimating page. The two lists
# overlap on exactly one drawing type:
#
#   staging.DRAWING_SUFFIXES   .pdf .dxf .dwg .sldprt .sldasm .slddrw .step .stp
#   config.ALLOWED_EXTENSIONS  .doc .docx .htm .html .jpeg .jpg .json .log .md .pdf .png ...
#
# So a job folder holding 19 SLDPRT, 7 SLDASM, a SLDDRW, a DWG, a PDF and the SolidWorks
# sidecar listed as TWO files, offered "Add all 2", and read as though the pack had been
# lost off the share. It had not: "Use this folder" stages by DRAWING_SUFFIXES and had been
# taking all 29 the whole time. The picker was asking the wrong question and answering it
# accurately.
#
# DXF is the one that would have cost real money. The picker is invisible to it, and a DXF
# drop is exactly what this pack is waiting on — an estimator adding files one at a time
# would have seen nothing arrive and had no reason to doubt the screen.
#
# Widening the LISTING does not widen what can be downloaded: /api/file re-checks
# _allowed_ext itself and returns 415, so a model appears in the browser and still cannot be
# fetched through the service. `servable` is reported per item so the page can show that
# distinction rather than the browser having to infer it from the extension.
try:
    from staging import DRAWING_SUFFIXES as _DRAWING_SUFFIXES
except Exception:                                                # noqa: BLE001
    # The listing must not fall over if staging moves; it simply narrows to documents,
    # which is exactly the behaviour that was there before this.
    _DRAWING_SUFFIXES = ()


def _listable_ext(p: Path) -> bool:
    return _allowed_ext(p) or p.suffix.lower() in _DRAWING_SUFFIXES


# ── Endpoints ────────────────────────────────────────────────────────────────
@app.get("/api/health")
def health(x_sdi_key: str | None = Header(default=None)):
    check_key(x_sdi_key)
    roots_ok = []
    for root in config.FILE_ROOTS:
        roots_ok.append({"root": root, "reachable": os.path.isdir(root)})
    db = db_status()

    # WHERE THE DRAWINGS GET STAGED, AND WHETHER THAT WILL ACTUALLY WORK.
    #
    # Every run now copies its drawings into this folder before the engine reads them, so a
    # staging root that is unset, unreachable, or outside the readable roots stops every
    # estimate. The first failure in the field was a mapped drive in the default — "cannot find
    # the path specified: 'K:\'" — and the only way to tell whether the service had picked up
    # a corrected .env was to try another run and read the error. Reporting it here answers that
    # in one request, the same reason the commit is reported.
    _staging = (getattr(config, "STAGING_ROOT", "") or "").strip()
    staging = {
        "root": _staging or None,
        "configured": bool(_staging),
        "reachable": bool(_staging) and os.path.isdir(_staging),
        "within_file_roots": bool(_staging) and _within_a_root(_staging) is not None,
        "mapped_drive": bool(re.match(r"^[A-Za-z]:", _staging)),
    }
    if staging["mapped_drive"]:
        staging["note"] = ("This is a mapped drive letter. Drive letters belong to a login "
                           "session, so a service running as a service account will not have "
                           "it. Use the \\\\server\\share form.")
    elif not staging["within_file_roots"] and staging["configured"]:
        staging["note"] = "Not inside SDI_FILE_ROOTS — add it, or runs will be refused."

    # THE TEMPLATE THE WORKBOOK IS BUILT FROM, FOR THE SAME REASON STAGING IS ABOVE.
    #
    # 10575-02 ran for 971 seconds and produced a summary and no estimate, because this file
    # was not on the share. Every deliverable hangs off the workbook -- the client quote, the
    # job report, the Decision Report and AI Provenance tabs are all gated on it -- so one
    # missing file takes out all five, and the run still reported itself complete.
    #
    # The runner now refuses such a run up front. This answers the same question without
    # starting one at all, which is what "is the tool ready?" should cost.
    _tpl = (os.environ.get("SDI_WB_TEMPLATE") or "").strip().strip('"') or _WB_TEMPLATE_DEFAULT
    template = {
        "path": _tpl,
        "from_env": bool((os.environ.get("SDI_WB_TEMPLATE") or "").strip()),
        "reachable": os.path.isfile(_tpl),
    }
    if not template["reachable"]:
        template["note"] = ("No workbook can be built without it, so a run would produce a "
                            "summary and no estimate. Restore it on the share under that exact "
                            "name -- the double space is real -- or set SDI_WB_TEMPLATE to a "
                            "copy this machine can read.")

    overall = (all(r["reachable"] for r in roots_ok)
               and db["status"] in ("ok", "not_configured")
               and staging["reachable"] and staging["within_file_roots"]
               and template["reachable"])
    return {"status": "ok" if overall else "degraded", "commit": SDI_COMMIT,
            "file_roots": roots_ok, "database": db, "staging": staging,
            "workbook_template": template}


@app.get("/api/roots")
def roots(x_sdi_key: str | None = Header(default=None)):
    check_key(x_sdi_key)
    return {"roots": [{"name": Path(r).name or r, "path": r} for r in config.FILE_ROOTS]}


@app.get("/api/files")
def list_files(path: str = Query(...), x_sdi_key: str | None = Header(default=None)):
    check_key(x_sdi_key)
    folder = _within_a_root(path)
    if folder is None:
        raise HTTPException(status_code=403, detail="Path is outside the allowed roots")
    if not folder.is_dir():
        raise HTTPException(status_code=404, detail="Folder not found")
    items = []
    try:
        for entry in sorted(os.scandir(folder), key=lambda e: (not e.is_dir(), e.name.lower())):
            p = Path(entry.path)
            is_dir = entry.is_dir()
            if not is_dir and not _listable_ext(p):
                continue  # hide what we can neither serve nor stage
            stat = entry.stat()
            items.append({
                "name": entry.name,
                "path": str(p),
                "is_dir": is_dir,
                "ext": p.suffix.lower(),
                "size_bytes": None if is_dir else stat.st_size,
                "modified": int(stat.st_mtime),
                # False for a model or a DXF: it can be added to a job, and /api/file will
                # still refuse to hand it to a browser. Said here so the page does not have
                # to keep its own copy of either list.
                "servable": is_dir or _allowed_ext(p),
            })
    except PermissionError:
        raise HTTPException(status_code=403, detail="Service account lacks rights to this share")
    return {"path": str(folder), "items": items}


# What a browser can usefully SHOW rather than save. A quote or a decision report
# is meant to be read; landing it in Downloads and making someone find it again is
# the difference between a report and a file. Everything else — the workbook above
# all — belongs in Excel, so it downloads.
_VIEWABLE = {".html", ".htm", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".svg",
             ".txt", ".log", ".md", ".json", ".mp4", ".webm"}


@app.get("/api/file")
def get_file(path: str = Query(...), x_sdi_key: str | None = Header(default=None)):
    check_key(x_sdi_key)
    target = _within_a_root(path)
    if target is None:
        raise HTTPException(status_code=403, detail="Path is outside the allowed roots")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    if not _allowed_ext(target):
        raise HTTPException(status_code=415, detail=f"Extension {target.suffix} is not served")

    media_type, _ = mimetypes.guess_type(str(target))
    inline = target.suffix.lower() in _VIEWABLE
    headers = {}
    if inline:
        # SANDBOXED, because these roots are shares. An .html served from this
        # origin can script the page that served it and reach every endpoint with
        # the caller's rights — and anybody who can write to the Estimating share
        # can put an .html on it. The sandbox keeps it rendering and takes away
        # the origin, which costs a report nothing: ours is one static document.
        headers["Content-Security-Policy"] = "sandbox allow-downloads allow-popups"
    return FileResponse(str(target), media_type=media_type or "application/octet-stream",
                        filename=target.name, headers=headers,
                        content_disposition_type="inline" if inline else "attachment")


# ── Database ─────────────────────────────────────────────────────────────────
def db_status() -> dict:
    if not config.DB_CONFIGURED:
        return {"status": "not_configured"}
    try:
        import pyodbc
        with pyodbc.connect(config.db_connection_string(), timeout=5) as conn:
            conn.cursor().execute("SELECT 1").fetchone()
        return {"status": "ok", "server": config.DB_SERVER, "database": config.DB_NAME}
    except Exception as exc:  # noqa: BLE001 — surface the reason, but never the secrets
        out = {"status": "error", "detail": str(exc)[:300],
               "user": config.DB_USER, "server": config.DB_SERVER}
        # WHICH FILE SUPPLIED THE PASSWORD, because "Login failed for user 'AIBot'" does not
        # say and that is the entire question.
        #
        # This service reads sdi-intelligence-backend\.env FIRST and the repo-root .env
        # second, with override=False — so the value beside the service SHADOWS the shared
        # one. The engine reads them the other way round and stops at the first. So after a
        # rotation applied to the root .env only, the ENGINE connects and the SERVICE does
        # not, on the same machine, as the same user, against the same server — and the
        # header says DEGRADED with no way to tell why from the message.
        #
        # Never the value: the layer list is filenames, which is exactly what is needed and
        # nothing that is a secret.
        layers = getattr(config, "ENV_LAYERS", None)
        if layers:
            out["credential_from"] = layers
            if "Login failed" in out["detail"]:
                out["note"] = (
                    "The password came from the FIRST of these files that set it. This "
                    "service reads its own .env before the repo-root one, so a rotation "
                    "applied only at the root is shadowed here. Update the first file that "
                    "sets SDI_DB_PASSWORD, then RESTART the service — .env is read once at "
                    "start.")
        return out


@app.get("/api/db/ping")
def db_ping(x_sdi_key: str | None = Header(default=None)):
    check_key(x_sdi_key)
    result = db_status()
    code = 200 if result["status"] in ("ok", "not_configured") else 503
    return JSONResponse(status_code=code, content=result)


# Serve the portal at "/" so the site and API are same-origin (http://<host>:<port>/)
_PORTAL = Path(__file__).with_name("sdi-intelligence-portal.html")


_ESTIMATOR = Path(__file__).with_name("sdi-estimating-intelligence.html")
_GUIDE = Path(__file__).with_name("sdi-estimating-guide.html")


@app.get("/estimating")
def estimating_page():
    """The estimator's page, same-origin with the API it calls."""
    if _ESTIMATOR.exists():
        return FileResponse(str(_ESTIMATOR))
    return JSONResponse(status_code=404,
                        content={"detail": "sdi-estimating-intelligence.html "
                                           "is not next to app.py"})


@app.get("/guide")
def estimating_guide():
    """What each deliverable means and what it is asking the estimator to decide.

    Served from the same origin as the page it explains, so it is one click from the run
    button rather than a document somebody has to be sent and then find again."""
    if _GUIDE.exists():
        return FileResponse(str(_GUIDE))
    return JSONResponse(status_code=404,
                        content={"detail": "sdi-estimating-guide.html is not next to app.py"})


_LOGO_EXTS = (".svg", ".png", ".jpg", ".jpeg", ".webp")
_LOGO_FALLBACK = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100" height="100">'
    '<circle cx="50" cy="50" r="50" fill="#e8a33d"/>'
    '<text x="50" y="66" text-anchor="middle" font-family="Inter,Arial,sans-serif" '
    'font-weight="800" font-size="54" fill="#000">S</text></svg>'
)


@app.get("/api/brand/logo")
def brand_logo():
    """The we.are.sdi logo, read from the SAME folder the client quote reads.

    One file, two consumers. A logo copied into the portal would drift from the one on the
    customer's quotation, and the quotation is the copy that must never be wrong.

    This endpoint never 404s. If the file is missing it returns a plain mark rather than a
    broken image, because a header with a hole in it looks like a broken site, while a plain
    mark looks like a plain mark — the same reasoning the quote generator already applies.
    """
    folder = Path(config.BRAND_ASSETS_DIR)
    key = config.BRAND_SDI_LOGO_KEY.lower()
    try:
        if folder.is_dir():
            for ext in _LOGO_EXTS:                       # .svg first — it scales
                for entry in folder.iterdir():
                    if entry.suffix.lower() != ext:
                        continue
                    stem = "".join(c for c in entry.stem.lower() if c.isalnum())
                    if stem == key:
                        media = mimetypes.guess_type(entry.name)[0] or "application/octet-stream"
                        return FileResponse(str(entry), media_type=media,
                                            headers={"Cache-Control": "public, max-age=300"})
    except OSError as exc:
        logging.getLogger("sdi").warning(
            "brand logo unreadable in %s (%s) — serving the fallback mark", folder, exc)

    return Response(content=_LOGO_FALLBACK, media_type="image/svg+xml",
                    headers={"Cache-Control": "no-store"})


@app.get("/")
def home():
    if _PORTAL.exists():
        return FileResponse(str(_PORTAL))
    return JSONResponse({"status": "backend up",
                         "note": "place sdi-intelligence-portal.html next to app.py to serve it here"})


# ── HR pipeline (BrightHR -> InVentry) ──
from hr_routes import router as hr_router
app.include_router(hr_router)

# ── Estimating (the SDI Estimating Intelligence page) ──
from estimate_routes import router as estimate_router
app.include_router(estimate_router)


if __name__ == "__main__":
    import uvicorn

    if os.getenv("SDI_LOG_POLLING", "").strip().lower() not in {"1", "true", "yes", "on"}:
        from log_filters import QuietPolling
        logging.getLogger("uvicorn.access").addFilter(QuietPolling())
        print("[log] runner polling is not logged. SDI_LOG_POLLING=1 to see it.")

    uvicorn.run(app, host=config.HOST, port=config.PORT)
