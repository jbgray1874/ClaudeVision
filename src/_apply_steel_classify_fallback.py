#!/usr/bin/env python3
r"""
_apply_steel_classify_fallback.py

PROBLEM (12532): 12532-04-01G — a real 1.2mm MILD STEEL laser part with a DXF, blank
2106 x 1378mm — was SILENTLY DROPPED ("unclassifiable ... skipped"). Root cause: the
part_estimates record wb_populate classifies has normalized_material=None (the material
string doesn't survive into the stripped record, same as finish/textual_operations),
so rule 7's `_is_sheet_metal(mat)` test is False, and with stock_form=None / roles=None
the part matched no rule and fell to the else -> skipped. On a job with NO manual sheet,
a silent drop of a real steel part is the worst credibility failure.

The geometry, however, DOES survive into part_estimates:
    material_estimate.blank_length_mm = 2106.0
    material_estimate.blank_width_mm  = 1378.44
    normalized_thickness_mm           = 1.2
A part with blank length AND width AND a gauge is unambiguously a sheet-metal blank,
whatever the (missing) material string says.

FIX: broaden rule 7 so it ALSO catches a part with a full blank (L + W + thickness)
even when _is_sheet_metal(mat) is False because the material string is empty. This
recovers real steel parts without sweeping in:
  - junk (e.g. 'G-G' has no dimensions -> fails the L+W+thickness guard)
  - board parts   (rule 6 runs BEFORE rule 7)
  - bought-ins    (rule 5 runs BEFORE rule 7)
  - tubes         (rule 4 runs BEFORE rule 7; and tubes have no flat blank width)

Two edits:
  1. Read blank_w and thickness alongside blank_l (line ~305).
  2. Broaden rule 7's condition to accept a full-blank fallback.

Exact-string, asserted once each, backs up, idempotent. 1282 REGRESSION REQUIRED after.
"""
import shutil, sys, os, datetime

PATH = r"C:\ClaudeVision\src\wb_populate.py"

# ---- Edit 1: read blank_w + thickness next to blank_l ----
OLD_VARS = '        blank_l = _safe(me.get("blank_length_mm"))\n'
NEW_VARS = (
    '        blank_l = _safe(me.get("blank_length_mm"))\n'
    '        blank_w = _safe(me.get("blank_width_mm"))\n'
    '        thick_mm = _safe(pe.get("normalized_thickness_mm") or me.get("thickness_mm"))\n'
)

# ---- Edit 2: broaden rule 7 ----
OLD_RULE7 = (
    '        # 7. sheet metal with geometry but no stock_form set\n'
    '        elif _is_sheet_metal(mat) and blank_l is not None:\n'
    '            steel_parts.append(pe)\n'
)
NEW_RULE7 = (
    '        # 7. sheet metal with geometry but no stock_form set. Two ways to qualify:\n'
    '        #    (a) material string recognises as sheet metal, OR\n'
    '        #    (b) a FULL flat blank (length + width + gauge) even when the material\n'
    '        #        string did not survive into part_estimates (e.g. 12532-04-01G, a\n'
    '        #        1.2mm mild steel DXF part that classified with normalized_material=None).\n'
    '        #        Requiring all three of L+W+thickness keeps junk (no dims) and non-sheet\n'
    '        #        parts out; board(6)/bought-in(5)/tube(4) already matched above.\n'
    '        elif blank_l is not None and (\n'
    '            _is_sheet_metal(mat)\n'
    '            or (blank_w is not None and thick_mm is not None)\n'
    '        ):\n'
    '            if not _is_sheet_metal(mat):\n'
    '                _flag(f"recovered steel part {pe.get(\'part_number\')} via blank "\n'
    '                      f"geometry (L={blank_l} W={blank_w} t={thick_mm}mm) — material "\n'
    '                      f"string was empty in part_estimates; would previously have been "\n'
    '                      f"silently dropped.", flags)\n'
    '            steel_parts.append(pe)\n'
)


def main():
    if not os.path.exists(PATH):
        sys.exit(f"NOT FOUND: {PATH}")
    src = open(PATH, "r", encoding="utf-8").read()

    if "blank_w = _safe(me.get(" in src or "recovered steel part" in src:
        sys.exit("Already applied (found blank_w / recovered-steel). No change made.")

    for label, old in (("blank_l var", OLD_VARS), ("rule 7", OLD_RULE7)):
        n = src.count(old)
        if n != 1:
            sys.exit(f"ABORT: expected exactly 1 occurrence of the {label} block, found {n}. "
                     f"Source drifted — re-pull and re-anchor. No change made.")

    new = src.replace(OLD_VARS, NEW_VARS).replace(OLD_RULE7, NEW_RULE7)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{PATH}.bak_steelclassify_{ts}"
    shutil.copy2(PATH, bak)
    open(PATH, "w", encoding="utf-8").write(new)

    print("PATCHED:", PATH)
    print("backup :", bak)
    print("\n--- steel classification fallback installed ---")
    print("  rule 7 now also matches: full blank (L + W + gauge) with empty material string")
    print("  guard keeps out: junk (no dims), board/bought-in/tube (matched by earlier rules)")
    print("  a recovered part raises a flag so it's visible, not silent")
    print("\nEXPECT on 12532: 12532-04-01G no longer 'unclassifiable — skipped'; instead a")
    print("  'recovered steel part' flag, and it appears in the Sheet Steel block WITH a cost.")
    print("  (12532-03-GA 'CARD POCKET' may also recover if it has a full blank.)")
    print("\nREGRESSION GATE:")
    print("  - 1282 MUST still be £273.55 (the fallback must not sweep in any 1282 part)")
    print("  - 12532-04-01G must land in steel AND get a non-zero Cost Per Part")
    print("  - 'G-G' junk must STILL drop (no dimensions -> fails guard)")


if __name__ == "__main__":
    main()
