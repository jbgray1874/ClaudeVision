# -*- coding: utf-8 -*-
"""READ-ONLY. The 3 dropped parts (09M/10M/07M) have NO record in estimate_summary.part_estimates
at all — they fell out of the costing loop. The estimable-parts filter in estimator.py
(_is_estimable_part + _is_weldment_parent_part) decides which parts get costed. Find why these
3 were excluded but 02-07M (same kind of channel) was included.

Checks each dropped part's record for the fields the filter keys on:
  has_part_number, has_material, has_dims, has_ops, and weldment-parent conditions.

Run from C:\\ClaudeVision\\src :
  C:\\ClaudeVision\\.venv\\Scripts\\python.exe _probe_why_no_estimate.py
"""
import json
from pathlib import Path

J = Path(r"C:\ClaudeVision\output\json\12532-03RecipeCard.json")
data = json.loads(J.read_text(encoding="utf-8"))

def walk(o, path=""):
    if isinstance(o, dict):
        yield path,o
        for k,v in o.items(): yield from walk(v,f"{path}.{k}")
    elif isinstance(o, list):
        for i,v in enumerate(o): yield from walk(v,f"{path}[{i}]")

# find the part record that the ESTIMATOR would see (the manufacturing_writeup.parts list is the
# input to costing). Print the filter-relevant fields for dropped vs costed.
TARGETS = {"12532-02-09M":"DROPPED","12532-02-10M":"DROPPED","12532-03-07M":"DROPPED",
           "12532-02-07M":"COSTED"}

# collect from manufacturing_writeup.parts specifically (the costing input list)
parts_list = None
for path, node in walk(data):
    if path.endswith(".manufacturing_writeup.parts") or path.endswith("manufacturing_writeup.parts"):
        pass
# simpler: find the list under manufacturing_writeup
mw = data.get("manufacturing_writeup") or {}
plist = mw.get("parts") or []
print(f"manufacturing_writeup.parts count: {len(plist)}\n")

FILTER_FIELDS = ("part_number","description","normalized_material","normalized_thickness_mm",
                 "blank_length_mm","overall_length_mm","blank_width_mm","textual_operations",
                 "operations","fab_ops","page_roles","geometry_source","dxf_augmented",
                 "manufacturing_features")

for pn, tag in TARGETS.items():
    rec = next((p for p in plist if str(p.get("part_number") or "")==pn), None)
    print(f"=== [{tag}] {pn} ===")
    if not rec:
        print("   NOT in manufacturing_writeup.parts!\n"); continue
    has_pn = bool(rec.get("part_number") and not str(rec.get("part_number")).startswith("part_"))
    has_mat = bool(rec.get("normalized_material") and str(rec.get("normalized_material")).strip() not in ("","None","?","UNKNOWN"))
    has_dims = bool(rec.get("blank_length_mm") or rec.get("overall_length_mm") or rec.get("blank_width_mm"))
    has_ops = bool(rec.get("fab_ops") or rec.get("operations") or rec.get("textual_operations")
                   or (rec.get("manufacturing_features") or {}).get("operations"))
    print(f"   has_part_number={has_pn}  has_material={has_mat}  has_dims={has_dims}  has_ops={has_ops}")
    print(f"   -> estimable = {has_pn or has_mat or has_dims or has_ops}")
    for f in ("normalized_material","normalized_thickness_mm","blank_length_mm","blank_width_mm",
              "overall_length_mm","page_roles","geometry_source"):
        print(f"      {f}: {json.dumps(rec.get(f))[:80] if not isinstance(rec.get(f),str) else rec.get(f)[:80]}")
    print()

print("VERDICT: if a dropped part shows has_dims=False (no blank_length/width) while 02-07M has them,")
print("the geometry didn't populate blank dims on the costing record -> coster produced no estimate.")
print("Compare the dims fields: the dropped parts likely have null blank_length_mm/blank_width_mm.")
