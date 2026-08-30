r"""
patch_fold_operation_inference.py — general, evidence-based fold OPERATION inference.

THE GAP: the Fold labour row is created only when "folding" is in a part's op list
(estimator.py:2150). Parts whose folds live in PDF callouts (UP/DOWN + angle) rather than
a DXF BENDLINES layer never get "folding" in textual_operations, so no Fold row — the
press-brake work is silently uncosted. (Verified: footbase parts with angles_deg=['90.00']
and fold_count_textual=4 were absent from both Fold groups on job 1282.)

THE FIX: just before the "if folding in ops" labour block, infer a Fold operation when the
part carries fold evidence and is press-foldable stock (sheet/board). Follows the SAME
pattern the file already uses to infer laser_cutting (2052) and punch (2082).

GENERAL / SCALABLE — keys on the evidence CLASS, never a part number:
  fold evidence = bends>0 OR angles_deg non-empty OR fold_count_textual>0 OR mf.bend_count>0
TUBE-GUARDED three ways: material must be SHEET_METAL/CUT_BOARD (a tube is a section, not
  sheet), _section_no_dxf excluded (bought-as-length + tubebent), and a tube carries no fold
  evidence anyway. Works with the line-1975 fix so `bends` already reflects PDF fold callouts.

Single insert, exact-match-or-refuse, one .bak.
"""
import sys, shutil, ast
from pathlib import Path

TARGET = Path(r"C:\ClaudeVision\src\estimator.py")

# anchor: the exact folding-labour line (verbatim from the live dump)
ANCHOR = '''    if "folding" in ops:
        rule = LABOUR_RULES["folding"]'''

INSERT = '''    # ---- Fold operation inference (general, evidence-based) ----------------------
    # A part folds if it carries fold evidence — PDF callouts (UP/DOWN + angle -> angles_deg
    # / fold_count_textual), a DXF BENDLINES bend count, or textual bend mentions — even when
    # the extractor did not emit "folding" in textual_operations (folds often live ONLY in the
    # PDF, not a DXF layer). Add the op so it is costed. Same shape as the laser/punch
    # inference above. Sheet metal / board ONLY: a tube is bent on a tubebender (its own op),
    # a bought section is not press-folded. Uses `bends` (already set from PDF fold evidence).
    if "folding" not in ops and (_mat_u in _SHEET_METALS or _mat_u in _CUT_BOARDS) and not _section_no_dxf:
        _fold_evidence = (
            (bends or 0) > 0
            or len(part.get("angles_deg") or []) > 0
            or int(part.get("fold_count_textual") or 0) > 0
            or int((part.get("manufacturing_features") or {}).get("bend_count") or 0) > 0
        )
        if _fold_evidence:
            ops = list(ops) + ["folding"]
            part.setdefault("inferred_operations", [])
            if "folding" not in part["inferred_operations"]:
                part["inferred_operations"].append("folding")

    if "folding" in ops:
        rule = LABOUR_RULES["folding"]'''

def main():
    if not TARGET.is_file():
        sys.exit(f"NOT FOUND: {TARGET}")
    src = TARGET.read_text(encoding="utf-8")

    if "Fold operation inference (general, evidence-based)" in src:
        sys.exit("Already patched (found fold-inference marker). No change made.")

    n = src.count(ANCHOR)
    if n != 1:
        sys.exit(f"REFUSE: anchor found {n} times (expected 1). Live bytes differ — no change written.")

    src2 = src.replace(ANCHOR, INSERT, 1)
    try:
        ast.parse(src2)
    except SyntaxError as e:
        sys.exit(f"REFUSE: patched file does not parse: {e}")

    bak = TARGET.with_suffix(".py.bak_foldop")
    if not bak.exists():
        shutil.copy2(TARGET, bak)
    TARGET.write_text(src2, encoding="utf-8")
    print(f"PATCHED {TARGET}")
    print(f"  backup: {bak}")
    print("  inserted evidence-based fold-op inference before the folding labour block (line ~2150)")
    print("  general: keys on angles_deg / fold_count_textual / bend_count / bends — no part numbers")
    print("  tube-guarded: SHEET_METAL/CUT_BOARD only, _section_no_dxf excluded, no evidence on tubes")
    print("  VERIFY BY EFFECT: 3886-02/03 should now appear in a Fold labour row; total rises.")

if __name__ == "__main__":
    main()
