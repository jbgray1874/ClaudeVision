"""
Live Orders endpoints for the SDI Intelligence portal. Written 20 Nov 2026 (history + regenerate added the same day).

Mount in app.py with two lines (add_live_orders_to_portal.py does it):
    from live_orders_routes import router as live_orders_router
    app.include_router(live_orders_router)

The workbooks live in Production's folder (K:\\Operations\\Reporting\\LiveOrders). Every generation is a new pair,
SDI_Live_Orders_<date>_<time>.xlsx (to open and edit) + .json (the views), never overwritten - the folder IS the
history. Regenerate pulls fresh data from Sage X3 (read-only), builds, saves a new pair and the views refresh.

Endpoints (X-SDI-Key on all but the dashboard page, which holds no data):
    GET  /api/live-orders/latest            the newest run's data (.json)
    GET  /api/live-orders/history           every run: when, counts, file names
    GET  /api/live-orders/run/{name}        one past run's data (.json) - the dashboard shows it
    GET  /api/live-orders/workbook/{name}   one past run's workbook (.xlsx) download
    POST /api/live-orders/regenerate        start a new run (one at a time)
    GET  /api/live-orders/regenerate        is a run going, the last result, the last log lines
    GET  /api/live-orders/status            short status for a portal tile
    GET  /api/live-orders/files             every spreadsheet in Production's folder (generated + saved by hand)
    GET  /api/live-orders/file/{name}       download one of them
    GET  /api/live-orders/preview/{name}    its tabs and first rows (xlsx_preview.py), to look without Excel
    GET  /api/live-orders/dashboard         the dashboard page

.env (written by add_live_orders_to_portal.py; all optional):
    LIVE_ORDERS_SHARE      \\\\sdi-dc01\\shareddata$\\Shared\\Operations\\Reporting\\LiveOrders  (network path: services
                           don't see mapped drives)
    LIVE_ORDERS_SHARE_USER K:\\Operations\\Reporting\\LiveOrders  (the path shown to people, for "Copy path")
    LIVE_ORDERS_RUNS       working folder for runs (latest.json, status.json, regenerate.log)
    LIVE_ORDERS_HOME       folder holding run_x3.py (C:\\SDI_X3\\repo\\sagex3\\production\\live_orders)
    LIVE_ORDERS_ROUTES     optional: a route load file instead of X3 routings (ignored if the file isn't there)
    LIVE_ORDERS_PYTHON     python to run it with (default: the portal's own)
    X3_API_CONFIG, X3_EXPORT_DIR  passed through to the X3 pull (the read-only connected-application settings)
"""
import datetime as dt
import json
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

import config

router = APIRouter(prefix="/api/live-orders", tags=["live-orders"])

RUNS = Path(os.getenv("LIVE_ORDERS_RUNS", str(Path.home() / "SDI_X3_runs")))
SHARE = Path(os.getenv("LIVE_ORDERS_SHARE", r"\\sdi-dc01\shareddata$\Shared\Operations\Reporting\LiveOrders"))
SHARE_USER = os.getenv("LIVE_ORDERS_SHARE_USER", r"K:\Operations\Reporting\LiveOrders")
HOME = Path(os.getenv("LIVE_ORDERS_HOME", r"C:\SDI_X3\repo\sagex3\production\live_orders"))
ROUTES = os.getenv("LIVE_ORDERS_ROUTES", "")
PYTHON = os.getenv("LIVE_ORDERS_PYTHON", sys.executable)
DASHBOARD = Path(os.getenv("LIVE_ORDERS_DASHBOARD", str(Path(__file__).with_name("live_orders_dashboard.html"))))
NAME = re.compile(r"^SDI_Live_Orders_[0-9_-]+$")          # only our own files can be asked for

_proc = {"p": None, "started": None}
_lock = threading.Lock()
_meta_cache = {}                                           # path -> (mtime, meta)


def _check_key(key):
    if config.API_KEY and key != config.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-SDI-Key")


def _runs_in_share():
    if not SHARE.exists():
        return []
    return sorted((p for p in SHARE.glob("SDI_Live_Orders_*.json") if NAME.match(p.stem)), key=lambda p: p.name, reverse=True)


def _meta(p):
    m = p.stat().st_mtime
    hit = _meta_cache.get(str(p))
    if hit and hit[0] == m:
        return hit[1]
    try:
        meta = json.loads(p.read_text(encoding="utf-8")).get("meta", {})
    except (ValueError, OSError):
        meta = {}
    _meta_cache[str(p)] = (m, meta)
    return meta


def _latest():
    share = _runs_in_share()
    if share:
        return share[0]
    f = RUNS / "latest.json"
    return f if f.exists() else None


def _file(name, ext):
    if not NAME.match(name):
        raise HTTPException(status_code=400, detail="Not a Live Orders file name")
    f = SHARE / f"{name}.{ext}"
    if not f.exists():
        raise HTTPException(status_code=404, detail=f"{name}.{ext} is not in the Live Orders folder")
    return f


@router.get("/latest")
def latest(x_sdi_key: str | None = Header(default=None)):
    _check_key(x_sdi_key)
    f = _latest()
    if not f:
        raise HTTPException(status_code=404, detail="No Live Orders run yet - press Regenerate")
    return FileResponse(f, media_type="application/json", headers={"Cache-Control": "no-store"})


@router.get("/history")
def history(x_sdi_key: str | None = Header(default=None)):
    _check_key(x_sdi_key)
    out = []
    for p in _runs_in_share():
        m = _meta(p)
        x = p.with_suffix(".xlsx")
        out.append({"name": p.stem, "as_at": m.get("as_at"), "wos": m.get("wos"), "red": m.get("red"),
                    "amber": m.get("amber"), "green": m.get("green"), "overdue": m.get("overdue"),
                    "hours": m.get("hours"), "carried": m.get("carried"), "workbook": x.exists(),
                    "path": f"{SHARE_USER}\\{x.name}"})
    return {"folder": SHARE_USER, "runs": out}


@router.get("/run/{name}")
def run(name: str, x_sdi_key: str | None = Header(default=None)):
    _check_key(x_sdi_key)
    return FileResponse(_file(name, "json"), media_type="application/json", headers={"Cache-Control": "no-store"})


@router.get("/workbook/{name}")
def workbook(name: str, x_sdi_key: str | None = Header(default=None)):
    _check_key(x_sdi_key)
    f = _file(name, "xlsx")
    return FileResponse(f, filename=f.name,
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def _running():
    p = _proc["p"]
    return p is not None and p.poll() is None


@router.post("/regenerate")
def regenerate(full: bool = False, x_sdi_key: str | None = Header(default=None)):
    """Pull from Sage X3 (read-only), build, save a new workbook + views. One at a time."""
    _check_key(x_sdi_key)
    with _lock:
        if _running():
            raise HTTPException(status_code=409, detail=f"Already running since {_proc['started']}")
        script = HOME / "run_x3.py"
        if not script.exists():
            raise HTTPException(status_code=500, detail=f"run_x3.py not found in {HOME} (LIVE_ORDERS_HOME)")
        RUNS.mkdir(parents=True, exist_ok=True)
        cmd = [PYTHON, "-u", str(script), "--pull", "api", "--runs", str(RUNS), "--share", str(SHARE)]
        if ROUTES and Path(ROUTES).is_file():     # optional: an old route load file. Default: routings from X3
            cmd += ["--routes", ROUTES]
        if full:
            cmd.append("--full")
        log = open(RUNS / "regenerate.log", "w", encoding="utf-8")
        _proc["p"] = subprocess.Popen(cmd, cwd=str(HOME), stdout=log, stderr=subprocess.STDOUT,
                                      env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        _proc["started"] = dt.datetime.now().isoformat(timespec="seconds")
    return {"started": _proc["started"], "full": full}


@router.get("/regenerate")
def regenerate_status(x_sdi_key: str | None = Header(default=None)):
    _check_key(x_sdi_key)
    log = RUNS / "regenerate.log"
    tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-12:] if log.exists() else []
    st = {}
    if (RUNS / "status.json").exists():
        st = json.loads((RUNS / "status.json").read_text(encoding="utf-8"))
        st.pop("trace", None)
    return {"running": _running(), "started": _proc["started"], "log": tail,
            "last": {k: st.get(k) for k in ("ok", "finished", "error", "warning", "published", "carried_from",
                                            "master_refreshed", "pull_failed")}}


@router.get("/status")
def status(x_sdi_key: str | None = Header(default=None)):
    _check_key(x_sdi_key)
    f = _latest()
    age = round((dt.datetime.now().timestamp() - f.stat().st_mtime) / 3600, 1) if f else None
    return {"folder": SHARE_USER, "latest": f.name if f else None, "age_hours": age, "running": _running(),
            "runs_saved": len(_runs_in_share()), "meta": _meta(f) if f else None}


SHEET_EXT = (".xlsx", ".xlsm", ".xls")


def _sheet_file(name):
    """A spreadsheet directly in Production's folder - by its plain name only, never a path."""
    if name != Path(name).name or not name.lower().endswith(SHEET_EXT) or name.startswith("~$") or len(name) > 160:
        raise HTTPException(status_code=400, detail="Not a spreadsheet name")
    f = SHARE / name
    if not f.is_file():
        raise HTTPException(status_code=404, detail=f"{name} is not in the Live Orders folder")
    return f


@router.get("/files")
def files(x_sdi_key: str | None = Header(default=None)):
    """Every spreadsheet in Production's folder (20 Nov, James): the generated ones and any saved there by hand.
    Excel's ~$ lock files are left out. The page sorts and filters."""
    _check_key(x_sdi_key)
    out = []
    if SHARE.exists():
        for p in SHARE.iterdir():
            if p.is_file() and p.suffix.lower() in SHEET_EXT and not p.name.startswith("~$"):
                st = p.stat()
                gen = bool(NAME.match(p.stem)) and p.with_suffix(".json").exists()
                out.append({"name": p.name, "stem": p.stem, "modified": dt.datetime.fromtimestamp(st.st_mtime)
                            .isoformat(timespec="seconds"), "size": st.st_size, "generated": gen,
                            "path": f"{SHARE_USER}\\{p.name}"})
    out.sort(key=lambda f: f["modified"], reverse=True)
    return {"folder": SHARE_USER, "files": out}


@router.get("/file/{name}")
def sheet_download(name: str, x_sdi_key: str | None = Header(default=None)):
    _check_key(x_sdi_key)
    f = _sheet_file(name)
    return FileResponse(f, filename=f.name, media_type="application/octet-stream")


@router.get("/preview/{name}")
def preview(name: str, sheet: str = "", rows: int = 300, x_sdi_key: str | None = Header(default=None)):
    """A look inside a spreadsheet without Excel: its tabs and the first rows of one (xlsx_preview.py, run with the
    Live Orders Python, which has openpyxl / xlrd)."""
    _check_key(x_sdi_key)
    f = _sheet_file(name)
    script = HOME / "xlsx_preview.py"
    if not script.exists():
        raise HTTPException(status_code=500, detail=f"xlsx_preview.py not found in {HOME} (LIVE_ORDERS_HOME)")
    try:
        r = subprocess.run([PYTHON, str(script), str(f), "--sheet", sheet[:60], "--rows", str(max(10, min(rows, 2000)))],
                           capture_output=True, text=True, timeout=90, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="The workbook took too long to read")
    try:
        res = json.loads(r.stdout)
    except ValueError:
        raise HTTPException(status_code=500, detail=(r.stderr or r.stdout)[-400:] or "Couldn't read the workbook")
    if res.get("error"):
        raise HTTPException(status_code=500, detail=res["error"])
    return res


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    if not DASHBOARD.exists():
        raise HTTPException(status_code=404, detail=f"Dashboard page not found: {DASHBOARD} (set LIVE_ORDERS_DASHBOARD)")
    return FileResponse(DASHBOARD, media_type="text/html", headers={"Cache-Control": "no-store"})
