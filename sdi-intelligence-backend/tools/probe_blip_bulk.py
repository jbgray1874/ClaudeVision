"""Can one BrightHR request return everyone's current clockings? Read-only.

A check asks BrightHR about each employee separately, ~200 requests, and
BrightHR's rate limit turns that into minutes. BrightHR describes the clockings
query as listing clockings "for all employees in your organisation", so one
request (with paging) may do. This finds out, without changing how the check
works: a bulk answer that silently missed people would drop them from the fire
roll call, so it is only adopted once it is shown to agree with the
person-by-person check.

    python tools/probe_blip_bulk.py

Run it straight after a check, so the comparison is against a fresh snapshot.
Prints counts and field names only, no names.
"""
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests                  # noqa: E402

import hr_blip                   # noqa: E402
import hr_config as cfg          # noqa: E402

MAX_PAGES = 50


def employee_id_of(item: dict):
    """The employee id in a clocking, wherever BrightHR puts it."""
    for key in ("employeeId", "employee_id", "EmployeeId"):
        if item.get(key):
            return str(item[key])
    emp = item.get("employee")
    if isinstance(emp, dict):
        for key in ("id", "employeeId"):
            if emp.get(key):
                return str(emp[key])
    return None


def main() -> int:
    token = hr_blip._get_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = {"filters": {"from": now}}
    items, pages, cont, first_keys = [], 0, None, None
    while pages < MAX_PAGES:
        if cont:
            body["continuationToken"] = cont
        r = requests.post(hr_blip.BLIP_URL, json=body, headers=headers, timeout=cfg.BH_TIMEOUT)
        pages += 1
        print(f"page {pages}: HTTP {r.status_code}")
        if r.status_code != 200:
            print("  answer:", r.text[:300].replace("\n", " "))
            print("\nRESULT: a query without employeeId is refused. The check stays per person.")
            return 1
        data = r.json()
        if pages == 1:
            print("  top-level fields:", sorted(data.keys()))
        page_items = data.get("items") or []
        if page_items and first_keys is None:
            first_keys = sorted(page_items[0].keys())
            print("  clocking fields:", first_keys)
        items += page_items
        cont = data.get("continuationToken")
        if not cont or not page_items:
            break

    ids = {employee_id_of(i) for i in items} - {None}
    print(f"\n{len(items)} clockings over {pages} page(s), {len(ids)} distinct employees"
          + ("" if ids or not items else " (no employee id field recognised)"))

    snap_path = Path(cfg.HR_SNAPSHOT_DIR) / "blip_latest.json"
    try:
        snap = json.loads(snap_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print("No recent per-person check to compare against: run one, then this again.")
        return 0
    checked = (snap.get("summary") or {}).get("timestamp", "?")
    per_person = {str(r.get("id")) for r in snap.get("on_site") or []}
    print(f"\nper-person check at {checked}: {len(per_person)} clocked in")
    print(f"  also in the bulk answer:      {len(per_person & ids)}")
    print(f"  MISSING from the bulk answer: {len(per_person - ids)}")
    print(f"  only in the bulk answer:      {len(ids - per_person)}")
    if per_person and not per_person - ids:
        print("\nRESULT: the bulk answer contains everyone the per-person check found."
              " Send this output to have the check switched to one request.")
    else:
        print("\nRESULT: the bulk answer does not match. The check stays per person.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
