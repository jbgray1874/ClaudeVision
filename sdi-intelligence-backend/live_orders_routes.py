"""
Live Orders endpoints for the SDI Intelligence portal. Written 20 Nov 2026 (history + regenerate added the same day).

Mount in app.py with two lines (add_live_orders_to_portal.py does it):
    from live_orders_routes import router as live_orders_router
    app.include_router(live_orders_router)

The workbooks live in Production's folder (K:\\Operations\\Reporting\\LiveOrders). Every generation is a new pair,
SDI_Live_Orders_<date>_<time>.xlsx (to open and edit) + .json (the views), never overwritten - the folder IS the
history. Regenerate pulls fresh data from Sage X3 (read-only), builds, saves a new pair and the views refresh.

Environments (22 Nov, James: "SDI Mig / Stage choice ... We are SDI is the users' UAT"): every data endpoint takes
?env=mig (SDI Mig, test - the default) or ?env=uat (We are SDI, UAT). Each has its own runs folder and X3 exports, and
its workbooks are named SDI_Live_Orders_<MIG|UAT>_<date>_<time> in the same folder (untagged names from before 22 Nov
are SDI Mig's). One Regenerate at a time across both, to be gentle on X3.

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
NAME = re.compile(r"^SDI_Live_Orders_(?:(MIG|UAT)_)?\d{4}-\d\d-\d\d_\d{4,6}$")   # only our own files can be asked for
ENVS = {"mig": {"label": "SDI Mig (test)", "tag": "MIG"}, "uat": {"label": "We are SDI (UAT)", "tag": "UAT"}}

_proc = {"p": None, "started": None, "env": None}
_lock = threading.Lock()
_meta_cache = {}                                           # path -> (mtime, meta)


def _check_key(key):
    if config.API_KEY and key != config.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-SDI-Key")


def _env(env):
    if env not in ENVS:
        raise HTTPException(status_code=400, detail="env is mig (SDI Mig) or uat (We are SDI)")
    return env


def _env_of(stem):
    m = NAME.match(stem)
    return None if not m else ("uat" if m.group(1) == "UAT" else "mig")


def _when(stem):
    return NAME.match(stem) and re.search(r"\d{4}-\d\d-\d\d_\d{4,6}$", stem).group(0)


def _runs(env):
    """SDI Mig keeps the original runs folder; We are SDI gets <folder>_UAT beside it."""
    return RUNS if env == "mig" else RUNS.with_name(f"{RUNS.name}_{ENVS[env]['tag']}")


def _runs_in_share(env="mig"):
    if not SHARE.exists():
        return []
    return sorted((p for p in SHARE.glob("SDI_Live_Orders_*.json") if _env_of(p.stem) == env),
                  key=lambda p: _when(p.stem), reverse=True)


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


def _latest(env="mig"):
    share = _runs_in_share(env)
    if share:
        return share[0]
    f = _runs(env) / "latest.json"
    return f if f.exists() else None


def _file(name, ext):
    if not NAME.match(name):
        raise HTTPException(status_code=400, detail="Not a Live Orders file name")
    f = SHARE / f"{name}.{ext}"
    if not f.exists():
        raise HTTPException(status_code=404, detail=f"{name}.{ext} is not in the Live Orders folder")
    return f


@router.get("/latest")
def latest(env: str = "mig", x_sdi_key: str | None = Header(default=None)):
    _check_key(x_sdi_key)
    f = _latest(_env(env))
    if not f:
        raise HTTPException(status_code=404, detail=f"No Live Orders run yet for {ENVS[env]['label']} - press Regenerate")
    return FileResponse(f, media_type="application/json", headers={"Cache-Control": "no-store"})


@router.get("/history")
def history(env: str = "mig", x_sdi_key: str | None = Header(default=None)):
    _check_key(x_sdi_key)
    out = []
    for p in _runs_in_share(_env(env)):
        m = _meta(p)
        x = p.with_suffix(".xlsx")
        out.append({"name": p.stem, "as_at": m.get("as_at"), "wos": m.get("wos"), "red": m.get("red"),
                    "amber": m.get("amber"), "green": m.get("green"), "overdue": m.get("overdue"),
                    "hours": m.get("hours"), "carried": m.get("carried"), "workbook": x.exists(),
                    "path": f"{SHARE_USER}\\{x.name}", "env": env})
    return {"folder": SHARE_USER, "env": env, "label": ENVS[env]["label"], "runs": out}


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
def regenerate(env: str = "mig", full: bool = False, x_sdi_key: str | None = Header(default=None)):
    """Pull from Sage X3 (read-only), build, save a new workbook + views. One at a time, across both environments."""
    _check_key(x_sdi_key)
    _env(env)
    with _lock:
        if _running():
            raise HTTPException(status_code=409, detail=f"Already generating {ENVS[_proc['env']]['label']} since "
                                                        f"{_proc['started']} - one at a time, try again when it's done")
        script = HOME / "run_x3.py"
        if not script.exists():
            raise HTTPException(status_code=500, detail=f"run_x3.py not found in {HOME} (LIVE_ORDERS_HOME)")
        runs = _runs(env)
        runs.mkdir(parents=True, exist_ok=True)
        cmd = [PYTHON, "-u", str(script), "--pull", "api", "--runs", str(runs), "--share", str(SHARE), "--env", env]
        if ROUTES and Path(ROUTES).is_file():     # optional: an old route load file. Default: routings from X3
            cmd += ["--routes", ROUTES]
        if full:
            cmd.append("--full")
        log = open(runs / "regenerate.log", "w", encoding="utf-8")
        _proc["p"] = subprocess.Popen(cmd, cwd=str(HOME), stdout=log, stderr=subprocess.STDOUT,
                                      env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        _proc["started"] = dt.datetime.now().isoformat(timespec="seconds")
        _proc["env"] = env
    return {"started": _proc["started"], "full": full, "env": env}


@router.get("/regenerate")
def regenerate_status(env: str = "mig", x_sdi_key: str | None = Header(default=None)):
    _check_key(x_sdi_key)
    runs = _runs(_env(env))
    mine = _running() and _proc["env"] == env
    log = runs / "regenerate.log"
    tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-12:] if log.exists() else []
    st = {}
    if (runs / "status.json").exists():
        st = json.loads((runs / "status.json").read_text(encoding="utf-8"))
        st.pop("trace", None)
    return {"running": mine, "busy": ENVS[_proc["env"]]["label"] if _running() and not mine else None,
            "started": _proc["started"] if _proc["env"] == env else st.get("started"), "log": tail, "env": env,
            "last": {k: st.get(k) for k in ("ok", "started", "finished", "error", "warning", "published",
                                            "carried_from", "master_refreshed", "pull_failed", "adapter")}}


@router.get("/status")
def status(env: str = "mig", x_sdi_key: str | None = Header(default=None)):
    _check_key(x_sdi_key)
    f = _latest(_env(env))
    age = round((dt.datetime.now().timestamp() - f.stat().st_mtime) / 3600, 1) if f else None
    return {"folder": SHARE_USER, "env": env, "latest": f.name if f else None, "age_hours": age,
            "running": _running() and _proc["env"] == env, "runs_saved": len(_runs_in_share(env)),
            "meta": _meta(f) if f else None}


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
def files(env: str = "", x_sdi_key: str | None = Header(default=None)):
    """Every spreadsheet in Production's folder (20 Nov, James): the generated ones and any saved there by hand.
    Excel's ~$ lock files are left out. The page sorts and filters. ?env= keeps that environment's generated ones
    and the hand-saved ones (which carry no environment)."""
    _check_key(x_sdi_key)
    if env:
        _env(env)
    out = []
    if SHARE.exists():
        for p in SHARE.iterdir():
            if p.is_file() and p.suffix.lower() in SHEET_EXT and not p.name.startswith("~$"):
                fe = _env_of(p.stem)
                if env and fe and fe != env:
                    continue
                st = p.stat()
                gen = bool(fe) and p.with_suffix(".json").exists()
                out.append({"name": p.name, "stem": p.stem, "modified": dt.datetime.fromtimestamp(st.st_mtime)
                            .isoformat(timespec="seconds"), "size": st.st_size, "generated": gen, "env": fe,
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
