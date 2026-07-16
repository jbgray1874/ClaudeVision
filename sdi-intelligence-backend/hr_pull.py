"""
Stage 1 — PULL active staff from BrightHR and STORE a snapshot on local disk.
Does NOT touch InVentry (that's hr_load_inventry.py). Runnable two ways:
  * On demand via the backend  POST /api/hr/pull
  * On a schedule              python hr_pull.py   (Task Scheduler)
Keeps every pull as a timestamped JSON snapshot (audit trail) and advances a
"latest.json" pointer only when the pull passes the safety guard.

NEW (24 Jun 2026): in addition to the local audit snapshot, writes one clean,
dated, browsable file per run to HR_OUTPUT_DIR (K:/IT/HRSystemsOutput) — the
folder exposed in the portal Files view — so the COO can run a pull and view
the result through the intranet. Filename: brighthr_staff_<UTC stamp>.json.
Writing this file is NON-FATAL: the audit snapshot is already saved, so a
permissions / drive-mapping problem on K: can never lose the pull.
"""
import csv  # noqa: F401  (kept for parity tooling; load writes the CSV)
import json
import os
import sys
import datetime
from pathlib import Path
import hr_config as cfg
import hr_brighthr as bh
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
    tmp.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    os.replace(tmp, path)
def _last_active_count():
    latest = Path(cfg.HR_SNAPSHOT_DIR) / "latest.json"
    try:
        return json.loads(latest.read_text(encoding="utf-8")).get("active")
    except (OSError, ValueError):
        return None
def _write_status(summary: dict):
    p = Path(cfg.HR_SNAPSHOT_DIR) / "hr_status.json"
    try:
        cur = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except ValueError:
        cur = {}
    cur["pull"] = summary
    _atomic_write_json(p, cur)
def _write_output_file(active: list, summary: dict):
    """
    Write the clean, dated, browsable output file to HR_OUTPUT_DIR
    (K:\\IT\\HRSystemsOutput) so the COO can view it in the portal Files view.
    Returns the path written, or None if the folder isn't reachable/writable.
    NON-FATAL: the audit snapshot is already written before this runs.
    """
    out_dir = getattr(cfg, "HR_OUTPUT_DIR", "").strip()
    if not out_dir:
        _log("HR_OUTPUT_DIR not set — skipping browsable output file.")
        return None
    try:
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        out_path = Path(out_dir) / f"brighthr_staff_{_stamp()}.json"
        payload = {
            "generated": summary["timestamp"],
            "environment": summary["env"],
            "pulled": summary["pulled"],
            "active": summary["active"],
            "skipped": summary["skipped"],
            "status": summary["status"],
            "warnings": summary.get("warnings", []),
            "employees": [
                {
                    "first_name": e.get("first_name", ""),
                    "surname": e.get("surname", ""),
                }
                for e in active
            ],
        }
        _atomic_write_json(out_path, payload)
        _log(f"Output file written -> {out_path}")
        return str(out_path)
    except OSError as exc:
        _log(f"OUTPUT FILE FAILED ({out_dir}): {exc}. "
             f"If this is a mapped drive, set HR_OUTPUT_DIR to the UNC path — "
             f"a Windows service cannot see user drive mappings.")
        return None
def run_pull() -> dict:
    Path(cfg.HR_SNAPSHOT_DIR).mkdir(parents=True, exist_ok=True)
    _log(f"PULL start (env={cfg.BH_ENV}, auth={cfg.BH_AUTH_MODE})")
    token = bh.get_access_token()
    raw = bh.fetch_employees(token)
    employees = [bh.normalise_employee(e) for e in raw]
    active = [
        e for e in employees
        if not e["terminated"] and e["first_name"] and e["surname"] and e["email"]
    ]
    summary = {
        "timestamp": _now().isoformat(),
        "env": cfg.BH_ENV,
        "pulled": len(raw),
        "active": len(active),
        "skipped": len(raw) - len(active),
        "status": "ok",
        "warnings": [],
    }
    # ── safety guard ──
    prev = _last_active_count()
    if len(active) < cfg.HR_MIN_RECORDS:
        summary["status"] = "aborted"
        summary["warnings"].append(
            f"Active count {len(active)} < HR_MIN_RECORDS {cfg.HR_MIN_RECORDS}; "
            f"snapshot archived but latest-good NOT advanced."
        )
    elif prev and prev > 0 and len(active) < prev * (1 - cfg.HR_MAX_DROP_PCT / 100):
        summary["status"] = "flagged"
        summary["warnings"].append(
            f"Active dropped {prev} -> {len(active)} (> {cfg.HR_MAX_DROP_PCT}%); review before load."
        )
    # always archive the raw pull (audit trail)
    snap_path = Path(cfg.HR_SNAPSHOT_DIR) / f"brighthr_{_stamp()}.json"
    _atomic_write_json(snap_path, {"summary": summary, "records": active})
    summary["snapshot"] = str(snap_path)
    # advance latest-good only when trustworthy
    if summary["status"] in ("ok", "flagged"):
        _atomic_write_json(Path(cfg.HR_SNAPSHOT_DIR) / "latest.json", {**summary, "records": active})
    # NEW: write the clean dated file to the portal-visible HR output folder
    if summary["status"] in ("ok", "flagged"):
        out_file = _write_output_file(active, summary)
        if out_file:
            summary["output_file"] = out_file
        else:
            summary["warnings"].append(
                "Browsable output file not written — check HR_OUTPUT_DIR path/permissions."
            )
    _write_status(summary)
    _log(f"PULL {summary['status']}: pulled={summary['pulled']} active={summary['active']} -> {snap_path}")
    return summary
if __name__ == "__main__":
    try:
        s = run_pull()
        sys.exit(0 if s["status"] in ("ok", "flagged") else 2)
    except Exception as exc:  # noqa: BLE001
        _log(f"PULL CRITICAL: {exc}")
        sys.exit(1)
