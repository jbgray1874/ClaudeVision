"""Build employee_map.json - BrightHR employee_id -> InVentry StaffID.

The two systems have separate identifiers, so the sync needs an explicit map.
This pulls the employee list from BrightHR, reads an InVentry staff export, and
matches on email, then payroll/staff number, then normalised full name.

    # 1. See what BrightHR has (writes nothing)
    python tools/build_employee_map.py --list-brighthr

    # 2. Match against an InVentry export and write the map
    python tools/build_employee_map.py --inventry-csv inventry_staff.csv -o employee_map.json

The InVentry CSV needs a staff id column and a name column; --id-column and
--name-column override the auto-detected headers. Matches are printed for
review - check the file before pointing the sync at it.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brighthr_client import BrightHRClient, BrightHRError  # noqa: E402
from config import ConfigError, load_config  # noqa: E402
from employee_map import EmployeeMap  # noqa: E402

log = logging.getLogger("build_employee_map")

ID_HEADERS = ("staffid", "staff_id", "id", "employeeid", "employee_id", "reference")
NAME_HEADERS = ("staffname", "staff_name", "name", "fullname", "full_name", "displayname")
EMAIL_HEADERS = ("email", "emailaddress", "email_address", "workemail")


def _norm_name(value: str) -> str:
    return " ".join(str(value).strip().lower().split())


def _norm_email(value: str) -> str:
    return str(value).strip().lower()


def _pick_column(headers: Sequence[str], wanted: Sequence[str]) -> Optional[str]:
    lookup = {h.replace(" ", "").replace("_", "").lower(): h for h in headers}
    for candidate in wanted:
        key = candidate.replace("_", "")
        if key in lookup:
            return lookup[key]
    return None


def read_inventry_csv(
    path: Path, id_column: Optional[str], name_column: Optional[str], email_column: Optional[str]
) -> List[Dict[str, str]]:
    with Path(path).open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        id_col = id_column or _pick_column(headers, ID_HEADERS)
        name_col = name_column or _pick_column(headers, NAME_HEADERS)
        email_col = email_column or _pick_column(headers, EMAIL_HEADERS)
        if not id_col:
            raise SystemExit(
                f"Could not find a staff id column in {path}. Headers: {headers}. Use --id-column."
            )
        rows = []
        for row in reader:
            staff_id = (row.get(id_col) or "").strip()
            if not staff_id:
                continue
            rows.append(
                {
                    "staff_id": staff_id,
                    "name": (row.get(name_col) or "").strip() if name_col else "",
                    "email": (row.get(email_col) or "").strip() if email_col else "",
                }
            )
    log.info("Read %s InVentry staff rows from %s", len(rows), path)
    return rows


def match(
    brighthr_employees: Sequence[Dict[str, str]], inventry_staff: Sequence[Dict[str, str]]
) -> tuple:
    by_email = {_norm_email(s["email"]): s for s in inventry_staff if s.get("email")}
    by_id = {s["staff_id"].strip().lower(): s for s in inventry_staff}
    by_name: Dict[str, List[Dict[str, str]]] = {}
    for staff in inventry_staff:
        if staff.get("name"):
            by_name.setdefault(_norm_name(staff["name"]), []).append(staff)

    mapped: Dict[str, Dict[str, str]] = {}
    unmatched: List[Dict[str, str]] = []
    claimed = set()

    for employee in brighthr_employees:
        candidate = None
        how = ""
        email = _norm_email(employee.get("email", ""))
        number = str(employee.get("employee_number", "")).strip().lower()
        name = _norm_name(employee.get("employee_name", ""))

        if email and email in by_email:
            candidate, how = by_email[email], "email"
        elif number and number in by_id:
            candidate, how = by_id[number], "employee number == staff id"
        elif name and len(by_name.get(name, [])) == 1:
            candidate, how = by_name[name][0], "name"
        elif name and len(by_name.get(name, [])) > 1:
            unmatched.append({**employee, "note": "ambiguous - several InVentry staff share this name"})
            continue

        if candidate is None:
            unmatched.append({**employee, "note": "no InVentry match"})
            continue
        if candidate["staff_id"] in claimed:
            unmatched.append({**employee, "note": f"InVentry {candidate['staff_id']} already matched"})
            continue

        claimed.add(candidate["staff_id"])
        mapped[employee["employee_id"]] = {
            "inventry_staff_id": candidate["staff_id"],
            "name": employee.get("employee_name") or candidate.get("name", ""),
            "matched_on": how,
        }

    unclaimed = [s for s in inventry_staff if s["staff_id"] not in claimed]
    return mapped, unmatched, unclaimed


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build the BrightHR -> InVentry employee map.")
    parser.add_argument("--inventry-csv", type=Path, help="CSV export of InVentry staff.")
    parser.add_argument("--id-column", help="InVentry CSV column holding the staff id.")
    parser.add_argument("--name-column", help="InVentry CSV column holding the staff name.")
    parser.add_argument("--email-column", help="InVentry CSV column holding the email address.")
    parser.add_argument("--list-brighthr", action="store_true", help="Print BrightHR employees and exit.")
    parser.add_argument("-o", "--output", type=Path, help="Where to write employee_map.json.")
    parser.add_argument("--env-file", type=Path)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")

    try:
        config = load_config(args.env_file)
        config.validate_for_brighthr()
        employees = BrightHRClient(config.brighthr).get_employees()
    except (ConfigError, BrightHRError) as exc:
        log.error("Could not read BrightHR employees: %s", exc)
        return 1

    log.info("BrightHR returned %s employees", len(employees))

    if args.list_brighthr or not args.inventry_csv:
        for employee in employees:
            print(
                f"{employee['employee_id']:<16} {employee['employee_name'] or '?':<30} "
                f"{employee['email']:<32} {employee['employee_number']}"
            )
        if not args.inventry_csv:
            print("\nPass --inventry-csv <export.csv> to build the map.", file=sys.stderr)
        return 0

    inventry_staff = read_inventry_csv(
        args.inventry_csv, args.id_column, args.name_column, args.email_column
    )
    mapped, unmatched, unclaimed = match(employees, inventry_staff)

    print(f"\nMatched {len(mapped)} of {len(employees)} BrightHR employees")
    for brighthr_id, entry in sorted(mapped.items()):
        print(f"  {brighthr_id:<16} -> {entry['inventry_staff_id']:<16} {entry['name']:<28} ({entry['matched_on']})")

    if unmatched:
        print(f"\nUnmatched BrightHR employees ({len(unmatched)}) - map these by hand:")
        for employee in unmatched:
            print(f"  {employee['employee_id']:<16} {employee.get('employee_name', '?'):<30} {employee['note']}")

    if unclaimed:
        print(f"\nInVentry staff with no BrightHR match ({len(unclaimed)}):")
        for staff in unclaimed:
            print(f"  {staff['staff_id']:<16} {staff.get('name', '')}")

    output = args.output or config.sync.employee_map_path
    employee_map = EmployeeMap(
        brighthr_to_inventry={k: v["inventry_staff_id"] for k, v in mapped.items()},
        names={k: v["name"] for k, v in mapped.items()},
    )
    payload = employee_map.to_dict()
    payload["_unmatched_brighthr"] = [e["employee_id"] for e in unmatched]
    Path(output).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nWrote {output}. Review it before running the sync with --apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
