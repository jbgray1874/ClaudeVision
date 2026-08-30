# -*- coding: utf-8 -*-
"""READ-ONLY. The acrylic RISER shows £0 in the WB 'Other Sheet' block because the 'Cost per sheet'
cell is BLANK. The engine's material result has cost_per_part_gbp=0.75 but NO raw sheet-price key.
wb_populate writes the Other Sheet block — we need to know which FIELD it reads for the 'Cost per
sheet' (column L) cell, so we add the matching key to the acrylic result (not guess the name).

This greps the LIVE wb_populate.py for how it fills the Other Sheet / acrylic block, printing the
lines that reference cost_per_sheet / the material result keys.

Run from C:\\ClaudeVision\\src :
  C:\\ClaudeVision\\.venv\\Scripts\\python.exe _probe_othersheet_cost.py
"""
import re
from pathlib import Path

WB = Path(r"C:\ClaudeVision\src\wb_populate.py")
if not WB.exists():
    print(f"NOT FOUND: {WB}"); raise SystemExit(1)

src = WB.read_text(encoding="utf-8", errors="replace")
lines = src.splitlines()

print("=== Lines mentioning 'Other Sheet' / other_sheet / cost_per_sheet / Cost per sheet ===")
for i, ln in enumerate(lines, 1):
    if re.search(r"other[_ ]sheet|cost[_ ]per[_ ]sheet|Cost per sheet|other_material|acrylic", ln, re.IGNORECASE):
        print(f"  {i}: {ln.strip()[:120]}")

print("\n=== Lines reading material_estimate keys near the other-sheet writer ===")
for i, ln in enumerate(lines, 1):
    if re.search(r"cost_per_part_gbp|unit_material_cost_gbp|extended_material_cost_gbp|sheet_price|per_sheet|stock_estimate|cost_method", ln):
        print(f"  {i}: {ln.strip()[:120]}")

print("\n=== The block that writes the other-sheet rows (search 'Sheet Length' / 'Qty Per Sheet' write) ===")
for i, ln in enumerate(lines, 1):
    if re.search(r"Qty Per Sheet|Sheet Length|Sheet Width|parts_per_sheet|Cost per|sheet_length|sheet_width", ln, re.IGNORECASE):
        # print a small window
        lo = max(0, i-2); hi = min(len(lines), i+3)
        print(f"  --- around line {i} ---")
        for j in range(lo, hi):
            print(f"    {j+1}: {lines[j].strip()[:110]}")
