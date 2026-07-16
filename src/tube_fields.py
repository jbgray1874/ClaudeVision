# -*- coding: utf-8 -*-
"""Show every text field on 3886-01 so we can see WHERE the tube evidence lives
(description, process_notes, page text, geometry). Reads PRECACHE, no re-run.
  C:\\ClaudeVision\\.venv\\Scripts\\python.exe _tube_fields.py"""
import json
PATH = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.PRECACHE.json"
with open(PATH, encoding="utf-8") as fh:
    d = json.load(fh)
parts = (d.get("manufacturing_writeup") or {}).get("parts") or []
for p in parts:
    if str(p.get("part_number") or "") != "3886-01":
        continue
    print("=== 3886-01 all text-ish fields ===")
    for k in ("part_number","description","normalized_material","material",
              "section_stock","geometry_source","textual_operations","inferred_operations"):
        print(f"  {k}: {p.get(k)!r}")
    print(f"  process_notes: {p.get('process_notes')!r}")
    # any field whose string contains TUBE or '30 x 60' or '60 x'
    print("\n  --- fields containing tube evidence ---")
    def walk(obj, path=""):
        if isinstance(obj, dict):
            for kk,vv in obj.items(): walk(vv, f"{path}.{kk}")
        elif isinstance(obj, list):
            for i,vv in enumerate(obj): walk(vv, f"{path}[{i}]")
        else:
            s = str(obj).upper()
            if "TUBE" in s or "30 X 60" in s or "60 X 1.5" in s or "X 60 X" in s:
                print(f"    {path}: {str(obj)[:80]!r}")
    walk(p)
    break