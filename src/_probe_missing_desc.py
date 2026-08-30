# -*- coding: utf-8 -*-
"""READ-ONLY. Two parts came back Description=None (12532-02-03M FRONT PANEL, 12532-03-03M
SHELF BODY) though the assembly BOMs clearly name them. Find out WHY the engine missed the
description: is it (a) on the part's own detail page but in a format the extractor missed, or
(b) only present in the assembly BOM table (so the part page genuinely has no title-block desc)?

Reads the persisted JSON for this job and dumps, for the None-desc parts:
  - what description-related fields the part record holds (description, raw title block, page)
  - what the assembly BOM rows say for that part number
Touches nothing.

Run from C:\\ClaudeVision\\src :
  C:\\ClaudeVision\\.venv\\Scripts\\python.exe _probe_missing_desc.py
"""
import json
from pathlib import Path

JSON = Path(r"C:\ClaudeVision\output\json\12532-03RecipeCard.json")
data = json.loads(JSON.read_text(encoding="utf-8"))

TARGETS = ("12532-02-03M", "12532-03-03M")

def walk(o, path=""):
    out = []
    if isinstance(o, dict):
        out.append((path, o))
        for k, v in o.items():
            out += walk(v, f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            out += walk(v, f"{path}[{i}]")
    return out

nodes = walk(data)

print("=== Part records for the None-description parts ===")
for pn in TARGETS:
    print(f"\n--- {pn} ---")
    for path, node in nodes:
        if isinstance(node, dict) and str(node.get("part_number") or "") == pn:
            # dump description-relevant fields only
            for key in ("part_number","description","desc","title","title_block",
                        "normalized_material","page","pages","page_roles",
                        "raw_title_block","document_analysis"):
                if key in node:
                    val = node[key]
                    s = json.dumps(val)[:200] if not isinstance(val,str) else val[:200]
                    print(f"   {key}: {s}")
            print(f"   [record at {path}]")
            break

print("\n=== Any BOM rows / text mentioning these part numbers (where the name DOES live) ===")
for pn in TARGETS:
    print(f"\n--- BOM/text hits for {pn} ---")
    hits = 0
    for path, node in nodes:
        if isinstance(node, dict):
            blob = json.dumps(node)[:0]  # skip; we check strings below
        if isinstance(node, str):
            continue
    # search string values across the whole doc
    def search_strings(o, pn, path=""):
        found=[]
        if isinstance(o, dict):
            for k,v in o.items():
                found += search_strings(v, pn, f"{path}.{k}")
        elif isinstance(o, list):
            for i,v in enumerate(o):
                found += search_strings(v, pn, f"{path}[{i}]")
        elif isinstance(o, str):
            if pn in o and ("PANEL" in o.upper() or "BODY" in o.upper() or "SHELF" in o.upper() or "FRONT" in o.upper()):
                found.append((path, o[:160]))
        return found
    for path, s in search_strings(data, pn)[:6]:
        print(f"   {path}: {s}")
        hits += 1
    if not hits:
        print("   (no descriptive string found alongside the part number)")

print("\nVERDICT: if the part record's title_block has a description the engine didn't copy to")
print("'description' -> extractor field-mapping bug. If the name only appears in assembly BOM rows")
print("-> add a fallback: use the assembly BOM description when the part's own title block has none.")
