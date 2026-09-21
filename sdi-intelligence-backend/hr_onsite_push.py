"""
Stage 3 (API) — PUSH Blip on-site presence into InVentry via the Partner API.

This is the supported delivery route, using the API documentation InVentry
supplied on 16 Sep 2026. It replaces the CSV file drop in hr_blip_inventry.py,
which was written against an assumed watched folder that never existed. That
module is still the right thing if a file-based import is ever wanted, and it
remains the source-loading layer used here.

What happens on each run:

  1. Read who BrightHR says is on site (the Blip snapshot, or the on-site JSON
     the portal exposes).
  2. GET InVentry's personnel list, and work out who InVentry already shows as
     signed in (its own LastActivityType field).
  3. Match the two sides. First on PersonID - the field InVentry documents for
     storing an external system's ID, where we put the BrightHR employee UUID -
     then falling back to email, then to name.
  4. POST a sign-in for anyone on site in BrightHR but not in InVentry.
  5. Optionally POST a sign-out for the reverse. OFF by default, see below.

  Dry run unless apply=True: everything is planned and logged, nothing is sent.

Why sign-out is off by default (INVENTRY_ENABLE_SIGN_OUT):
  InVentry has no settable field recording which system signed someone in, so we
  cannot tell our own sign-ins from someone signing in at the reception
  touchscreen. Signing a person out of the fire roll because BrightHR has no
  clocking for them could therefore override a real, human sign-in. Sign-ins are
  safe in a way sign-outs are not, so sign-ins go live first and sign-outs are
  enabled deliberately, once the matching is proven.

Runnable two ways:
  * On demand via the backend  POST /api/hr/blip/push
  * On a schedule              python hr_onsite_push.py [--apply] [--source output]
"""
import datetime
import json
import os
import sys
from pathlib import Path

import hr_blip_inventry as source_loader
import hr_config as cfg
import hr_inventry_api as api


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _log(msg):
    line = f"{_now().isoformat()}  {msg}"
    print(line)
    try:
        Path(cfg.HR_SNAPSHOT_DIR).mkdir(parents=True, exist_ok=True)
        with open(Path(cfg.HR_SNAPSHOT_DIR) / "hr_pipeline.log", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def _atomic_write_json(path, obj):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)


def _write_status(summary):
    p = Path(cfg.HR_SNAPSHOT_DIR) / "hr_status.json"
    try:
        cur = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except ValueError:
        cur = {}
    cur["onsite_push"] = summary
    _atomic_write_json(p, cur)


def _index_personnel(people):
    """Build lookups from InVentry's personnel list."""
    by_person_id, by_email, by_name = {}, {}, {}
    for record in people:
        key = api.person_key(record)
        if key:
            by_person_id[key] = record
        email = str(api._field(record, "EmailAddress")).strip().lower()
        if email:
            by_email[email] = record
        name = source_loader._name_key(
            api._field(record, "FirstName"), api._field(record, "Surname"))
        if name:
            # A duplicated name is ambiguous, so mark it rather than pick one.
            by_name[name] = None if name in by_name else record
    return by_person_id, by_email, by_name


def _match(person, by_person_id, by_email, by_name):
    """Find a person's InVentry record. Returns (record, how)."""
    brighthr_id = (person.get("brighthr_id") or "").strip()
    if brighthr_id and brighthr_id in by_person_id:
        return by_person_id[brighthr_id], "PersonID"

    email = (person.get("email") or "").strip().lower()
    if email and email in by_email:
        return by_email[email], "email"

    name = source_loader._name_key(person.get("first_name"), person.get("surname"))
    if name and by_name.get(name):
        return by_name[name], "name"
    if name in by_name:                      # present but ambiguous
        return None, "ambiguous name"
    return None, "no match"


def run_push(apply=False, force=False, source=source_loader.SOURCE_LATEST,
             client=None, enable_sign_out=None):
    """Reconcile InVentry's on-site register against BrightHR."""
    if enable_sign_out is None:
        enable_sign_out = cfg.INVENTRY_ENABLE_SIGN_OUT

    source_path = source_loader._resolve_source(source)
    payload = json.loads(Path(source_path).read_text(encoding="utf-8"))
    records, meta = source_loader._normalise(payload)
    age = source_loader._age_minutes(meta.get("timestamp"))

    summary = {
        "timestamp": _now().isoformat(),
        "source": str(source_path),
        "source_blip": meta.get("timestamp"),
        "source_status": meta.get("status"),
        "snapshot_age_minutes": round(age, 1) if age is not None else None,
        "brighthr_on_site": len(records),
        "inventry_on_site_before": None,
        "signed_in": [],
        "signed_out": [],
        "already_on_site": 0,
        "unmatched": [],
        "matched_by": {"PersonID": 0, "email": 0, "name": 0},
        "failures": [],
        "status": "ok",
        "warnings": [],
        "dry_run": not apply,
        "sign_out_enabled": bool(enable_sign_out),
    }

    def abort(reason):
        summary["status"] = "aborted"
        summary["warnings"].append(reason)
        _write_status(summary)
        _log(f"PUSH aborted: {reason}")
        return summary

    # ── the same presence guards as the file load ──
    # A degraded Blip run under-reports who is in the building, and an
    # under-reported evacuation list is the failure that matters.
    if meta.get("status") not in ("ok", None) and not force:
        return abort(
            f"On-site source status is '{meta.get('status')}' "
            f"({meta.get('query_failures', '?')} query failure(s)); refusing to push a "
            f"possibly incomplete on-site list. Re-run the Blip query, or use --force."
        )
    if age is not None and age > cfg.BLIP_MAX_STALE_MINUTES and not force:
        return abort(
            f"On-site data is {age:.0f} minutes old (> BLIP_MAX_STALE_MINUTES "
            f"{cfg.BLIP_MAX_STALE_MINUTES}); a stale roll call is worse than no update."
        )
    if not records and meta.get("query_failures") and not force:
        return abort(
            f"Zero staff on site and {meta['query_failures']} query failure(s) — "
            f"treating as a data problem rather than an empty building."
        )

    client = client or api.InVentryAPI()
    summary["warnings"].extend(client.warnings)

    try:
        people = client.get_personnel()
    except api.InVentryAPIError as exc:
        return abort(f"Could not read InVentry personnel: {exc}")

    by_person_id, by_email, by_name = _index_personnel(people)
    inventry_on_site = {api.inventry_id(r): r for r in people if api.is_on_site(r)}
    summary["inventry_on_site_before"] = len(inventry_on_site)
    summary["inventry_personnel"] = len(people)

    # ── plan sign-ins ──
    should_be_on_site = set()
    to_sign_in = []
    for person in records:
        record, how = _match(person, by_person_id, by_email, by_name)
        label = f"{person.get('first_name','')} {person.get('surname','')}".strip() or "?"
        if record is None:
            summary["unmatched"].append({"name": label, "reason": how,
                                         "brighthr_id": person.get("brighthr_id", "")})
            continue
        summary["matched_by"][how] = summary["matched_by"].get(how, 0) + 1
        ident = api.inventry_id(record)
        should_be_on_site.add(ident)
        if ident in inventry_on_site:
            summary["already_on_site"] += 1
            continue
        to_sign_in.append((ident, label, person.get("signed_in")))

    # ── plan sign-outs ──
    to_sign_out = []
    if enable_sign_out:
        for ident, record in inventry_on_site.items():
            if ident in should_be_on_site:
                continue
            if not api.person_key(record):
                # Not a person we manage: a visitor, contractor or someone
                # InVentry knows and we do not. Never ours to sign out.
                continue
            label = f"{api._field(record,'FirstName')} {api._field(record,'Surname')}".strip()
            to_sign_out.append((ident, label))

        if len(to_sign_out) > cfg.INVENTRY_MAX_SIGN_OUTS_PER_RUN and not force:
            summary["warnings"].append(
                f"{len(to_sign_out)} sign-outs exceeds INVENTRY_MAX_SIGN_OUTS_PER_RUN "
                f"({cfg.INVENTRY_MAX_SIGN_OUTS_PER_RUN}); suppressed as a likely data problem."
            )
            _log(f"  sign-outs suppressed: {summary['warnings'][-1]}")
            to_sign_out = []

    _log(f"PUSH plan: BrightHR on site {len(records)}, InVentry on site "
         f"{len(inventry_on_site)}, sign in {len(to_sign_in)}, sign out "
         f"{len(to_sign_out)}, already on site {summary['already_on_site']}, "
         f"unmatched {len(summary['unmatched'])}")

    # ── apply ──
    for ident, label, when in to_sign_in:
        if not apply:
            _log(f"  [DRY RUN] would SIGN IN  {label} ({ident}) at {when or 'now'}")
            summary["signed_in"].append(ident)
            continue
        try:
            client.sign_in(ident, when=when)
            summary["signed_in"].append(ident)
            _log(f"  signed in {label} ({ident})")
        except api.InVentryAPIError as exc:
            summary["failures"].append(f"sign_in {ident}: {exc}")
            _log(f"  FAILED to sign in {label}: {exc}")

    for ident, label in to_sign_out:
        if not apply:
            _log(f"  [DRY RUN] would SIGN OUT {label} ({ident})")
            summary["signed_out"].append(ident)
            continue
        try:
            client.sign_out(ident)
            summary["signed_out"].append(ident)
            _log(f"  signed out {label} ({ident})")
        except api.InVentryAPIError as exc:
            summary["failures"].append(f"sign_out {ident}: {exc}")
            _log(f"  FAILED to sign out {label}: {exc}")

    if summary["unmatched"]:
        summary["warnings"].append(
            f"{len(summary['unmatched'])} on-site staff could not be matched to an InVentry "
            f"record. Populate InVentry's PersonID with the BrightHR employee id (see "
            f"docs/INVENTRY_API_NOTES.md) so matching is exact rather than by name."
        )
    if summary["failures"]:
        summary["status"] = "partial"
    if not enable_sign_out and len(inventry_on_site) and not apply:
        summary["warnings"].append(
            "Sign-out is disabled (INVENTRY_ENABLE_SIGN_OUT), so people who have left will "
            "stay on InVentry's register until signed out at the terminal."
        )

    _write_status(summary)
    _log(f"PUSH {'(dry run) ' if not apply else ''}{summary['status']}: "
         f"signed in {len(summary['signed_in'])}, signed out {len(summary['signed_out'])}, "
         f"failures {len(summary['failures'])}")
    return summary


def _arg(flag, default):
    for i, a in enumerate(sys.argv):
        if a == flag and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        if a.startswith(flag + "="):
            return a.split("=", 1)[1]
    return default


if __name__ == "__main__":
    try:
        if "--check" in sys.argv:
            print(json.dumps(api.InVentryAPI().check(), indent=2))
            sys.exit(0)
        s = run_push(
            apply="--apply" in sys.argv,
            force="--force" in sys.argv,
            source=_arg("--source", source_loader.SOURCE_LATEST),
        )
        sys.exit(0 if s["status"] == "ok" else 2)
    except Exception as exc:  # noqa: BLE001
        _log(f"PUSH CRITICAL: {exc}")
        sys.exit(1)
