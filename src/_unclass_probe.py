"""
Read-only. Dump the classification-relevant fields for the two 'unclassifiable'
parts plus a known BI- item and the kick-plate assembly, to see how their price
and role are actually stored. Run:
C:\ClaudeVision\.venv\Scripts\python.exe _unclass_probe.py
"""
import json
from pathlib import Path

P = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
data = json.loads(Path(P).read_text(encoding="utf-8"))
pes = (data.get("estimate_summary") or {}).get("part_estimates") or data.get("parts") or []

TARGETS = {"1453-GA-C", "BI-ADHESIVECABLE", "BI-DOMERIVET", "FIXING5", "NOTE-JUNCTIONBOX"}

for pe in pes:
    pn = str(pe.get("part_number") or "")
    if pn not in TARGETS:
        continue
    me = pe.get("material_estimate") or {}
    print("="*66)
    print(f"{pn} — {pe.get('description')}")
    print(f"  page_roles           : {pe.get('page_roles')}")
    print(f"  normalized_material  : {pe.get('normalized_material')}")
    print(f"  stock_form (me)      : {me.get('stock_form')!r}")
    print(f"  reliability_flags    : {me.get('reliability_flags')!r}")
    print(f"  note (me)            : {str(me.get('note'))[:70]!r}")
    print(f"  --- price fields ---")
    print(f"  top unit_cost_gbp          : {pe.get('unit_cost_gbp')}")
    print(f"  top unit_material_cost_gbp : {pe.get('unit_material_cost_gbp')}")
    print(f"  top extended_total_cost_gbp: {pe.get('extended_total_cost_gbp')}")
    print(f"  me unit_material_cost_gbp  : {me.get('unit_material_cost_gbp')}")
    print(f"  me cost_per_part_gbp       : {me.get('cost_per_part_gbp')}")
    print(f"  me extended_material_cost  : {me.get('extended_material_cost_gbp')}")
    print(f"  source / cost_source       : {pe.get('source')} / {pe.get('cost_source')}")
    print(f"  top-level keys             : {[k for k in pe.keys() if 'cost' in k.lower() or 'price' in k.lower() or 'qty' in k.lower() or 'quantity' in k.lower()]}")
