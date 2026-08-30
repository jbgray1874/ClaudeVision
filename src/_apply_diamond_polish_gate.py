#!/usr/bin/env python3
r"""
_apply_diamond_polish_gate.py

PROBLEM (12532): diamond_polish appears as a labour op on 4 parts (02-02M, 02-302,
03-05M, 03-201) — but ALL FOUR are POWDER COATED (Polyester Matt / Matt). A powder-
coated part is not diamond-polished; these finishes are mutually exclusive. The
diamond_polish is spurious (the 'CHROME PLATING - POLISHING' boilerplate in the general
notes misfiring into an operation). It currently costs £0 (not in OP_NAME_MAP), so it
does not inflate the total, but it is a visibly-wrong labour line — bad for credibility.

FIX: suppress diamond_polish in the labour loop when the part's drawing finish is
POWDER COATED. Powder and diamond-polish cannot coexist, so a powder finish is a
definitive signal the diamond_polish is spurious. This mirrors the powder gate exactly
(same loop, same reliable finish source: manufacturing_writeup.parts textual/finish).

Fail-safe: only POWDER finishes trigger suppression. A genuinely diamond-polished part
(no powder finish) keeps its diamond_polish. The acrylic riser 03-04A has 'POLISHED
EDGES' but carries NO diamond_polish op, so it is unaffected either way.

Reuses the _powder_ok / _mw_parts lookup already built for the powder gate: we add a
parallel {part_number -> is_powder_finish} check. Since _powder_ok is derived from
textual_operations (powder_coating present), and we need the FINISH here, we build a
small finish lookup from manufacturing_writeup.parts.

Two edits:
  1. Build a {part_number -> finish_is_powder} lookup next to the existing _powder_ok.
  2. In the op loop, skip 'diamond_polish' when the part's finish is powder.

Exact-string, asserted once each, backs up, idempotent. Regress 1282 + 12532 after.
"""
import shutil, sys, os, datetime

PATH = r"C:\ClaudeVision\src\wb_populate.py"

# ---- Edit 1: add finish-powder lookup next to the existing powder-ops lookup ----
# The powder gate added a block building _powder_ok from textual_operations. We anchor
# on that block's end (the 'for pe in labour_parts:' that follows) and insert a finish
# lookup just before it.
OLD_ANCHOR = (
    '        _powder_ok[_pn] = any("powder" in str(_o).lower() for _o in _tops)\n'
    '\n'
    '    for pe in labour_parts:\n'
)
NEW_ANCHOR = (
    '        _powder_ok[_pn] = any("powder" in str(_o).lower() for _o in _tops)\n'
    '\n'
    '    # Diamond-polish gate: diamond_polish is spurious on powder-coated parts\n'
    '    # (mutually exclusive finishes; boilerplate misfire). Build {pn -> finish is\n'
    '    # powder} from the fuller record\'s normalized_finish.\n'
    '    _finish_is_powder = {}\n'
    '    for _mp in _mw_parts:\n'
    '        _pn = str(_mp.get("part_number") or "")\n'
    '        _fin = str(_mp.get("normalized_finish") or "").upper()\n'
    '        _finish_is_powder[_pn] = "POWDER" in _fin\n'
    '\n'
    '    for pe in labour_parts:\n'
)

# ---- Edit 2: skip diamond_polish when finish is powder (place right after the powder skip) ----
OLD_SKIP = (
    '            if "powder" in str(op).lower():\n'
    '                _pn2 = str(pe.get("part_number") or "")\n'
    '                if _pn2 in _powder_ok and not _powder_ok[_pn2]:\n'
    '                    _flag(f"dropped powder on {_pn2} — drawing finish is not powder "\n'
    '                          f"(RAW/assembly/weldment); costs_gbp over-applied it.", flags)\n'
    '                    continue\n'
)
NEW_SKIP = (
    '            if "powder" in str(op).lower():\n'
    '                _pn2 = str(pe.get("part_number") or "")\n'
    '                if _pn2 in _powder_ok and not _powder_ok[_pn2]:\n'
    '                    _flag(f"dropped powder on {_pn2} — drawing finish is not powder "\n'
    '                          f"(RAW/assembly/weldment); costs_gbp over-applied it.", flags)\n'
    '                    continue\n'
    '            # Diamond-polish gate: suppress diamond_polish on powder-coated parts —\n'
    '            # the finishes are mutually exclusive, so it is a spurious boilerplate op.\n'
    '            if "diamond" in str(op).lower() or ("polish" in str(op).lower() and "edge" not in str(op).lower()):\n'
    '                _pn3 = str(pe.get("part_number") or "")\n'
    '                if _finish_is_powder.get(_pn3):\n'
    '                    _flag(f"dropped diamond_polish on {_pn3} — part is POWDER COATED "\n'
    '                          f"(diamond-polish is spurious/boilerplate on a powder finish).", flags)\n'
    '                    continue\n'
)


def main():
    if not os.path.exists(PATH):
        sys.exit(f"NOT FOUND: {PATH}")
    src = open(PATH, "r", encoding="utf-8").read()

    if "_finish_is_powder" in src:
        sys.exit("Already applied (found _finish_is_powder). No change made.")

    # sanity: the powder gate must be present (we anchor on it)
    if "_powder_ok" not in src:
        sys.exit("ABORT: powder gate (_powder_ok) not found — this fix anchors on it. "
                 "Re-check wb_populate. No change made.")

    for label, old in (("powder-lookup anchor", OLD_ANCHOR), ("powder-skip block", OLD_SKIP)):
        n = src.count(old)
        if n != 1:
            sys.exit(f"ABORT: expected exactly 1 occurrence of the {label}, found {n}. "
                     f"Source drifted — re-pull and re-anchor. No change made.")

    new = src.replace(OLD_ANCHOR, NEW_ANCHOR).replace(OLD_SKIP, NEW_SKIP)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{PATH}.bak_diamondgate_{ts}"
    shutil.copy2(PATH, bak)
    open(PATH, "w", encoding="utf-8").write(new)

    print("PATCHED:", PATH)
    print("backup :", bak)
    print("\n--- diamond_polish gate installed ---")
    print("  lookup: manufacturing_writeup.parts[*].normalized_finish -> is_powder")
    print("  loop  : skip diamond_polish when the part's finish is POWDER COATED")
    print("  fail-safe: non-powder parts keep diamond_polish; 'edge' polish not matched")
    print("\nEXPECT on 12532: 4 'dropped diamond_polish' flags (02-02M, 02-302, 03-05M,")
    print("  03-201 — all powder-coated). The £0 diamond_polish lines disappear from the")
    print("  labour sheet. TOTAL UNCHANGED (they were £0).")
    print("\nREGRESSION GATE:")
    print("  - 1282 MUST still be £273.55 (1282 has no diamond_polish — pure safety check)")
    print("  - 12532 total UNCHANGED (~£427.14); the 4 diamond_polish lines gone")


if __name__ == "__main__":
    main()
