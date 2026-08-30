#!/usr/bin/env python3
r"""
_apply_widened_template_map.py

WHAT THIS FIXES
---------------
The BOM block held 15 rows. Job 1282 produces 16 bought-in parts. The 16th — LED Downlights,
£26.00 (£27.04 with scrap) — was SILENTLY DROPPED behind flag #2 of 18:

    [wb_populate] BOM overflow: 16 BOM/tube parts but only 15 rows — extra parts DROPPED.

That was the entire "£28 mystery" on the regression anchor. Not price drift, not the phantom
guards. One part, thrown away, with a warning nobody read.

The template has now been widened IN EXCEL (BOM 15 -> 40 rows). Excel re-pointed every
formula and LOOKUP range automatically. VERIFIED against the saved template:

    M92 = SUM(M11:M50) + SUM(M53:M60) + SUM(M63:M81) + SUM(M84:M91) + AF83
            BOM 40        Wire 8         Steel 19       Other 8        Powder

This script re-points CELL_MAP to the MEASURED new rows, and makes overflow LOUD.

CHANGES
-------
 1. CELL_MAP row bounds, all +25 below the BOM block:
        BOM    11..25  ->  11..50   (15 -> 40 slots)
        wire   28..35  ->  53..60
        steel  38..56  ->  63..81
        other  59..66  ->  84..91
        labour 71..142 ->  96..167
 2. Powder rate cell AF57 -> AF82 (AF58 -> AF83 in comments).
 3. BOM overflow now RAISES instead of dropping parts.
       An estimate that will not build is recoverable.
       An estimate that is quietly £27 light goes out the door.
    Set STRICT_BOM_OVERFLOW = False in wb_populate.py to revert to the old flag-and-drop.
 4. NEW: a load-time consistency check. wb_populate reads M92's own formula and asserts the
    BOM range agrees with CELL_MAP. If the estimators re-shape the template again, the code
    says so IMMEDIATELY instead of writing into the wrong rows. The template stays the single
    source of truth. (Non-fatal if the formula cannot be parsed — falls back to constants.)

Usage (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _apply_widened_template_map.py
"""
from __future__ import annotations
import shutil, sys, datetime, os

TARGET = r"C:\ClaudeVision\src\wb_populate.py"
SENTINEL = "_CELLMAP_WIDENED_BOM40"


def sub(src: str, old: str, new: str, label: str) -> str:
    n = src.count(old)
    if n != 1:
        sys.exit(f"ABORT [{label}]: expected exactly 1 match, found {n}.\n"
                 f"Deployed file differs from what was probed. Nothing written.\n"
                 f"--- looked for ---\n{old}\n")
    print(f"  ok  {label}")
    return src.replace(old, new, 1)


def main():
    if not os.path.exists(TARGET):
        sys.exit(f"not found: {TARGET}")

    src = open(TARGET, "r", encoding="utf-8").read()

    if SENTINEL in src:
        sys.exit("Already applied (sentinel present). Nothing to do.")

    print("Patching CELL_MAP to the widened template...\n")

    # ---- 1. row bounds -------------------------------------------------------
    src = sub(src,
              '        "first_row": 11, "last_row": 25,          # 15 slots',
              '        "first_row": 11, "last_row": 50,          # 40 slots  '
              f'({SENTINEL}: was 11..25 = 15; widened in Excel 2026-07-13 after 1282 '
              'silently dropped its 16th BOM part)',
              "BOM 11..25 -> 11..50")

    src = sub(src,
              '        "first_row": 28, "last_row": 35,          # 8 slots',
              '        "first_row": 53, "last_row": 60,          # 8 slots (+25: BOM widened)',
              "wire 28..35 -> 53..60")

    src = sub(src,
              '        "first_row": 38, "last_row": 56,          # 19 slots (widened template 2026-07-09)',
              '        "first_row": 63, "last_row": 81,          # 19 slots (+25: BOM widened 2026-07-13)',
              "steel 38..56 -> 63..81")

    src = sub(src,
              '        "first_row": 59, "last_row": 66,          # 8 slots (shifted +8 for widened steel)',
              '        "first_row": 84, "last_row": 91,          # 8 slots (+25: BOM widened 2026-07-13)',
              "other 59..66 -> 84..91")

    src = sub(src,
              '        "first_row": 71, "last_row": 142,         # shifted +8 for widened steel; 72 slots',
              '        "first_row": 96, "last_row": 167,         # 72 slots (+25: BOM widened 2026-07-13)',
              "labour 71..142 -> 96..167")

    # ---- 2. powder cell AF57 -> AF82 ----------------------------------------
    src = sub(src,
              '            ws["AF57"] = float(_POWDER_COST_PER_KG)',
              '            ws["AF82"] = float(_POWDER_COST_PER_KG)',
              "powder rate cell AF57 -> AF82")

    src = sub(src,
              '    # Powder £/kg — write the code-controlled rate into the sheet (cell AF57),',
              '    # Powder £/kg — write the code-controlled rate into the sheet (cell AF82),',
              "powder comment AF57 -> AF82")

    src = sub(src,
              '    # overwriting the template\'s static default. AF58 (=AD57*AF57) then computes',
              '    # overwriting the template\'s static default. AF83 (=AD82*AF82) then computes',
              "powder comment AF58 -> AF83")

    # ---- 3. BOM overflow: raise, do not drop ---------------------------------
    old_bom = (
        '        if row > b["last_row"]:\n'
        '            _flag(f"BOM overflow: {len(bom_parts)} BOM/tube parts but only "\n'
        '                  f"{b[\'last_row\']-b[\'first_row\']+1} rows — extra parts DROPPED. Widen block.", flags)\n'
        '            break'
    )
    new_bom = (
        '        if row > b["last_row"]:\n'
        '            _n_rows = b["last_row"] - b["first_row"] + 1\n'
        '            _lost = [str(p.get("part_number") or p.get("description") or "?")\n'
        '                     for p in bom_parts[_n_rows:]]\n'
        '            _msg = (f"BOM overflow: {len(bom_parts)} BOM/tube parts but only {_n_rows} rows. "\n'
        '                    f"Would DROP: {\', \'.join(_lost)}. Widen the BOM block in the template.")\n'
        '            if STRICT_BOM_OVERFLOW:\n'
        '                # A dropped bought-in is pure lost money with no visual cue on the sheet.\n'
        '                # 1282 lost £27 of LED Downlights this way, behind a flag nobody read.\n'
        '                # Refuse to produce a quietly-short estimate.\n'
        '                raise RuntimeError("[wb_populate] " + _msg)\n'
        '            _flag(_msg + " — extra parts DROPPED.", flags)\n'
        '            break'
    )
    src = sub(src, old_bom, new_bom, "BOM overflow -> RuntimeError")

    # ---- 4. strict flag + template consistency check --------------------------
    src = sub(src,
              'CELL_MAP = {',
              '# Refuse to emit an estimate that has silently dropped bought-in parts.\n'
              '# Set False to revert to the old flag-and-drop behaviour.\n'
              'STRICT_BOM_OVERFLOW = True\n'
              '\n'
              'CELL_MAP = {',
              "STRICT_BOM_OVERFLOW flag")

    helper = '''

def _verify_template_matches_cellmap(ws, cm, flags=None):
    """The template is the single source of truth for its own layout.

    M92 (Total Material Cost) sums every material block:
        =(SUM(M11:M50)+SUM(M53:M60)+SUM(M63:M81)+SUM(M84:M91)+AF83)
    Read it back and check CELL_MAP agrees. If the estimators re-shape the sheet again,
    we find out HERE — not by writing into merged header cells, and not by silently
    truncating a block.

    Non-fatal if the formula cannot be found or parsed: we fall back to the constants.
    """
    import re as _re
    try:
        f = ws["M92"].value
        if not isinstance(f, str) or "SUM(" not in f:
            return
        spans = _re.findall(r"SUM\\(M(\\d+):M(\\d+)\\)", f)
        if not spans:
            return
        found = {int(a): int(b) for a, b in spans}
        for key in ("bom", "wire", "steel", "other_sheet"):
            blk = cm.get(key)
            if not blk:
                continue
            fr, lr = blk["first_row"], blk["last_row"]
            if fr in found and found[fr] != lr:
                raise RuntimeError(
                    f"[wb_populate] TEMPLATE/CELL_MAP MISMATCH in '{key}': "
                    f"CELL_MAP says rows {fr}..{lr}, but the template's M92 formula sums "
                    f"M{fr}:M{found[fr]}. The template layout changed. "
                    f"Update CELL_MAP — do NOT run with a stale map."
                )
    except RuntimeError:
        raise
    except Exception:
        return  # never let the safety check itself break a run

'''
    src = sub(src,
              '\ndef _flag(',
              helper + '\ndef _flag(',
              "template consistency helper")

    # wire the check in right after the worksheet is resolved
    src = sub(src,
              '    ws = wb[cm["estimate_sheet"]]',
              '    ws = wb[cm["estimate_sheet"]]\n'
              '    _verify_template_matches_cellmap(ws, cm, flags)',
              "call consistency check")

    # ---- write ---------------------------------------------------------------
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{TARGET}.bak_cellmap_bom40_{ts}"
    shutil.copy2(TARGET, bak)
    open(TARGET, "w", encoding="utf-8").write(src)

    print(f"\n  backup: {bak}")
    print(f"  written: {TARGET}")
    print("""
NEXT — regress the anchor:

    Get-Process EXCEL -ErrorAction SilentlyContinue | Stop-Process -Force
    $env:ESTIMATE_DEFAULT_JOB_QUANTITY="10"
    C:\\ClaudeVision\\.venv\\Scripts\\python.exe -u main.py --search-root "<1282 folder>" --folder-as-job

EXPECT:
  * NO "BOM overflow" flag
  * 16 BOM lines, INCLUDING BI-LEDDOWNLIGHTS £26.00
  * D6 = 10  (verify before comparing — the env var is a known footgun)
  * AF82 = 9.73
  * Unit Cost ~ £278  (£250.64 + ~£27.04 downlights)

If it raises TEMPLATE/CELL_MAP MISMATCH, the template is not what we measured — stop and
re-probe rather than forcing it.
""")


if __name__ == "__main__":
    main()
