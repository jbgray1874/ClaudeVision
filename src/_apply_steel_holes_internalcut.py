#!/usr/bin/env python3
r"""
_apply_steel_holes_internalcut.py

WHAT: Populate the two laser-calculator INPUT cells the engine currently leaves
blank on every steel row:
    S (col 19) = No of holes            <- estimated_hole_count (measured, DXF)
    T (col 20) = Internal Cutting Dist  <- derived: cut_length - 2*(length+width)

WHY: The Estimate sheet's Laser Rate Calculator computes Non-Profile cutting time
from S and T (U38 = T38/Q38 + S38). With S/T blank, internal cuts (holes, jigsaw,
notch) are invisible on the sheet. The values are already read from the drawing;
we were dropping them on the way to the workbook. This shows the engine's
drawing-reading work.

NOTE (honesty): this feeds the DISPLAY calculator. The charged laser cost is on a
separate (decoupled) path, so this does NOT change the £ — by design, agreed. It
makes the sheet read honestly.

DESIGN RULES (match JG's principle — honest gaps, never false precision):
  - holes: write ONLY if a positive int. 0/None -> leave BLANK ("not read", not a
    measured zero).
  - internal_cut: write ONLY if length, width AND cut_length are all present.
    value = max(0, cut_length - 2*(length+width)) rounded to 1dp. Else BLANK + flag.
  - internal_cut is DERIVED (bounding-perimeter subtraction, overshoots on complex
    profiles) — flagged as derived in the run flags, not presented as measured.
  - blank (not 0) is safe: WB U38=T38/Q38+S38 treats blank as 0, no #VALUE!.

Two edits, both exact-string, asserted once each. Backs up first. Idempotent.
"""
import shutil, sys, os, datetime

PATH = r"C:\ClaudeVision\src\wb_populate.py"

# ── Edit 1: add col_holes / col_internal_cut to the steel CELL_MAP ──
OLD_MAP = (
    '        "col_desc": 3, "col_qty": 5, "col_length": 6, "col_width": 7, "col_gauge": 8,\n'
    '        "col_sheet_l": 9, "col_sheet_w": 10,      # optional; WB defaults if blank\n'
)
NEW_MAP = (
    '        "col_desc": 3, "col_qty": 5, "col_length": 6, "col_width": 7, "col_gauge": 8,\n'
    '        "col_sheet_l": 9, "col_sheet_w": 10,      # optional; WB defaults if blank\n'
    '        "col_holes": 19, "col_internal_cut": 20,  # S/T: laser-calc inputs (No of holes / Internal Cutting Distance)\n'
)

# ── Edit 2: write S (holes) and T (internal cut) after the gauge write ──
OLD_WRITE = (
    '        ws.cell(row=row, column=s["col_gauge"],  value=gauge)\n'
    '        if not (length and width and gauge):\n'
    '            _flag(f"steel {pe.get(\'part_number\')} missing dim(s) "\n'
    '                  f"(L={length} W={width} G={gauge}) — WB cost will be 0/wrong.", flags)\n'
    '        row += 1\n'
)
NEW_WRITE = (
    '        ws.cell(row=row, column=s["col_gauge"],  value=gauge)\n'
    '        # Laser-calc inputs S (No of holes) and T (Internal Cutting Distance).\n'
    '        # Drawing-derived; feeds the sheet\'s laser calculator display. Honest gaps:\n'
    '        # blank (not 0) when not read, so a genuine no-hole part is not a false claim.\n'
    '        _geom = pe.get("geometry") or {}\n'
    '        _holes = _geom.get("estimated_hole_count")\n'
    '        if isinstance(_holes, (int, float)) and int(_holes) > 0:\n'
    '            ws.cell(row=row, column=s["col_holes"], value=int(_holes))\n'
    '        _cutlen = _safe(_geom.get("estimated_cut_length_mm"))\n'
    '        if length and width and _cutlen:\n'
    '            _internal = round(max(0.0, float(_cutlen) - 2.0 * (float(length) + float(width))), 1)\n'
    '            ws.cell(row=row, column=s["col_internal_cut"], value=_internal)\n'
    '            if _internal > 0:\n'
    '                _flag(f"steel {pe.get(\'part_number\')}: internal-cut T={_internal}mm is DERIVED "\n'
    '                      f"(cut_len {_cutlen} - bounding perim); overshoots on complex profiles.", flags)\n'
    '        elif _holes:\n'
    '            _flag(f"steel {pe.get(\'part_number\')}: {int(_holes or 0)} holes read but internal-cut T "\n'
    '                  f"not derivable (missing L/W/cut_len) — left blank, not 0.", flags)\n'
    '        if not (length and width and gauge):\n'
    '            _flag(f"steel {pe.get(\'part_number\')} missing dim(s) "\n'
    '                  f"(L={length} W={width} G={gauge}) — WB cost will be 0/wrong.", flags)\n'
    '        row += 1\n'
)


def main():
    if not os.path.exists(PATH):
        sys.exit(f"NOT FOUND: {PATH}")
    src = open(PATH, "r", encoding="utf-8").read()

    if '"col_holes"' in src or "col_internal_cut" in src:
        sys.exit("Already patched (found col_holes/col_internal_cut). No change made.")

    for label, old in (("CELL_MAP", OLD_MAP), ("steel-writer", OLD_WRITE)):
        n = src.count(old)
        if n != 1:
            sys.exit(f"ABORT: expected exactly 1 occurrence of the {label} block, found {n}. "
                     f"No change made — the source has drifted; re-pull the block.")

    new = src.replace(OLD_MAP, NEW_MAP).replace(OLD_WRITE, NEW_WRITE)

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{PATH}.bak_holesT_{ts}"
    shutil.copy2(PATH, bak)
    open(PATH, "w", encoding="utf-8").write(new)

    print("PATCHED:", PATH)
    print("backup :", bak)
    print("\n--- added ---")
    print('  CELL_MAP steel: col_holes=19 (S), col_internal_cut=20 (T)')
    print('  steel writer  : writes holes (if >0) to S, derived internal-cut to T (blank when unknown)')
    print("\nVerify:")
    print(r'  Select-String -Path C:\ClaudeVision\src\wb_populate.py -Pattern "col_holes|col_internal_cut|estimated_hole_count" -Context 0,1')


if __name__ == "__main__":
    main()
