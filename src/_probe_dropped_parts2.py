# -*- coding: utf-8 -*-
"""READ-ONLY v2. The first probe matched thin summary copies (only part_number+description).
This version finds ALL records for each target part number, and for each prints how many fields
it has + the cost-relevant ones, so we see the RICH estimate record (the one with stock_form,
material, unit cost) and compare dropped vs costed.

Run from C:\\ClaudeVision\\src :
  C:\\ClaudeVision\\.venv\\Scripts\\python.exe _probe_dropped_parts2.py
"""
import json
from pathlib import Path

J = Path(r"C:\ClaudeVision\output\json\12532-03RecipeCard.json")
data = json.loads(J.read_text(encoding="utf-8"))

def walk(o, path=""):
    if isinstance(o, dict):
        yield path, o
        for k,v in o.items(): yield from walk(v, f"{path}.{k}")
    elif isinstance(o, list):
        for i,v in enumerate(o): yield from walk(v, f"{path}[{i}]")

TARGETS = {
  "12532-02-09M":"DROPPED", "12532-02-10M":"DROPPED", "12532-03-07M":"DROPPED",
  "12532-02-07M":"COSTED(control)",
}

# collect every record per part number, keep the one with the most cost-relevant keys
COST_KEYS = ("stock_form","requires_flat_blank","cost_method","unit_material_cost_gbp",
             "cost_per_part_gbp","material","thickness_mm","blank_length_mm","blank_width_mm",
             "material_estimate","unit_estimate","extended_estimate")

best = {}  # pn -> (score, path, node)
for path, node in walk(data):
    if not isinstance(node, dict): continue
    pn = str(node.get("part_number") or "")
    if pn in TARGETS:
        score = sum(1 for k in COST_KEYS if k in node)
        # also score nested material_estimate richness
        me = node.get("material_estimate")
        if isinstance(me, dict): score += sum(1 for k in COST_KEYS if k in me)
        if pn not in best or score > best[pn][0]:
            best[pn] = (score, path, node)

for pn, tag in TARGETS.items():
    print(f"\n=== [{tag}] {pn} — richest record ===")
    if pn not in best:
        print("   (no record found)"); continue
    score, path, node = best[pn]
    print(f"   [path {path}  richness={score}]")
    def show(d, prefix=""):
        for k in COST_KEYS:
            if k in d:
                v = d[k]
                if k=="material_estimate" and isinstance(v, dict):
                    print(f"   {prefix}material_estimate:")
                    for kk in ("stock_form","cost_method","requires_flat_blank","material",
                               "thickness_mm","blank_length_mm","blank_width_mm",
                               "unit_material_cost_gbp","cost_per_part_gbp","extended_material_cost_gbp"):
                        if kk in v:
                            print(f"      {kk}: {json.dumps(v[kk])[:90]}")
                else:
                    print(f"   {prefix}{k}: {json.dumps(v)[:90] if not isinstance(v,str) else v[:90]}")
    show(node)
    # also show manufacturing_interpretation stock_form/routing
    mi = node.get("manufacturing_interpretation")
    if isinstance(mi, dict):
        print(f"   mfg_interp.stock_form: {mi.get('stock_form')}")
        r = mi.get("routing")
        if r: print(f"   mfg_interp.routing: {json.dumps(r)[:120]}")

print("\nVERDICT: the field present on 02-07M (COSTED) but missing/different on the 3 DROPPED parts is the cause.")
