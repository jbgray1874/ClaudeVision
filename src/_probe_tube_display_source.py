# -*- coding: utf-8 -*-
"""READ-ONLY. Confirmed: estimator.py:1416 stores stock_estimate.catalogue_description =
the catalogue entry's description (job 11406's 'ITEM 1 - 11406-02-02M ... @798MM'). The tube
BOM line on the sheet shows THAT foreign identity instead of this part's 'CROSS RAIL'.

Find WHERE wb_populate reads it for the display line, so we fix the right place. Greps the LIVE
wb_populate.py (not in snapshot) for catalogue_description / the BOM-line description build.

Run from C:\\ClaudeVision\\src :
  C:\\ClaudeVision\\.venv\\Scripts\\python.exe _probe_tube_display_source.py
"""
import re
from pathlib import Path
SRC = Path(r"C:\ClaudeVision\src")

for fn in ("wb_populate.py", "xlsx_output.py", "estimator.py"):
    p = SRC / fn
    if not p.exists():
        print(f"{fn}: NOT FOUND"); continue
    lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    print(f"\n===== {fn}: catalogue_description / tube BOM-line description usage =====")
    for i, l in enumerate(lines):
        if re.search(r"catalogue_description|catalogue_part_code|stock_estimate.*descr|bom.*descr.*catalogue|ITEM \d|description.*stock_estimate", l, re.I):
            print(f"  {i+1}: {l.strip()[:110]}")

# Also: what does THIS tube's part record actually have for its own description/part_number?
print("\n===== the tube part record (12532-02-08M) in the JSON — its own identity =====")
import json
J = Path(r"C:\ClaudeVision\output\json\12532-03RecipeCard.json")
if J.exists():
    data = json.loads(J.read_text(encoding="utf-8"))
    def walk(o):
        if isinstance(o, dict):
            yield o
            for v in o.values(): yield from walk(v)
        elif isinstance(o, list):
            for v in o: yield from walk(v)
    for node in walk(data):
        if isinstance(node, dict) and str(node.get("part_number") or "")=="12532-02-08M":
            se = (node.get("material_estimate") or {}).get("stock_estimate") or node.get("stock_estimate") or {}
            print(f"  part_number: {node.get('part_number')}")
            print(f"  description: {node.get('description')}")
            print(f"  stock_estimate.catalogue_description: {se.get('catalogue_description')}")
            print(f"  stock_estimate.catalogue_part_code: {se.get('catalogue_part_code')}")
            print(f"  stock_estimate.section_length_mm: {se.get('section_length_mm')}")
            break

print("\nVERDICT: whichever writer builds the BOM line from catalogue_description is the fix site.")
print("Fix = display THIS part's number+description (12532-02-08M CROSS RAIL); keep catalogue for PRICE only.")
