r"""
Patch: family-aware distinct-part-number guard in estimator._reconcile_bought_in.

The existing guard cancels ANY merge between two lines with different non-empty part
numbers. That correctly stops VINYL-668X200 / VINYL-668X1264 (real distinct display
boards) merging on token overlap -- but it ALSO blocks the legitimate cross-layer
duplicate this pass exists for: the same physical item found by two layers under
different identifier schemes (the loom -- "ELECTRICS 50CM" from the drawing BOM vs
"BI-50CMLOOM" from the note-scan). Result on 1282: the loom stayed duplicated even
after it was correctly routed into the reconciler.

Fix: cancel the merge only when the two codes are genuinely distinct catalogue lines --
same alphabetic family prefix (VINYL/VINYL), OR both numeric-style SDI codes. When the
families differ and at least one is alphabetic (ELECTRICS vs BI), allow the merge.

Exact-string match-or-refuse + ast.parse before write.
Run:  C:\\ClaudeVision\\.venv\\Scripts\\python.exe patch_boughtin_family_guard.py
"""
import pathlib

SRC = pathlib.Path(r"C:\ClaudeVision\src\estimator.py")

ANCHOR = '        if match_idx is not None:\n            _pn_new = str(p.get("part_number") or "").strip().upper()\n            _pn_old = str(keep[match_idx].get("part_number") or "").strip().upper()\n            if _pn_new and _pn_old and _pn_new != _pn_old:\n                match_idx = None\n'

REPLACEMENT = '        if match_idx is not None:\n            _pn_new = str(p.get("part_number") or "").strip().upper()\n            _pn_old = str(keep[match_idx].get("part_number") or "").strip().upper()\n            if _pn_new and _pn_old and _pn_new != _pn_old:\n                # Cancel the merge only when the two codes are genuinely DISTINCT catalogue\n                # lines, not the same physical item found by two layers under different\n                # identifiers. Distinct = same alphabetic family differing in detail\n                # (VINYL-668X200 vs VINYL-668X1264 — real different boards), OR both\n                # numeric-style SDI codes. DIFFERENT identifier schemes for one item\n                # (ELECTRICS 50CM vs BI-50CMLOOM — a described BOM commodity vs its\n                # catalogue code) SHOULD still merge: that is the cross-layer duplicate\n                # this pass exists to catch.\n                import re as _re_fam\n                _fam_new = (_re_fam.match(r"[A-Za-z]+", _pn_new) or [None])\n                _fam_new = _fam_new.group(0) if hasattr(_fam_new, "group") else ""\n                _fam_old = (_re_fam.match(r"[A-Za-z]+", _pn_old) or [None])\n                _fam_old = _fam_old.group(0) if hasattr(_fam_old, "group") else ""\n                _same_family = bool(_fam_new and _fam_old and _fam_new == _fam_old)\n                _both_numeric = (not _fam_new) and (not _fam_old)\n                if _same_family or _both_numeric:\n                    match_idx = None\n'


def run():
    src = SRC.read_text(encoding="utf-8")
    if "_same_family" in src:
        print("ABORT: family guard already present -- nothing changed.")
        return
    if src.count(ANCHOR) != 1:
        print(f"ABORT: anchor found {src.count(ANCHOR)} times (need exactly 1). Nothing changed.")
        return
    src2 = src.replace(ANCHOR, REPLACEMENT, 1)
    import ast
    try:
        ast.parse(src2)
    except SyntaxError as e:
        print(f"ABORT: patched result failed syntax check ({e}). Nothing written.")
        return
    SRC.write_text(src2, encoding="utf-8")
    print("OK: family-aware bought-in merge guard installed.")
    print()
    print("RE-RUN flag ON -- expect the loom to FINALLY fold:")
    print(r'  $env:SDI_DUALPATH_BOM="1"')
    print(r'  C:\ClaudeVision\.venv\Scripts\python.exe main.py --search-root "K:\Estimating\Completed\AI Estimating\Live Enquiry\1282 - Milwaukee Wall Bay" --folder-as-job')
    print("  1) [reconcile] 1 duplicate bought-in line(s) merged  <- the line that was missing")
    print("  2) SINGLE loom: BI-50CMLOOM kept at 24.15, ELECTRICS 50CM gone; material down ~26.")
    print("  3) VINYL76 still its own line (family guard still protects distinct vinyls).")


if __name__ == "__main__":
    run()
