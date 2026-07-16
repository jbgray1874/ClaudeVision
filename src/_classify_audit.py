"""
Read-only. For EVERY part, print the fields that drive classification, so we can
see the whole picture at once instead of patching branch by branch. Groups by what
the CORRECT block should be, based on the engine's own fields.
Run: C:\ClaudeVision\.venv\Scripts\python.exe _classify_audit.py
"""
import json, re
from pathlib import Path

P = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
data = json.loads(Path(P).read_text(encoding="utf-8"))
pes = (data.get("estimate_summary") or {}).get("part_estimates") or data.get("parts") or []

def safe(v):
    try:
        if v in (None,"","None"): return None
        return float(v)
    except: return None

print(f"{'PART':<24}{'role':<10}{'stock_form':<11}{'unit£':<8}{'ext£':<8}{'mat?':<6}{'blankL':<8}")
print("-"*80)
for pe in pes:
    pn = str(pe.get("part_number") or "")[:23]
    me = pe.get("material_estimate") or {}
    roles = ",".join(pe.get("page_roles") or []) or "-"
    sf = me.get("stock_form") or "-"
    up = safe(pe.get("unit_cost_gbp") or pe.get("unit_material_cost_gbp"))
    ext = safe(pe.get("extended_total_cost_gbp"))
    blank = me.get("blank_length_mm")
    # what fields signal "has real material geometry"
    has_mat_geom = safe(me.get("blank_length_mm")) is not None
    has_stockform_val = bool(me.get("stock_form"))
    matflag = ("geom" if has_mat_geom else ("sf" if has_stockform_val else "-"))
    print(f"{pn:<24}{roles[:9]:<10}{str(sf):<11}{str(up if up is not None else '-'):<8}"
          f"{str(ext if ext is not None else '-'):<8}{matflag:<6}{str(blank or '-'):<8}")

print("\nLegend: role=page_roles, mat?=has material (geom=blank dims / sf=stock_form value)")
print("Count parts by what they clearly are, so we size the BOM block correctly.")
