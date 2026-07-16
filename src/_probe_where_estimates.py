# -*- coding: utf-8 -*-
"""READ-ONLY. Contradiction: filters pass the 3 parts and the loop appends every filtered part,
yet they seem absent from part_estimates. Resolve it: list EVERY part_number/description in
estimate_summary.part_estimates, and check what unit cost each has. The 3 'dropped' parts may be
PRESENT but with a null/None unit cost (costed to None), not absent.

Run from C:\\ClaudeVision\\src :
  C:\\ClaudeVision\\.venv\\Scripts\\python.exe _probe_where_estimates.py
"""
import json
from pathlib import Path

J = Path(r"C:\ClaudeVision\output\json\12532-03RecipeCard.json")
data = json.loads(J.read_text(encoding="utf-8"))

pe = (data.get("estimate_summary") or {}).get("part_estimates") or []
print(f"estimate_summary.part_estimates count: {len(pe)}\n")
print("=== every part_estimate: part_number | description | unit material | unit total ===")
for i, p in enumerate(pe):
    pn = p.get("part_number")
    desc = p.get("description")
    me = p.get("material_estimate") or {}
    umat = me.get("unit_material_cost_gbp") or me.get("cost_per_part_gbp")
    ce = p.get("cost_breakdown") or {}
    ut = p.get("unit_cost_gbp") or ce.get("unit_total_gbp")
    flag = ""
    if str(pn) in ("12532-02-09M","12532-02-10M","12532-03-07M"):
        flag = "  <<< 'DROPPED' TARGET"
    print(f"  [{i}] {str(pn):16} {str(desc)[:26]:26} mat={umat} total={ut}{flag}")

print("\n=== are the 3 targets present here at all? ===")
present = {str(p.get('part_number')) for p in pe}
for pn in ("12532-02-09M","12532-02-10M","12532-03-07M"):
    print(f"   {pn}: {'PRESENT' if pn in present else 'ABSENT'}")

# also count manufacturing_writeup.parts vs part_estimates to see the drop
mw = (data.get("manufacturing_writeup") or {}).get("parts") or []
print(f"\nmanufacturing_writeup.parts = {len(mw)}   part_estimates = {len(pe)}   diff = {len(mw)-len(pe)}")
