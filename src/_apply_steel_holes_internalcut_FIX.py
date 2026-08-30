#!/usr/bin/env python3
r"""
_apply_steel_holes_internalcut_FIX.py

The first holes/T patch read pe.get("geometry") — but there is NO "geometry" key
on the part record (confirmed by probe). So both writes silently skipped and
S38/T38 stayed blank.

The canonical, normalised geometry lives in pe["geometry_rollup"]:
    geometry_rollup.estimated_hole_count    = 2
    geometry_rollup.estimated_cut_length_mm = 1329.63   (matches every console readout)

This applier REPLACES the broken block (which read _geom = pe.get("geometry"))
with one that reads from geometry_rollup. Same honest-gap rules:
  - holes: write only if positive int, else blank (not 0)
  - internal_cut = max(0, cut_length - 2*(length+width)); write only if L/W/cut all
    present, else blank + flag; flagged as DERIVED.

Idempotent; asserts the broken block appears exactly once; backs up first.
Run this AFTER the first patch (it fixes that patch's block). If the first patch
was reverted, this still applies cleanly against the same anchor lines.
"""
import shutil, sys, os, datetime

PATH = r"C:\ClaudeVision\src\wb_populate.py"

# the BROKEN block written by the first applier (reads pe.get("geometry"))
OLD = (
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
)

# corrected: read from geometry_rollup (the canonical normalised block)
NEW = (
    '        # Laser-calc inputs S (No of holes) and T (Internal Cutting Distance).\n'
    '        # Drawing-derived; feeds the sheet\'s laser calculator display. Honest gaps:\n'
    '        # blank (not 0) when not read, so a genuine no-hole part is not a false claim.\n'
    '        # Canonical geometry lives in pe["geometry_rollup"] (NOT "geometry").\n'
    '        _geom = pe.get("geometry_rollup") or pe.get("normalized_geometry") or {}\n'
    '        _holes = _geom.get("estimated_hole_count")\n'
    '        if _holes is None:\n'
    '            _holes = _geom.get("hole_count")\n'
    '        if isinstance(_holes, (int, float)) and int(_holes) > 0:\n'
    '            ws.cell(row=row, column=s["col_holes"], value=int(_holes))\n'
    '        _cutlen = _safe(_geom.get("estimated_cut_length_mm") or _geom.get("cut_length_mm"))\n'
    '        if length and width and _cutlen:\n'
    '            _internal = round(max(0.0, float(_cutlen) - 2.0 * (float(length) + float(width))), 1)\n'
    '            ws.cell(row=row, column=s["col_internal_cut"], value=_internal)\n'
    '            if _internal > 0:\n'
    '                _flag(f"steel {pe.get(\'part_number\')}: internal-cut T={_internal}mm is DERIVED "\n'
    '                      f"(cut_len {_cutlen} - bounding perim); overshoots on complex profiles.", flags)\n'
    '        elif _holes:\n'
    '            _flag(f"steel {pe.get(\'part_number\')}: {int(_holes or 0)} holes read but internal-cut T "\n'
    '                  f"not derivable (missing L/W/cut_len) — left blank, not 0.", flags)\n'
)


def main():
    if not os.path.exists(PATH):
        sys.exit(f"NOT FOUND: {PATH}")
    src = open(PATH, "r", encoding="utf-8").read()

    if 'pe.get("geometry_rollup")' in src:
        sys.exit("Already fixed (reads geometry_rollup). No change made.")

    n = src.count(OLD)
    if n != 1:
        sys.exit(f"ABORT: expected exactly 1 occurrence of the broken block, found {n}. "
                 f"Was the first holes/T patch applied? If not, apply it first, or paste "
                 f"lines 442-460 so I can re-anchor. No change made.")

    new = src.replace(OLD, NEW)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{PATH}.bak_holesTfix_{ts}"
    shutil.copy2(PATH, bak)
    open(PATH, "w", encoding="utf-8").write(new)

    print("PATCHED:", PATH)
    print("backup :", bak)
    print("\n--- fix ---")
    print('  reads pe["geometry_rollup"].estimated_hole_count / estimated_cut_length_mm')
    print('  (was pe["geometry"] which does not exist -> was writing nothing)')
    print("\nVerify: re-run 1300, then dump S38/T38.")


if __name__ == "__main__":
    main()
