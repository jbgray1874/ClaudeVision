# -*- coding: utf-8 -*-
"""FIX: stop _reconcile_bought_in merging the 3 distinct DISPLAY BOARDs into 1.

Root cause (PROVEN from code): the 3 boards have part numbers VINYL-668X200 / VINYL-668X1264 /
VINYL-150X1504 (DISTINCT) but descriptions sharing words (DISPLAY BOARD PROVISIONAL) AND a spurious
shared number 25 (from "£25/m²"). In _bought_in_same_item the number-guard only blocks a merge when
BOTH sides have numbers and they share NONE — but every board shares 25, so the guard never fires,
and the shared words satisfy containment -> all 3 collapse to 1 (2 boards dropped from the BOM).

The reconcile pass is DESIGNED for "same physical item found by two layers under different part
numbers" (cross-layer dupes). Two parts with DISTINCT, non-empty part numbers that ENCODE DIFFERENT
DIMENSIONS are demonstrably NOT the same item. FIX: guard at the top of _bought_in_same_item is not
enough (it only sees token sets); instead guard in the reconcile LOOP — before treating a line as a
duplicate, require that the candidate and the matched keep-line do NOT have two different, non-empty
part numbers. Same-identifier cross-layer dupes (the real target) usually differ in SOURCE not
part-number, or one lacks a pn; distinct real part numbers => keep both.

SAFE: exact-string match-or-refuse. Only PREVENTS merges between lines with two different explicit
part numbers — it never forces a merge. Legit cross-layer dupes (same item, one lacking a pn, or
same pn) still merge. Regression: 1282's bought-ins have distinct pns for distinct items -> now
correctly NOT merged (matches reality); items that were genuine dupes are unaffected if they share
a pn or one lacks one.

BEFORE APPLYING, confirm anchor:
  Select-String -Path C:\ClaudeVision\src\estimator.py -Pattern "Duplicate of an already-kept bought-in line" -Context 3,2

Run from C:\ClaudeVision\src :
  C:\ClaudeVision\.venv\Scripts\python.exe _apply_reconcile_partnum_guard.py

AFTER: re-run Recipe Card — all 3 DISPLAY BOARD lines should appear in the BOM (668x200, 668x1264,
150x1504), and console "[reconcile] N duplicate ... merged" should drop (fewer/zero board merges).
"""
from pathlib import Path

TARGET = Path(r"C:\ClaudeVision\src\estimator.py")

ANCHOR = '''        if match_idx is None:
            if toks is not None:
                kept_tokens.append((len(keep), toks))
            keep.append(p)
            continue
        # Duplicate of an already-kept bought-in line — keep the more-grounded source.
        existing = keep[match_idx]'''

REPLACEMENT = '''        # Guard: never merge two lines that carry DIFFERENT, non-empty part numbers. Distinct
        # part numbers = distinct items (e.g. VINYL-668X200 vs VINYL-668X1264 are different display
        # boards that only *look* similar because their descriptions share words + the spurious "25"
        # from "£25/m²"). The token-overlap merge is meant for the SAME item found under different
        # numbers by different layers, not for genuinely distinct catalogue lines.
        if match_idx is not None:
            _pn_new = str(p.get("part_number") or "").strip().upper()
            _pn_old = str(keep[match_idx].get("part_number") or "").strip().upper()
            if _pn_new and _pn_old and _pn_new != _pn_old:
                match_idx = None
        if match_idx is None:
            if toks is not None:
                kept_tokens.append((len(keep), toks))
            keep.append(p)
            continue
        # Duplicate of an already-kept bought-in line — keep the more-grounded source.
        existing = keep[match_idx]'''

src = TARGET.read_text(encoding="utf-8")
if ANCHOR not in src:
    print("REFUSED: anchor not found exactly. Paste the reconcile loop (estimator.py ~3160-3175) so I can re-key.")
    raise SystemExit(1)
if src.count(ANCHOR) != 1:
    print(f"REFUSED: anchor found {src.count(ANCHOR)} times (need 1).")
    raise SystemExit(1)
src = src.replace(ANCHOR, REPLACEMENT)
TARGET.write_text(src, encoding="utf-8")
print("APPLIED: reconcile no longer merges lines with different explicit part numbers (keeps all 3 boards).")
print("Fingerprint:")
print('  Select-String -Path C:\\ClaudeVision\\src\\estimator.py -Pattern "never merge two lines that carry DIFFERENT"')
