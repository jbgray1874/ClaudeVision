# -*- coding: utf-8 -*-
r"""READ-ONLY diagnostic: why is section detection finding nothing on the tubes?
Replays the EXACT logic from drawing_job_merge's section loop against the live JSON.
  cd C:\ClaudeVision\src
  C:\ClaudeVision\.venv\Scripts\python.exe _section_diag.py
"""
import json
from document_builder import _detect_section_stock, _get_page_text, _page_lookup_key

J = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
data = json.load(open(J, encoding="utf-8"))

# 1. Build the page lookup EXACTLY as drawing_job_merge does
page_lookup = {}
for pg in data.get("pages", []) or []:
    pnum = _page_lookup_key(pg, data)
    print(f"  page key={pnum}  job_page_number={pg.get('job_page_number')}  text_len={len(_get_page_text(pg))}")
    if pnum is not None:
        page_lookup[pnum] = _get_page_text(pg)

print(f"\n  page_lookup keys: {sorted(page_lookup.keys())}")

# 2. For each tube part, replay the detection
parts = (data.get("estimate_summary",{}) or {}).get("part_estimates") or data.get("parts") or []
for pe in parts:
    pn = pe.get("part_number","")
    if pn not in ("3886-01","1448-01"):
        continue
    page_nums = pe.get("pages", []) or []
    print(f"\n=== {pn}: pages={page_nums}, section_stock already set? {bool(pe.get('section_stock'))} ===")
    ptext = " ".join(page_lookup.get(pn2, "") for pn2 in page_nums)
    print(f"  combined page text length: {len(ptext)}")
    print(f"  text sample: {ptext[:200]!r}")
    sec = _detect_section_stock(ptext)
    print(f"  _detect_section_stock -> {sec}")

# 3. Foam Tape £132 — is it from the recogniser or a downstream override?
print("\n\n=== FOAM TAPE pricing trace ===")
for pe in parts:
    if "FOAM" in str(pe.get("part_number","")).upper() or "FOAM" in str(pe.get("description","")).upper():
        print(f"  {pe.get('part_number')}: {pe.get('description')}")
        print(f"    unit_cost_gbp: {pe.get('unit_cost_gbp')}")
        print(f"    extended_total_cost_gbp: {pe.get('extended_total_cost_gbp')}")
        print(f"    cost_source: {pe.get('cost_source')}")
        print(f"    _matched_historical_desc: {pe.get('_matched_historical_desc')}")
        print(f"    _match_score: {pe.get('_match_score')}")
        print(f"    review_flags: {pe.get('review_flags')}")
        me = pe.get("material_estimate") or {}
        print(f"    material_estimate.cost_per_part_gbp: {me.get('cost_per_part_gbp')}")
        print(f"    material_estimate keys: {list(me.keys())[:10]}")
