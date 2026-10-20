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

Sign-out (INVENTRY_ENABLE_SIGN_OUT, still off by default):
  InVentry records where each person's last event came from and reports it as
  LastEventLocation - "CONSOLE", a touchscreen location id, and so on. We send
  INVENTRY_ACTION_LOCATION with our own sign-ins, so we can recognise them
  later. With INVENTRY_ONLY_SIGN_OUT_OUR_OWN on (the default) only people whose
  last event carries our marker are ever signed out, so a sign-in made at
  reception is never undone by this sync.

  That makes sign-out materially safer than it was, but it stays off until the
  marker is confirmed to round-trip on the live system: InVentry may require
  ActionLocation to be an existing location rather than free text. Check
  /api/hr/inventry/check, which reports how many on-site records carry it.

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


def _pick(records):
    """Of several InVentry records that are evidently one person, the one to use.

    Currently on site first: reception has already signed them in on that copy,
    and choosing another would sign them in a second time. Then the most
    recently used. Then the lowest ID, so the answer never depends on the order
    the API happens to list them in - otherwise a different copy could be
    signed in on different days.
    """
    ordered = sorted(records, key=api.inventry_id)
    return max(ordered, key=lambda r: (api.is_on_site(r),
                                       str(api._field(r, "LastActivityDate"))))


def _first_last(record):
    return (str(api._field(record, "FirstName")).strip().lower(),
            str(api._field(record, "Surname")).strip().lower())


def _record_name(record):
    return source_loader._name_key(*_first_last(record))


def _display(record):
    return f"{api._field(record, 'FirstName')} {api._field(record, 'Surname')}".strip() or "?"


def _could_be(person, record):
    """Could this InVentry record plausibly belong to this BrightHR person?

    First name OR surname must agree. That admits a nickname (Rob / Robert
    Lane) and a changed surname, and refuses an identifier that has ended up on
    somebody else's record. Real data, 14 Oct: one person's BrightHR record
    resolved, by a shared identifier, to a record filed under someone else's name.
    """
    first = str(person.get("first_name") or "").strip().lower()
    last = str(person.get("surname") or "").strip().lower()
    r_first, r_last = _first_last(record)
    return bool((first and first == r_first) or (last and last == r_last))


def _resolve(person, candidates, how):
    """Choose among the InVentry records holding the identifier a person matched.

    One person can have several records (duplicates). Several people can also
    share one identifier (a data error) - so the records must agree with the
    person's name, and must all be the same name, before one is used.
    """
    plausible = [r for r in candidates if _could_be(person, r)]
    if not plausible:
        names = ", ".join(sorted({_display(r) for r in candidates}))
        return None, f"{how} is on the InVentry record of a different person ({names})"
    if len({_record_name(r) for r in plausible}) > 1:
        names = ", ".join(sorted({_display(r) for r in plausible}))
        return None, f"{how} is shared by several people in InVentry ({names})"
    return _pick(plausible), how


def _identifier_keys(record):
    keys = set()
    pid = api.person_key(record)
    if pid:
        keys.add("pid:" + pid)
    email = str(api._field(record, "EmailAddress")).strip().lower()
    if email:
        keys.add("email:" + email)
    return keys


def _linked(records):
    """True when shared emails or PersonIDs join all these records into one.

    Two records with the same name AND a shared identifier are one person on
    two records. Two with the same name and nothing shared may be namesakes,
    and stay ambiguous.
    """
    keys = [_identifier_keys(r) for r in records]
    component, members, grew = set(keys[0]), {0}, True
    while grew:
        grew = False
        for i, ks in enumerate(keys):
            if i not in members and ks & component:
                members.add(i)
                component |= ks
                grew = True
    return len(members) == len(records)


def _index_personnel(people):
    """Group InVentry's personnel by PersonID, email and name.

    Lists, not single records: every group of more than one is a decision that
    _match makes with the person in hand, rather than one taken blind here.
    """
    by_person_id, by_email, by_name = {}, {}, {}
    for record in people:
        key = api.person_key(record)
        if key:
            by_person_id.setdefault(key, []).append(record)
        email = str(api._field(record, "EmailAddress")).strip().lower()
        if email:
            by_email.setdefault(email, []).append(record)
        name = _record_name(record)
        if name:
            by_name.setdefault(name, []).append(record)
    return by_person_id, by_email, by_name


def _shared_identifiers(by_person_id, by_email):
    """Records sharing an identifier: duplicates (one name) and conflicts (several).

    Returns two lists of (what, records). A duplicate is one person on several
    records. A conflict is several people on one identifier, which is a data
    error in InVentry that no amount of matching logic can safely resolve.
    """
    duplicates, conflicts, seen = [], [], set()
    for what, groups in (("PersonID", by_person_id), ("email", by_email)):
        for group in groups.values():
            if len(group) < 2:
                continue
            ids = frozenset(api.inventry_id(r) for r in group)
            if ids in seen:
                continue
            seen.add(ids)
            one_name = len({_record_name(r) for r in group}) == 1
            (duplicates if one_name else conflicts).append((what, group))
    return duplicates, conflicts


def _match(person, by_person_id, by_email, by_name):
    """Find a person's InVentry record. Returns (record, how).

    A problem with a stronger identifier does not stop a weaker one being
    tried: if one person's email has landed on someone else's record, their own
    record can still be found by name. The problem is kept for the report if nothing
    else works.
    """
    problems = []

    brighthr_id = (person.get("brighthr_id") or "").strip()
    if brighthr_id and brighthr_id in by_person_id:
        record, how = _resolve(person, by_person_id[brighthr_id], "PersonID")
        if record is not None:
            return record, how
        problems.append(how)

    email = (person.get("email") or "").strip().lower()
    if email and email in by_email:
        record, how = _resolve(person, by_email[email], "email")
        if record is not None:
            return record, how
        problems.append(how)

    name = source_loader._name_key(person.get("first_name"), person.get("surname"))
    records = by_name.get(name) if name else None
    if records:
        if len(records) == 1 or _linked(records):
            return _pick(records), "name"
        problems.append("ambiguous name")

    return None, "; ".join(problems) if problems else "no match"


def run_push(apply=False, force=False, source=source_loader.SOURCE_LATEST,
             client=None, enable_sign_out=None, now=None):
    """Reconcile InVentry's on-site register against BrightHR."""
    if enable_sign_out is None:
        enable_sign_out = cfg.INVENTRY_ENABLE_SIGN_OUT

    source_path = source_loader._resolve_source(source)
    payload = json.loads(Path(source_path).read_text(encoding="utf-8"))
    records, meta = source_loader._normalise(payload)
    age = source_loader._age_minutes(meta.get("timestamp"))

    # Drop anyone whose clocking has been open so long they cannot be in the
    # building - forgotten clock-outs, not presence.
    records, forgotten = source_loader.split_stale_clockins(records, now=now)

    summary = {
        "timestamp": _now().isoformat(),
        "source": str(source_path),
        "source_blip": meta.get("timestamp"),
        "source_status": meta.get("status"),
        "snapshot_age_minutes": round(age, 1) if age is not None else None,
        "brighthr_on_site": len(records),
        "forgotten_clockouts": [
            {"name": f"{r.get('first_name','')} {r.get('surname','')}".strip(),
             "clocked_in": r.get("signed_in"),
             "age_hours": r.get("clockin_age_hours")}
            for r in forgotten
        ],
        "inventry_on_site_before": None,
        "signed_in": [],
        "signed_out": [],
        # Names beside the ids, for the portal: whoever presses the button sees
        # who was (or would be) changed, not just how many.
        "signed_in_names": [],
        "signed_out_names": [],
        "sign_outs_held_back": [],
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
    # Not lifted by --force: --force is for a backlog over the sign-out cap, and
    # a plan built on an old snapshot would sign out whoever has arrived since.
    # The cure for stale data is always a fresh Blip query, never an override.
    if age is not None and age > cfg.BLIP_MAX_STALE_MINUTES:
        return abort(
            f"On-site data is {age:.0f} minutes old (> BLIP_MAX_STALE_MINUTES "
            f"{cfg.BLIP_MAX_STALE_MINUTES}); a stale roll call is worse than no update. "
            f"Run the Blip query first (python hr_blip.py, or Who's clocked in? on the portal)."
        )
    if not records and meta.get("query_failures") and not force:
        return abort(
            f"Zero staff on site and {meta['query_failures']} query failure(s) — "
            f"treating as a data problem rather than an empty building."
        )

    if forgotten:
        oldest = max(f.get("clockin_age_hours") or 0 for f in forgotten)
        summary["warnings"].append(
            f"{len(forgotten)} person(s) excluded: their BrightHR clocking has been open "
            f"longer than BLIP_MAX_CLOCKIN_AGE_HOURS "
            f"({cfg.BLIP_MAX_CLOCKIN_AGE_HOURS}h), the oldest by {oldest/24:.0f} days. They "
            f"forgot to clock out and are not in the building. Worth chasing in BrightHR."
        )
        _log(f"  excluded {len(forgotten)} forgotten clock-out(s), oldest {oldest/24:.0f} days")

    client = client or api.InVentryAPI()
    summary["warnings"].extend(client.warnings)
    warnings_taken = len(client.warnings)

    try:
        people = client.get_personnel()
    except api.InVentryAPIError as exc:
        return abort(f"Could not read InVentry personnel: {exc}")

    by_person_id, by_email, by_name = _index_personnel(people)
    duplicates, conflicts = _shared_identifiers(by_person_id, by_email)

    # People whose BrightHR query failed this run. Their presence is unknown,
    # not absent, so their InVentry records are left exactly as they are.
    unknown_idents = set()
    for e in (payload.get("query_failed") or []):
        unknown = {"brighthr_id": e.get("id") or "", "first_name": e.get("first_name", ""),
                   "surname": e.get("surname", ""), "email": e.get("email", "")}
        record, _ = _match(unknown, by_person_id, by_email, by_name)
        if record is not None:
            unknown_idents.add(api.inventry_id(record))
    if duplicates:
        names = sorted({_display(g[0]) for _, g in duplicates})
        summary["warnings"].append(
            f"{len(duplicates)} person(s) have more than one InVentry record sharing an "
            f"email or PersonID ({', '.join(names[:5])}{', ...' if len(names) > 5 else ''}). "
            f"The copy already on site, else the most recently used, is the one matched. "
            f"Worth merging in InVentry: reception may sign people in on the other copy."
        )
        for what, g in duplicates:
            _log(f"  DUPLICATE {_display(g[0])}: {len(g)} records share a {what} - "
                 f"{', '.join(sorted(api.inventry_id(r) for r in g))}")
    if conflicts:
        pairs = sorted(" / ".join(sorted({_display(r) for r in g})) for _, g in conflicts)
        summary["warnings"].append(
            f"{len(conflicts)} InVentry identifier(s) are shared by different people "
            f"({'; '.join(pairs[:5])}{'; ...' if len(pairs) > 5 else ''}). Those records are "
            f"matched by name only, never by the shared identifier. Fix them in InVentry."
        )
        for what, g in conflicts:
            _log(f"  CONFLICT {what} shared by different people: "
                 + ", ".join(f"{_display(r)} ({api.inventry_id(r)})" for r in g))

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
        if how != "name" and _record_name(record) != source_loader._name_key(
                person.get("first_name"), person.get("surname")):
            # Accepted - a nickname or a changed surname - but a human should
            # glance at it before it is trusted on a fire roll.
            summary.setdefault("name_checks", []).append(
                {"brighthr": label, "inventry": _display(record), "by": how})
            _log(f"  CHECK BrightHR '{label}' -> InVentry '{_display(record)}' ({how})")
        ident = api.inventry_id(record)
        should_be_on_site.add(ident)
        if ident in inventry_on_site:
            summary["already_on_site"] += 1
            continue
        to_sign_in.append((ident, label, person.get("signed_in")))

    # ── plan sign-outs ──
    to_sign_out = []
    if enable_sign_out:
        only_our_own = cfg.INVENTRY_ONLY_SIGN_OUT_OUR_OWN
        for ident, record in inventry_on_site.items():
            if ident in should_be_on_site:
                continue
            if ident in unknown_idents:
                # Their BrightHR lookup failed this run. Not knowing is not the
                # same as clocked out; the next run will know.
                summary["skipped_unknown"] = summary.get("skipped_unknown", 0) + 1
                continue
            if only_our_own:
                if not api.signed_in_by_us(record):
                    # Their last event came from reception, the Anywhere app or
                    # a rule - a human decision, or InVentry's own. Not ours.
                    summary["skipped_not_ours"] = summary.get("skipped_not_ours", 0) + 1
                    continue
                # The marker alone settles it: only this sync writes it, so the
                # record is on site because we put it there. PersonID is NOT
                # required - it was once meant to hold our BrightHR id, but on
                # the live site it is Active Directory's, and 104 of 255 records
                # have none. Requiring it left those people signed in for ever.
            elif not api.person_key(record):
                # Marker check off: a PersonID is the only remaining sign that
                # the record is someone managed rather than a stray. Weak, which
                # is why the marker check is the default.
                continue
            label = f"{api._field(record,'FirstName')} {api._field(record,'Surname')}".strip()
            to_sign_out.append((ident, label))

        if summary.get("skipped_unknown"):
            summary["warnings"].append(
                f"{summary['skipped_unknown']} person(s) left as they are: their BrightHR "
                f"lookup failed this run, and an unknown is not a clock-out."
            )
            _log(f"  left as is (BrightHR lookup failed): {summary['skipped_unknown']}")

        if summary.get("skipped_not_ours"):
            summary["warnings"].append(
                f"{summary['skipped_not_ours']} person(s) left signed in: their last event "
                f"was not ours (LastEventLocation != {cfg.INVENTRY_ACTION_LOCATION!r}), so "
                f"signing them out could undo a sign-in made at reception."
            )

        if len(to_sign_out) > cfg.INVENTRY_MAX_SIGN_OUTS_PER_RUN and not force:
            summary["warnings"].append(
                f"{len(to_sign_out)} sign-outs exceeds INVENTRY_MAX_SIGN_OUTS_PER_RUN "
                f"({cfg.INVENTRY_MAX_SIGN_OUTS_PER_RUN}); suppressed as a likely data problem."
            )
            _log(f"  sign-outs suppressed: {summary['warnings'][-1]}")
            summary["sign_outs_held_back"] = [label for _, label in to_sign_out]
            to_sign_out = []

    _log(f"PUSH plan: BrightHR on site {len(records)}, InVentry on site "
         f"{len(inventry_on_site)}, sign in {len(to_sign_in)}, sign out "
         f"{len(to_sign_out)}, already on site {summary['already_on_site']}, "
         f"unmatched {len(summary['unmatched'])}, snapshot "
         f"{'?' if age is None else f'{age:.0f} min'} old")
    # How people matched is the single most informative number on a first run:
    # it says whether matching is exact (PersonID), good (email) or fragile
    # (name). And the unmatched are the people a fire roll would miss, so they
    # are named here rather than left in a status file nobody opens.
    mb = summary["matched_by"]
    _log(f"  matched by PersonID {mb.get('PersonID', 0)}, email {mb.get('email', 0)}, "
         f"name {mb.get('name', 0)}")
    for u in summary["unmatched"]:
        _log(f"  UNMATCHED {u['name']}: {u['reason']}")

    # ── apply ──
    for ident, label, when in to_sign_in:
        if not apply:
            _log(f"  [DRY RUN] would SIGN IN  {label} ({ident}) at {when or 'now'}")
            summary["signed_in"].append(ident)
            summary["signed_in_names"].append(label)
            continue
        try:
            client.sign_in(ident, when=when)
            summary["signed_in"].append(ident)
            summary["signed_in_names"].append(label)
            _log(f"  signed in {label} ({ident})")
        except api.InVentryAPIError as exc:
            summary["failures"].append(f"sign_in {ident}: {exc}")
            _log(f"  FAILED to sign in {label}: {exc}")

    for ident, label in to_sign_out:
        if not apply:
            _log(f"  [DRY RUN] would SIGN OUT {label} ({ident})")
            summary["signed_out"].append(ident)
            summary["signed_out_names"].append(label)
            continue
        try:
            client.sign_out(ident)
            summary["signed_out"].append(ident)
            summary["signed_out_names"].append(label)
            _log(f"  signed out {label} ({ident})")
        except api.InVentryAPIError as exc:
            summary["failures"].append(f"sign_out {ident}: {exc}")
            _log(f"  FAILED to sign out {label}: {exc}")

    # ── who InVentry shows on site now ──
    # After a live run that changed anything, read InVentry back, so the list
    # is InVentry's own word rather than what we sent. Otherwise (a dry run, or
    # nothing to do) it is the list the run leaves: before, less sign-outs,
    # plus sign-ins.
    after = None
    if apply and (summary["signed_in"] or summary["signed_out"]):
        try:
            after = [r for r in client.get_personnel() if api.is_on_site(r)]
            summary["on_site_after_read_back"] = True
        except api.InVentryAPIError as exc:
            summary["warnings"].append(f"Could not read InVentry back after the run: {exc}")
    if after is None:
        by_id = {api.inventry_id(r): r for r in people}
        gone = set(summary["signed_out"])
        after = [r for i, r in inventry_on_site.items() if i not in gone]
        after += [by_id[i] for i in summary["signed_in"] if i in by_id]
        summary["on_site_after_read_back"] = False
    summary["on_site_after"] = sorted({_display(r) for r in after}, key=str.lower)

    # Anything the client raised while writing - notably the ActionLocation
    # fallback, which only shows up once a real POST has been refused.
    summary["warnings"].extend(client.warnings[warnings_taken:])

    if summary["unmatched"]:
        summary["warnings"].append(
            f"{len(summary['unmatched'])} on-site staff could not be matched to an InVentry "
            f"record, so InVentry is not updated for them. Check that their name and email "
            f"in InVentry match BrightHR."
        )
    if summary["failures"]:
        summary["status"] = "partial"
    if not enable_sign_out and len(inventry_on_site):
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
