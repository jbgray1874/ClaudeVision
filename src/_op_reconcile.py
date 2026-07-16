"""
READ-ONLY. Reconcile what the ENGINE actually assigned as operations for the tube and
acrylic parts, vs what appeared in the workbook. Shows textual_operations,
inferred_operations, labour costs_gbp keys, and the bend fields that drive fold time.

Run: C:\ClaudeVision\.venv\Scripts\python.exe _op_reconcile.py
"""
import json
from pathlib import Path

P = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
data = json.loads(Path(P).read_text(encoding="utf-8"))
pes = (data.get("estimate_summary") or {}).get("part_estimates") or data.get("parts") or []

targets = {"1448-01", "3886-01", "1455-C-005", "1449-01C"}  # tubes, acrylic, a peg panel

for pe in pes:
    pn = str(pe.get("part_number") or "")
    if pn not in targets:
        continue
    le = pe.get("labour_estimate") or {}
    me = pe.get("material_estimate") or {}
    mf = pe.get("manufacturing_features") or {}
    gr = pe.get("geometry_rollup") or {}
    print("=" * 66)
    print(f"{pn} — {pe.get('description')}  [{pe.get('normalized_material')}]")
    print(f"  stock_form            : {me.get('stock_form')}")
    print(f"  textual_operations    : {pe.get('textual_operations')}")
    print(f"  inferred_operations   : {pe.get('inferred_operations')}")
    print(f"  labour costs_gbp keys : {list((le.get('costs_gbp') or {}).keys())}")
    print(f"  batch_hours keys      : {list((le.get('batch_hours') or {}).keys())}")
    print(f"  -- bend signals --")
    print(f"  mf.bend_count         : {mf.get('bend_count')}")
    print(f"  gr.estimated_bend_line_count : {gr.get('estimated_bend_line_count')}")
    print(f"  fold_count_textual    : {pe.get('fold_count_textual')}")
    print(f"  fold_values_mm        : {pe.get('fold_values_mm')}")
    print(f"  bend_count_dxf        : {pe.get('bend_count_dxf')}")
    print(f"  section_costing_adjustment : {pe.get('section_costing_adjustment', {}).get('rule') if pe.get('section_costing_adjustment') else None}")

print("\n" + "=" * 66)
print("KEY QUESTIONS:")
print("  - Do the tubes show 'folding' in costs_gbp? (engine keeps it: SDI bends tubes)")
print("  - Does the acrylic show 'folding' or 'linebend'? (engine should use linebend)")
print("  - Are the bend counts tiny/zero -> explaining the tiny fold time / absurd throughput?")
