"""
Estimate → Sage X3 endpoints for the SDI Intelligence portal. Written 20 Nov 2026.

Mount in app.py (add_live_orders_to_portal.py does it, next to Live Orders):
    from estimating_routes import router as estimating_router
    app.include_router(estimating_router)

Upload an estimate (.xls / .xlsx), get the X3 import files - product (ZSDIITM, always), BOM (YA00408BOM),
route (ZSDIROU2) - and the write-up workbook (<part>_estimate_to_SageX3.xlsx), checked against the live X3 product
list (products.json from the daily X3 pull). Every run is kept. Nothing is written to Sage X3.

Endpoints (X-SDI-Key on all but the page, which holds no data):
    GET  /api/estimate-x3/page                 the page (shown in the portal's frame)
    POST /api/estimate-x3/run?name=&parent=&category=&sheet_material=&rev_in_code=&env=   body = the estimate file
         env = mig (SDI Mig, test; default) or uat (We are SDI, the users' UAT; 22 Nov): which X3's product list it is
         checked against, the MIG / UAT tag on its saved folder, and where "Load into Sage X3" writes it back
    GET  /api/estimate-x3/runs                 every run: when, file, part, READY / NOT READY, counts, X3 load
    GET  /api/estimate-x3/run/{id}             one run (run.json)
    GET  /api/estimate-x3/run/{id}/file/{name} one output file
    GET  /api/estimate-x3/run/{id}/preview/{name}   a look inside one (load file or workbook), no Excel
    GET  /api/estimate-x3/run/{id}/zip         all output files
  Saved estimates - every folder in K:\Operations\Reporting\SageEstimates (20 Nov, James: "see that they are saved
  down" and "a button to load up previously generated files"):
    GET  /api/estimate-x3/saved                every saved folder: part, when, files, READY, loaded into X3 or not
    GET  /api/estimate-x3/saved/{folder}       its run.json, to show it again on the page
    GET  /api/estimate-x3/saved/{folder}/file/{name} | /preview/{name} | /zip
  Load into Sage X3 - test company only, create-only (x3_load.py; 20 Nov, James: "save estimates to Sage X3"):
    GET  /api/estimate-x3/x3/status            set up? which X3? can X3 create product / BOM / routing?
    POST /api/estimate-x3/run/{id}/x3-plan     dry run: what would be created, what X3 already has
    POST /api/estimate-x3/run/{id}/x3-load?confirm=<part>   creates what X3 doesn't have (one load at a time)
    (the same two under /saved/{folder}/ for a run reopened from the folder)

.env (written by add_live_orders_to_portal.py; all optional):
    EST_RUNS      folder for runs (default %USERPROFILE%\\SDI_X3_runs\\estimating)
    EST_HOME      folder holding est_run.py (C:\\SDI_X3\\repo\\sagex3\\estimating)
    EST_PYTHON    python to run it with (default LIVE_ORDERS_PYTHON, else the portal's own)
    EST_PRODUCTS  a product list file instead of the newest X3 products.json (X3_EXPORT_DIR)
    EST_SHARE     where READY runs are saved for loading (network path; services don't see K:) - default
                  \\\\sdi-dc01\\shareddata$\\Shared\\Operations\\Reporting\\SageEstimates; '' = don't save
    EST_SHARE_USER the same folder as people see it (K:\\Operations\\Reporting\\SageEstimates)
    EST_X3_LOAD   x3_load.py (default <repo>\\sagex3\\integration\\x3_api\\x3_load.py); its settings: X3_LOAD_CONFIG
    EST_PREVIEW   xlsx_preview.py (default <repo>\\sagex3\\production\\live_orders\\xlsx_preview.py)
"""
import asyncio
import datetime as dt
import io
import json
import os
import re
import subprocess
import sys
import threading
import zipfile
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse

import config

router = APIRouter(prefix="/api/estimate-x3", tags=["estimate-x3"])

RUNS = Path(os.getenv("EST_RUNS", str(Path.home() / "SDI_X3_runs" / "estimating")))
HOME = Path(os.getenv("EST_HOME", r"C:\SDI_X3\repo\sagex3\estimating"))
PYTHON = os.getenv("EST_PYTHON") or os.getenv("LIVE_ORDERS_PYTHON") or sys.executable
SHARE = os.getenv("EST_SHARE", r"\\sdi-dc01\shareddata$\Shared\Operations\Reporting\SageEstimates")
SHARE_USER = os.getenv("EST_SHARE_USER", r"K:\Operations\Reporting\SageEstimates")
PAGE = Path(os.getenv("EST_PAGE", str(Path(__file__).with_name("est_x3_page.html"))))
X3_LOAD = Path(os.getenv("EST_X3_LOAD", str(HOME.parent / "integration" / "x3_api" / "x3_load.py")))
PREVIEW = Path(os.getenv("EST_PREVIEW", str(HOME.parent / "production" / "live_orders" / "xlsx_preview.py")))
RUN_ID = re.compile(r"^\d{8}-\d{6}(-\d+)?_[\w.\- ]{1,80}$")
FILE = re.compile(r"^[\w.\- ]{1,120}\.(txt|xlsx)$")
SAVED = re.compile(r"^[\w][\w.\-]{0,99}$")
ENVS = {"mig": {"label": "SDI Mig (test)", "tag": "MIG"}, "uat": {"label": "We are SDI (UAT)", "tag": "UAT"}}
MAX_BYTES = 20 * 1024 * 1024
# the load files are data rows only (; separated, code page 850): these headings go on top in a preview
TXT_HEAD = {"ZSDIITM": ["Category", "Product", "Description", "Description 2", "Description 3", "Stock unit",
                        "Purchase unit", "PUR-STK", "Sales unit", "SAL-STK", "Weight unit", "Weight", "Base price"],
            "YA00408BOM": ["Parent product", "BOM code", "Use status", "Valid from", "Valid to", "Base qty",
                           "Management unit", "Sequence", "Component", "Component type", "Link qty"],
            "ZSDIROU2": ["Product", "Routing code", "Site", "Use status", "Time unit", "WO mode", "Operation",
                         "Main work centre", "Operation description", "Set-up (min)", "Run (min)"]}
_load_lock = threading.Lock()


def _check_key(key):
    if config.API_KEY and key != config.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-SDI-Key")


def _run_dir(run_id):
    if not RUN_ID.match(run_id):
        raise HTTPException(status_code=400, detail="Not a run id")
    d = RUNS / run_id
    if not (d / "run.json").exists():
        raise HTTPException(status_code=404, detail="No such run")
    return d


def _x3_summary(d):
    """Has this run been loaded into X3? (x3_load.json, written by x3_load.py)"""
    f = d / "x3_load.json"
    if not f.exists():
        return None
    try:
        j = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return {"ok": j.get("ok"), "when": j.get("when"), "by": j.get("by"), "error": j.get("error"),
            "endpoint": (j.get("target") or {}).get("endpoint"),
            "done": [[r.get("what"), r.get("action"), r.get("ok")] for r in j.get("results") or []]}


_guide_cache = {}


@router.post("/ask")
async def ask_guide(request: Request, x_sdi_key: str | None = Header(default=None)):
    """Ask the user guide (25 Nov): {"q": question, "history": [{"q", "a"}, ...]} -> {"answer", "source", "why"}.
    Claude sees only the page's user guide (guide_ask.py); with no Claude the page shows the matching guide sections."""
    _check_key(x_sdi_key)
    import guide_ask
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="Send JSON: {\"q\": \"your question\"}")
    m = PAGE.stat().st_mtime if PAGE.exists() else 0
    if _guide_cache.get("m") != m:
        html_ = PAGE.read_text(encoding="utf-8") if PAGE.exists() else ""
        _guide_cache.update(m=m, text=guide_ask.text_of(guide_ask.section(html_, '<details class="card guide" id="guide">',
                                                                          "</details>")))
    return await asyncio.to_thread(guide_ask.ask, body.get("q"), body.get("history"), _guide_cache["text"],
                                   "Estimate → X3 - turns a saved estimate into Sage X3 product / BOM / route import "
                                   "files and a write-up, and can load them into X3")


@router.get("/page", response_class=HTMLResponse)
def page():
    if not PAGE.exists():
        raise HTTPException(status_code=404, detail=f"Page not found: {PAGE}")
    return FileResponse(PAGE, media_type="text/html", headers={"Cache-Control": "no-store"})


@router.post("/run")
async def run(request: Request, name: str, parent: str = "", category: str = "FGML", sheet_material: str = "CR4",
              rev_in_code: bool = False, env: str = "mig", x_sdi_key: str | None = Header(default=None)):
    """The estimate file is the request body (the page sends it as is). Runs the converter, returns run.json."""
    _check_key(x_sdi_key)
    if env not in ENVS:
        raise HTTPException(status_code=400, detail="env is mig (SDI Mig) or uat (We are SDI)")
    base = Path(name).name
    if not re.search(r"\.(xls|xlsx|xlsm)$", base, re.I):
        raise HTTPException(status_code=400, detail="An estimate is an .xls or .xlsx file")
    body = await request.body()
    if not body or len(body) > MAX_BYTES:
        raise HTTPException(status_code=400, detail="Empty file, or over 20 MB")
    script = HOME / "est_run.py"
    if not script.exists():
        raise HTTPException(status_code=500, detail=f"est_run.py not found in {HOME} (EST_HOME)")
    if category not in ("FGML", "FGSL") or not re.match(r"^[\w\- ]{0,20}$", sheet_material) \
            or not re.match(r"^[\w\-&./() ]{0,40}$", parent):
        raise HTTPException(status_code=400, detail="Bad option")
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    safe = re.sub(r"[^\w.\- ]+", "_", Path(base).stem)[:60].strip() or "estimate"
    run_id, n = f"{stamp}_{safe}", 1
    while (RUNS / run_id).exists():
        n += 1
        run_id = f"{stamp}-{n}_{safe}"
    d = RUNS / run_id
    (d / "in").mkdir(parents=True)
    est = d / "in" / re.sub(r"[^\w.\- ]+", "_", base)
    est.write_bytes(body)
    cmd = [PYTHON, str(script), str(est), str(d), "--category", category, "--sheet-material", sheet_material,
           "--by", request.client.host if request.client else "", "--env", env]
    if SHARE:                                       # READY runs are saved there for loading (James, 20 Nov)
        cmd += ["--publish", SHARE, "--publish-user", SHARE_USER]
    if parent:
        cmd += ["--parent", parent]
    if rev_in_code:
        cmd.append("--rev-in-code")
    try:
        r = await asyncio.to_thread(subprocess.run, cmd, cwd=str(HOME), capture_output=True, text=True, timeout=300,
                                    env=dict(os.environ, PYTHONIOENCODING="utf-8"))   # off the portal's event loop
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="The converter took over 5 minutes")
    if not (d / "run.json").exists():
        raise HTTPException(status_code=500, detail=(r.stderr or r.stdout)[-600:] or "The converter wrote nothing")
    out = json.loads((d / "run.json").read_text(encoding="utf-8"))
    out["id"] = run_id
    return out


@router.get("/runs")
def runs(x_sdi_key: str | None = Header(default=None)):
    _check_key(x_sdi_key)
    out = []
    if RUNS.exists():
        for d in sorted((p for p in RUNS.iterdir() if p.is_dir() and RUN_ID.match(p.name)), reverse=True)[:300]:
            try:
                j = json.loads((d / "run.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            out.append({"id": d.name, "when": j.get("started"), "estimate": j.get("estimate"), "code": j.get("code"),
                        "ok": j.get("ok"), "ready": j.get("ready"), "new": j.get("new"), "bom": j.get("bom"),
                        "ops": j.get("ops"), "stop": j.get("stop"), "warn": j.get("warn"), "error": j.get("error"),
                        "saved": (j.get("published") or {}).get("folder"),
                        "by": j.get("by"), "x3": _x3_summary(d), "env": (j.get("env") or {}).get("key") or "mig"})
    return {"folder": str(RUNS), "saved_to": SHARE_USER if SHARE else "", "runs": out}


@router.get("/run/{run_id}")
def one(run_id: str, x_sdi_key: str | None = Header(default=None)):
    _check_key(x_sdi_key)
    d = _run_dir(run_id)
    j = json.loads((d / "run.json").read_text(encoding="utf-8"))
    j["id"] = run_id
    j.pop("trace", None)
    j["x3_load"] = _x3_summary(d)
    return j


@router.get("/run/{run_id}/file/{name}")
def file(run_id: str, name: str, x_sdi_key: str | None = Header(default=None)):
    _check_key(x_sdi_key)
    if not FILE.match(name):
        raise HTTPException(status_code=400, detail="Not an output file name")
    f = _run_dir(run_id) / "out" / name
    if not f.is_file():
        raise HTTPException(status_code=404, detail="No such file")
    media = "text/plain" if name.endswith(".txt") else \
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return FileResponse(f, filename=name, media_type=media)


@router.get("/run/{run_id}/zip")
def zip_all(run_id: str, x_sdi_key: str | None = Header(default=None)):
    _check_key(x_sdi_key)
    out = _run_dir(run_id) / "out"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(out.iterdir()) if out.exists() else []:
            if f.is_file() and FILE.match(f.name):
                z.write(f, f.name)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="{run_id}.zip"'})


# ------------------------------------------------------------------ a look inside a file (no Excel)
def _preview(f, sheet="", rows=300):
    if f.suffix.lower() == ".txt":                          # a load file: ; separated, no headings
        lines = f.read_text(encoding="cp850", errors="replace").splitlines()
        head = next((h for k, h in TXT_HEAD.items() if k in f.name), None)
        body = [ln.split(";") for ln in lines if ln.strip()]
        out = ([head] if head else []) + body[:rows]
        return {"sheets": [f.name], "sheet": f.name, "rows": out, "total_rows": len(body),
                "truncated": len(body) > rows, "note": "the X3 load file: data rows only, ; between fields"}
    if not PREVIEW.exists():
        raise HTTPException(status_code=500, detail=f"xlsx_preview.py not found: {PREVIEW} (EST_PREVIEW)")
    try:
        r = subprocess.run([PYTHON, str(PREVIEW), str(f), "--sheet", sheet[:60], "--rows", str(max(10, min(rows, 2000)))],
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


@router.get("/run/{run_id}/preview/{name}")
def run_preview(run_id: str, name: str, sheet: str = "", x_sdi_key: str | None = Header(default=None)):
    _check_key(x_sdi_key)
    if not FILE.match(name):
        raise HTTPException(status_code=400, detail="Not an output file name")
    f = _run_dir(run_id) / "out" / name
    if not f.is_file():
        raise HTTPException(status_code=404, detail="No such file")
    return _preview(f, sheet)


# ------------------------------------------------------------------ saved estimates (K:\...\SageEstimates)
def _saved_dir(folder):
    if not SHARE:
        raise HTTPException(status_code=404, detail="Runs aren't saved to a folder (EST_SHARE is blank)")
    if not SAVED.match(folder):
        raise HTTPException(status_code=400, detail="Not a saved-estimate folder name")
    d = Path(SHARE) / folder
    if not d.is_dir():
        raise HTTPException(status_code=404, detail=f"{folder} is not in {SHARE_USER}")
    return d


def _saved_file(folder, name):
    if not FILE.match(name) and name not in ("run.json", "x3_load.json"):
        raise HTTPException(status_code=400, detail="Not a file name")
    f = _saved_dir(folder) / name
    if not f.is_file():
        raise HTTPException(status_code=404, detail="No such file")
    return f


def _files(d):
    out = []
    for f in sorted(d.iterdir()):
        if f.is_file() and FILE.match(f.name) and not f.name.startswith("~$"):
            st = f.stat()
            out.append({"name": f.name, "size": st.st_size,
                        "modified": dt.datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds")})
    return out


@router.get("/saved")
def saved(x_sdi_key: str | None = Header(default=None)):
    """Every folder in the SageEstimates folder, newest first: what was saved and whether it has been loaded."""
    _check_key(x_sdi_key)
    root = Path(SHARE) if SHARE else None
    out = []
    if root and root.exists():
        for d in root.iterdir():
            if not (d.is_dir() and SAVED.match(d.name)):
                continue
            try:
                files = _files(d)
                run = {}
                if (d / "run.json").exists():
                    run = json.loads((d / "run.json").read_text(encoding="utf-8"))
                m = re.match(r"^(.*?)(?:_(MIG|UAT))?_(\d{4})-(\d\d)-(\d\d)_(\d\d)(\d\d)(\d\d)?$", d.name)
                when = run.get("started") or (f"{m[3]}-{m[4]}-{m[5]}T{m[6]}:{m[7]}:{m[8] or '00'}" if m else
                                             dt.datetime.fromtimestamp(d.stat().st_mtime).isoformat(timespec="seconds"))
                env = (run.get("env") or {}).get("key") or ("uat" if m and m[2] == "UAT" else "mig")
                out.append({"folder": d.name, "path": f"{SHARE_USER}\\{d.name}", "when": when, "env": env,
                            "code": run.get("code") or (m[1] if m else d.name), "estimate": run.get("estimate"),
                            "ready": run.get("ready"), "bom": run.get("bom"), "ops": run.get("ops"), "by": run.get("by"),
                            "has_run": bool(run), "files": files, "x3": _x3_summary(d)})
            except (OSError, ValueError):
                continue
    out.sort(key=lambda r: r["when"] or "", reverse=True)
    return {"folder": SHARE_USER if SHARE else "", "saved": out[:1000]}


@router.get("/saved/{folder}")
def saved_one(folder: str, x_sdi_key: str | None = Header(default=None)):
    """A saved folder, shown again on the page: its run.json if it has one (saved from 20 Nov night), else just its files."""
    _check_key(x_sdi_key)
    d = _saved_dir(folder)
    m = re.match(r"^(.*?)(?:_(MIG|UAT))?_\d{4}-\d\d-\d\d_\d{4,6}$", folder)
    j = {"ok": True, "saved_only": True, "code": m[1] if m else folder,
         "env": {"key": "uat" if m and m[2] == "UAT" else "mig"}}
    if (d / "run.json").exists():
        j = json.loads((d / "run.json").read_text(encoding="utf-8"))
    j.pop("trace", None)
    j.update(id=f"saved:{folder}", saved_folder=folder, saved_path=f"{SHARE_USER}\\{folder}", saved_files=_files(d),
             x3_load=_x3_summary(d))
    return j


@router.get("/saved/{folder}/file/{name}")
def saved_file(folder: str, name: str, x_sdi_key: str | None = Header(default=None)):
    _check_key(x_sdi_key)
    f = _saved_file(folder, name)
    media = "text/plain" if name.endswith(".txt") else "application/json" if name.endswith(".json") else \
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return FileResponse(f, filename=name, media_type=media)


@router.get("/saved/{folder}/preview/{name}")
def saved_preview(folder: str, name: str, sheet: str = "", x_sdi_key: str | None = Header(default=None)):
    _check_key(x_sdi_key)
    return _preview(_saved_file(folder, name), sheet)


@router.get("/saved/{folder}/zip")
def saved_zip(folder: str, x_sdi_key: str | None = Header(default=None)):
    _check_key(x_sdi_key)
    d = _saved_dir(folder)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in _files(d):
            z.write(d / f["name"], f["name"])
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="{folder}.zip"'})


# ------------------------------------------------------------------ load into Sage X3 (test company, create-only)
def _x3(args, timeout=180):
    if not X3_LOAD.exists():
        raise HTTPException(status_code=500, detail=f"x3_load.py not found: {X3_LOAD} (EST_X3_LOAD)")
    try:
        r = subprocess.run([PYTHON, str(X3_LOAD), *args, "--json"], capture_output=True, text=True, timeout=timeout,
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="Sage X3 took too long to answer - check in X3 before trying again")
    try:
        return json.loads(r.stdout)
    except ValueError:
        raise HTTPException(status_code=500, detail=(r.stderr or r.stdout)[-600:] or "x3_load.py said nothing")


@router.get("/x3/status")
def x3_status(env: str = "mig", x_sdi_key: str | None = Header(default=None)):
    _check_key(x_sdi_key)
    if env not in ENVS:
        raise HTTPException(status_code=400, detail="env is mig (SDI Mig) or uat (We are SDI)")
    if not X3_LOAD.exists():
        return {"setup": False, "ready": False, "problem": f"x3_load.py not found: {X3_LOAD}"}
    return _x3(["status", "--env", env], 60)


def _target(kind, ref):
    return _run_dir(ref) if kind == "run" else _saved_dir(ref)


@router.post("/{kind}/{ref}/x3-plan")
async def x3_plan(kind: str, ref: str, update: bool = False, x_sdi_key: str | None = Header(default=None)):
    """Dry run: reads X3 (live) and says what would be created - and, where X3 already has a different BOM / route,
    every change an update would make. Nothing is written to X3."""
    _check_key(x_sdi_key)
    if kind not in ("run", "saved"):
        raise HTTPException(status_code=404, detail="Not found")
    d = _target(kind, ref)
    return await asyncio.to_thread(_x3, ["plan", str(d)] + (["--update"] if update else []), 300)


@router.post("/{kind}/{ref}/x3-load")
async def x3_load(kind: str, ref: str, request: Request, confirm: str = "", update: bool = False,
                  x_sdi_key: str | None = Header(default=None)):
    """Creates the product, BOM and route X3 doesn't have yet - test company only (x3_load.py refuses anything else).
    update=true (26 Nov, estimators re-saving): also changes a BOM / route X3 has to match the estimate (never a
    product; nothing deleted; X3's version saved first)."""
    _check_key(x_sdi_key)
    if kind not in ("run", "saved"):
        raise HTTPException(status_code=404, detail="Not found")
    d = _target(kind, ref)
    if not _load_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="Another load into X3 is running - try again in a minute")
    try:
        by = request.client.host if request.client else ""
        return await asyncio.to_thread(_x3, ["load", str(d), "--apply", "--confirm", confirm, "--by", by]
                                       + (["--update"] if update else []), 900)
    finally:
        _load_lock.release()
