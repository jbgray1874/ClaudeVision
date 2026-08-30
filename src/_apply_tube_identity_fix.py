# -*- coding: utf-8 -*-
"""FIX: tube BOM line shows THIS part's identity, not a borrowed catalogue neighbour's.

Root cause (PROVEN): wb_populate.py:368-372 builds the tube BOM line preferring
se.catalogue_description / se.catalogue_part_code over the part's own. For 12532-02-08M CROSS RAIL,
the catalogue section-match borrowed job 11406's tube (TUBE0173, "ITEM 1 - 11406-02-02M - 38.1 X
19.1 X 1.5MM @798MM - LASER TUBE") because this tube's own dims weren't extracted — so the sheet
shows ANOTHER JOB'S part number. Embarrassing + misleading to an estimator.

FIX (2a, identity): prefer THIS part's own number + description for the DISPLAYED line and code.
Keep the catalogue match for PRICE only. Preserve the useful size info from the catalogue
description by appending it as a parenthetical REFERENCE (not as the identity), so the line reads
e.g. "12532-02-08M CROSS RAIL (cat ref: 38.1 X 19.1 X 1.5MM @798MM)". Non-tube bought-ins
(fixings/vinyl/electricals) have no catalogue_description -> unchanged.

NOTE (2b, deferred): the price is still the catalogue neighbour's (798mm tube applied to this
720mm tube). Accurate length-based pricing needs this tube's real dims extracted from page 11 BOM
(garbled thickness) — that's the tube-geometry task, roadmapped separately. This fix corrects the
IDENTITY now (the visibly-wrong part), price stays a flagged catalogue approximation.

SAFE: exact-string match-or-refuse on the desc/code build. Regression: 1282's tubes
(SLOTTEDTUBE01/02) have their OWN catalogue identity that IS this job's — but they're priced via
their own part records, and this change prefers the part's own number+desc which for 1282 is
correct (SLOTTED TUBE). Verify 1282 tube lines still read correctly after.

BEFORE APPLYING, confirm anchor:
  Select-String -Path C:\ClaudeVision\src\wb_populate.py -Pattern "prefer the catalogue description" -Context 1,5

Run from C:\ClaudeVision\src :
  C:\ClaudeVision\.venv\Scripts\python.exe _apply_tube_identity_fix.py

AFTER: re-run Recipe Card — the tube line should read "12532-02-08M  CROSS RAIL (cat ref: ...)"
NOT "ITEM 1 - 11406-02-02M ...". Then 1282: its SLOTTED TUBE lines must still read correctly.
"""
from pathlib import Path

TARGET = Path(r"C:\ClaudeVision\src\wb_populate.py")

ANCHOR = '''        # description: for tube sections, prefer the catalogue description (has size+length)
        desc = (se.get("catalogue_description")
                or pe.get("description")
                or pe.get("part_number"))
        # code: for tube, the catalogue part code; else the part number
        code = se.get("catalogue_part_code") or pe.get("part_number")'''

REPLACEMENT = '''        # description: prefer THIS part's OWN identity (number + description). The catalogue
        # section-match can borrow a *different job's* tube row (e.g. 11406-02-02M / TUBE0173) when
        # this tube's own dims weren't extracted — showing another job's part number is misleading.
        # Keep the catalogue's size text only as a parenthetical REFERENCE, never as the identity.
        _own_pn = pe.get("part_number")
        _own_desc = pe.get("description")
        _cat_desc = se.get("catalogue_description")
        if _own_pn or _own_desc:
            desc = f"{_own_pn or ''}  {_own_desc or ''}".strip()
            # append catalogue size ref (helpful for tubes) without borrowing the foreign identity
            if _cat_desc and se.get("catalogue_part_code"):
                # strip any leading "ITEM n - <foreign pn> - " so only the size/length remains
                import re as _re
                _size = _re.sub(r"^\\s*ITEM\\s*\\d+\\s*-\\s*[\\w-]+\\s*-\\s*", "", str(_cat_desc)).strip()
                _size = _re.sub(r"\\s*-\\s*LASER TUBE\\s*$", "", _size, flags=_re.I).strip()
                if _size:
                    desc = f"{desc} (cat ref: {_size})"
        else:
            desc = _cat_desc or _own_pn
        # code: THIS part's own number; fall back to catalogue code only if the part has none
        code = _own_pn or se.get("catalogue_part_code")'''

src = TARGET.read_text(encoding="utf-8")
if ANCHOR not in src:
    print("REFUSED: anchor not found exactly. Paste wb_populate.py ~line 367-372 so I can re-key.")
    raise SystemExit(1)
if src.count(ANCHOR) != 1:
    print(f"REFUSED: anchor found {src.count(ANCHOR)} times (need 1).")
    raise SystemExit(1)
src = src.replace(ANCHOR, REPLACEMENT)
TARGET.write_text(src, encoding="utf-8")
print("APPLIED: tube BOM line now shows THIS part's identity; catalogue size kept as (cat ref: ...).")
print("Fingerprint:")
print('  Select-String -Path C:\\ClaudeVision\\src\\wb_populate.py -Pattern "cat ref:"')
