# -*- coding: utf-8 -*-
"""READ-ONLY. The RISER (12532-03-04A, HIGH IMPACT ACRYLIC, 651x108x3mm) shows £0 in Other Sheet
Material despite the acrylic sheet-pricing path existing (estimator.py:1299). That gate requires:
   material in {ACRYLIC, HIGH IMPACT ACRYLIC, ...}  AND  blank_length  AND  blank_width
Find which condition fails for the RISER — almost certainly null blank_length/blank_width (the
part has dims elsewhere but the pricing fn reads blank_*). Dump the exact fields the gate reads.

Run from C:\\ClaudeVision\\src :
  C:\\ClaudeVision\\.venv\\Scripts\\python.exe _probe_acrylic_gate.py
"""
import json
from pathlib import Path

J = Path(r"C:\ClaudeVision\output\json\12532-03RecipeCard.json")
data = json.loads(J.read_text(encoding="utf-8"))

def walk(o):
    if isinstance(o, dict):
        yield o
        for v in o.values(): yield from walk(v)
    elif isinstance(o, list):
        for v in o: yield from walk(v)

print("=== RISER (12532-03-04A) — fields the acrylic gate reads ===")
best = None
for node in walk(data):
    if isinstance(node, dict) and str(node.get("part_number") or "")=="12532-03-04A":
        # prefer the richest record
        score = sum(1 for k in ("material_estimate","normalized_material","blank_length_mm","blank_width_mm","normalized_thickness_mm") if k in node)
        if best is None or score > best[0]:
            best = (score, node)
if best:
    n = best[1]
    print(f"  normalized_material: {n.get('normalized_material')!r}")
    print(f"  material (raw):      {n.get('material')!r}")
    print(f"  normalized_thickness_mm: {n.get('normalized_thickness_mm')!r}")
    print(f"  blank_length_mm: {n.get('blank_length_mm')!r}")
    print(f"  blank_width_mm:  {n.get('blank_width_mm')!r}")
    print(f"  overall_length_mm: {n.get('overall_length_mm')!r}")
    print(f"  overall_width_mm:  {n.get('overall_width_mm')!r}")
    me = n.get("material_estimate") or {}
    print(f"  material_estimate.cost_method: {me.get('cost_method')!r}")
    print(f"  material_estimate.unit_material_cost_gbp: {me.get('unit_material_cost_gbp')!r}")
    print(f"  material_estimate.blank_length_mm: {me.get('blank_length_mm')!r}")
    print(f"  material_estimate.blank_width_mm:  {me.get('blank_width_mm')!r}")
    print(f"  material_estimate.material: {me.get('material')!r}")

    # simulate the gate
    _mat = str(n.get("normalized_material") or n.get("material") or "").upper().replace("_"," ")
    bl = n.get("blank_length_mm") or me.get("blank_length_mm")
    bw = n.get("blank_width_mm") or me.get("blank_width_mm")
    print(f"\n  GATE SIMULATION:")
    print(f"    material '{_mat}' in acrylic set? {_mat in {'ACRYLIC','HIGH IMPACT ACRYLIC','PERSPEX','PMMA','POLYCARBONATE'}}")
    print(f"    blank_length truthy? {bool(bl)} ({bl!r})")
    print(f"    blank_width truthy?  {bool(bw)} ({bw!r})")
    print(f"    -> gate passes? {(_mat in {'ACRYLIC','HIGH IMPACT ACRYLIC','PERSPEX','PMMA','POLYCARBONATE'}) and bool(bl) and bool(bw)}")

print("\n=== is ACRYLIC_SHEET_PRICE_GBP populated? (config check) ===")
import re
cfg = Path(r"C:\ClaudeVision\src\config.py").read_text(encoding="utf-8", errors="ignore")
m = re.search(r"ACRYLIC_SHEET_PRICE_GBP\s*=\s*\{[^}]*\}", cfg)
print("  " + (m.group(0)[:200] if m else "NOT FOUND"))

print("\nVERDICT: if gate fails on blank_length/width being null, the fix is to fall back to")
print("overall_length/width (which the RISER has) when blank_* are null. If material mismatches,")
print("it's a normalisation issue. Config check shows whether a 3mm price exists.")
