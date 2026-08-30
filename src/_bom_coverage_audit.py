# -*- coding: utf-8 -*-
r"""READ-ONLY BOM coverage audit. For the 1282 run JSON:
  1. Every BOM row the engine extracted from every page (extract_bom_rows).
  2. Every part that got costed (part_estimates).
  3. Every loose item mentioned in assembly-note prose (page 10 consumables).
Then reconcile: which BOM lines are costed, which are dropped, which note-items are missing.
This systematically answers "are we missing items" — not from memory, from the data.
  C:\ClaudeVision\.venv\Scripts\python.exe _bom_coverage_audit.py
"""
import json, re, sys
sys.path.insert(0, r"C:\ClaudeVision\src")
J = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
data = json.load(open(J, encoding="utf-8"))

# 1. costed parts
parts = (data.get("estimate_summary",{}) or {}).get("part_estimates") or data.get("parts") or []
costed = {}
for pe in parts:
    pn = str(pe.get("part_number") or "").strip().upper()
    cost = pe.get("extended_total_cost_gbp") or pe.get("unit_total_cost_gbp") or 0
    if pn:
        costed[pn] = cost
print(f"=== COSTED PARTS: {len(costed)} ===")
for pn, c in sorted(costed.items()):
    flag = "  <-- £0" if (c or 0) == 0 else ""
    print(f"   {pn:<16} £{c}{flag}")

# 2. every BOM row extracted from page text
print("\n=== BOM ROWS found in page text (what the drawings actually list) ===")
try:
    from extractor_patterns import extract_bom_rows
    seen_bom = {}
    for p in data.get("pages", []):
        txt = " ".join(str(p.get(k) or "") for k in ("pdfplumber_text","normalized_text","pypdf_text"))
        for row in extract_bom_rows(txt):
            pn = str(row.get("part_number") or "").strip().upper()
            if pn and pn not in seen_bom:
                seen_bom[pn] = row.get("description","")
    for pn, desc in sorted(seen_bom.items()):
        in_cost = "costed" if pn in costed else "*** NOT COSTED ***"
        print(f"   {pn:<18} {str(desc)[:34]:<34} [{in_cost}]")
except Exception as e:
    print("   (couldn't run extract_bom_rows:", e, ")")

# 3. loose items in assembly-note prose (page 10) — the consumables question
print("\n=== LOOSE ITEMS in assembly-note prose (page 10) ===")
note_items = ["JUNCTION BOX","MAINS CABLE","EARTH STRAP","FOAM TAPE","ADHESIVE CABLE","LOOM","DOME RIVET","D/S CLIP"]
page10 = ""
for p in data.get("pages", []):
    txt = " ".join(str(p.get(k) or "") for k in ("pdfplumber_text","normalized_text","pypdf_text")).upper()
    if "JUNCTION BOX" in txt or "MAINS CABLE" in txt or "EARTH STRAP" in txt:
        page10 = txt; break
for item in note_items:
    present_in_text = item in page10
    costed_match = any(item.replace(" ","") in pn.replace(" ","") or item in str(costed.get(pn,"")) for pn in costed)
    # cruder: is the item mentioned anywhere in costed descriptions?
    in_estimate = any(item in str(pe.get("description","")).upper() for pe in parts)
    status = "in estimate" if in_estimate else ("*** ON DRAWING, NOT IN ESTIMATE ***" if present_in_text else "not on drawing")
    print(f"   {item:<16} on_page10={present_in_text}   {status}")
