#!/usr/bin/env python3
r"""
_apply_board_material_guard.py

PROBLEM (12532): display boards (VINYL-668X200 / 668X1264 / 150X1504) show
normalized_material = MILD_STEEL, inherited from the assembly's document-level title
block (file_scan.py inheritance loop, lines 924-935). Their OWN drawings say
"MATERIAL: DISPLAY BOARD". They are COSTED correctly (£3.34 etc. via the display-board
recogniser, independent of this label), but the material LABEL is wrong. This is a
latent problem — a display board tagged MILD_STEEL would pollute the planned RAG/vector
corpus and any material-based routing/summary.

FIX: in the doc-level material inheritance loop, SKIP parts that are display boards —
identified by part_number starting 'VINYL-' OR description containing 'DISPLAY BOARD'.
Those parts should NOT inherit the assembly's steel material.

IMPORTANT — do NOT key on 'GRAPHIC': parts like 12532-02-07M 'LOWER GRAPHIC CHANNEL',
02-09M 'HEADER GRAPHIC CHANNEL', 02-10M 'GRAPHIC CHANNEL' are REAL MILD STEEL channels
and must keep their (correct) steel material. Only VINYL-/DISPLAY BOARD parts are boards.

Inserts a guard as the first check in the per-part loop body (after `for part in parts:`),
before the `existing = ...` line. Exact-string, asserted once, backs up, idempotent.

Cost impact: NONE (boards priced by recogniser, not this label). Deliverable impact:
NONE (sheet shows the description 'DISPLAY BOARD', not this field). This corrects the
internal label only. Regress 1282 (no boards -> must be unchanged) + 12532 (VINYL parts
no longer MILD_STEEL; total still £427.14).
"""
import shutil, sys, os, datetime

PATH = r"C:\ClaudeVision\src\file_scan.py"

OLD = (
    '    for part in parts:\n'
    '        existing = str(part.get("normalized_material") or "").strip()\n'
)
NEW = (
    '    for part in parts:\n'
    '        # Display boards (VINYL-* / DISPLAY BOARD) must NOT inherit the assembly\'s\n'
    '        # document-level material (typically MILD STEEL). They are printed boards,\n'
    '        # costed by the display-board recogniser. Skip inheritance for them.\n'
    '        # NOTE: do not key on "GRAPHIC" — "GRAPHIC CHANNEL" parts are real steel.\n'
    '        _pn_u = str(part.get("part_number") or "").upper()\n'
    '        _desc_u = str(part.get("description") or "").upper()\n'
    '        if _pn_u.startswith("VINYL-") or "DISPLAY BOARD" in _desc_u:\n'
    '            continue\n'
    '        existing = str(part.get("normalized_material") or "").strip()\n'
)


def main():
    if not os.path.exists(PATH):
        sys.exit(f"NOT FOUND: {PATH}")
    src = open(PATH, "r", encoding="utf-8").read()

    if 'startswith("VINYL-")' in src:
        sys.exit("Already applied (found VINYL- guard). No change made.")

    n = src.count(OLD)
    if n != 1:
        sys.exit(f"ABORT: expected exactly 1 occurrence of the loop-start block, found {n}. "
                 f"Source drifted — re-view file_scan.py around line 924. No change made.")

    new = src.replace(OLD, NEW)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{PATH}.bak_boardmatguard_{ts}"
    shutil.copy2(PATH, bak)
    open(PATH, "w", encoding="utf-8").write(new)

    print("PATCHED:", PATH)
    print("backup :", bak)
    print("\n--- board material guard installed (file_scan.py) ---")
    print("  skip doc-level material inheritance for VINYL-* / DISPLAY BOARD parts")
    print("  GRAPHIC CHANNEL steel parts unaffected (not keyed on 'GRAPHIC')")
    print("\nEXPECT on 12532: VINYL-668X200 / 668X1264 / 150X1504 no longer show")
    print("  normalized_material=MILD_STEEL (will be blank/own material instead).")
    print("  Their cost is UNCHANGED (£3.34 etc.). Total UNCHANGED (£427.14).")
    print("\nREGRESSION GATE:")
    print("  - 1282 MUST be £273.55 (no display boards -> guard never fires; safety check)")
    print("  - 12532 total UNCHANGED (£427.14); VINYL parts' material label corrected")
    print("  - GRAPHIC CHANNEL steel parts (02-07M/09M/10M) still MILD_STEEL")


if __name__ == "__main__":
    main()
