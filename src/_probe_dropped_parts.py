# -*- coding: utf-8 -*-
"""READ-ONLY. Three parts returned Unit estimate: None despite having geometry (reliability 1.0):
  12532-02-09M HEADER GRAPHIC CHANNEL, 02-10M GRAPHIC CHANNEL, 03-07M CHANNEL L.
They have cut_length, holes, bends — so why does costing return None? Compare their records
against a part that DID cost (e.g. 02-07M LOWER GRAPHIC CHANNEL, £1.14) to spot the difference.

Run from C:\\ClaudeVision\\src :
  C:\\ClaudeVision\\.venv\\Scripts\\python.exe _probe_dropped_parts.py
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

DROPPED = ("12532-02-09M", "12532-02-10M", "12532-03-07M")
COSTED  = ("12532-02-07M",)  # LOWER GRAPHIC CHANNEL, costed £1.14 — the control

FIELDS = ("part_number","description","normalized_material","normalized_thickness_mm",
          "blank_length_mm","blank_width_mm","overall_length_mm","stock_form",
          "requires_flat_blank","unit_estimate","unit_material_cost_gbp","cost_method",
          "geometry_source","manufacturing_interpretation")

def dump(pn, tag):
    seen=set()
    for node in walk(data):
        if isinstance(node, dict) and str(node.get("part_number") or "")==pn:
            key = id(node)
            # prefer the richest record (one with material_estimate or unit_estimate)
            rec = {}
            for f in FIELDS:
                if f in node:
                    v = node[f]
                    if f=="manufacturing_interpretation" and isinstance(v, dict):
                        v = {k: v.get(k) for k in ("stock_form","routing","material") if k in v}
                    rec[f]=v
            me = node.get("material_estimate")
            if isinstance(me, dict):
                rec["_material_estimate.stock_form"]=me.get("stock_form")
                rec["_material_estimate.cost_method"]=me.get("cost_method")
                rec["_material_estimate.unit_material_cost_gbp"]=me.get("unit_material_cost_gbp")
                rec["_material_estimate.requires_flat_blank"]=me.get("requires_flat_blank")
            if rec:
                print(f"\n--- [{tag}] {pn} ---")
                for k,v in rec.items():
                    print(f"   {k}: {json.dumps(v)[:120] if not isinstance(v,str) else v[:120]}")
                return
    print(f"\n--- [{tag}] {pn}: no record found ---")

print("=== DROPPED parts (Unit estimate None) ===")
for pn in DROPPED: dump(pn, "DROPPED")
print("\n=== CONTROL: a channel that DID cost ===")
for pn in COSTED: dump(pn, "COSTED")

print("\nVERDICT: compare the DROPPED vs COSTED records. The field that differs (stock_form,")
print("requires_flat_blank, material, or a routing/classification flag) is why costing bailed.")
