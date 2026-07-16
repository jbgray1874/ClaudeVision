# -*- coding: utf-8 -*-
"""READ-ONLY runtime trace. Static reading says the acrylic path (estimate_material, estimator.py
:1299-1337) SHOULD price the RISER — gate passes in simulation, £46.20/sheet exists — yet the run's
material_estimate came back cost_method=None. Resolve the contradiction by actually CALLING
estimate_material() on the RISER's real part record and printing exactly what it returns.

Also probes the 2026x2026 garbage blank: reads the RISER's DXF and reports its raw bbox extents vs
the real 645x102, to localise the drawing_job_merge bbox bug.

Run from C:\\ClaudeVision\\src :
  C:\\ClaudeVision\\.venv\\Scripts\\python.exe _probe_acrylic_runtime.py
"""
import json, sys
from pathlib import Path

sys.path.insert(0, r"C:\ClaudeVision\src")

# 1) Load the RISER's real part record from the run JSON
J = Path(r"C:\ClaudeVision\output\json\12532-03RecipeCard.json")
data = json.loads(J.read_text(encoding="utf-8"))

def walk(o):
    if isinstance(o, dict):
        yield o
        for v in o.values(): yield from walk(v)
    elif isinstance(o, list):
        for v in o: yield from walk(v)

riser = None
best = -1
for node in walk(data):
    if isinstance(node, dict) and str(node.get("part_number") or "")=="12532-03-04A":
        score = sum(1 for k in ("normalized_material","blank_length_mm","normalized_thickness_mm","operations","textual_operations") if k in node)
        if score > best:
            best, riser = score, node

if not riser:
    print("RISER record not found in JSON"); raise SystemExit(1)

print("=== RISER record keys the pricing path cares about ===")
for k in ("part_number","description","normalized_material","material","normalized_thickness_mm",
          "blank_length_mm","blank_width_mm","overall_length_mm","overall_width_mm","quantity"):
    print(f"  {k}: {riser.get(k)!r}")

# 2) Call estimate_material directly and print the result
print("\n=== CALLING estimate_material(riser) LIVE ===")
try:
    import estimator
    res = estimator.estimate_material(dict(riser))
    print(f"  returned type: {type(res).__name__}")
    if isinstance(res, dict):
        for k in ("cost_method","unit_material_cost_gbp","cost_per_part_gbp","extended_material_cost_gbp",
                  "material","thickness_mm","blank_length_mm","blank_width_mm","note"):
            print(f"    {k}: {res.get(k)!r}")
    else:
        print(f"    raw: {res!r}")
except Exception as e:
    import traceback
    print("  EXCEPTION calling estimate_material:")
    traceback.print_exc()

# 3) The 2026 blank — read the RISER DXF bbox raw
print("\n=== RISER DXF bbox (source of 2026x2026?) ===")
try:
    import drawing_job_merge as djm
    # find the DXF
    up = Path(r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\AI Estimating\Live Enquiry\12532-03RecipeCard")
    dxfs = list(up.rglob("*12532-03-04A*"))
    print(f"  RISER dxf candidates: {[d.name for d in dxfs]}")
    for d in dxfs:
        if d.suffix.lower()==".dxf":
            wh = djm._dxf_bbox_wh(d)
            print(f"    {d.name}: _dxf_bbox_wh -> {wh}  (real part is 645 x 102)")
except Exception as e:
    import traceback
    print("  (dxf bbox probe failed — not fatal)")
    traceback.print_exc()

print("\nVERDICT: the estimate_material return above is authoritative. If it returns the acrylic dict")
print("(cost_method='acrylic_sheet_provisional', a real cost) -> the loss is DOWNSTREAM in estimate_part")
print("(an early return or overwrite before line 2488). If it returns None/zero -> the acrylic block")
print("isn't being reached at runtime despite the static gate passing (something earlier in")
print("estimate_material returns first). The DXF bbox tells us if 2026 is the raw extent.")
