#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
_apply_phantom_steel_guard.py  — structural guard in wb_populate.py so a part with
NO gauge AND NO geometry AND NO DXF (an empty detail/callout artefact like 'D-M4')
is EXCLUDED from the Sheet Steel block (kills the blank-gauge #DIV/0!) AND from the
labour groups (drops its phantom Fold/Laser/Weld). Catches it by its EMPTINESS at
the workbook layer — independent of how it entered upstream.

THREE exact-string-replace edits:
  1. Init `_skip_pns = set()` next to `_steel_row_by_pn = {}` (line ~759).
  2. Steel loop: right after `me`/`ng` are read (line ~781-782), detect the empty
     phantom, flag it, and `continue` (skip its steel row + record its part_number).
  3. Labour loop: right after `for pe in labour_parts:` (line ~1195), skip any part
     whose number is in `_skip_pns`.

Safe: uses the SAME `_safe()` + field names the loops already use. The 7 real
12120 parts all have gauge+geometry+DXF, so they can't be caught. Makes a .bak,
verifies each edit landed, idempotent.

Run (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _apply_phantom_steel_guard.py
"""
from __future__ import annotations
import shutil
from pathlib import Path

TARGET = Path("wb_populate.py")

# ── Edit 1: init the skip-set next to _steel_row_by_pn ───────────────────────
OLD1 = "    _steel_row_by_pn = {}\n"
NEW1 = ("    _steel_row_by_pn = {}\n"
        "    # Parts excluded from fabrication (empty detail/callout artefacts): keep them\n"
        "    # out of the Sheet Steel block (blank gauge -> #DIV/0!) AND the labour groups.\n"
        "    _skip_pns = set()\n")

# ── Edit 2: steel-loop guard, anchored to the me/ng read at the loop top ──────
OLD2 = ("        me = pe.get(\"material_estimate\") or {}\n"
        "        ng = pe.get(\"normalized_geometry\") or {}\n"
        "        length = _safe(me.get(\"blank_length_mm\") or ng.get(\"blank_length_mm\"))\n"
        "        width  = _safe(me.get(\"blank_width_mm\")  or ng.get(\"blank_width_mm\"))\n"
        "        gauge  = _safe(pe.get(\"normalized_thickness_mm\") or me.get(\"thickness_mm\"))\n")
NEW2 = ("        me = pe.get(\"material_estimate\") or {}\n"
        "        ng = pe.get(\"normalized_geometry\") or {}\n"
        "        # Guard: an empty detail/callout artefact (no gauge, no geometry, no DXF)\n"
        "        # is not a fabricatable steel part. It must not reach the Sheet Steel cost\n"
        "        # row (blank gauge -> #DIV/0!). Skip it here and record it so the labour\n"
        "        # loop drops its phantom ops too. Catches e.g. 'D-M4' regardless of how it\n"
        "        # entered the part-estimate flow (upstream false-part filter missed it).\n"
        "        _pn_g = str(pe.get(\"part_number\") or \"\")\n"
        "        _len_g = _safe(me.get(\"blank_length_mm\") or ng.get(\"blank_length_mm\"))\n"
        "        _wid_g = _safe(me.get(\"blank_width_mm\")  or ng.get(\"blank_width_mm\"))\n"
        "        _gau_g = _safe(pe.get(\"normalized_thickness_mm\") or me.get(\"thickness_mm\"))\n"
        "        _dxf_g = (pe.get(\"geometry_source\") == \"dxf_flat_pattern\")\n"
        "        if (not _gau_g) and (not _len_g) and (not _wid_g) and (not _dxf_g):\n"
        "            _skip_pns.add(_pn_g)\n"
        "            _flag(\"excluded non-fabricatable part '\" + _pn_g + \"' from Sheet Steel \"\n"
        "                  \"(no gauge, no geometry, no DXF) - detail/callout artefact, \"\n"
        "                  \"estimator to verify\", flags)\n"
        "            continue\n"
        "        length = _safe(me.get(\"blank_length_mm\") or ng.get(\"blank_length_mm\"))\n"
        "        width  = _safe(me.get(\"blank_width_mm\")  or ng.get(\"blank_width_mm\"))\n"
        "        gauge  = _safe(pe.get(\"normalized_thickness_mm\") or me.get(\"thickness_mm\"))\n")

# ── Edit 3: labour-loop skip, anchored to the loop opener + first body line ───
OLD3 = ("    for pe in labour_parts:\n"
        "        le = pe.get(\"labour_estimate\") or {}\n")
NEW3 = ("    for pe in labour_parts:\n"
        "        if str(pe.get(\"part_number\") or \"\") in _skip_pns:\n"
        "            continue   # phantom excluded from Sheet Steel — drop its ops too\n"
        "        le = pe.get(\"labour_estimate\") or {}\n")

def _apply(src, old, new, label):
    n = src.count(old)
    if new in src and old not in src:
        print(f"  [{label}] already applied.")
        return src, True
    if n == 0:
        print(f"  [{label}] ANCHOR NOT FOUND — live file differs. Stopping.")
        return src, False
    if n > 1:
        print(f"  [{label}] anchor found {n}x (expected 1) — stopping to avoid a wrong edit.")
        return src, False
    print(f"  [{label}] applied (1 match).")
    return src.replace(old, new), True

def main():
    if not TARGET.exists():
        raise SystemExit(f"Not found: {TARGET.resolve()} (run from C:\\ClaudeVision\\src)")
    src = TARGET.read_text(encoding="utf-8")
    orig = src

    print("Applying phantom-steel guard (3 edits):")
    ok_all = True
    for old, new, label in ((OLD1, NEW1, "init _skip_pns"),
                            (OLD2, NEW2, "steel-loop guard"),
                            (OLD3, NEW3, "labour-loop skip")):
        src, ok = _apply(src, old, new, label)
        ok_all = ok_all and ok

    if not ok_all:
        print("\nOne or more anchors failed. NO changes written. "
              "Paste the exact lines around 759 / 781-785 / 1195-1196 so I can re-target.")
        return

    if src == orig:
        print("\nAll edits already present — nothing to write.")
        return

    bak = TARGET.with_suffix(".py.bak_phantomguard")
    shutil.copy2(TARGET, bak)
    TARGET.write_text(src, encoding="utf-8")

    back = TARGET.read_text(encoding="utf-8")
    checks = ("_skip_pns = set()" in back,
              "excluded non-fabricatable part" in back,
              "phantom excluded from Sheet Steel" in back)
    if all(checks):
        print(f"\nPATCHED wb_populate.py (backup: {bak.name}).")
        print("Re-run 12120. Expect:")
        print("  - D-M4 GONE from Sheet Steel -> #DIV/0! cleared, 7 parts compute")
        print("  - D-M4 GONE from labour -> Weld line becomes (12120-01-101) only")
        print("  - a flag: \"excluded non-fabricatable part 'D-M4' ...\"")
    else:
        shutil.copy2(bak, TARGET)
        raise SystemExit(f"Verification failed {checks} — restored from backup. No change.")

if __name__ == "__main__":
    main()
