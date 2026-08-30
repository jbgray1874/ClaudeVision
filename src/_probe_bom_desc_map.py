# -*- coding: utf-8 -*-
"""READ-ONLY. The engine ALREADY has a BOM-description fallback (document_builder.py ~L1469:
`if not p.get('description'): p['description'] = _bom_desc.get(partno)`). But it didn't fire
for 12532-02-03M / 12532-03-03M. Find out WHY: does _bom_desc contain entries for these part
numbers, and if not, does QTY_TABLE_ROW_PATTERN actually match their BOM rows?

Re-runs the SAME parsing the engine uses (extract_bom_rows + the pattern) on the real BOM text
from this job's pages, and prints what part->description map results. Touches nothing; imports
the live modules read-only.

Run from C:\\ClaudeVision\\src :
  C:\\ClaudeVision\\.venv\\Scripts\\python.exe _probe_bom_desc_map.py
"""
import re, json
from pathlib import Path

# the two BOM row texts from the probe (real, from this job's pages 4 and 17)
bom_texts = {
  "page4":  "ITEM DWG NO. DESCRIPTION QTY 1 12532-02-03M FRONT PANEL 1 2 12532-02-04M SIDE PANEL 2 3 12532-02-05M TOP CAP 1 4 12532-02-06M CASTOR PLATE 4 5 12532-02-07M LOWER GRAPHIC CHANNEL 2 6 12532-02-08M CROSS RAIL 2 7 12532-02-09M HEADER GRAPHIC CHANNEL 2 8 12532-02-10M GRAPHIC CHANNEL 2 9 12532-02-11M BACK PANEL 1",
  "page17": "ITEM DWG NO. DESCRIPTION QTY 1 12532-03-03M SHELF BODY 1 2 12532-03-06M BACK WALL 1 3 12532-03-07M CHANNEL L 2",
}

# the live pattern
try:
    from config import QTY_TABLE_ROW_PATTERN
    print("QTY_TABLE_ROW_PATTERN =", QTY_TABLE_ROW_PATTERN, "\n")
except Exception as e:
    print("could not import pattern:", e)
    QTY_TABLE_ROW_PATTERN = r"(\d+)\s+([A-Z0-9_]+(?:-[A-Z0-9_]+|\s-\s[A-Z0-9_]+){1,4})-?\s+(.+?)\s+(\d+)"

for name, txt in bom_texts.items():
    print(f"=== {name}: raw regex matches ===")
    matches = re.findall(QTY_TABLE_ROW_PATTERN, txt, flags=re.IGNORECASE)
    if not matches:
        print("   (NO MATCHES — pattern fails on this BOM text entirely)")
    for m in matches:
        print(f"   qty={m[0]!r}  part={m[1]!r}  desc={m[2]!r}  trailingqty={m[3]!r}")
    print()

# Now run the ACTUAL engine function, if importable
print("=== extract_bom_rows() live output (what the engine actually builds) ===")
try:
    from extractor_patterns import extract_bom_rows
    for name, txt in bom_texts.items():
        rows = extract_bom_rows(txt)
        print(f"--- {name} ---")
        for r in rows:
            print(f"   part={r.get('part_number')!r}  desc={r.get('description')!r}")
except Exception as e:
    print("   could not import/run extract_bom_rows:", e)

print("\nVERDICT: if part=12532-02-03M has desc='FRONT PANEL' here but the part record had")
print("description=None, the fallback lookup key doesn't match (case/format). If the regex")
print("captures desc wrongly (e.g. part group swallowed 'FRONT'), the PATTERN is the bug.")
