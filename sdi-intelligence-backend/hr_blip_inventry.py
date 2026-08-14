"""
Stage 3 — LOAD Blip on-site presence into InVentry's watched folder.

Stage 1/2 (hr_pull.py -> hr_load_inventry.py) sync the staff *roster*: who
exists. This stage syncs *presence*: who is in the building right now, so the
InVentry fire roll call and H&S reporting are live rather than manual.

  hr_blip.py  ──▶  blip_latest.json  ──▶  THIS  ──▶  brighthr_onsite.csv
  (who's clocked in)   snapshot on disk        InVentry CSV Automation Service

The CSV is the FULL current on-site list, written atomically: present in the
file = on site, absent from the file = signed out. That is the same
watched-folder mechanism the roster load already uses.

  ⚠ CONFIRM WITH INVENTRY before enabling on the live watched folder: that
    their CSV Automation Service accepts a presence/attendance import, that it
    treats the file as full current state, and what column headers it expects.
    Until then run with --dry-run, which writes the CSV next to the snapshot
    instead of into the watched folder.

Runnable two ways:
  * On demand via the backend  POST /api/hr/blip/load   (or /blip/sync)
  * On a schedule              python hr_blip_inventry.py
"""
import csv
import json
import os
import sys
import datetime
from pathlib import Path

import hr_config as cfg

# Match these headers to InVentry's presence import mapping. The roster import
# keys on name + email (see hr_load_inventry.INVENTRY_FIELDS), so presence uses
# the same identifiers - no separate ID mapping table is needed.
ONSITE_FIELDS = ["First Name", "Surname", "Email Address", "Signed In"]


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


def _load_blip_latest() -> dict:
    p = Path(cfg.HR_SNAPSHOT_DIR) / "blip_latest.json"
    if not p.exists():
        raise RuntimeError("No Blip snapshot — run hr_blip.py (or POST /api/hr/blip) first.")
    return json.loads(p.read_text(encoding="utf-8"))


def _write_status(summary: dict):
    p = Path(cfg.HR_SNAPSHOT_DIR) / "hr_status.json"
    try:
        cur = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except ValueError:
        cur = {}
    cur["blip_load"] = summary
    _atomic_write_json(p, cur)


def _age_minutes(timestamp: str):
    """Age of the snapshot in minutes, or None if the timestamp is unusable."""
    if not timestamp:
        return None
    try:
        when = datetime.datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=datetime.timezone.utc)
    return (_now() - when).total_seconds() / 60.0


def _sign_in_time(entry: dict) -> str:
    """Clock-in time for one person, from the Blip clocking record."""
    clocking = entry.get("clocking") or {}
    return str(clocking.get("start") or clocking.get("startTime") or "").strip()


def run_blip_load(force: bool = False, dry_run: bool = False) -> dict:
    """Write the current on-site list to the InVentry watched folder."""
    snapshot = _load_blip_latest()
    blip_summary = snapshot.get("summary") or {}
    on_site = snapshot.get("on_site") or []
    age = _age_minutes(blip_summary.get("timestamp"))

    target = Path(cfg.INVENTRY_ONSITE_CSV_PATH)
    if dry_run:
        # Somewhere harmless: never the watched folder InVentry sweeps.
        target = Path(cfg.HR_SNAPSHOT_DIR) / f"dryrun_onsite_{_stamp()}.csv"

    summary = {
        "timestamp": _now().isoformat(),
        "source_blip": blip_summary.get("timestamp"),
        "source_status": blip_summary.get("status"),
        "snapshot_age_minutes": round(age, 1) if age is not None else None,
        "on_site": len(on_site),
        "written": 0,
        "skipped": 0,
        "status": "ok",
        "warnings": [],
        "dry_run": bool(dry_run),
        "target": str(target),
    }

    def abort(reason: str) -> dict:
        summary["status"] = "aborted"
        summary["warnings"].append(reason)
        _write_status(summary)
        _log(f"BLIP LOAD aborted: {reason}")
        return summary

    # ── guard 1: only publish a snapshot Blip itself trusts ──
    # A degraded run means some employee queries failed, so people who ARE on
    # site may be missing from the list. Publishing that as the fire roll is
    # worse than leaving the last good file in place.
    if blip_summary.get("status") not in ("ok", None) and not force:
        return abort(
            f"Blip snapshot status is '{blip_summary.get('status')}' "
            f"({blip_summary.get('query_failures', '?')} query failure(s)); "
            f"refusing to publish a possibly incomplete on-site list. "
            f"Re-run the Blip query, or use --force to override."
        )

    # ── guard 2: presence goes stale fast ──
    if age is not None and age > cfg.BLIP_MAX_STALE_MINUTES and not force:
        return abort(
            f"Blip snapshot is {age:.0f} minutes old (> BLIP_MAX_STALE_MINUTES "
            f"{cfg.BLIP_MAX_STALE_MINUTES}); a stale roll call is worse than no update. "
            f"Re-run the Blip query first."
        )
    if age is None:
        summary["warnings"].append("Snapshot timestamp unreadable — could not check staleness.")

    # ── guard 3: an empty building is plausible at night, but is also exactly
    # what a broken token looks like. Only accept zero from a clean run. ──
    if not on_site and not force:
        if blip_summary.get("query_failures"):
            return abort(
                f"Zero staff on site and {blip_summary['query_failures']} query failure(s) — "
                f"treating as a data problem rather than an empty building."
            )
        summary["warnings"].append("Zero staff on site — clean Blip run, so publishing an empty roll.")

    # ── write the CSV atomically: InVentry never sees a half-written file ──
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ONSITE_FIELDS)
        writer.writeheader()
        for entry in on_site:
            first = (entry.get("first_name") or "").strip()
            surname = (entry.get("surname") or "").strip()
            email = (entry.get("email") or "").strip()
            if not (first and surname and email):
                # InVentry matches on these, so a partial row cannot be linked
                # to a person - count it rather than writing an unmatchable row.
                summary["skipped"] += 1
                continue
            writer.writerow({
                "First Name": first,
                "Surname": surname,
                "Email Address": email,
                "Signed In": _sign_in_time(entry),
            })
            summary["written"] += 1
    os.replace(tmp, target)

    if summary["skipped"]:
        summary["warnings"].append(
            f"{summary['skipped']} on-site record(s) skipped — missing name or email."
        )

    _write_status(summary)
    _log(f"BLIP LOAD {'(dry run) ' if dry_run else ''}ok: wrote {summary['written']} "
         f"of {len(on_site)} on site -> {target}")
    return summary


if __name__ == "__main__":
    try:
        s = run_blip_load(force="--force" in sys.argv, dry_run="--dry-run" in sys.argv)
        sys.exit(0 if s["status"] == "ok" else 2)
    except Exception as exc:  # noqa: BLE001
        _log(f"BLIP LOAD CRITICAL: {exc}")
        sys.exit(1)
