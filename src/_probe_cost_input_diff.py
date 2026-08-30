# -*- coding: utf-8 -*-
"""READ-ONLY. Blank dims are NULL on BOTH costed (02-07M) and dropped parts, so that's not it.
02-07M priced via stock_form='stated_weight' — so it had a WEIGHT to cost from. Hypothesis:
the 3 dropped parts lack a stated weight (and have null blanks), so the coster had no basis.

Dumps EVERY field on each part's manufacturing_writeup.parts record, diffing dropped vs costed,
to find the field that lets 02-07M cost but not the others (likely stated_weight_kg / mass, or a
geometry field like estimated_area / cut_length that feeds a weight).

Run from C:\\ClaudeVision\\src :
  C:\\ClaudeVision\\.venv\\Scripts\\python.exe _probe_cost_input_diff.py
"""
import json
from pathlib import Path

J = Path(r"C:\ClaudeVision\output\json\12532-03RecipeCard.json")
data = json.loads(J.read_text(encoding="utf-8"))
plist = (data.get("manufacturing_writeup") or {}).get("parts") or []

def rec(pn):
    return next((p for p in plist if str(p.get("part_number") or "")==pn), {})

costed = rec("12532-02-07M")
dropped = [rec(pn) for pn in ("12532-02-09M","12532-02-10M","12532-03-07M")]

# collect all keys across these records
allkeys = set(costed.keys())
for d in dropped: allkeys |= set(d.keys())

print("=== field-by-field: COSTED(02-07M) vs the 3 DROPPED — only rows that DIFFER ===\n")
def val(d, k):
    v = d.get(k)
    if isinstance(v, (dict, list)):
        return json.dumps(v)[:70]
    return str(v)[:70]

for k in sorted(allkeys):
    cv = val(costed, k)
    dvals = [val(d, k) for d in dropped]
    # show if costed differs from ANY dropped, or if presence differs
    if any(cv != dv for dv in dvals):
        print(f"  {k}:")
        print(f"      COSTED 02-07M : {cv}")
        for pn, d in zip(("09M","10M","07M-3"), dropped):
            print(f"      DROP  {pn:7}: {val(d,k)}")
        print()

# specifically check weight/mass/area/cut fields
print("=== weight / mass / geometry cost-basis fields ===")
for k in ("stated_weight_kg","weight_kg","unit_weight_kg","mass_kg","estimated_area_mm2",
          "blank_area_m2","estimated_cut_length_mm","geometry"):
    print(f"  {k}: COSTED={val(costed,k)}  | 09M={val(dropped[0],k)} 10M={val(dropped[1],k)} 07M={val(dropped[2],k)}")

# dig into geometry sub-dict for area/cut length
print("\n=== geometry sub-fields (blank area / cut length that could feed weight) ===")
for tag, d in (("COSTED-07M",costed),("DROP-09M",dropped[0]),("DROP-10M",dropped[1]),("DROP-07M",dropped[2])):
    g = d.get("geometry") or {}
    print(f"  {tag}: cut_len={g.get('estimated_cut_length_mm')} area_like={g.get('blank_area_mm2') or g.get('estimated_area_mm2')} "
          f"bbox={g.get('bounding_box') or (g.get('bbox_w_mm'),g.get('bbox_h_mm'))}")
