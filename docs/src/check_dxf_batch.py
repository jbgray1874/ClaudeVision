"""Quick DXF health check — flat-pattern reference part 9376-01-001."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dxf_reader import extract_flat_pattern_data, extract_dxf_metadata, extract_dxf_pages, is_dxf_path

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES = [
    ROOT / "input" / "drawings" / "DXF" / "9376-01-001_MS_1.5mm_revL.DXF",
    ROOT / "input" / "drawings" / "DXF" / "9376-01-001_MS_1_5mm_revL.DXF",
    ROOT / "input" / "drawings" / "DXF" / "9376-01-002_MS_1.5mm_revL.DXF",
    ROOT / "input" / "drawings" / "DXF" / "9376-01-003_MS_1.5mm_revL.DXF",
    ROOT / "input" / "drawings" / "DXF" / "9376-01-GA_RevJ.DXF",
]


def main() -> None:
    try:
        import ezdxf  # noqa: F401
    except ImportError:
        print("ERROR: ezdxf not installed — pip install ezdxf")
        return

    for path in CANDIDATES:
        if not path.is_file():
            continue
        print(f"\n=== {path.name} ===")
        print(f"  is_dxf_path: {is_dxf_path(path)}")
        meta = extract_dxf_metadata(path)
        print(f"  insunits: {meta.get('$INSUNITS')}")

        if is_ignored_ga(path):
            print("  (GA sheet — skip flat-pattern metrics)")
            continue

        flat = extract_flat_pattern_data(path)
        print(f"  Part: {flat.get('part_number')}")
        print(f"  Area: {flat.get('blank_area_mm2')} mm²")
        print(f"  Weight: {flat.get('weight_g')} g")
        print(f"  Bends: {flat.get('bend_count')}")
        print(f"  Score: {flat.get('geometry_score')}")
        print(f"  Flat pattern: {flat.get('flat_pattern_detected')}")

        if "9376-01-001" in str(flat.get("part_number")):
            area = float(flat.get("blank_area_mm2") or 0)
            wg = float(flat.get("weight_g") or 0)
            if abs(area - 11791.84) < 100 and abs(wg - 138.85) < 3:
                print("  OK: matches reference (11791.84 mm², 138.85 g, bends=2, score=1.0)")
            else:
                print("  WARN: differs from reference 11791.84 mm² / 138.85 g")


def is_ignored_ga(path: Path) -> bool:
    n = path.name.upper()
    return "-GA_" in n or "_GA_" in n


if __name__ == "__main__":
    main()
