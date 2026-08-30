# -*- coding: utf-8 -*-
"""READ-ONLY. Verify whether the 3 overflow steel parts (12532-03-05M, -06M, -07M) have their
MATERIAL cost counted anywhere, or ONLY their labour. The steel DISPLAY block is 11 rows; 14 steel
parts exist, so 3 overflow. Their LABOUR is confirmed in the labour block. But the steel MATERIAL
calc (M59 sums the 11 steel rows) may miss the 3 overflow parts' material. This determines what the
cover note must honestly say: 'fully costed' vs 'labour costed, material of 3 parts not in sheet total'.

Reads the run JSON: each of the 3 parts' material_estimate (do they have a material cost?), and
whether the estimate_document total includes them.

Run from C:\\ClaudeVision\\src :
  C:\\ClaudeVision\\.venv\\Scripts\\python.exe _probe_overflow_material.py
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

targets = {"12532-03-05M", "12532-03-06M", "12532-03-07M"}
print("=== The 3 overflow steel parts — do they have MATERIAL cost + LABOUR cost? ===")
seen = {}
for node in walk(data):
    if isinstance(node, dict) and str(node.get("part_number") or "") in targets:
        pn = node["part_number"]
        me = node.get("material_estimate") or {}
        # prefer the record that actually has costs
        mcost = me.get("cost_per_part_gbp") or me.get("unit_material_cost_gbp") or me.get("extended_material_cost_gbp")
        lab = node.get("labour_estimate") or node.get("labour") or {}
        ue = node.get("unit_estimate") or node.get("unit_cost_gbp")
        if pn not in seen or mcost is not None:
            seen[pn] = {
                "material_cost": mcost,
                "material_cost_method": me.get("cost_method"),
                "unit_estimate": ue,
                "extended": node.get("extended_estimate") or node.get("extended_total_cost_gbp"),
            }
for pn in sorted(targets):
    d = seen.get(pn, {})
    print(f"  {pn}: material_cost={d.get('material_cost')!r} (method={d.get('material_cost_method')!r}) "
          f"unit_estimate={d.get('unit_estimate')!r} extended={d.get('extended')!r}")

print("\n=== Are these 3 included in the estimate_document TOTAL (385.45)? ===")
es = data.get("estimate_summary") or {}
print(f"  estimate_summary keys: {list(es.keys())[:10]}")
tot = es.get("document_total_gbp") or es.get("total_gbp") or es.get("estimated_document_total")
print(f"  document total: {tot!r}")
parts_in_total = es.get("part_count") or es.get("parts_costed")
print(f"  parts in total: {parts_in_total!r}")

print("\nVERDICT: if the 3 parts show a material_cost AND a unit_estimate, their material+labour ARE")
print("in the engine's document total (385.45). The overflow is a DISPLAY-block limit in the WB sheet")
print("(only 11 steel rows render), NOT a costing exclusion — the engine total already counts all 14.")
print("So the WB sheet's STEEL MATERIAL sum (M38:M48) may miss the 3, but the engine's own total does")
print("not. Cover note must state which total the estimator should trust.")
