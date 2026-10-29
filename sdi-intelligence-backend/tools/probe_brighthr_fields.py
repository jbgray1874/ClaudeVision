"""Which BrightHR employee field says who someone reports to? Read-only.

Simon wants HRInventry Anywhere's lists grouped by each person's BrightHR
manager or approver. BrightHR's field name was not in any documentation to
hand, so hr_brighthr tries the usual spellings. This shows what BrightHR
actually sends, so the guess can be confirmed or replaced:

    python tools/probe_brighthr_fields.py

It prints every field name in BrightHR's employee records with how many
records have it, marks the ones that look like a manager or approver, and
says which one the app is using now. Field names and counts only - no names,
emails or ids - so the output is safe to paste into a message.

If the app is using the wrong field, or none, set HR_MANAGER_FIELD in .env to
the right one (e.g. lineManager or holidayApprover.id) and restart the service.
"""
import collections
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hr_brighthr as bh         # noqa: E402
import hr_config as cfg          # noqa: E402

LOOKS_LIKE = re.compile(r"manager|approv|report|supervis|line|team|lead", re.I)


def paths(value, prefix=""):
    """Every field path in one record: name.givenName, lineManager.id, ..."""
    if isinstance(value, dict):
        for key, inner in value.items():
            yield from paths(inner, f"{prefix}.{key}" if prefix else key)
    elif isinstance(value, list):
        if value and isinstance(value[0], dict):
            for item in value[:3]:
                yield from paths(item, prefix + "[]")
        else:
            yield prefix + "[]"
    else:
        yield prefix


def main() -> int:
    records = bh.fetch_employees(bh.get_access_token())
    print(f"{len(records)} employee records from BrightHR")
    seen = collections.Counter()
    for r in records:
        for p in set(paths(r)):
            seen[p] += 1
    print("\nField                                         records")
    for p, n in sorted(seen.items()):
        print(f"  {p:<44}{n:>6}{'   <- manager or approver?' if LOOKS_LIKE.search(p) else ''}")
    staff = bh.name_managers([bh.normalise_employee(r) for r in records])
    current = [e for e in staff if not e["terminated"]]
    used = collections.Counter(e["manager_field"] for e in current if e["manager_field"])
    named = sum(1 for e in current if e["manager_name"])
    print(f"\nHR_MANAGER_FIELD is {cfg.HR_MANAGER_FIELD or '(not set: trying the usual names)'}")
    print(f"Current staff: {len(current)}; with a manager found: "
          f"{sum(used.values())}; with the manager's name: {named}")
    print("Fields the managers came from: " + (", ".join(f"{f} ({n})" for f, n in used.items())
                                             or "none - no manager field was recognised"))
    print(f"Distinct managers: {len({e['manager_name'] for e in current if e['manager_name']})}")
    return 0 if named else 2


if __name__ == "__main__":
    sys.exit(main())
