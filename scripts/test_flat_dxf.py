#!/usr/bin/env python3
"""
Test flat-pattern DXF extraction (9376-01-001 reference part).

Usage:
  python scripts/test_flat_dxf.py
  python scripts/test_flat_dxf.py "input\\drawings\\DXF\\9376-01-001_MS_1.5mm_revL.DXF"
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Reference values from upgraded dxf_reader on 9376-01-001 channel frame
EXPECTED_9376_001 = {
    "part_number": "9376-01-001",
    "blank_area_mm2": 11791.84,
    "weight_g": 138.85,
    "bend_count": 2,
    "geometry_score": 1.0,
    "thickness_mm": 1.5,
}


def _close(a: float, b: float, tol: float) -> bool:
    return abs(float(a) - float(b)) <= tol


def test_path(path: Path, *, strict: bool = False) -> int:
    from dxf_reader import _parse_filename, extract_flat_pattern_data

    if not path.is_file():
        print(f"ERROR: not found: {path}")
        return 1

    parsed = _parse_filename(path)
    flat = extract_flat_pattern_data(path)

    pn = flat.get("part_number") or parsed.get("part_number")
    area = float(flat.get("blank_area_mm2") or 0)
    weight_g = float(flat.get("weight_g") or 0)
    bends = int(flat.get("bend_count") or 0)
    score = float(flat.get("geometry_score") or 0)
    thk = parsed.get("thickness_mm") or flat.get("thickness_mm")

    print(f"Part: {pn}")
    print(f"  File: {path.name}")
    print(f"  _parse_filename: {parsed}")
    print(f"  Area: {area} mm²")
    print(f"  Weight: {weight_g} g")
    print(f"  Bends: {bends}")
    print(f"  Score: {score}")
    print(f"  Flat pattern: {flat.get('flat_pattern_detected')}")
    print(f"  Perimeter: {flat.get('perimeter_mm')} mm")

    if not strict or "9376-01-001" not in str(pn):
        return 0

    exp = EXPECTED_9376_001
    ok = True
    if thk is not None and not _close(thk, exp["thickness_mm"], 0.01):
        print(f"  WARN thickness_mm={thk} (expected {exp['thickness_mm']})")
        ok = False
    if not _close(area, exp["blank_area_mm2"], 50.0):
        print(f"  WARN area (expected ~{exp['blank_area_mm2']})")
        ok = False
    if not _close(weight_g, exp["weight_g"], 2.0):
        print(f"  WARN weight_g (expected ~{exp['weight_g']})")
        ok = False
    if bends != exp["bend_count"]:
        print(f"  WARN bend_count (expected {exp['bend_count']})")
        ok = False
    if score < 0.99:
        print(f"  WARN geometry_score (expected {exp['geometry_score']})")
        ok = False

    if ok:
        print("  OK: matches 9376-01-001 reference expectations.")
    else:
        print("  Some metrics differ — check DXF revision or layer names.")
    return 0 if ok or not strict else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dxf", nargs="?", help="DXF path (default: 9376-01-001 on disk)")
    parser.add_argument("--strict", action="store_true", help="Fail if 9376-01-001 metrics differ")
    args = parser.parse_args()

    if args.dxf:
        return test_path(Path(args.dxf), strict=args.strict)

    default = ROOT / "input" / "drawings" / "DXF" / "9376-01-001_MS_1.5mm_revL.DXF"
    if default.is_file():
        return test_path(default, strict=args.strict)

    print(f"Default DXF not found: {default}")
    print("Pass a path: python scripts/test_flat_dxf.py path\\to\\file.DXF")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
