"""Fixes the metal hole-strip's material condition so it fires even when normalized_material
is not yet set at the point the strip runs.

ROOT CAUSE (proven via _show_mat_u_1298.py): the strip checks `_mat_u in _SHEET_METALS`
where `_mat_u = normalized_material.upper()`. For 1298-01, at strip time normalized_material
is None (-> _mat_u = '' -> condition False -> strip SKIPPED), even though the FINAL persisted
record shows 'MILD_STEEL'. The normalization lands later / on another copy. So the strip's
own material gate misses the part.

FIX: broaden the gate to ALSO look at part['materials'] and part['material'] (the raw
material list shows ['MILD STEEL'] and is populated at strip time). If ANY of the material
fields indicates a sheet metal, the strip fires. Acrylic/board still excluded (they won't
match _SHEET_METALS on any field).

SAFE: exact-string match-or-refuse. Replaces only the `if _mat_u in _SHEET_METALS:` line
that guards the metal hole-strip (the one immediately above `_metal_hole_ops = (...)`).

BEFORE APPLYING, confirm the exact guard line in live src:
  Select-String -Path C:\ClaudeVision\src\estimator.py -Pattern "_mat_u in _SHEET_METALS" -Context 0,2

Run from C:\ClaudeVision\src :
  C:\ClaudeVision\.venv\Scripts\python.exe _fix_metal_holestrip_matcheck.py
Then re-run 1298 (Operations should lose hole_machining; total ~£3.08; warning/GUIL gone)
AND 1282 (MUST stay £204.66 / labour £72.38; acrylic lens intact).
"""
from pathlib import Path

TARGET = Path(r"C:\ClaudeVision\src\estimator.py")

# The guard is the line right before our _metal_hole_ops assignment. Match BOTH lines
# together so we replace only THIS occurrence (there may be other _mat_u in _SHEET_METALS).
OLD = '''    if _mat_u in _SHEET_METALS:
        _metal_hole_ops = ("hole_machining", "drilling")'''

NEW = '''    # Broadened metal gate: normalized_material may not be set yet at this point in the
    # pipeline (seen None on 1298-01 while the raw `materials` list already held MILD STEEL),
    # which silently skipped the strip. Check ALL material fields so a not-yet-normalized
    # part is still recognised as sheet metal. Acrylic/board won't match on any field.
    _mat_fields = [_mat_u]
    _mat_fields.append(str(part.get("material") or "").upper())
    for _m in (part.get("materials") or []):
        _mat_fields.append(str(_m or "").upper().replace(" ", "_"))
        _mat_fields.append(str(_m or "").upper())
    _is_metal_any = any(mf in _SHEET_METALS for mf in _mat_fields if mf)
    if _is_metal_any:
        _metal_hole_ops = ("hole_machining", "drilling")'''

src = TARGET.read_text(encoding="utf-8")

if "_is_metal_any = any(mf in _SHEET_METALS" in src:
    print("ALREADY APPLIED — broadened metal gate already present.")
    raise SystemExit(0)

if OLD not in src:
    print("NOT APPLIED — the guard+strip pair was not found verbatim.")
    print("Dump the region and paste back:")
    print(r'  Select-String -Path C:\ClaudeVision\src\estimator.py -Pattern "_metal_hole_ops = " -Context 2,1')
    raise SystemExit(1)

if src.count(OLD) > 1:
    print(f"NOT APPLIED — pattern appears {src.count(OLD)} times, expected 1. Refusing to guess.")
    raise SystemExit(1)

TARGET.write_text(src.replace(OLD, NEW), encoding="utf-8")
print("APPLIED — metal hole-strip gate broadened to check all material fields.")
print("Fingerprint: Select-String estimator.py -Pattern '_is_metal_any = any'")
print("Next: re-run 1298 (hole_machining/drilling gone; ~£3.08; GUIL+warning gone)")
print("AND 1282 (MUST stay £204.66 / labour £72.38; acrylic HEADER LENS intact).")
