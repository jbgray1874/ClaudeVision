# -*- coding: utf-8 -*-
"""READ-ONLY. Test JG's insight: the big spec block (weld/plating/timber/glass/wiring/China grades
+ 'CHROME PLATING - POLISHING SPECIFICATION IS 400 GRIT FINAL POLISH') is TEMPLATE BOILERPLATE
stamped on EVERY drawing, not part-specific. Question: does diamond_polish on steel parts
(BASE PLINTH, DIVIDER) come from this boilerplate 'POLISH' text rather than a real part callout?

Checks:
  1. Does the boilerplate 'POLISHING SPECIFICATION' / 'FINAL POLISH' text appear in the notes of
     the parts that got diamond_polish? (and in parts that did NOT — if it's on all, it's boilerplate)
  2. Do the DIVIDER/BASE PLINTH pages have a REAL polish callout, or only the boilerplate?

Run from C:\\ClaudeVision\\src :
  C:\\ClaudeVision\\.venv\\Scripts\\python.exe _probe_boilerplate_polish.py
"""
import json, re
from pathlib import Path

J = Path(r"C:\ClaudeVision\output\json\12532-03RecipeCard.json")
data = json.loads(J.read_text(encoding="utf-8"))
pages = data.get("pages", [])

BOILER = ["POLISHING SPECIFICATION", "FINAL POLISH", "400 GRIT", "CHROME PLATING",
          "TIG UNLESS", "RESISTANCE WELDING", "FSC CERTIFIED", "SAFETY FILM",
          "ZERO HALOGEN", "Q195", "Q235", "SPCC"]

print("=== 1. Which pages contain the boilerplate spec block? (should be MANY = boilerplate) ===")
for i, pg in enumerate(pages):
    txt = json.dumps(pg).upper()
    hits = [b for b in BOILER if b in txt]
    if hits:
        print(f"   page[{i}]: {len(hits)} boilerplate markers {hits[:4]}...")

print("\n=== 2. Parts with diamond_polish — do their pages have a REAL polish callout or only boilerplate? ===")
mw = (data.get("manufacturing_writeup") or {}).get("parts") or []
for p in mw:
    ops = p.get("operations") or []
    if "diamond_polish" in ops:
        pn = p.get("part_number"); desc = p.get("description"); pgs = p.get("pages") or []
        # gather this part's own page text
        own = ""
        for pi in pgs:
            if 0 <= (pi-1) < len(pages):
                rt = pages[pi-1].get("region_text") or {}
                own += " ".join(str(rt.get(k) or "") for k in ("title_block","notes","bom","general")).upper()
        real_polish = bool(re.search(r"\bDIAMOND\s+POLISH\b|\bMATT\s+POLISH\b|\bPOLISHED\s+EDGES?\b", own))
        boiler_polish = bool(re.search(r"POLISHING SPECIFICATION|FINAL POLISH|400 GRIT", own))
        print(f"   {pn} ({desc}): real_polish_callout={real_polish}  boilerplate_polish_text={boiler_polish}  material={p.get('normalized_material')}")

print("\n=== 3. The DIVIDER (03-05M) finish per drawing: what does page 20 actually say about polish? ===")
if len(pages) > 19:
    rt = pages[19].get("region_text") or {}
    t = " ".join(str(rt.get(k) or "") for k in ("title_block","notes")).upper()
    print(f"   page20 finish text: {t[:220]}")

print("\nVERDICT: if diamond_polish parts show real_polish_callout=False but boilerplate_polish_text=True,")
print("the op is coming from the TEMPLATE boilerplate, not the part -> strip boilerplate before op-scan,")
print("OR only add diamond_polish for acrylic / genuine 'POLISHED EDGES' callouts.")
