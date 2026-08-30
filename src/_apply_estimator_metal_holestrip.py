"""THE REAL FIX for hole_machining on metal parts — in the ESTIMATOR (the right place).

Root cause (proven via _hole_op_stage_trace.py): the WB labour block costs ops from the
estimator's op list (_part_ops -> textual_operations + inferred_operations). For a metal
part with holes, hole_machining sits in textual_operations, gets costed (-> GUIL £0.29),
and shows on the sheet — even though mfg_interp.routing already correctly drops it. The 3
prior fixes (extractor guard, document_builder Fix D) were on the wrong field/branch and
never affected the estimator's op list.

FIX: in estimator._estimate_part_labour (the region where ops are finalised, right where
the existing section/laser strip lives at ~line 1748), strip hole_machining + drilling from
BOTH the local `ops` (costing) AND part['textual_operations'] (displayed sheet), for
SHEET-METAL parts only. Metal holes are laser-cut (fold into laser); acrylic/board keeps
drilling (Tim's "Drill (Acrylic)"). Mirrors the proven section-strip pattern exactly.

SAFE: exact-string match-or-refuse. Uses _mat_u and _SHEET_METALS already defined a few
lines above (confirmed in scope). Inserts right after `_has_cut_op = ...`.

BEFORE APPLYING, confirm the anchor in live src:
  Select-String -Path C:\ClaudeVision\src\estimator.py -Pattern "_has_cut_op = any" -Context 0,3

Run from C:\ClaudeVision\src :
  C:\ClaudeVision\.venv\Scripts\python.exe _apply_estimator_metal_holestrip.py

AFTER: re-run 1298 (Operations should lose hole_machining/drilling, GUIL line gone,
total ~£3.08) AND 1282 (MUST stay £203.99 / labour £72.38 — full regression). Also good to
re-run once more on any acrylic part to confirm drilling is preserved there (1282's HEADER
LENS is acrylic — check it still routes correctly).
"""
from pathlib import Path

TARGET = Path(r"C:\ClaudeVision\src\estimator.py")

ANCHOR = '''    _has_cut_op = any(o in ops for o in _CUTTING_OPS)'''

INSERT = '''    _has_cut_op = any(o in ops for o in _CUTTING_OPS)

    # SDI Intelligence — metal holes are LASER-CUT, not a separate hole/drill op. Tim's
    # sheets have no metal hole op (only "Drill (Acrylic)"); job 1282 (all metal) carries
    # none. But a metal part with holes can arrive with a stale hole_machining/drilling in
    # textual_operations (from the note/geometry extractor), which then gets costed -> a
    # wrong Guillotine line on the sheet. Strip it from BOTH the costing ops and the part's
    # displayed textual_operations, for sheet-metal only. Acrylic/board KEEP drilling.
    if _mat_u in _SHEET_METALS:
        _metal_hole_ops = ("hole_machining", "drilling")
        ops = [o for o in ops if o not in _metal_hole_ops]
        if isinstance(part.get("textual_operations"), list):
            part["textual_operations"] = [
                o for o in part["textual_operations"] if o not in _metal_hole_ops
            ]
        if isinstance(part.get("inferred_operations"), list):
            part["inferred_operations"] = [
                o for o in part["inferred_operations"] if o not in _metal_hole_ops
            ]'''

src = TARGET.read_text(encoding="utf-8")

if "_metal_hole_ops = (\"hole_machining\", \"drilling\")" in src:
    print("ALREADY APPLIED — estimator metal hole-op strip already present.")
    raise SystemExit(0)

if ANCHOR not in src:
    print("NOT APPLIED — anchor '_has_cut_op = any(o in ops for o in _CUTTING_OPS)' not found verbatim.")
    print("Dump live src and paste back:")
    print(r'  Select-String -Path C:\ClaudeVision\src\estimator.py -Pattern "_has_cut_op = any" -Context 0,2')
    raise SystemExit(1)

if src.count(ANCHOR) > 1:
    print(f"NOT APPLIED — anchor appears {src.count(ANCHOR)} times, expected 1. Refusing to guess.")
    raise SystemExit(1)

TARGET.write_text(src.replace(ANCHOR, INSERT), encoding="utf-8")
print("APPLIED — estimator now strips hole_machining/drilling from metal parts' ops +")
print("textual_operations + inferred_operations (acrylic/board keep drilling).")
print("Fingerprint: Select-String estimator.py -Pattern '_metal_hole_ops = '")
print("Next: re-run 1298 (GUIL line gone, ~£3.08) AND 1282 (MUST stay £203.99 / labour £72.38).")
print("Also check 1282's HEADER LENS (acrylic) still routes correctly — drilling preserved for non-metal.")
