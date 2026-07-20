#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
_apply_fold_debug_strip.py — INSTRUMENT + strip 'folding' at the DXF-augment
convergence point (drawing_job_merge.py ~291, where part['dxf_augmented']=True).

WHY INSTRUMENT (not another blind patch):
  Four placement attempts have each self-tested-pass but left the run unchanged.
  Ground truth from the live JSON: 03M has geometry_source='dxf_flat_pattern'
  (so it DID enter the flat-pattern branch we patched) and operations_source=None
  (so the re-infer block never ran), yet 'folding' is STILL in its
  textual_operations. So either our strip code isn't executing, or 'folding' is
  (re)added AFTER augment_summary_with_dxf. A debug print at the convergence
  point will show, in the run log, EXACTLY which — no more inference.

This patch, at line 291 (hit by EVERY augmented part, after both geometry
branches):
  1. prints  [FOLD-DBG] <pn> gs=<geometry_source> bcx=<bend_count_dxf> ebl=<...>
             ops=<operations> txt=<textual_operations>
  2. if flat_pattern_detected AND the resolved DXF bend count is 0/None, strips
     'folding' from operations + textual_operations and prints
             [FOLD-DBG] STRIPPED folding from <pn>

Then re-run 12120 and read the [FOLD-DBG] lines for 03M:
  A. shows ops=[...folding...] then STRIPPED, and final JSON has no folding
     -> FIXED here (this is the right convergence point; remove debug later).
  B. shows ops=[...folding...] then STRIPPED, but final JSON STILL has folding
     -> 'folding' is re-added downstream of augment; the debug proves it and we
        trace the re-adder (file_scan pre-estimate norm / estimate_document).
  C. no [FOLD-DBG] line for 03M at all
     -> augment_summary_with_dxf isn't processing 03M's DXF via this path.

Resolved bend count = flat/DXF bend, read defensively from the fields the merge
sets: bend_count_dxf, else geometry_rollup.estimated_bend_line_count, else 0.
01M/08M (real bends) => count>0 => NOT stripped.

ONE exact-string edit. .bak. Idempotent. Verifies write. (Diagnostic build —
the print stays until we confirm behaviour, then a clean version removes it.)

Run (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _apply_fold_debug_strip.py
"""
from __future__ import annotations
import shutil
from pathlib import Path

TARGET = Path("drawing_job_merge.py")

# Anchor: the convergence lines 291-293 (from the live grep).
OLD = (
    "    part[\"dxf_augmented\"] = True\n"
    "    part[\"dxf_geometry_reliability\"] = reliability\n"
    "    part[\"dxf_raw_geometry\"] = dxf_raw\n"
)

NEW = (
    "    part[\"dxf_augmented\"] = True\n"
    "    part[\"dxf_geometry_reliability\"] = reliability\n"
    "    part[\"dxf_raw_geometry\"] = dxf_raw\n"
    "    # ── FOLD-DBG: instrument + DXF-flat fold strip at the convergence point ──\n"
    "    # Every augmented part reaches here, after both geometry branches. The DXF\n"
    "    # flat-pattern is ground truth: 0 bends => no fold, even if a shared note\n"
    "    # baked 'folding' into the ops upstream. Print state, then strip if flat+0.\n"
    "    try:\n"
    "        _pn_dbg = part.get(\"part_number\") or part.get(\"part_no\") or \"?\"\n"
    "        _gr_dbg = part.get(\"geometry_rollup\") or {}\n"
    "        _bcx = part.get(\"bend_count_dxf\")\n"
    "        _ebl = _gr_dbg.get(\"estimated_bend_line_count\")\n"
    "        _resolved_bends = int(_bcx if _bcx is not None else (_ebl if _ebl is not None else 0) or 0)\n"
    "        print(\"[FOLD-DBG]\", _pn_dbg,\n"
    "              \"gs=\" + str(part.get(\"geometry_source\")),\n"
    "              \"fpd=\" + str(part.get(\"flat_pattern_detected\")),\n"
    "              \"bcx=\" + str(_bcx), \"ebl=\" + str(_ebl), \"resolved=\" + str(_resolved_bends),\n"
    "              \"ops=\" + str(part.get(\"operations\")),\n"
    "              \"txt=\" + str(part.get(\"textual_operations\")), flush=True)\n"
    "        if part.get(\"flat_pattern_detected\") and _resolved_bends == 0:\n"
    "            _did = False\n"
    "            for _k in (\"operations\", \"textual_operations\"):\n"
    "                _ops = part.get(_k)\n"
    "                if isinstance(_ops, list) and \"folding\" in _ops:\n"
    "                    part[_k] = [_o for _o in _ops if _o != \"folding\"]\n"
    "                    _did = True\n"
    "            if _did:\n"
    "                print(\"[FOLD-DBG] STRIPPED folding from\", _pn_dbg, flush=True)\n"
    "    except Exception as _e:\n"
    "        print(\"[FOLD-DBG] error:\", _e, flush=True)\n"
    "    # ── end FOLD-DBG ──\n"
)


def main():
    if not TARGET.exists():
        raise SystemExit(f"Not found: {TARGET.resolve()} (run from C:\\ClaudeVision\\src)")

    src = TARGET.read_text(encoding="utf-8")
    if "FOLD-DBG" in src:
        print("Already instrumented (FOLD-DBG present). Nothing to do.")
        return
    n = src.count(OLD)
    if n == 0:
        raise SystemExit(
            "Anchor not found — lines 291-293 differ from expected.\n"
            "Paste drawing_job_merge.py lines 291-293 so I can re-target.")
    if n > 1:
        raise SystemExit(f"Anchor found {n}x (expected 1) — stopping.")

    bak = TARGET.with_suffix(".py.bak_folddbg")
    shutil.copy2(TARGET, bak)
    TARGET.write_text(src.replace(OLD, NEW), encoding="utf-8")

    back = TARGET.read_text(encoding="utf-8")
    if "FOLD-DBG" in back:
        print(f"INSTRUMENTED drawing_job_merge.py (backup: {bak.name}).")
        print("")
        print("Re-run 12120 and look at the [FOLD-DBG] lines in stdout for 03M (and 01M):")
        print("  - 03M should show fpd=True, resolved=0, txt=[...folding...] then STRIPPED")
        print("  - 01M should show resolved=2 (or >0) and NO strip")
        print("Then check the LABOUR section + the JSON one-liner:")
        print("  A. 03M debug shows STRIPPED and final ops have no folding + Fold row")
        print("     loses the flat parts  -> FIXED.")
        print("  B. 03M shows STRIPPED but final JSON/Fold row STILL has folding")
        print("     -> re-added downstream; we trace where (paste the [FOLD-DBG] lines).")
        print("  C. no [FOLD-DBG] 03M line -> 03M's DXF isn't augmented via this path.")
        print("Paste the [FOLD-DBG] lines for 03M + 01M, the Fold rows, and labour total.")
    else:
        shutil.copy2(bak, TARGET)
        raise SystemExit("Write verification failed — restored from backup. No change.")


if __name__ == "__main__":
    main()
