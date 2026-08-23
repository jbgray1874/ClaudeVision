"""
Stage 3 — BUILD the InVentry on-site presence file from Blip data.

Stage 1/2 (hr_pull.py -> hr_load_inventry.py) sync the staff *roster*: who
exists. This stage syncs *presence*: who is in the building right now, so the
InVentry fire roll call and H&S reporting are live rather than manual.

  hr_blip.py  ──▶  on-site JSON  ──▶  THIS  ──▶  brighthr_onsite.csv  ──▶  ???
  (who's clocked in)                                                  (see warning)

Two sources hold the same on-site list, and either can be loaded:

  latest  (default)  C:\\SDIIntelligence\\hr\\snapshots\\blip_latest.json
                     The full snapshot. Includes email.
  output             K:\\IT\\HRSystemsOutput\\blip_onsite_<UTC>.json
                     The file the portal Files view exposes — the "site signed
                     in" page. hr_blip.py strips email from it (names only), so
                     loading from here recovers emails from the roster snapshot
                     by name; anyone left without one is written name-only and
                     reported.

The CSV is written as the FULL current on-site list, atomically: present in the
file = on site, absent from the file = signed out.

  ⚠ HOW INVENTRY RECEIVES THIS IS NOT YET ESTABLISHED. INVENTRY_ONSITE_CSV_PATH
    defaults to a local folder on this server, mirroring the roster load's
    default - but no InVentry service has been configured to read either, and a
    local C:\ path is not reachable by an off-box or cloud InVentry instance.
    The vendor request that settles it is in docs/INVENTRY_INTEGRATION_REQUEST.md.
    Their answer may change the destination (a share, a database, an API), the
    format, and whether full-state or delta semantics are expected - but not the
    data itself, which is what this module produces.
    Run with --dry-run until then; it writes the CSV next to the snapshot.

Runnable two ways:
  * On demand via the backend  POST /api/hr/blip/load   (or /blip/sync)
  * On a schedule              python hr_blip_inventry.py [--source output]
"""
import csv
import json
import os
import sys
import datetime
from pathlib import Path

import hr_config as cfg

# Match these headers to InVentry's presence import mapping once they confirm it.
# These mirror the roster import's columns (hr_load_inventry.INVENTRY_FIELDS) on
# the assumption that InVentry matches people on name + email; which identifier
# they actually key on is an open question for the vendor.
ONSITE_FIELDS = ["First Name", "Surname", "Email Address", "Signed In"]

SOURCE_LATEST = "latest"
SOURCE_OUTPUT = "output"


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


def _write_status(summary: dict):
    p = Path(cfg.HR_SNAPSHOT_DIR) / "hr_status.json"
    try:
        cur = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except ValueError:
        cur = {}
    cur["blip_load"] = summary
    _atomic_write_json(p, cur)


# ── source resolution ────────────────────────────────────────────────────────

def _resolve_source(source: str) -> Path:
    """Turn 'latest' / 'output' / a path into the JSON file to load."""
    if source in ("", None, SOURCE_LATEST):
        p = Path(cfg.HR_SNAPSHOT_DIR) / "blip_latest.json"
        if not p.exists():
            raise RuntimeError("No Blip snapshot — run hr_blip.py (or POST /api/hr/blip) first.")
        return p

    if source == SOURCE_OUTPUT:
        out_dir = (getattr(cfg, "HR_OUTPUT_DIR", "") or "").strip()
        if not out_dir:
            raise RuntimeError("HR_OUTPUT_DIR is not set — cannot load the portal's on-site file.")
        candidates = sorted(Path(out_dir).glob("blip_onsite_*.json"))
        if not candidates:
            raise RuntimeError(
                f"No blip_onsite_*.json in {out_dir} — click \"Who's clocked in?\" first."
            )
        return candidates[-1]      # filenames are UTC stamped, so last = newest

    p = Path(source)
    if not p.is_file():
        raise RuntimeError(f"Source file not found: {p}")
    return p


def _normalise(payload: dict) -> tuple:
    """Return (records, meta) for either on-site JSON shape.

    records: [{first_name, surname, email, signed_in}]
    meta:    {timestamp, status, query_failures, on_site}
    """
    # Snapshot shape: {"summary": {...}, "on_site": [{... "clocking": {...}}]}
    if isinstance(payload.get("on_site"), list):
        summary = payload.get("summary") or {}
        records = []
        for entry in payload["on_site"]:
            clocking = entry.get("clocking") or {}
            records.append({
                "first_name": (entry.get("first_name") or "").strip(),
                "surname": (entry.get("surname") or "").strip(),
                "email": (entry.get("email") or "").strip(),
                "signed_in": str(clocking.get("start") or clocking.get("startTime") or "").strip(),
            })
        meta = {
            "timestamp": summary.get("timestamp"),
            "status": summary.get("status"),
            "query_failures": summary.get("query_failures"),
            "on_site": len(records),
        }
        return records, meta

    # Portal output shape: {"generated", "status", "staff_on_site": [...]} —
    # email stripped by hr_blip._write_output_file.
    if isinstance(payload.get("staff_on_site"), list):
        records = [
            {
                "first_name": (e.get("first_name") or "").strip(),
                "surname": (e.get("surname") or "").strip(),
                "email": (e.get("email") or "").strip(),
                "signed_in": str(e.get("clocked_in") or "").strip(),
            }
            for e in payload["staff_on_site"]
        ]
        meta = {
            "timestamp": payload.get("generated"),
            "status": payload.get("status"),
            "query_failures": payload.get("query_failures"),
            "on_site": len(records),
        }
        return records, meta

    raise RuntimeError(
        "Unrecognised on-site JSON — expected an 'on_site' or 'staff_on_site' list."
    )


def _roster_email_index() -> dict:
    """Map normalised 'first surname' -> email from the roster snapshot.

    Used to recover emails when loading the portal's on-site file, which has
    them stripped. Names appearing more than once are dropped rather than
    guessed: matching the wrong person onto a fire roll is worse than a blank.
    """
    p = Path(cfg.HR_SNAPSHOT_DIR) / "latest.json"
    if not p.exists():
        return {}
    try:
        records = json.loads(p.read_text(encoding="utf-8")).get("records") or []
    except (OSError, ValueError):
        return {}

    index, ambiguous = {}, set()
    for r in records:
        key = _name_key(r.get("first_name"), r.get("surname"))
        email = (r.get("email") or "").strip()
        if not key or not email:
            continue
        if key in index and index[key] != email:
            ambiguous.add(key)
        index[key] = email
    for key in ambiguous:
        index.pop(key, None)
    return index


def _name_key(first, surname) -> str:
    return " ".join(f"{first or ''} {surname or ''}".lower().split())


def _age_minutes(timestamp):
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


# ── the load ─────────────────────────────────────────────────────────────────

def run_blip_load(force: bool = False, dry_run: bool = False,
                  source: str = SOURCE_LATEST) -> dict:
    """Write the current on-site list to the configured InVentry path."""
    source_path = _resolve_source(source)
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    records, meta = _normalise(payload)
    age = _age_minutes(meta.get("timestamp"))

    target = Path(cfg.INVENTRY_ONSITE_CSV_PATH)
    if dry_run:
        # Somewhere harmless: never the configured InVentry destination.
        target = Path(cfg.HR_SNAPSHOT_DIR) / f"dryrun_onsite_{_stamp()}.csv"

    summary = {
        "timestamp": _now().isoformat(),
        "source": str(source_path),
        "source_blip": meta.get("timestamp"),
        "source_status": meta.get("status"),
        "snapshot_age_minutes": round(age, 1) if age is not None else None,
        "on_site": len(records),
        "written": 0,
        "skipped": 0,
        "name_only": 0,
        "emails_recovered": 0,
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
    if meta.get("status") not in ("ok", None) and not force:
        return abort(
            f"On-site source status is '{meta.get('status')}' "
            f"({meta.get('query_failures', '?')} query failure(s)); "
            f"refusing to publish a possibly incomplete on-site list. "
            f"Re-run the Blip query, or use --force to override."
        )

    # ── guard 2: presence goes stale fast ──
    if age is not None and age > cfg.BLIP_MAX_STALE_MINUTES and not force:
        return abort(
            f"On-site data is {age:.0f} minutes old (> BLIP_MAX_STALE_MINUTES "
            f"{cfg.BLIP_MAX_STALE_MINUTES}); a stale roll call is worse than no update. "
            f"Re-run the Blip query first."
        )
    if age is None:
        summary["warnings"].append("Source timestamp unreadable — could not check staleness.")

    # ── guard 3: an empty building is plausible at night, but is also exactly
    # what a broken token looks like. Only accept zero from a clean run. ──
    if not records and not force:
        if meta.get("query_failures"):
            return abort(
                f"Zero staff on site and {meta['query_failures']} query failure(s) — "
                f"treating as a data problem rather than an empty building."
            )
        summary["warnings"].append("Zero staff on site — clean run, so publishing an empty roll.")

    # ── recover emails stripped from the portal's on-site file ──
    if any(not r["email"] for r in records):
        index = _roster_email_index()
        for record in records:
            if record["email"]:
                continue
            found = index.get(_name_key(record["first_name"], record["surname"]))
            if found:
                record["email"] = found
                summary["emails_recovered"] += 1
        if summary["emails_recovered"]:
            _log(f"  recovered {summary['emails_recovered']} email(s) from the roster snapshot")

    # ── write the CSV atomically: InVentry never sees a half-written file ──
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=ONSITE_FIELDS)
        writer.writeheader()
        for record in records:
            if not (record["first_name"] and record["surname"]):
                # Nothing to match a person on at all.
                summary["skipped"] += 1
                continue
            if not record["email"]:
                # Written anyway: leaving someone off the fire roll because we
                # could not find their email is the more dangerous failure.
                summary["name_only"] += 1
            writer.writerow({
                "First Name": record["first_name"],
                "Surname": record["surname"],
                "Email Address": record["email"],
                "Signed In": record["signed_in"],
            })
            summary["written"] += 1
    os.replace(tmp, target)

    if summary["skipped"]:
        summary["warnings"].append(
            f"{summary['skipped']} on-site record(s) skipped — no name to match on."
        )
    if summary["name_only"]:
        summary["warnings"].append(
            f"{summary['name_only']} row(s) written without an email — InVentry must match "
            f"those on name alone. Load with source='latest' to keep emails."
        )

    _write_status(summary)
    _log(f"BLIP LOAD {'(dry run) ' if dry_run else ''}ok: wrote {summary['written']} "
         f"of {len(records)} on site from {source_path.name} -> {target}")
    return summary


def _arg_value(flag: str, default: str) -> str:
    """Read '--flag value' or '--flag=value' from argv."""
    for i, arg in enumerate(sys.argv):
        if arg == flag and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        if arg.startswith(flag + "="):
            return arg.split("=", 1)[1]
    return default


if __name__ == "__main__":
    try:
        s = run_blip_load(
            force="--force" in sys.argv,
            dry_run="--dry-run" in sys.argv,
            source=_arg_value("--source", SOURCE_LATEST),
        )
        sys.exit(0 if s["status"] == "ok" else 2)
    except Exception as exc:  # noqa: BLE001
        _log(f"BLIP LOAD CRITICAL: {exc}")
        sys.exit(1)
