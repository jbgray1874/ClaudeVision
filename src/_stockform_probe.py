"""
Read-only. Show the exact stock_form value and where a tube's CUT LENGTH lives,
so tube routing uses real values. Compares tubes vs sheet vs weldment.
Run: C:\ClaudeVision\.venv\Scripts\python.exe _stockform_probe.py
"""
import json
from pathlib import Path

P = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
data = json.loads(Path(P).read_text(encoding="utf-8"))
pes = (data.get("estimate_summary") or {}).get("part_estimates") or data.get("parts") or []

for pe in pes:
    pn = str(pe.get("part_number") or "")
    if pn not in {"1448-01", "3886-01", "1449-01C", "1455-C-101"}:
        continue
    me = pe.get("material_estimate") or {}
    se = me.get("stock_estimate") or {}
    print("="*66)
    print(f"{pn} — {pe.get('description')}")
    print(f"  stock_form           : {me.get('stock_form')!r}")
    print(f"  cost_method          : {me.get('cost_method')!r}")
    print(f"  price_source         : {me.get('price_source')!r}")
    print(f"  requires_flat_blank  : {me.get('requires_flat_blank')!r}")
    print(f"  has powder_consumable: {'powder_consumable' in me}")
    print(f"  has ext_sheet_cost   : {'extended_sheet_material_cost_gbp' in me}")
    print(f"  has supplier key     : {'supplier' in me}  -> {me.get('supplier')!r}")
    print(f"  blank_length_mm      : {me.get('blank_length_mm')}")
    print(f"  blank_width_mm       : {me.get('blank_width_mm')}")
    print(f"  stock_estimate keys  : {list(se.keys())}")
    print(f"  stock_estimate       : {json.dumps(se)[:300]}")
    print(f"  note                 : {me.get('note')!r}")
    print(f"  reliability_flags    : {me.get('reliability_flags')!r}")
    # hunt for a length-like value (the 1125mm cut length for tube)
    for k, v in me.items():
        if "length" in k.lower() or "cut" in k.lower() or "1125" in str(v):
            print(f"    length-ish: {k} = {v}")
