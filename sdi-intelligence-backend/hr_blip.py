"""
hr_blip.py — BrightHR Blip attendance: who is currently clocked in.
Queries the Blip clockings endpoint per employee (employeeId is required).
Uses a thread pool to run requests concurrently — 192 employees in ~20s
instead of ~170s sequential.

Writes output to:
  HR_SNAPSHOT_DIR:  blip_<UTC>.json (audit) + blip_latest.json (pointer)
  HR_OUTPUT_DIR:    blip_onsite_<UTC>.json (browsable by COO in portal)
"""
import json
import os
import sys
import datetime
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import hr_config as cfg

BLIP_URL = "https://api.bright.hr/blip/v1/clockings/query"
MAX_WORKERS = 5   # concurrent requests — stays well under BrightHR rate limit


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _stamp():
    return _now().strftime("%Y%m%dT%H%M%SZ")


def _log(msg: str):
    line = f"{_now().isoformat()}  {msg}"
    print(line)
    try:
        Path(cfg.HR_SNAPSHOT_DIR).mkdir(parents=True, exist_ok=True)
        with open(Path(cfg.HR_SNAPSHOT_DIR) / "hr_pipeline.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def _atomic_write_json(path: Path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)


def _get_token() -> str:
    import hr_brighthr as bh
    return bh.get_access_token()


def _load_active_employees() -> list:
    p = Path(cfg.HR_SNAPSHOT_DIR) / "latest.json"
    if not p.exists():
        raise RuntimeError("No employee snapshot — run hr_pull.py first.")
    return json.loads(p.read_text(encoding="utf-8")).get("records") or []


def _query_one(token: str, employee_id: str, from_dt: str) -> list:
    """
    Query clockings for one employee at a point in time.
    Returns clockings active at that moment (i.e. still clocked in).
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    body = {"filters": {"employeeId": employee_id, "from": from_dt}}
    for attempt in range(3):
        try:
            r = requests.post(BLIP_URL, json=body, headers=headers,
                              timeout=cfg.BH_TIMEOUT)
            if r.status_code == 404:
                return []
            if r.status_code == 429:
                wait = 10 * (attempt + 1)
                _log(f"  [429] employee {employee_id} — backing off {wait}s")
                time.sleep(wait)
                continue
            if r.status_code != 200:
                return []
            items = r.json().get("items") or []
            return items
        except requests.RequestException:
            return []
    return []


def _write_output_file(on_site: list, summary: dict):
    """
    Write a clean, dated, browsable output file to HR_OUTPUT_DIR
    so the COO can view who is on site in the portal Files view.
    Email stripped — names only. NON-FATAL.
    """
    out_dir = getattr(cfg, "HR_OUTPUT_DIR", "").strip()
    if not out_dir:
        _log("HR_OUTPUT_DIR not set — skipping browsable output file.")
        return None
    try:
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        out_path = Path(out_dir) / f"blip_onsite_{_stamp()}.json"
        payload = {
            "generated": summary["timestamp"],
            "query_type": "point_in_time",
            "employees_checked": summary["employees_checked"],
            "on_site": summary["on_site"],
            "status": summary["status"],
            "staff_on_site": [
                {
                    "first_name": e.get("first_name", ""),
                    "surname": e.get("surname", ""),
                    "clocked_in": e.get("clocking", {}).get("start", ""),
                }
                for e in on_site
            ],
        }
        _atomic_write_json(out_path, payload)
        _log(f"Output file written -> {out_path}")
        return str(out_path)
    except OSError as exc:
        _log(f"OUTPUT FILE FAILED ({out_dir}): {exc}.")
        return None


def run_blip() -> dict:
    Path(cfg.HR_SNAPSHOT_DIR).mkdir(parents=True, exist_ok=True)
    _log("BLIP start — querying current clockings (concurrent)")

    token = _get_token()
    employees = _load_active_employees()
    emp_index = {e["id"]: e for e in employees if e.get("id")}
    _log(f"  {len(employees)} active employees to check")

    # BrightHR: 'from' without 'to' is a POINT-IN-TIME filter — returns clockings
    # active at exactly that moment. Use NOW to get who is currently on site.
    from_dt = _now().strftime("%Y-%m-%dT%H:%M:%SZ")
    _log(f"  Querying at point-in-time {from_dt} with {MAX_WORKERS} workers")

    on_site = []
    checked = 0
    emp_list = [e for e in employees if e.get("id")]

    # ── concurrent queries ──
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(_query_one, token, emp["id"], from_dt): emp
            for emp in emp_list
        }
        for future in as_completed(futures):
            emp = futures[future]
            checked += 1
            try:
                clockings = future.result()
            except Exception:
                clockings = []
            if clockings:
                on_site.append({
                    "id": emp.get("id"),
                    "first_name": emp.get("first_name", ""),
                    "surname": emp.get("surname", ""),
                    "email": emp.get("email", ""),
                    "clocking": clockings[0],
                })
            if checked % 40 == 0:
                _log(f"  Progress: {checked}/{len(emp_list)} checked, {len(on_site)} on site")

    on_site.sort(key=lambda x: x.get("first_name", "").lower())

    summary = {
        "timestamp": _now().isoformat(),
        "employees_checked": len(emp_list),
        "on_site": len(on_site),
        "status": "ok",
    }

    # ── audit snapshot ──
    snap_path = Path(cfg.HR_SNAPSHOT_DIR) / f"blip_{_stamp()}.json"
    _atomic_write_json(snap_path, {"summary": summary, "on_site": on_site})
    _atomic_write_json(Path(cfg.HR_SNAPSHOT_DIR) / "blip_latest.json",
                       {"summary": summary, "on_site": on_site})

    # ── browsable output for the COO ──
    out_file = _write_output_file(on_site, summary)
    if out_file:
        summary["output_file"] = out_file

    _log(f"BLIP ok: {len(on_site)} on site of {len(emp_list)} -> {snap_path}")
    return summary


if __name__ == "__main__":
    try:
        s = run_blip()
        sys.exit(0 if s["status"] == "ok" else 2)
    except Exception as exc:
        _log(f"BLIP CRITICAL: {exc}")
        sys.exit(1)
