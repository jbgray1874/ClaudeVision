"""Map a real BrightHR JSON sample onto field_map.json.

The handover flags the exact BrightHR field names as unknown. Point this at the
JSON you already have and it reports what the current field map resolves, what
it misses, and the exact edit to make.

    python tools/inspect_brighthr_json.py sample.json
    python tools/inspect_brighthr_json.py sample.json --section event
    cat sample.json | python tools/inspect_brighthr_json.py -

Reads only; changes nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brighthr_client import (  # noqa: E402
    AttendanceEvent,
    FieldMap,
    _lookup,
    _normalise_key,
    derive_presence,
    unwrap_collection,
)

SECTION_ROOTS = {"event": "events_root", "employee": "employees_root", "absence": "absences_root"}


def flatten_keys(record: Mapping[str, Any], prefix: str = "") -> List[str]:
    keys: List[str] = []
    for key, value in record.items():
        path = f"{prefix}{key}"
        keys.append(path)
        if isinstance(value, Mapping):
            keys.extend(flatten_keys(value, f"{path}."))
    return keys


def report_section(records: Sequence[Mapping[str, Any]], field_map: FieldMap, section: str) -> Dict[str, Any]:
    logical_fields = getattr(field_map, section, {})
    resolved: Dict[str, Dict[str, Any]] = {}
    used_keys = set()

    for logical_name, candidates in logical_fields.items():
        matched_key = None
        sample_value = None
        hits = 0
        for record in records:
            # Test candidates one at a time so the report names the key that
            # actually matched, not just the first one in the list.
            for candidate in candidates:
                value = _lookup(record, [candidate])
                if value is None:
                    continue
                hits += 1
                if matched_key is None:
                    flat = {_normalise_key(str(k)): str(k) for k in flatten_keys(record)}
                    matched_key = flat.get(_normalise_key(candidate), candidate)
                    sample_value = value
                break
        resolved[logical_name] = {
            "matched_key": matched_key,
            "sample_value": sample_value,
            "coverage": f"{hits}/{len(records)}",
        }
        if matched_key:
            used_keys.add(_normalise_key(matched_key))

    all_keys: Dict[str, str] = {}
    for record in records:
        for key in flatten_keys(record):
            all_keys.setdefault(_normalise_key(key), key)
    unused = sorted(original for norm, original in all_keys.items() if norm not in used_keys)

    return {"resolved": resolved, "unused_keys": unused}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check field_map.json against a real BrightHR JSON sample.")
    parser.add_argument("path", help="Path to the JSON sample, or - for stdin.")
    parser.add_argument(
        "--section",
        choices=sorted(SECTION_ROOTS),
        default="event",
        help="Which shape the sample contains (default: event).",
    )
    parser.add_argument(
        "--field-map",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "field_map.json",
    )
    args = parser.parse_args(argv)

    raw_text = sys.stdin.read() if args.path == "-" else Path(args.path).read_text(encoding="utf-8")
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        print(f"Not valid JSON: {exc}", file=sys.stderr)
        return 1

    field_map = FieldMap.load(args.field_map)
    roots = getattr(field_map, SECTION_ROOTS[args.section])
    records = unwrap_collection(payload, roots)

    print(f"Sample: {args.path}")
    print(f"Section: {args.section}")
    print(f"Records found: {len(records)}")
    if not records:
        top_level = list(payload)[:20] if isinstance(payload, Mapping) else type(payload).__name__
        print("\nNo records found. Top-level keys:", top_level)
        print(f"Add the wrapping key to '{SECTION_ROOTS[args.section]}' in field_map.json.")
        return 1

    report = report_section(records, field_map, args.section)

    print("\nField mapping")
    print("-" * 72)
    missing = []
    for logical_name, info in report["resolved"].items():
        if info["matched_key"]:
            value = str(info["sample_value"])
            value = value[:40] + "..." if len(value) > 40 else value
            print(f"  OK      {logical_name:<16} <- {info['matched_key']:<24} {info['coverage']:>8}  e.g. {value}")
        else:
            missing.append(logical_name)
            print(f"  MISSING {logical_name:<16} <- (no candidate matched)")

    if report["unused_keys"]:
        print("\nKeys in the sample that the field map does not use:")
        for key in report["unused_keys"]:
            print(f"  {key}")

    if missing:
        print("\nAdd the right key from the list above to field_map.json under")
        print(f'  "{args.section}": {{ "<field>": ["<key>", ...] }}')
        print("Unmapped fields:", ", ".join(missing))

    if args.section == "event":
        events = [e for e in (AttendanceEvent.from_record(r, field_map) for r in records) if e]
        unknown_types = sorted({e.raw_event_type for e in events if e.event_type is None and e.raw_event_type})
        if unknown_types:
            print("\nEvent type values not recognised - add them to field_map.json event_types:")
            for value in unknown_types:
                print(f"  {value!r}")
        bad_timestamps = [e for e in events if e.timestamp is None]
        if bad_timestamps:
            print(f"\n{len(bad_timestamps)} event(s) had an unparseable timestamp, e.g.:")
            print("  ", field_map.get("event", "timestamp", bad_timestamps[0].raw))

        presence = derive_presence(events, treat_break_as_on_site=True)
        on_site = [p for p in presence.values() if p.is_on_site]
        print(f"\nDerived presence: {len(on_site)} of {len(presence)} employees on site")
        for person in on_site[:15]:
            since = person.since.isoformat() if person.since else "unknown"
            print(f"  {person.employee_id:<14} {person.employee_name or '?':<26} {person.state:<9} since {since}")
        if len(on_site) > 15:
            print(f"  ... and {len(on_site) - 15} more")

    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main())
