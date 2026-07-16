#!/usr/bin/env python3
"""Smoke-test upgraded dxf_reader (_parse_filename 1_5mm fix + flat-pattern API)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    from dxf_reader import (
        CUT_LAYERS,
        _parse_filename,
        extract_flat_pattern_data,
        extract_dxf_geometry,
        is_dxf_path,
    )

    print("CUT_LAYERS:", sorted(CUT_LAYERS))

    for label, sample in [
        ("underscore", Path("9376-01-001_MS_1_5mm_revL.DXF")),
        ("dot", Path("9376-01-001_MS_1.5mm_revL.DXF")),
    ]:
        parsed = _parse_filename(sample)
        thk = parsed.get("thickness_mm")
        pn = parsed.get("part_number")
        print(f"_parse_filename ({label}):", parsed)
        if thk != 1.5:
            print(f"FAIL [{label}]: expected thickness_mm=1.5, got {thk!r}")
            return 1
        if pn != "9376-01-001":
            print(f"FAIL [{label}]: expected part_number=9376-01-001, got {pn!r}")
            return 1

    for name in ("extract_dxf_geometry", "extract_flat_pattern_data", "is_dxf_path"):
        print(f"OK: {name} imported")

    dxf_dir = ROOT / "input" / "drawings" / "DXF"
    if dxf_dir.is_dir():
        matches = list(dxf_dir.glob("9376-01-001*MS*1*5mm*.DXF")) + list(
            dxf_dir.glob("9376-01-001*MS*1*5mm*.dxf")
        )
        if matches:
            path = matches[0]
            flat = extract_flat_pattern_data(path)
            print(f"\nPart: {flat.get('part_number')}")
            print(f"  File: {path.name}")
            print(f"  Area: {flat.get('blank_area_mm2')} mm²")
            print(f"  Weight: {flat.get('weight_g')} g")
            print(f"  Bends: {flat.get('bend_count')}")
            print(f"  Score: {flat.get('geometry_score')}")
    else:
        print("(skip flat-pattern file test — no input/drawings/DXF)")

    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
