# -*- coding: utf-8 -*-
r"""READ-ONLY. Dump the GENUINE extracted text (all extractors) for the two tube
pages, so we design tube parsing against REAL strings, not idealised ones.
  C:\ClaudeVision\.venv\Scripts\python.exe _tube_rawtext_probe.py
"""
import json, re
J = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
data = json.load(open(J, encoding="utf-8"))
pages = data.get("pages", [])

# find pages whose text mentions TUBE or the leg part numbers, and the 1448 detail (page 4) + 3886 (page 21)
def page_blob(p):
    return " ".join(str(p.get(k) or "") for k in ("pypdf_text","normalized_text","pdfplumber_text"))

for idx, p in enumerate(pages):
    blob = page_blob(p).upper()
    jpn = p.get("job_page_number") or p.get("page_number")
    is_tube_page = ("TUBE" in blob) or ("WALL" in blob and "1.5" in blob and ("60" in blob and "30" in blob))
    if not is_tube_page:
        continue
    print(f"\n{'='*70}\nPAGE index {idx}  (job_page_number={jpn}, role={p.get('page_role')})\n{'='*70}")
    for field in ("pypdf_text","normalized_text","pdfplumber_text"):
        t = str(p.get(field) or "")
        if not t.strip():
            print(f"\n--- {field}: (empty) ---")
            continue
        # show the window around TUBE / WALL / the dimension cluster
        up = t.upper()
        anchor = up.find("TUBE")
        if anchor < 0: anchor = up.find("WALL")
        if anchor < 0: anchor = up.find("LENGTH")
        if anchor < 0: anchor = 0
        seg = t[max(0,anchor-120):anchor+120]
        print(f"\n--- {field} (window around TUBE/WALL/LENGTH) ---")
        print("   " + seg.replace(chr(10)," | "))
        # also: what number tokens appear near the anchor?
        nums = re.findall(r"\d+(?:\.\d+)?", t[max(0,anchor-120):anchor+120])
        print(f"   numbers near anchor: {nums}")
