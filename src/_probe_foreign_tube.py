# -*- coding: utf-8 -*-
"""READ-ONLY. The Recipe Card sheet's biggest material line is a tube from a DIFFERENT job:
'ITEM 1 - 11406-02-02M - 38.1 X 19.1 X 1.5MM @798MM - LASER TUBE — TUBE0173 — HALL & PICKLES —
£7.43 — £30.91'. This job (12532) has its OWN tube (CROSS RAIL 02-08M, 19x38x1.63mm @720mm,
page 11). So the engine substituted job 11406's tube for this job's.

Find WHERE 11406-02-02M / TUBE0173 comes from:
  1. Is it in this job's persisted JSON parts/materials? (what record carries it)
  2. Is it a catalogue match (BoughtInCatalogue) or historical_quote match?
  3. Is it in a stale job_bought_in_materials.json / by-drawing entry?

Run from C:\\ClaudeVision\\src :
  C:\\ClaudeVision\\.venv\\Scripts\\python.exe _probe_foreign_tube.py
"""
import json, os
from pathlib import Path

JSON = Path(r"C:\ClaudeVision\output\json\12532-03RecipeCard.json")
data = json.loads(JSON.read_text(encoding="utf-8"))

print("=== 1. Where does 11406 / TUBE0173 appear in this job's JSON? ===")
def find(o, needles, path=""):
    out=[]
    if isinstance(o, dict):
        for k,v in o.items(): out+=find(v,needles,f"{path}.{k}")
    elif isinstance(o, list):
        for i,v in enumerate(o): out+=find(v,needles,f"{path}[{i}]")
    elif isinstance(o, str):
        for n in needles:
            if n in o:
                out.append((path, n, o[:120]))
    return out
for path, needle, snippet in find(data, ["11406", "TUBE0173"]):
    print(f"   [{needle}] {path}: {snippet}")

print("\n=== 2. Any material/part record with a tube + supplier + these dims? ===")
def walk(o, path=""):
    out=[]
    if isinstance(o, dict):
        out.append((path,o))
        for k,v in o.items(): out+=walk(v,f"{path}.{k}")
    elif isinstance(o, list):
        for i,v in enumerate(o): out+=walk(v,f"{path}[{i}]")
    return out
for path, node in walk(data):
    if isinstance(node, dict):
        blob = json.dumps(node)
        if ("TUBE0173" in blob or "11406" in blob) and ("supplier" in node or "price" in node or "part_number" in node):
            keys = {k: node[k] for k in ("part_number","description","supplier","price","source",
                                          "catalogue_source","match_source","unit_cost","length_mm")
                    if k in node}
            if keys:
                print(f"   {path}: {json.dumps(keys)[:220]}")

print("\n=== 3. Stale JSON sources: job_bought_in_materials.json entries for 11406 or 12532? ===")
for fn in ("job_bought_in_materials.json", "job_assembly_labour.json"):
    p = Path(r"C:\ClaudeVision\src") / fn
    if not p.exists():
        p = Path(r"C:\ClaudeVision") / fn
    if p.exists():
        try:
            j = json.loads(p.read_text(encoding="utf-8"))
            s = json.dumps(j)
            print(f"   {fn}: 11406 present={('11406' in s)}  12532 present={('12532' in s)}  TUBE0173 present={('TUBE0173' in s)}")
        except Exception as e:
            print(f"   {fn}: read error {e}")
    else:
        print(f"   {fn}: not found")

print("\n=== 4. This job's OWN tube (CROSS RAIL 02-08M) — what did it get? ===")
for path, node in walk(data):
    if isinstance(node, dict) and str(node.get("part_number") or "") == "12532-02-08M":
        keys = {k: node.get(k) for k in ("part_number","description","normalized_material",
                "normalized_thickness_mm","blank_length_mm","overall_length_mm","unit_estimate")}
        print(f"   {path}: {json.dumps(keys)[:260]}")
        break

print("\nVERDICT: whichever source carries 11406-02-02M/TUBE0173 is where the substitution happens.")
print("Likely a catalogue/historical tube match keyed on section+length that returned another job's")
print("tube row. Fix = price THIS job's tube from its drawing (page 11 BOM), not a catalogue neighbour.")
