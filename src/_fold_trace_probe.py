# Read-only: for 3886-02/03 (and a WORKING fold part like 1455-C-003 as control),
# dump the EXACT fields estimator.py:1975 reads:
#   manufacturing_features.bend_count, angles_deg, fold_values_mm, fold_count_textual
# to prove whether bend_count=0 is shadowing the angles_deg fallback via .get(k, default).
import json, glob, os
d = r"C:\ClaudeVision\output\json"
f = max(glob.glob(os.path.join(d, "*.json")), key=os.path.getmtime)
print("reading:", os.path.basename(f), "\n")
J = json.load(open(f, encoding="utf-8"))

TARGETS = ("3886-02", "3886-03", "1455-C-003", "1448-01")  # 2 broken, 1 working control, 1 tube control

def walk(o):
    if isinstance(o, dict):
        yield o
        for v in o.values(): yield from walk(v)
    elif isinstance(o, list):
        for v in o: yield from walk(v)

for tgt in TARGETS:
    print("="*60); print(f"PART {tgt}"); print("="*60)
    for node in walk(J):
        if not isinstance(node, dict): continue
        if str(node.get("part_number") or "") != tgt: continue
        mf = node.get("manufacturing_features") or {}
        # only print records that actually carry fold-ish fields (skip thin dupes)
        keys = set(node.keys())
        if not (keys & {"angles_deg","fold_values_mm","fold_count_textual","manufacturing_features","textual_operations","stock_form","material_estimate"}):
            continue
        print(f"  stock_form: {(node.get('material_estimate') or {}).get('stock_form')!r}")
        print(f"  manufacturing_features.bend_count: {mf.get('bend_count')!r}  (present={'bend_count' in mf})")
        print(f"  angles_deg: {node.get('angles_deg')!r}")
        print(f"  fold_values_mm: {node.get('fold_values_mm')!r}")
        print(f"  fold_count_textual: {node.get('fold_count_textual')!r}")
        print(f"  bend_count_dxf: {node.get('bend_count_dxf')!r}")
        print(f"  textual_operations: {node.get('textual_operations')!r}")
        # SIMULATE estimator.py:1975 exactly
        import math
        bc = mf.get("bend_count", max(len(node.get("angles_deg", []) if isinstance(node.get("angles_deg"), list) else []),
                                      len(node.get("fold_values_mm", []) if isinstance(node.get("fold_values_mm"), list) else [])))
        print(f"  -> estimator bends = mf.get('bend_count', max(angles,folds)) = {bc}")
        if 'bend_count' in mf and mf.get('bend_count') == 0:
            alt = max(len(node.get("angles_deg",[]) or []), len(node.get("fold_values_mm",[]) or []))
            print(f"     !!! bend_count=0 PRESENT -> .get returns 0, SHADOWING angles_deg fallback ({alt})")
        print()
