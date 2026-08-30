r"""
patch_fold_shadowing.py  —  fix the fold-count shadowing bug in estimator.py line 1975.

BUG: bends = manufacturing_features.get("bend_count", max(angles, folds, textual))
     .get(k, default) returns the default ONLY if the key is ABSENT. But bend_count is
     PRESENT and 0 on parts whose folds come from PDF callouts (not a DXF BENDLINES layer),
     so the max(...) fallback is discarded and the fold evidence (angles_deg / fold_count_
     textual) is ignored. Result: 3886-03 has angles_deg=['90.00'], fold_count_textual=4,
     but bends=0 -> no Fold operation -> under-costed by one press-brake fold.

FIX: .get("bend_count", max(...))  ->  .get("bend_count") or max(...)
     A present-but-zero bend_count now falls through to the fold evidence.

Verified against real 1282 data:
  * 3886-03 (folds, PDF callouts):  0 -> 4   fold now captured
  * 1455-C-003 (DXF BENDLINES):     1 -> 1   unchanged
  * 1448-01 (tube, boilerplate):    0 -> 0   stays fold-free (no real evidence)
  * absent bend_count:              fallback path intact

NOT fixed here (logged separately): 3886-02's fold callouts live on detail pages that
don't name the part, so they were never attributed to it (empty angles_deg). That needs
cross-page fold attribution in the extractor — a different change.

Single edit, exact-match-or-refuse, one .bak.
"""
import sys, shutil, ast
from pathlib import Path

TARGET = Path(r"C:\ClaudeVision\src\estimator.py")

OLD = '    bends = manufacturing_features.get("bend_count", max(len(part.get("angles_deg", [])), len(part.get("fold_values_mm", [])), part.get("fold_count_textual", 0) or 0))'
NEW = '    bends = manufacturing_features.get("bend_count") or max(len(part.get("angles_deg", [])), len(part.get("fold_values_mm", [])), part.get("fold_count_textual", 0) or 0)  # fold-shadowing fix: present-but-zero bend_count falls through to PDF fold evidence (angles_deg/fold_count_textual), so parts folded from PDF callouts (no DXF BENDLINES layer) get their Fold op'

def main():
    if not TARGET.is_file():
        sys.exit(f"NOT FOUND: {TARGET}")
    src = TARGET.read_text(encoding="utf-8")

    if 'get("bend_count") or max(' in src:
        sys.exit("Already patched (found '.get(\"bend_count\") or max('). No change made.")

    n = src.count(OLD)
    if n != 1:
        sys.exit(f"REFUSE: anchor found {n} times (expected 1). Live bytes differ — no change written.")

    src2 = src.replace(OLD, NEW, 1)
    try:
        ast.parse(src2)
    except SyntaxError as e:
        sys.exit(f"REFUSE: patched file does not parse: {e}")

    bak = TARGET.with_suffix(".py.bak_foldfix")
    if not bak.exists():
        shutil.copy2(TARGET, bak)
    TARGET.write_text(src2, encoding="utf-8")
    print(f"PATCHED {TARGET}")
    print(f"  backup: {bak}")
    print("  line 1975: .get(\"bend_count\", max(...))  ->  .get(\"bend_count\") or max(...)")
    print("  effect: 3886-03 fold captured (0->4); BENDLINES parts + 1448 tube unchanged")
    print("  NEXT: re-run 1282. Expect a new Fold row covering 3886-03 (+ maybe 3886-02 if")
    print("        its data were present — it is NOT, so 3886-02 stays uncosted; logged).")

if __name__ == "__main__":
    main()
