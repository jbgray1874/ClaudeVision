# -*- coding: utf-8 -*-
"""READ-ONLY. The wb_populate warning 'Steel overflow: 14 steel parts but only 11 rows — extras
DROPPED' means the Sheet Steel block in the template has a fixed number of rows and parts beyond
that are silently lost. This UNDOES the dropped-parts fix at the writer stage.

Find in LIVE wb_populate.py:
  1. Where the steel-block row limit is defined / detected (the '11 rows' figure)
  2. How rows are written into it (fixed range? dynamic? insert vs overwrite?)
  3. The overflow warning site — what it does when parts > rows (drops silently)
So we can decide the fix: insert rows to widen the block, or spill overflow into another handling.

Run from C:\\ClaudeVision\\src :
  C:\\ClaudeVision\\.venv\\Scripts\\python.exe _probe_steel_block.py
"""
import re
from pathlib import Path
SRC = Path(r"C:\ClaudeVision\src")
p = SRC / "wb_populate.py"
if not p.exists():
    print("wb_populate.py NOT FOUND"); raise SystemExit(1)

lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
print(f"wb_populate.py: {len(lines)} lines\n")

# 1. the overflow warning + steel block row handling
print("=== steel block: rows, overflow, DROPPED, insert_rows, block boundaries ===")
for i, l in enumerate(lines):
    if re.search(r"overflow|DROPPED|steel.*row|row.*steel|SHEET STEEL|Sheet Steel|steel_rows|"
                 r"steel_block|max.*steel|steel.*limit|insert_rows|insert_row|Widen", l, re.I):
        print(f"  {i+1}: {l.strip()[:120]}")

# 2. how many rows the steel block has (search for the anchor/range detection)
print("\n=== block row-count detection (how it finds '11 rows') ===")
for i, l in enumerate(lines):
    if re.search(r"other sheet|Other Sheet|block_end|block_start|find.*row|anchor.*row|"
                 r"row_start|row_end|first_row|last_row|n_rows|num_rows", l, re.I):
        print(f"  {i+1}: {l.strip()[:120]}")

# 3. is there an insert-row capability anywhere (openpyxl insert_rows)?
print("\n=== openpyxl row-insertion available? ===")
for i, l in enumerate(lines):
    if re.search(r"insert_rows|insert_cols|move_range|\.insert\(", l):
        print(f"  {i+1}: {l.strip()[:120]}")

print("\nVERDICT: if the block is a FIXED row range (e.g. rows N..N+10) with no insert, the fix is to")
print("insert_rows to widen it to fit steel_part_count, OR (simpler/safer) warn+spill so nothing is")
print("SILENTLY dropped. Need to see the write mechanics to pick the safe one.")
