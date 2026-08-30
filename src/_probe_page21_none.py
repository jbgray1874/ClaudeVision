# -*- coding: utf-8 -*-
"""READ-ONLY. A part with part_number=None, description=None (page 21, SECTION G-G, a CHANNEL)
now shows on the sheet as a nameless 'None' line costed at £0.42. Before Fix A2 it was uncosted.
Find: (a) what identity page 21's part SHOULD have, (b) why part_number came back None, (c) is
it recoverable from the page text or a BOM row.

Run from C:\\ClaudeVision\\src :
  C:\\ClaudeVision\\.venv\\Scripts\\python.exe _probe_page21_none.py
"""
import json, re
from pathlib import Path

J = Path(r"C:\ClaudeVision\output\json\12532-03RecipeCard.json")
data = json.loads(J.read_text(encoding="utf-8"))
pages = data.get("pages", [])

# 1. the None part record — what pages/fields does it have?
print("=== the None part record (part_number None, pages ~[21]) ===")
def walk(o, path=""):
    out=[]
    if isinstance(o, dict):
        out.append((path,o))
        for k,v in o.items(): out+=walk(v,f"{path}.{k}")
    elif isinstance(o, list):
        for i,v in enumerate(o): out+=walk(v,f"{path}[{i}]")
    return out
for path, node in walk(data):
    if isinstance(node, dict) and node.get("part_number") is None and 21 in (node.get("pages") or []):
        for k in ("part_number","description","pages","normalized_material","geometry_source"):
            print(f"   {k}: {node.get(k)}")
        print(f"   [at {path}]")
        break

# 2. page 21 text — what part number / description is actually on the drawing?
print("\n=== page 21 (index 20) text: what identity is on the drawing? ===")
if len(pages) > 20:
    pg = pages[20]
    for fld in ("region_text",):
        rt = pg.get(fld) or {}
        for k in ("title_block","notes","bom"):
            v = str(rt.get(k) or "")
            if v:
                print(f"   region_text.{k}: {v[:200]}")
    # look for a 12532-xx-xx pattern and CHANNEL/description in any text field
    alltext = json.dumps(pg)
    pns = re.findall(r"12532-\d{2}-\d{2,3}[A-Z]?", alltext)
    print(f"\n   part-number-like strings on page 21: {sorted(set(pns))}")
    for word in ("CHANNEL","CHANN","SHELF","BODY","RISER","DIVIDER"):
        if word in alltext:
            print(f"   contains '{word}'")

# 3. is page 21's part in any BOM row?
print("\n=== does any BOM row map to a page-21 part? (CHANNEL etc.) ===")
for r in (data.get("document_analysis") or {}).get("bom_rows") or []:
    d = str(r.get("description") or "")
    if "CHANNEL" in d.upper() or "G-G" in str(r.get("part_number") or ""):
        print(f"   BOM: part={r.get('part_number')} desc={d}")

print("\nVERDICT: if page 21 has a clear 12532-xx part number in its title block that the extractor")
print("missed, that's the fix (recover it). If it genuinely has no part number on the drawing, the")
print("honest fix is to suppress the nameless line OR label it by its section/description, not 'None'.")
