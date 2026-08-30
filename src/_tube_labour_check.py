"""
Read-only. Check whether the tube parts (1448-01, 3886-01) have any LABOUR operations
in the engine's data (e.g. tube-cutting / saw), or only material cost. Tim's manual
sheet would have a cutting operation for them. Run:
  C:\ClaudeVision\.venv\Scripts\python.exe _tube_labour_check.py
"""
import json
from pathlib import Path

P = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
data = json.loads(Path(P).read_text(encoding="utf-8"))
pes = (data.get("estimate_summary") or {}).get("part_estimates") or data.get("parts") or []

for pe in pes:
    pn = str(pe.get("part_number") or "")
    if pn not in {"1448-01", "3886-01"}:
        continue
    le = pe.get("labour_estimate") or {}
    costs = le.get("costs_gbp") or {}
    me = pe.get("material_estimate") or {}
    print("="*60)
    print(f"{pn} — {pe.get('description')}")
    print(f"  stock_form         : {me.get('stock_form')}")
    print(f"  section_length_mm  : {(me.get('stock_estimate') or {}).get('section_length_mm')}")
    print(f"  labour operations  : {list(costs.keys()) if costs else 'NONE — no cutting labour!'}")
    print(f"  labour costs_gbp   : {costs}")
    print(f"  total_labour_cost  : {le.get('total_labour_cost_gbp')}")

print("\n" + "="*60)
print("If tubes have NO labour operations -> the tube-CUTTING labour is missing.")
print("Tim's sheet would have a Tube/Saw operation to cut the leg to length.")
print("This is a labour gap for tube parts (material is captured, cutting isn't).")
