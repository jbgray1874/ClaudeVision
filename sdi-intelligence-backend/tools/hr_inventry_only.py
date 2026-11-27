"""Who is signed in on InVentry but not clocked in on BrightHR. Read only.

    python tools/hr_inventry_only.py
    python tools/hr_inventry_only.py --csv "K:\\IT\\HRSystemsOutput\\InVentry only.csv"

The 5-minute sync only goes one way, BrightHR to InVentry. Someone who signs in
on the console but never clocks in on Blip is on InVentry's fire list but has no
BrightHR clocking, so their hours are missing. This lists them, using the sync's
own matching (PersonID, then email, then name), so anyone it names is someone
the sync also sees as not clocked in.

For each person it says how they were signed in (the console, or the sync
itself, which signs its own out on its next run), whether the sign-in is from
today, and whether BrightHR knows them at all: an employee who did not clock
in, a clocking left open for over 20 hours, or nobody BrightHR employs.

Reads the latest BrightHR check (blip_latest.json, refreshed every 5 minutes),
InVentry's staff records, and BrightHR's staff list. Writes nothing to either.
"""
import argparse
import csv
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hr_blip_inventry as source_loader   # noqa: E402
import hr_config as cfg                    # noqa: E402
import hr_inventry_api as api              # noqa: E402
import hr_onsite_push as push              # noqa: E402

CONSOLE, SYNC = "console", "sync"
NOT_CLOCKED_IN = "employee, not clocked in"
FORGOTTEN = "clocking open over 20 h"
NOT_EMPLOYED = "not a current BrightHR employee"
UNKNOWN = "staff list not read"


def _person(e):
    return {"brighthr_id": str(e.get("id") or e.get("brighthr_id") or "").strip(),
            "first_name": e.get("first_name") or "", "surname": e.get("surname") or "",
            "email": e.get("email") or ""}


def find(people, snapshot, staff=None, now=None):
    """people: InVentry personnel. snapshot: blip_latest.json as loaded.
    staff: BrightHR's current employees, or None if they could not be read.

    Returns {"rows": [...], "checked": <snapshot time>, "age_minutes": n}.
    """
    now = now or datetime.datetime.now(datetime.timezone.utc)
    records, meta = source_loader._normalise(snapshot)
    clocked, forgotten = source_loader.split_stale_clockins(records, now=now)
    by_person_id, by_email, by_name = push._index_personnel(people)

    def ids(persons):
        out = set()
        for p in persons:
            record, _ = push._match(_person(p), by_person_id, by_email, by_name)
            if record is not None:
                out.add(api.inventry_id(record))
        return out

    clocked_ids, forgotten_ids = ids(clocked), ids(forgotten)
    employed_ids = ids(staff) if staff is not None else None
    today = api.inventry_day(now)

    rows = []
    for r in people:
        if not api.is_on_site(r):
            continue
        ident = api.inventry_id(r)
        if ident in clocked_ids:
            continue
        if ident in forgotten_ids:
            brighthr = FORGOTTEN
        elif employed_ids is None:
            brighthr = UNKNOWN
        elif ident in employed_ids:
            brighthr = NOT_CLOCKED_IN
        else:
            brighthr = NOT_EMPLOYED
        day = api.activity_day(r)
        rows.append({
            "name": push._display(r),
            "since": str(api._field(r, "LastActivityDate") or "")[:16].replace("T", " "),
            "earlier_day": bool(day and today and day < today),
            "how": SYNC if api.signed_in_by_us(r) else CONSOLE,
            "brighthr": brighthr,
        })
    rows.sort(key=lambda x: (x["how"] != CONSOLE, x["name"].lower()))
    age = source_loader._age_minutes(meta.get("timestamp"))
    return {"rows": rows, "checked": meta.get("timestamp"),
            "age_minutes": None if age is None else round(age)}


def report(result):
    rows = result["rows"]
    lines = [f"Signed in on InVentry, not clocked in on BrightHR: {len(rows)}"]
    if result["age_minutes"] is not None:
        lines.append(f"BrightHR check {result['age_minutes']} min old")
        if result["age_minutes"] > cfg.BLIP_MAX_STALE_MINUTES:
            lines.append("  Old: the 5-minute sync may not be running, so this list may be wrong.")
    if not rows:
        lines.append("Nobody.")
        return "\n".join(lines)
    counts = {}
    for r in rows:
        counts[r["brighthr"]] = counts.get(r["brighthr"], 0) + 1
    lines.append("  " + ", ".join(f"{n} {k}" for k, n in counts.items()))
    earlier = sum(1 for r in rows if r["earlier_day"])
    if earlier:
        lines.append(f"  {earlier} signed in on an earlier day and never signed out")
    lines.append("")
    w = max(len(r["name"]) for r in rows) + 2
    lines.append(f"{'Name':<{w}}{'Signed in':<18}{'How':<10}BrightHR")
    for r in rows:
        when = r["since"] + (" *" if r["earlier_day"] else "")
        how = "sync" if r["how"] == SYNC else "console"
        lines.append(f"{r['name']:<{w}}{when:<18}{how:<10}{r['brighthr']}")
    if earlier:
        lines.append("\n* an earlier day")
    if any(r["how"] == SYNC for r in rows):
        lines.append("'sync' rows are the sync's own sign-ins; it signs them out on its next run.")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv", metavar="PATH", help="also write the list to a CSV file")
    args = ap.parse_args(argv)

    snapshot = json.loads(Path(source_loader._resolve_source(source_loader.SOURCE_LATEST))
                          .read_text(encoding="utf-8"))
    people = api.InVentryAPI().get_personnel()
    staff = None
    try:
        import hr_blip
        staff = hr_blip._current_staff(hr_blip._get_token())
    except Exception as exc:                       # noqa: BLE001
        print(f"BrightHR's staff list could not be read ({exc}); "
              f"the BrightHR column says '{UNKNOWN}'.\n")
    result = find(people, snapshot, staff)
    print(report(result))
    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["name", "since", "earlier_day", "how", "brighthr"])
            w.writeheader()
            w.writerows(result["rows"])
        print(f"\nWrote {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
