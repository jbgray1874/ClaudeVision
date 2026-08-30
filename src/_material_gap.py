# -*- coding: utf-8 -*-
r"""Pinpoint the material gap: engine per-part material vs Tim's material lines.
Read-only. Shows which parts the engine under-costs so we know the 2-3 to fix.
  cd C:\ClaudeVision\src
  C:\ClaudeVision\.venv\Scripts\python.exe _material_gap.py
"""
import json

J = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
data = json.load(open(J, encoding="utf-8"))

print("=== ENGINE per-part MATERIAL cost (from cost_breakdown.material.per_part) ===")
cb = data.get("cost_breakdown", {}) or {}
mat = (cb.get("material", {}) or {})
per_part = mat.get("per_part", []) or []
eng_total = 0.0
print(f"{'part':<14} {'ext_material_£':>14}  {'supplier_source':<22} {'thick/geom note'}")
print("-"*75)
# also pull part geometry to spot tube/flat issues
parts_by_pn = {}
for pe in (data.get("estimate_summary",{}) or {}).get("part_estimates", []) or []:
    parts_by_pn[str(pe.get("part_number"))] = pe

for pp in per_part:
    pn = str(pp.get("part_number") or "")
    ext = float(pp.get("extended_material_cost_gbp") or 0)
    eng_total += ext
    src = str(pp.get("supplier_source") or "")[:22]
    pe = parts_by_pn.get(pn, {})
    ng = pe.get("normalized_geometry", {}) or {}
    me = pe.get("material_estimate", {}) or {}
    note = f"thk={pe.get('normalized_thickness_mm')} blank_l={me.get('blank_length_mm')} cut={ng.get('estimated_cut_length_mm')}"
    flag = ""
    desc = str(pe.get("description") or "").upper()
    if ext == 0:
        flag = "  <-- £0 MATERIAL"
    if "TUBE" in desc or pn in ("1448-01","3886-01"):
        flag += "  <-- TUBE? (check basis)"
    print(f"{pn:<14} {ext:>14.2f}  {src:<22} {note}{flag}")
print(f"\nENGINE material total = £{eng_total:.2f}   (Tim = £90.60)\n")

print("=== TIM's manual material lines (from bom_set_reconciliation.manual_only) ===")
recon = data.get("bom_set_reconciliation", {}) or {}
# may not be in summary JSON — try the parity bundle instead
import os
PB = r"C:\ClaudeVision\output\csv\estimate_full_parity_bundle.json"
if os.path.exists(PB):
    pb = json.load(open(PB, encoding="utf-8"))
    recon = pb.get("bom_set_reconciliation", {}) or recon
manual_only = recon.get("manual_only", []) or []
if manual_only:
    # show the biggest manual lines (likely the material Tim has that we don't)
    big = []
    for m in manual_only:
        c = m.get("manual_cost_gbp")
        if isinstance(c,(int,float)):
            big.append((c, m))
    big.sort(reverse=True)
    print(f"{'£cost':>10}  description / code (top 15 by cost)")
    for c, m in big[:15]:
        lbl = m.get("description") or m.get("part_code") or m.get("code") or m.get("label") or "?"
        print(f"{c:>10.2f}  {str(lbl)[:50]}")
else:
    print("  (manual_only not in this JSON — read from parity bundle)")
