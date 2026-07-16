#!/usr/bin/env python3
"""
Deploy upgraded DXF reader from Downloads or src/dxf_reader.py.py.

Default layout (recommended): keep the 1,224-line module as src/dxf_reader.py.py;
src/dxf_reader.py is a thin loader shim.

Optional: pass --monolithic to copy the upgrade into src/dxf_reader.py directly
(replaces the shim with the full file).
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
DST = SRC_DIR / "dxf_reader.py"

SOURCES = [
    SRC_DIR / "dxf_reader.py.py",
    Path(r"C:\Users\james.gray\Documents\Downloads\dxf_reader.py.py"),
    Path(r"C:\Users\james.gray\Documents\Downloads\dxf_reader (1).py"),
    Path(r"C:\Users\james.gray\Documents\Downloads\dxf_reader.py"),
]


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--monolithic",
        action="store_true",
        help="Copy upgrade into dxf_reader.py (replaces loader shim).",
    )
    args = parser.parse_args()
    target = DST if args.monolithic else SRC_DIR / "dxf_reader.py.py"

    for src in SOURCES:
        if not src.is_file():
            continue
        shutil.copy2(src, target)
        text = target.read_text(encoding="utf-8")
        if "extract_flat_pattern_data" not in text:
            print(f"ERROR: {src} missing extract_flat_pattern_data", file=sys.stderr)
            return 1
        if "stem_norm" not in text and "1_5mm" not in text:
            print("WARN: _parse_filename 1_5mm pre-join not found", file=sys.stderr)
        lines = text.count("\n") + 1
        label = "dxf_reader.py" if args.monolithic else "dxf_reader.py.py"
        print(f"OK: deployed {src.name} -> {label} ({lines} lines, {target.stat().st_size} bytes)")
        if not args.monolithic:
            print("     dxf_reader.py loader shim will import from dxf_reader.py.py")
        return 0
    print("ERROR: no upgraded dxf_reader source found. Expected one of:", file=sys.stderr)
    for s in SOURCES:
        print(f"  - {s}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
