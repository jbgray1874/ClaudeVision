"""
Stage 2 — LOAD the latest good snapshot into InVentry's watched-folder CSV.

Reads the latest-good snapshot written by hr_pull.py and writes the InVentry
import CSV ATOMICALLY (temp -> os.replace), so InVentry's CSV Automation Service
never sees a half-written file. Refuses to write an empty/low CSV so a bad pull
can't silently wipe the front-desk roster.

Runnable two ways:
  * On demand via the backend  POST /api/hr/load
  * On a schedule              python hr_load_inventry.py   (a few minutes after the pull)
"""
import csv
import json
import os
import sys
import datetime
from pathlib import Path

import hr_config as cfg

# Match these headers to your InVentry CSV import mapping.
INVENTRY_FIELDS = ["First Name", "Surname", "Email Address"]


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


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


def _load_latest() -> dict:
    p = Path(cfg.HR_SNAPSHOT_DIR) / "latest.json"
    if not p.exists():
        raise RuntimeError("No latest snapshot found — run the pull first (hr_pull.py).")
    return json.loads(p.read_text(encoding="utf-8"))


def _write_status(summary: dict):
    p = Path(cfg.HR_SNAPSHOT_DIR) / "hr_status.json"
    try:
        cur = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except ValueError:
        cur = {}
    cur["load"] = summary
    _atomic_write_json(p, cur)


def run_load(force: bool = False) -> dict:
    latest = _load_latest()
    records = latest.get("records") or []
    summary = {
        "timestamp": _now().isoformat(),
        "source_pull": latest.get("timestamp"),
        "records": len(records),
        "written": 0,
        "status": "ok",
        "warnings": [],
        "target": cfg.INVENTRY_CSV_PATH,
    }

    # ── zero/low-record guard: never overwrite InVentry with an empty roster ──
    if len(records) < cfg.HR_MIN_RECORDS and not force:
        summary["status"] = "aborted"
        summary["warnings"].append(
            f"Only {len(records)} record(s) (< HR_MIN_RECORDS {cfg.HR_MIN_RECORDS}); "
            f"refusing to overwrite InVentry CSV. Re-run with force to override."
        )
        _write_status(summary)
        _log(f"LOAD aborted: {summary['warnings'][-1]}")
        return summary

    target = Path(cfg.INVENTRY_CSV_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=INVENTRY_FIELDS)
        writer.writeheader()
        for r in records:
            if not (r.get("first_name") and r.get("surname") and r.get("email")):
                continue
            writer.writerow({
                "First Name": r["first_name"],
                "Surname": r["surname"],
                "Email Address": r["email"],
            })
            summary["written"] += 1
    os.replace(tmp, target)   # atomic — InVentry only ever sees a complete file

    _write_status(summary)
    _log(f"LOAD ok: wrote {summary['written']} -> {target}")
    return summary


if __name__ == "__main__":
    try:
        s = run_load(force="--force" in sys.argv)
        sys.exit(0 if s["status"] == "ok" else 2)
    except Exception as exc:  # noqa: BLE001
        _log(f"LOAD CRITICAL: {exc}")
        sys.exit(1)
