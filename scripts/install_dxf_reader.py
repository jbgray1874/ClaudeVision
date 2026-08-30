#!/usr/bin/env python3
"""Install src/dxf_reader.py.py as the canonical src/dxf_reader.py (monolithic)."""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "dxf_reader.py.py"
DST = ROOT / "src" / "dxf_reader.py"
DOWNLOADS = [
    Path.home() / "Documents" / "Downloads" / "dxf_reader.py.py",
    Path.home() / "Documents" / "Downloads" / "dxf_reader_py (6).py",
    Path.home() / "Documents" / "Downloads" / "dxf_reader_py (5).py",
    Path.home() / "Documents" / "Downloads" / "dxf_reader_py (4).py",
    Path.home() / "Documents" / "Downloads" / "dxf_reader_py (2).py",
    Path.home() / "Documents" / "Downloads" / "dxf_reader_py (1).py",
    Path.home() / "Documents" / "Downloads" / "dxf_reader (1).py",
    Path.home() / "Documents" / "Downloads" / "dxf_reader.py",
]

if not SRC.is_file():
    for alt in DOWNLOADS:
        if alt.is_file():
            shutil.copy2(alt, SRC)
            print(f"Copied {alt} -> {SRC}")
            break

if not SRC.is_file():
    raise SystemExit(f"Missing {SRC} — copy your Downloads upgrade there first")

data = SRC.read_bytes()
DST.write_bytes(data)
text = data.decode("utf-8")
for needle in ("extract_flat_pattern_data", "stem_norm", "merge_dxf_into_scan_json"):
    if needle not in text:
        raise SystemExit(f"Upgrade incomplete: missing {needle}")
print(f"Installed {len(data)} bytes -> {DST}")
