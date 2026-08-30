# -*- coding: utf-8 -*-
"""READ-ONLY. The page-21 'Part: None / Description: None' is a phantom: page 21 is a SECTION G-G
detail VIEW of BACK WALL (12532-03-06M, an existing costed part), not a new part. We want to
suppress it — but ONLY it, not any real part. Find its exact distinguishing signature so the
suppression rule is precise (deterministic), not broad.

Checks the phantom's record for a clean signature:
  - part_number is None/empty AND description is None/empty
  - its page text contains a SECTION/DETAIL callout (G-G) referencing an existing part number
  - vs. real parts which have a part_number

Run from C:\\ClaudeVision\\src :
  C:\\ClaudeVision\\.venv\\Scripts\\python.exe _probe_phantom_part.py
"""
import json, re
from pathlib import Path

J = Path(r"C:\ClaudeVision\output\json\12532-03RecipeCard.json")
data = json.loads(J.read_text(encoding="utf-8"))
pages = data.get("pages", [])
mw = (data.get("manufacturing_writeup") or {}).get("parts") or []

print("=== all parts with NO part_number (the phantom candidates) ===")
existing_pns = {str(p.get("part_number")) for p in mw if p.get("part_number")}
for p in mw:
    pn = p.get("part_number")
    if not pn or str(pn).strip() in ("", "None"):
        pgs = p.get("pages") or []
        print(f"  phantom: part_number={pn!r} description={p.get('description')!r} pages={pgs} "
              f"geometry_source={p.get('geometry_source')} roles={p.get('page_roles')}")
        # look at its page text for SECTION/DETAIL + referenced existing part
        for pi in pgs:
            if 0 <= pi-1 < len(pages):
                blob = json.dumps(pages[pi-1]).upper()
                sects = re.findall(r"SECTION\s+[A-Z]-[A-Z]|DETAIL\s+[A-Z]\b", blob)
                refpns = [x for x in re.findall(r"12532-\d{2}-\d{2,3}[A-Z]?", blob) if x in existing_pns]
                print(f"     page {pi}: section/detail callouts={sects}  references existing parts={sorted(set(refpns))}")

print("\n=== for contrast: do any REAL parts also have section callouts on their page? (must NOT be suppressed) ===")
for p in mw[:24]:
    pn = p.get("part_number")
    if pn and str(pn).strip() not in ("", "None"):
        for pi in (p.get("pages") or []):
            if 0 <= pi-1 < len(pages):
                blob = json.dumps(pages[pi-1]).upper()
                if re.search(r"SECTION\s+[A-Z]-[A-Z]", blob):
                    print(f"  real part {pn} page {pi} ALSO has a SECTION callout — so 'has section' alone is NOT a safe suppress signal")
                    break

print("\nVERDICT: safest suppression = part_number is empty/None AND description empty/None (a nameless")
print("phantom). Real parts always have a part_number. That single clean condition suppresses the")
print("phantom without risking any real part. Confirm no real part is nameless above.")
