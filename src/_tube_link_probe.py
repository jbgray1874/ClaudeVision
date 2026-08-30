# -*- coding: utf-8 -*-
r"""READ-ONLY. Confirm HOW a part links to the page that holds its tube text,
so genuine extraction fetches the RIGHT page text per part. No hard-coding.
  C:\ClaudeVision\.venv\Scripts\python.exe _tube_link_probe.py
"""
import json
J = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
data = json.load(open(J, encoding="utf-8"))

parts = (data.get("estimate_summary",{}) or {}).get("part_estimates") or data.get("parts") or []
for pe in parts:
    pn = str(pe.get("part_number") or "")
    if pn.startswith("1448-01") or pn.startswith("3886-01"):
        print(f"\n=== {pn} — page-link fields ===")
        for k in ("pages","source_pages","page_indices","page_numbers","source_page","pages_roles"):
            if k in pe: print(f"  {k}: {pe[k]}")
        # what fields does the part actually have? (top-level keys)
        print(f"  ALL KEYS: {sorted(pe.keys())}")

# Now find the page record with the tube text and see its structure / how it's keyed
print("\n\n=== the page record holding '30 x 60 x 1.50mm TUBE 1125' ===")
def walk(d, path="root"):
    out=[]
    if isinstance(d, dict):
        blob = json.dumps(d)[:5000]
        if "30 x 60 x 1.50mm TUBE" in blob:
            # this dict (or a child) holds it; check if THIS level has the text directly
            for k,v in d.items():
                if isinstance(v,str) and "30 x 60 x 1.50mm TUBE" in v:
                    out.append((path, k, v[:120], sorted(d.keys())[:15]))
        for k,v in d.items(): out += walk(v, path+"."+str(k))
    elif isinstance(d, list):
        for i,it in enumerate(d): out += walk(it, f"{path}[{i}]")
    return out
for path, key, text, siblings in walk(data)[:3]:
    print(f"  at {path}")
    print(f"    field '{key}': ...{text}...")
    print(f"    sibling keys: {siblings}")
    # is there a page number / part link near it?
