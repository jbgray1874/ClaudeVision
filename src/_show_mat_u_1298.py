"""READ-ONLY. Prints the ACTUAL normalized_material (_mat_u) for 1298-01 from the persisted
JSON, and checks it against the _SHEET_METALS set the strip uses. This is the last unknown:
the strip is correctly placed (before costing) but its condition `_mat_u in _SHEET_METALS`
may not be matching 1298-01, so the strip body is skipped.

Run from C:\ClaudeVision\src :
  C:\ClaudeVision\.venv\Scripts\python.exe _show_mat_u_1298.py
"""
import json
from pathlib import Path

# The set as defined in estimator.py (keep in sync)
_SHEET_METALS = {"MILD_STEEL", "MILD STEEL", "STAINLESS_STEEL", "STAINLESS STEEL",
                 "ALUMINIUM", "ALUMINUM", "ZINTEC", "BRIGHT_DRAWN"}

JSON_OUT = Path(r"C:\ClaudeVision\output\json\1298DrillHolder.json")
data = json.loads(JSON_OUT.read_text(encoding="utf-8"))

def walk(o):
    found = []
    if isinstance(o, dict):
        pn = o.get("part_number") or o.get("description")
        if pn and ("1298" in str(pn) or "DRILL" in str(pn).upper()):
            found.append(o)
        for v in o.values():
            found += walk(v)
    elif isinstance(o, list):
        for v in o:
            found += walk(v)
    return found

seen = set()
for part in walk(data):
    nm = part.get("normalized_material")
    mat = part.get("material")
    mats = part.get("materials")
    pn = part.get("part_number") or part.get("description")
    key = (str(pn), str(nm), str(mat))
    if key in seen:
        continue
    seen.add(key)
    _mat_u = str(nm or "").upper()
    in_set = _mat_u in _SHEET_METALS
    print(f"PART {pn}:")
    print(f"  normalized_material (raw) = {nm!r}")
    print(f"  material                  = {mat!r}")
    print(f"  materials                 = {mats!r}")
    print(f"  _mat_u (upper)            = {_mat_u!r}")
    print(f"  _mat_u in _SHEET_METALS   = {in_set}  {'<-- STRIP WOULD FIRE' if in_set else '<-- STRIP SKIPPED (this is the bug)'}")
    print()

print("_SHEET_METALS =", sorted(_SHEET_METALS))
print("\nIf _mat_u is NOT in the set (e.g. None, a code, lowercase, or a variant spelling),")
print("that's why the strip is skipped. Fix: widen the condition to catch the actual value")
print("(e.g. also test part['material']/materials, or add the missing token to _SHEET_METALS).")
