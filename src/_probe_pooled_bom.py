# -*- coding: utf-8 -*-
"""READ-ONLY. The description fallback (document_builder.py L1463) reads from
summary['document_analysis']['bom_rows'] (the POOLED bom, 19 lines from the anchor PDF),
NOT from per-page extract_bom_rows. We proved extract_bom_rows maps 12532-02-03M->FRONT PANEL
correctly. So the remaining hypothesis: the POOLED bom_rows simply doesn't CONTAIN these two
parts (they live in page 4 / page 17 sub-assembly BOMs, not the anchor page).

Dumps the pooled document_analysis.bom_rows exactly as the fallback sees them, and checks
whether 12532-02-03M and 12532-03-03M are present with a description.

Run from C:\\ClaudeVision\\src :
  C:\\ClaudeVision\\.venv\\Scripts\\python.exe _probe_pooled_bom.py
"""
import json
from pathlib import Path

JSON = Path(r"C:\ClaudeVision\output\json\12532-03RecipeCard.json")
data = json.loads(JSON.read_text(encoding="utf-8"))

da = data.get("document_analysis") or {}
bom_rows = da.get("bom_rows") or []
print(f"Pooled document_analysis.bom_rows: {len(bom_rows)} row(s)\n")
print("=== full pooled BOM (what the fallback _bom_desc is built from) ===")
for r in bom_rows:
    print(f"   part={str(r.get('part_number'))!r:20}  desc={str(r.get('description'))!r}")

TARGETS = ("12532-02-03M", "12532-03-03M")
print("\n=== are the None-desc parts present in the pooled BOM? ===")
present = {str(r.get('part_number') or '').upper(): str(r.get('description') or '') for r in bom_rows}
for pn in TARGETS:
    hit = present.get(pn.upper())
    print(f"   {pn}: {'PRESENT desc='+repr(hit) if hit is not None else 'ABSENT — not in pooled BOM'}")

# also: is document_analysis at top level, or nested under summary?
print("\n=== where does document_analysis live in the JSON? ===")
def find_da(o, path=""):
    out=[]
    if isinstance(o, dict):
        if "bom_rows" in o:
            out.append((path, len(o.get("bom_rows") or [])))
        for k,v in o.items():
            out += find_da(v, f"{path}.{k}")
    elif isinstance(o, list):
        for i,v in enumerate(o):
            out += find_da(v, f"{path}[{i}]")
    return out
for path, n in find_da(data):
    print(f"   {path or '<root>'}.bom_rows : {n} rows")

print("\nVERDICT: if the parts are ABSENT from the pooled BOM, the fix is to build _bom_desc from")
print("ALL pages' extract_bom_rows (per-page), not just the pooled anchor BOM — the data exists")
print("per-page (proven) but pooling dropped it.")
