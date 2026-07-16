# -*- coding: utf-8 -*-
r"""Check BOM coverage: does every bought-in BOM row appear as a COSTED bay line?
Lists (a) all raw bay_bom_rows, (b) all costed bay_estimate.lines, and (c) BOM
items that did NOT make it into a costed line. Read-only.

  cd C:\ClaudeVision\src
  C:\ClaudeVision\.venv\Scripts\python.exe _bom_coverage.py
"""
import json, os, glob

path = max(glob.glob(r"C:\ClaudeVision\output\json\*1282*.json"), key=os.path.getmtime)
data = json.load(open(path, encoding="utf-8"))
print(f"Reading: {path}\n")

# (a) raw BOM rows (the full bill of materials)
bom = (data.get("document_analysis", {}) or {}).get("bay_bom_rows", []) or []
print(f"=== RAW BAY BOM ROWS ({len(bom)}) ===")
for r in bom:
    print(f"  item {r.get('item_number','?'):>3}  {str(r.get('part_number') or ''):<14}  qty {r.get('quantity','?'):>3}  {str(r.get('description') or '')[:48]}")

# (b) costed bay estimate lines
bay = data.get("bay_estimate", {}) or {}
lines = bay.get("lines", []) or []
print(f"\n=== COSTED BAY ESTIMATE LINES ({len(lines)}) ===")
print(f"{'code':<14} {'qty':>4} {'unit':>9} {'line':>9} {'src':<14} {'prov?':<5} {'conf'}")
costed_descs = set()
for ln in lines:
    d = str(ln.get('description') or '')
    costed_descs.add(d.upper())
    print(f"{str(ln.get('code') or ''):<14} {ln.get('qty_per_bay','?'):>4} "
          f"{float(ln.get('unit_cost_gbp') or 0):>9.2f} {float(ln.get('line_cost_gbp') or 0):>9.2f} "
          f"{str(ln.get('cost_source') or ''):<14} {str(ln.get('provisional','')):<5} {ln.get('cost_confidence','')}")
    print(f"               desc: {d[:55]}")

# (c) BOM bought-in items NOT in any costed line
print(f"\n=== BOM ITEMS NOT FOUND IN A COSTED BAY LINE ===")
# bought-in-ish keywords to focus on the loose items
bi_kw = ("LOOM","RIVET","CABLE","FOAM","JUNCTION","EARTH","STRAP","MAINS","PLUG",
         "FIXING","NUTSERT","GLIDE","CLIP","TAPE","ELECTRIC","LED","DOWNLIGHT")
missing = []
for r in bom:
    desc = str(r.get('description') or '').upper()
    pn = str(r.get('part_number') or '').upper()
    blob = desc + " " + pn
    looks_bought_in = any(k in blob for k in bi_kw)
    if not looks_bought_in:
        continue
    # did it make it into a costed line? loose match on description tokens
    matched = any(desc[:10] in cd or cd[:10] in desc for cd in costed_descs if cd)
    if not matched:
        missing.append(f"  item {r.get('item_number','?')}  {pn:<14} qty {r.get('quantity','?')}  {desc[:48]}")
if missing:
    print("\n".join(missing))
else:
    print("  (all bought-in BOM rows appear to be costed)")

print(f"\nbay bom_line_count={bay.get('bom_line_count')}  uncosted={bay.get('uncosted_lines')}  provisional={bay.get('provisional_lines')}")
