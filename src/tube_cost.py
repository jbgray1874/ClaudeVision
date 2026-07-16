# -*- coding: utf-8 -*-
"""Did 3886-01 actually get CHARGED laser time, or is laser only in the display list
while the cost correctly excludes it? Reads PRECACHE, no re-run.
  C:\\ClaudeVision\\.venv\\Scripts\\python.exe _tube_cost.py"""
import json
PATH = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.PRECACHE.json"
with open(PATH, encoding="utf-8") as fh:
    d = json.load(fh)
parts = (d.get("manufacturing_writeup") or {}).get("parts") or []
for p in parts:
    if str(p.get("part_number") or "") != "3886-01":
        continue
    print("=== 3886-01 cost breakdown ===")
    print("textual_operations:", p.get("textual_operations"))
    # process times — does laser have a run/setup time?
    for key in ("process_estimate","process_times","manufacturing_times","times"):
        pe = p.get(key)
        if pe:
            print(f"\n[{key}]")
            print("  setup_times_min:", pe.get("setup_times_min"))
            print("  run_times_min_per_unit:", pe.get("run_times_min_per_unit"))
            print("  times_min:", pe.get("times_min"))
    # labour cost per op — is there a laser_cutting £ line?
    for key in ("labour_costs","labour","labour_estimate"):
        lc = p.get(key)
        if lc:
            print(f"\n[{key}] costs_gbp:", lc.get("costs_gbp"))
    print("\nsection_costing_adjustment:", (p.get("section_costing_adjustment") or {}).get("rule"))
    print("unit_total_cost_gbp:", p.get("unit_total_cost_gbp") or p.get("unit_cost_gbp"))
    print("material_cost_gbp:", p.get("material_cost_gbp"), "material_unit_cost_gbp:", p.get("material_unit_cost_gbp"))
    break