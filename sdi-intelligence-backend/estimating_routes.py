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
    POST /api/estimate-x3/run?name=&parent=&category=&sheet_material=&rev_in_code=   body = the estimate file
    GET  /api/estimate-x3/runs                 every run: when, file, part, READY / NOT READY, counts
    GET  /api/estimate-x3/run/{id}             one run (run.json)
    GET  /api/estimate-x3/run/{id}/file/{name} one output file
    GET  /api/estimate-x3/run/{id}/zip         all output files

.env (written by add_live_orders_to_portal.py; all optional):
    EST_RUNS      folder for runs (default %USERPROFILE%\\SDI_X3_runs\\estimating)
    EST_HOME      folder holding est_run.py (C:\\SDI_X3\\repo\\sagex3\\estimating)
    EST_PYTHON    python to run it with (default LIVE_ORDERS_PYTHON, else the portal's own)
    EST_PRODUCTS  a product list file instead of the newest X3 products.json (X3_EXPORT_DIR)
    EST_SHARE     where READY runs are saved for loading (network path; services don't see K:) - default
                  \\\\sdi-dc01\\shareddata$\\Shared\\Operations\\Reporting\\SageEstimates; '' = don't save
    EST_SHARE_USER the same folder as people see it (K:\\Operations\\Reporting\\SageEstimates)
"""
import asyncio
import datetime as dt
import io
import json
import os
import re
import subprocess
import sys
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
RUN_ID = re.compile(r"^\d{8}-\d{6}(-\d+)?_[\w.\- ]{1,80}$")
FILE = re.compile(r"^[\w.\- ]{1,120}\.(txt|xlsx)$")
MAX_BYTES = 20 * 1024 * 1024


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


@router.get("/page", response_class=HTMLResponse)
def page():
    if not PAGE.exists():
        raise HTTPException(status_code=404, detail=f"Page not found: {PAGE}")
    return FileResponse(PAGE, media_type="text/html", headers={"Cache-Control": "no-store"})


@router.post("/run")
async def run(request: Request, name: str, parent: str = "", category: str = "FGML", sheet_material: str = "CR4",
              rev_in_code: bool = False, x_sdi_key: str | None = Header(default=None)):
    """The estimate file is the request body (the page sends it as is). Runs the converter, returns run.json."""
    _check_key(x_sdi_key)
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
           "--by", request.client.host if request.client else ""]
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
                        "by": j.get("by")})
    return {"folder": str(RUNS), "saved_to": SHARE_USER if SHARE else "", "runs": out}


@router.get("/run/{run_id}")
def one(run_id: str, x_sdi_key: str | None = Header(default=None)):
    _check_key(x_sdi_key)
    j = json.loads((_run_dir(run_id) / "run.json").read_text(encoding="utf-8"))
    j["id"] = run_id
    j.pop("trace", None)
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
