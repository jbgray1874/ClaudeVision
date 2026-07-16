# -*- coding: utf-8 -*-
"""FIX: suppress the nameless phantom part (page 21 SECTION G-G view of BACK WALL 12532-03-06M).

Root cause (PROVEN via _probe_phantom_part.py): the engine created a part record with
part_number=None AND description=None from a SECTION G-G detail VIEW on page 21 — which is a view
of the already-costed BACK WALL (12532-03-06M), not a separate part. It survives _is_estimable_part
because the final `return has_part_number or has_material or has_dims or has_ops` is rescued by its
incidental geometry (has_dims/has_ops True). It then shows on the BOM as a bare "None" line (£0.42).

FIX: at the TOP of _is_estimable_part, return False for a NAMELESS part — part_number empty/None
AND description empty/None. A genuine fabricated part always has at least a part number; only the
phantom is nameless. PROVEN safe: the probe confirmed exactly ONE nameless part (the phantom) and
that "has a section callout" is NOT the signal (real part 03-03M also has one) — so we key purely
on namelessness, which touches no real part.

SAFE: exact-string match-or-refuse on the docstring+first line of _is_estimable_part. Regression:
every real part on 1282/1298/Recipe Card has a part_number -> unaffected.

BEFORE APPLYING, confirm anchor:
  Select-String -Path C:\ClaudeVision\src\estimator.py -Pattern "Return False for junk parts" -Context 0,3

Run from C:\ClaudeVision\src :
  C:\ClaudeVision\.venv\Scripts\python.exe _apply_phantom_suppress.py

AFTER: re-run Recipe Card — the "Part: None / Description: None" record should be GONE (no bare
'None' BOM line). part_estimates drops by 1. 1282 unaffected (all parts named).
"""
from pathlib import Path

TARGET = Path(r"C:\ClaudeVision\src\estimator.py")

ANCHOR = '''    def _is_estimable_part(p: Dict[str, Any]) -> bool:
        """Return False for junk parts that have no meaningful content to estimate."""
        # Suppress GA/SA overview parts with no DXF geometry'''

REPLACEMENT = '''    def _is_estimable_part(p: Dict[str, Any]) -> bool:
        """Return False for junk parts that have no meaningful content to estimate."""
        # Suppress NAMELESS phantom parts: part_number AND description both empty/None. These arise
        # from SECTION/DETAIL callouts (e.g. page-21 SECTION G-G is a view of BACK WALL 12532-03-06M,
        # already costed) that the extractor turned into a separate record with no identity. A real
        # fabricated part always has at least a part number, so keying on namelessness suppresses
        # only the phantom (proven: exactly one nameless record; 'has section callout' is NOT safe
        # to key on because real parts also carry section views). Must run BEFORE the has_dims/has_ops
        # rescue below, since the phantom carries incidental geometry that would otherwise keep it.
        _pn_raw = str(p.get("part_number") or "").strip()
        _desc_raw = str(p.get("description") or "").strip()
        if _pn_raw in ("", "None") and _desc_raw in ("", "None"):
            return False
        # Suppress GA/SA overview parts with no DXF geometry'''

src = TARGET.read_text(encoding="utf-8")
if ANCHOR not in src:
    print("REFUSED: anchor not found exactly. Paste _is_estimable_part def so I can re-key.")
    raise SystemExit(1)
if src.count(ANCHOR) != 1:
    print(f"REFUSED: anchor found {src.count(ANCHOR)} times (need 1).")
    raise SystemExit(1)
src = src.replace(ANCHOR, REPLACEMENT)
TARGET.write_text(src, encoding="utf-8")
print("APPLIED: nameless-phantom guard added to _is_estimable_part (suppresses the page-21 'None' part).")
print("Fingerprint:")
print('  Select-String -Path C:\\ClaudeVision\\src\\estimator.py -Pattern "Suppress NAMELESS phantom"')
