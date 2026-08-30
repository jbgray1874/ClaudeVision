# -*- coding: utf-8 -*-
"""FIX: stop _reconcile_bought_in from dropping genuine FABRICATED parts.

Root cause (PROVEN): 12532-02-09M HEADER GRAPHIC CHANNEL, 02-10M GRAPHIC CHANNEL, 03-07M
CHANNEL L were dropped from part_estimates (understating the job). They carry page_roles
['detail','bought_in'], so _is_bought_in() = True, and _bought_in_same_item() collapsed them
as description-duplicates of LOWER GRAPHIC CHANNEL (07M) because the tokens GRAPHIC/CHANNEL
overlap. But these are REAL manufactured parts: each has its own flat-pattern DXF, SDI part
number, geometry, routing. The docstring already promises "Fabricated parts ... are never
dedup-dropped" — but _is_bought_in keys only on the role, so the guard was never implemented.

FIX: _is_bought_in returns False for a part that has genuine fabrication evidence — a DXF flat
pattern (geometry_source contains 'dxf' or dxf_augmented / dxf_source_file present), OR an SDI
part number with real blank/overall geometry. Such parts are manufactured, not bought-in lines,
and skip the dedup entirely (appended as-is). Pure bought-in lines (fixings, vinyls, castors,
looms — no DXF) still dedup exactly as before.

SAFE: exact-string match-or-refuse on the 2-line _is_bought_in body. Regression: 1282/1298
bought-in items are non-DXF commercial lines -> _is_fabricated False -> dedup unchanged.

BEFORE APPLYING, confirm anchor:
  Select-String -Path C:\ClaudeVision\src\estimator.py -Pattern "return .bought_in. in roles or str" -Context 2,0

Run from C:\ClaudeVision\src :
  C:\ClaudeVision\.venv\Scripts\python.exe _apply_reconcile_fab_guard.py

AFTER: re-run Recipe Card — 09M/10M/07M should now appear in the Sheet Steel block with costs.
Then 1282 + 1298 regression (bought-in dedup must be unchanged there).
"""
from pathlib import Path

TARGET = Path(r"C:\ClaudeVision\src\estimator.py")

ANCHOR = '''    def _is_bought_in(p: Dict[str, Any]) -> bool:
        roles = p.get("page_roles") or []
        return "bought_in" in roles or str(p.get("source") or "") in _BOUGHT_IN_SOURCE_RANK'''

REPLACEMENT = '''    def _is_fabricated_part(p: Dict[str, Any]) -> bool:
        # A part with its own flat-pattern DXF (or a real SDI part number + geometry) is a
        # MANUFACTURED part, not a bought-in line — even if it also carries a 'bought_in'
        # page-role. Such parts must never be collapsed by the bought-in description dedup
        # (which caused distinct GRAPHIC CHANNEL parts to be merged by token overlap).
        _gs = str(p.get("geometry_source") or "").lower()
        if "dxf" in _gs or p.get("dxf_augmented") or p.get("dxf_source_file"):
            return True
        import re as _re
        _pn = str(p.get("part_number") or "").upper()
        if _re.match(r"^\\d{4,5}-\\d{2}-\\d{2,3}[A-Z]?$", _pn) and (
            p.get("blank_length_mm") or p.get("overall_length_mm")
            or (p.get("dxf_raw_geometry") or {}).get("blank_area_mm2")
        ):
            return True
        return False

    def _is_bought_in(p: Dict[str, Any]) -> bool:
        if _is_fabricated_part(p):
            return False
        roles = p.get("page_roles") or []
        return "bought_in" in roles or str(p.get("source") or "") in _BOUGHT_IN_SOURCE_RANK'''

src = TARGET.read_text(encoding="utf-8")
if ANCHOR not in src:
    print("REFUSED: anchor not found exactly. Paste the _is_bought_in def (~line 3149) so I can re-key.")
    raise SystemExit(1)
if src.count(ANCHOR) != 1:
    print(f"REFUSED: anchor found {src.count(ANCHOR)} times (need 1).")
    raise SystemExit(1)
src = src.replace(ANCHOR, REPLACEMENT)
TARGET.write_text(src, encoding="utf-8")
print("APPLIED: fabricated-part guard added to _reconcile_bought_in._is_bought_in.")
print("Fingerprint:")
print('  Select-String -Path C:\\ClaudeVision\\src\\estimator.py -Pattern "_is_fabricated_part"')
