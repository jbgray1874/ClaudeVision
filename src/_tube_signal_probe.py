"""
Read-only. For the parts that fell out (1448-01, 3886-01 tubes; 1455-C-101 weldment)
plus a known-good steel part, dump the fields that could distinguish tube vs sheet vs
assembly — so tube detection keys off a REAL signal, not the description guess.
Run: C:\ClaudeVision\.venv\Scripts\python.exe _tube_signal_probe.py
"""
import json
from pathlib import Path

P = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
data = json.loads(Path(P).read_text(encoding="utf-8"))

pes = (data.get("estimate_summary") or {}).get("part_estimates") or data.get("parts") or []

TARGETS = {"1448-01", "3886-01", "1455-C-101", "1449-01C", "1455-C-001"}

for pe in pes:
    pn = str(pe.get("part_number") or "")
    if pn not in TARGETS:
        continue
    me = pe.get("material_estimate") or {}
    ng = pe.get("normalized_geometry") or {}
    geo = pe.get("geometry") or {}
    print("="*70)
    print(f"PART: {pn}  —  {pe.get('description')}")
    print(f"  page_roles          : {pe.get('page_roles')}")
    print(f"  normalized_material : {pe.get('normalized_material')}")
    print(f"  geometry_source     : {pe.get('geometry_source')}")
    print(f"  reliability         : {(geo.get('confidence') or {}).get('geometry_reliability')}")
    print(f"  blank_length_mm     : {me.get('blank_length_mm')} / ng: {ng.get('blank_length_mm')}")
    print(f"  blank_width_mm      : {me.get('blank_width_mm')} / ng: {ng.get('blank_width_mm')}")
    print(f"  thickness_mm        : {pe.get('normalized_thickness_mm')}")
    print(f"  cut_length_mm       : {geo.get('estimated_cut_length_mm')}")
    print(f"  operations          : {(pe.get('process_estimate') or {}).get('operations')}")
    print(f"  material_estimate keys: {list(me.keys())}")
    # look for any tube/length/section hint anywhere in the record
    blob = json.dumps(pe).upper()
    for kw in ("TUBE", "SECTION", "30 X 60", "30X60", "1.50MM TUBE", "LENGTH"):
        if kw in blob:
            print(f"    >>> contains '{kw}'")
