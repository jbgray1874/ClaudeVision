"""
Read-only. Check what material 1455-C-005 (HEADER LENS) actually is, and whether the
engine has hole-count / internal-cut data for the laser calculator (S and T columns).
Run: C:\ClaudeVision\.venv\Scripts\python.exe _lens_material_check.py
"""
import json
from pathlib import Path

P = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
data = json.loads(Path(P).read_text(encoding="utf-8"))
pes = (data.get("estimate_summary") or {}).get("part_estimates") or data.get("parts") or []

print("=== 1455-C-005 HEADER LENS — what material is it? ===")
for pe in pes:
    if str(pe.get("part_number") or "") == "1455-C-005":
        me = pe.get("material_estimate") or {}
        geo = pe.get("geometry") or {}
        print(f"  normalized_material : {pe.get('normalized_material')}")
        print(f"  material (me)       : {me.get('material')}")
        print(f"  thickness_mm        : {pe.get('normalized_thickness_mm')}")
        print(f"  stock_form          : {me.get('stock_form')}")
        print(f"  cost_method         : {me.get('cost_method')}")
        print(f"  description         : {pe.get('description')}")

print("\n=== Do sheet parts have HOLE / internal-cut data for the laser calc? ===")
print("(checking a peg panel which should have many holes)")
for pe in pes:
    pn = str(pe.get("part_number") or "")
    if pn in {"1449-01C", "2621-01C", "1455-C-001"}:
        geo = pe.get("geometry") or {}
        me = pe.get("material_estimate") or {}
        print(f"\n  {pn} — {pe.get('description')}")
        print(f"    estimated_cut_length_mm : {geo.get('estimated_cut_length_mm')}")
        # look for any hole / hole-count / internal-cut fields
        allkeys = json.dumps(pe).lower()
        for term in ("hole", "cutout", "internal", "perimeter", "pierce", "num_hole", "hole_count"):
            if term in allkeys:
                # find the actual key/value
                for k, v in {**geo, **me}.items():
                    if term in k.lower():
                        print(f"    >>> {k} = {v}")
        # print geometry keys so we see what's available
        print(f"    geometry keys: {list(geo.keys())}")
