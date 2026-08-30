#!/usr/bin/env python3
r"""
_apply_cellmap_widened_steel.py

The master template was widened by hand in Excel: steel block grew from 11 rows
(38-48) to 19 rows (38-56). Excel correctly shifted everything below down by 8 and
auto-updated the total formula to =(SUM(M11:M25)+SUM(M28:M35)+SUM(M38:M56)+SUM(M59:M66)).

Confirmed new layout (read from the widened file):
    BOM         11-25   (unchanged, above steel)
    tube        28-35   (unchanged, above steel)
    steel       38-56   (was 38-48)               <- +8 rows
    other_sheet 59-66   (was 51-58)               <- shifted +8
    labour      71-142  (was 63-134)              <- shifted +8

This applier updates the wb_populate CELL_MAP first_row/last_row to match, so the
engine writes into the correct (shifted) rows. Columns are unchanged (row insert
does not move columns), so col_holes=19 / col_internal_cut=20 stay correct.

BOM and tube blocks are ABOVE the steel insert, so they DO NOT move — left as-is.

Three exact-string edits, each asserted to appear once. Backs up first. Idempotent.
Does NOT touch the template itself (already done in Excel) — only the CELL_MAP.
"""
import shutil, sys, os, datetime

PATH = r"C:\ClaudeVision\src\wb_populate.py"

# steel: 38-48 -> 38-56
OLD_STEEL = '        "first_row": 38, "last_row": 48,          # 11 slots'
NEW_STEEL = '        "first_row": 38, "last_row": 56,          # 19 slots (widened template 2026-07-09)'

# other_sheet: 51-58 -> 59-66  (shifted down by 8)
OLD_OTHER = '        "first_row": 51, "last_row": 58,          # 8 slots'
NEW_OTHER = '        "first_row": 59, "last_row": 66,          # 8 slots (shifted +8 for widened steel)'

# labour: 63-134 -> 71-142  (shifted down by 8)
OLD_LABOUR = '        "first_row": 63, "last_row": 134,         # widened block (was 102); 72 slots'
NEW_LABOUR = '        "first_row": 71, "last_row": 142,         # shifted +8 for widened steel; 72 slots'


def main():
    if not os.path.exists(PATH):
        sys.exit(f"NOT FOUND: {PATH}")
    src = open(PATH, "r", encoding="utf-8").read()

    if '"last_row": 56' in src:
        sys.exit("Already applied (steel last_row=56). No change made.")

    edits = [("steel", OLD_STEEL, NEW_STEEL),
             ("other_sheet", OLD_OTHER, NEW_OTHER),
             ("labour", OLD_LABOUR, NEW_LABOUR)]

    for label, old, _new in edits:
        n = src.count(old)
        if n != 1:
            sys.exit(f"ABORT: expected exactly 1 occurrence of the {label} line, found {n}. "
                     f"Source may have drifted — re-pull the CELL_MAP and re-anchor. No change made.\n"
                     f"  looking for: {old!r}")

    new = src
    for _label, old, rep in edits:
        new = new.replace(old, rep)

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{PATH}.bak_cellmap_widened_{ts}"
    shutil.copy2(PATH, bak)
    open(PATH, "w", encoding="utf-8").write(new)

    print("PATCHED:", PATH)
    print("backup :", bak)
    print("\n--- CELL_MAP now matches widened template ---")
    print("  steel       : 38-56  (19 rows, was 11)")
    print("  other_sheet : 59-66  (shifted +8)")
    print("  labour      : 71-142 (shifted +8)")
    print("  BOM 11-25 / tube 28-35 : unchanged (above steel insert)")
    print("  columns (holes=19, internal_cut=20) : unchanged")
    print("\nVerify:")
    print(r'  Select-String -Path C:\ClaudeVision\src\wb_populate.py -Pattern "first_row|last_row" -Context 0,0')
    print("\nThen REGRESSION (in order):")
    print("  1. Run 1282 -> MUST still total ~204.10 (anchor). Other-sheet part (acrylic lens)")
    print("     must land in new rows 59-66, labour in 71-142.")
    print("  2. Run 12532 -> previously-dropped ~9 steel parts should now populate rows 49-56;")
    print("     total should RISE to include their material (that is the fix, not a regression).")


if __name__ == "__main__":
    main()
