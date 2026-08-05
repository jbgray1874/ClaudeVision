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
from pathlib import Path

from fastapi import FastAPI, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

import config

config.validate()

app = FastAPI(title="SDI Intelligence — Backend", version="0.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    # POST is required by /api/estimate. With GET only, the browser's preflight
    # fails and the run is refused before any handler sees it — which reads as
    # "the button does nothing" rather than as a permissions error.
    allow_methods=["GET", "POST"],
    allow_headers=["X-SDI-Key", "Content-Type"],
)


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


# ── Endpoints ────────────────────────────────────────────────────────────────
@app.get("/api/health")
def health(x_sdi_key: str | None = Header(default=None)):
    check_key(x_sdi_key)
    roots_ok = []
    for root in config.FILE_ROOTS:
        roots_ok.append({"root": root, "reachable": os.path.isdir(root)})
    db = db_status()
    overall = all(r["reachable"] for r in roots_ok) and db["status"] in ("ok", "not_configured")
    return {"status": "ok" if overall else "degraded", "file_roots": roots_ok, "database": db}


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
            if not is_dir and not _allowed_ext(p):
                continue  # hide file types we won't serve
            stat = entry.stat()
            items.append({
                "name": entry.name,
                "path": str(p),
                "is_dir": is_dir,
                "ext": p.suffix.lower(),
                "size_bytes": None if is_dir else stat.st_size,
                "modified": int(stat.st_mtime),
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
        return {"status": "error", "detail": str(exc)[:300]}


@app.get("/api/db/ping")
def db_ping(x_sdi_key: str | None = Header(default=None)):
    check_key(x_sdi_key)
    result = db_status()
    code = 200 if result["status"] in ("ok", "not_configured") else 503
    return JSONResponse(status_code=code, content=result)


# Serve the portal at "/" so the site and API are same-origin (http://<host>:<port>/)
_PORTAL = Path(__file__).with_name("sdi-intelligence-portal.html")


_ESTIMATOR = Path(__file__).with_name("sdi-estimating-intelligence.html")


@app.get("/estimating")
def estimating_page():
    """The estimator's page, same-origin with the API it calls."""
    if _ESTIMATOR.exists():
        return FileResponse(str(_ESTIMATOR))
    return JSONResponse(status_code=404,
                        content={"detail": "sdi-estimating-intelligence.html "
                                           "is not next to app.py"})


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
