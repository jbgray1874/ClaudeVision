"""
Live Orders endpoints for the SDI Intelligence portal (read-only). Written 20 Nov 2026.

Mount in app.py with two lines (beside the HR router):
    from live_orders_routes import router as live_orders_router
    app.include_router(live_orders_router)

Endpoints:
    GET /api/live-orders/latest     the newest Live Orders data (.json, schema sdi.live_orders/1)   X-SDI-Key
    GET /api/live-orders/status     when it was built, from what, and whether the last run failed    X-SDI-Key
    GET /api/live-orders/dashboard  the dashboard page (holds no data; it fetches /latest with the key)

Where the files are (in .env, both optional):
    LIVE_ORDERS_RUNS=C:\\Users\\<you>\\SDI_X3_runs           written by run_x3.py (latest.json, status.json)
    LIVE_ORDERS_DASHBOARD=C:\\SDI_X3\\...\\live_orders_dashboard.html

The portal tile opens:  /api/live-orders/dashboard#key=<the portal's key>
(the key after # never reaches the server or its logs; the page keeps it for that tab only).
"""
import datetime as dt
import json
import os
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

import config

router = APIRouter(prefix="/api/live-orders", tags=["live-orders"])

RUNS = Path(os.getenv("LIVE_ORDERS_RUNS", str(Path.home() / "SDI_X3_runs")))
DASHBOARD = Path(os.getenv("LIVE_ORDERS_DASHBOARD", str(Path(__file__).with_name("live_orders_dashboard.html"))))


def _check_key(key):
    if config.API_KEY and key != config.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-SDI-Key")


def _latest():
    f = RUNS / "latest.json"
    if f.exists():
        return f
    found = sorted(RUNS.rglob("SDI_Live_Orders_*.json"), key=lambda p: p.stat().st_mtime) if RUNS.exists() else []
    return found[-1] if found else None


@router.get("/latest")
def latest(x_sdi_key: str | None = Header(default=None)):
    _check_key(x_sdi_key)
    f = _latest()
    if not f:
        raise HTTPException(status_code=404, detail=f"No Live Orders run yet in {RUNS} - run run_x3.py")
    return FileResponse(f, media_type="application/json", headers={"Cache-Control": "no-store"})


@router.get("/status")
def status(x_sdi_key: str | None = Header(default=None)):
    _check_key(x_sdi_key)
    f, s = _latest(), {}
    st = RUNS / "status.json"
    if st.exists():
        s = json.loads(st.read_text())
        s.pop("trace", None)
    age = None
    if f:
        age = round((dt.datetime.now().timestamp() - f.stat().st_mtime) / 3600, 1)
    return {"runs": str(RUNS), "latest": f.name if f else None, "age_hours": age,
            "last_run_ok": s.get("ok"), "last_run_finished": s.get("finished"), "error": s.get("error"),
            "meta": s.get("meta"), "adapter": s.get("adapter")}


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    if not DASHBOARD.exists():
        raise HTTPException(status_code=404, detail=f"Dashboard page not found: {DASHBOARD} (set LIVE_ORDERS_DASHBOARD)")
    return FileResponse(DASHBOARD, media_type="text/html", headers={"Cache-Control": "no-store"})
