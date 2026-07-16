# -*- coding: utf-8 -*-
r"""section_stock IS set on the tubes (per key dump). So why do they price as flat sheet?
Inspect the ACTUAL section_stock + section_costing_adjustment + material_estimate values.
  C:\ClaudeVision\.venv\Scripts\python.exe _section_value_diag.py
"""
import json
J = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
data = json.load(open(J, encoding="utf-8"))

for container_name in ("parts","manufacturing_writeup"):
    c = data.get(container_name)
    if isinstance(c, dict): c = c.get("parts")
    if not c: continue
    print(f"\n===== {container_name} =====")
    for p in c:
        if p.get("part_number") not in ("3886-01","1448-01"): continue
        print(f"\n  {p.get('part_number')}  ({p.get('description')})")
        print(f"    section_stock: {json.dumps(p.get('section_stock'))}")
        print(f"    section_costing_adjustment: {json.dumps(p.get('section_costing_adjustment'))}")
        print(f"    normalized_material: {p.get('normalized_material')}")
        print(f"    normalized_thickness_mm: {p.get('normalized_thickness_mm')}")
        print(f"    textual_operations: {p.get('textual_operations')}")

# the estimated cost path
parts = (data.get("estimate_summary",{}) or {}).get("part_estimates") or []
print("\n\n===== estimate_summary.part_estimates (the COSTED record) =====")
for p in parts:
    if p.get("part_number") not in ("3886-01","1448-01"): continue
    me = p.get("material_estimate") or {}
    print(f"\n  {p.get('part_number')}:")
    print(f"    unit_total_cost_gbp: {p.get('unit_total_cost_gbp')}")
    print(f"    costing_basis: {p.get('costing_basis')}")
    print(f"    material_estimate.cost_method: {me.get('cost_method')}")
    print(f"    material_estimate.cost_per_part_gbp: {me.get('cost_per_part_gbp')}")
    print(f"    material_estimate.stock_form: {me.get('stock_form')}")
    print(f"    material_estimate.supplier: {p.get('supplier') or me.get('supplier')}")
    se = me.get('stock_estimate') or {}
    print(f"    stock_estimate keys: {list(se.keys())}")
    print(f"    section_stock present on costed rec? {bool(p.get('section_stock'))}")