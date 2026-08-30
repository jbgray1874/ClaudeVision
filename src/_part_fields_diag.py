# -*- coding: utf-8 -*-
r"""What page-identifying fields do the tube parts ACTUALLY carry?
The section loop uses _part.get('pages') but that's empty at loop time.
Find what field DOES link the part to its page (21 for 3886-01, 4 for 1448-01).
  C:\ClaudeVision\.venv\Scripts\python.exe _part_fields_diag.py
"""
import json
J = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
data = json.load(open(J, encoding="utf-8"))

# Look at the RAW parts (pre-estimation) if present, plus the estimated ones
for container_name in ("parts", "manufacturing_writeup"):
    c = data.get(container_name)
    if isinstance(c, dict):
        c = c.get("parts")
    if not c:
        continue
    print(f"\n===== container: {container_name} =====")
    for p in c:
        if p.get("part_number") in ("3886-01","1448-01"):
            print(f"\n  {p.get('part_number')}:")
            # print every key that might hold a page reference
            for k, v in p.items():
                if "page" in k.lower() or k in ("pages","source_pages","page_numbers","page_roles","drawing_file","source_pdf","pdf_page"):
                    print(f"    {k}: {v}")
            # also show all top-level keys so we see what's available
            print(f"    [all keys]: {sorted(p.keys())}")

# And the estimated parts
parts = (data.get("estimate_summary",{}) or {}).get("part_estimates") or []
print("\n\n===== estimate_summary.part_estimates =====")
for p in parts:
    if p.get("part_number") in ("3886-01","1448-01"):
        print(f"\n  {p.get('part_number')}: pages={p.get('pages')}")
        for k in ("pages","source_pages","page_numbers","page_roles","drawing_file","source_pdf"):
            if k in p:
                print(f"    {k}: {p.get(k)}")
