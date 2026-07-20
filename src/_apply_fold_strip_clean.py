#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
_apply_fold_strip_clean.py — production version of the DXF-flat fold strip.

Replaces the diagnostic FOLD-DBG block (from _apply_fold_debug_strip.py) with a
clean strip that keeps the working logic and removes all debug prints.

CONFIRMED WORKING on 12120: after the strip, 03M/04M/05M no longer fold (they
laser only); 01M/02M/06M/08M still fold — matching the estimator's routing. The
strip runs at the DXF-augment convergence point (part['dxf_augmented']=True),
which every augmented part reaches after both geometry branches.

LOGIC: a genuine flat-pattern part (flat_pattern_detected) whose resolved DXF
bend count is 0 does NOT fold — strip a stale 'folding' op (baked in upstream by
a shared/document note). Resolved bend count = bend_count_dxf, else
geometry_rollup.estimated_bend_line_count, else 0. Parts with a positive bend
count keep folding.

This applier is IDEMPOTENT and works whether or not the debug block is present:
  - if the FOLD-DBG block is present, it swaps it for the clean block;
  - if neither is present (fresh file), it inserts the clean block at line 291.

.bak. Verifies write.

Run (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _apply_fold_strip_clean.py
"""
from __future__ import annotations
import re
import shutil
from pathlib import Path

TARGET = Path("drawing_job_merge.py")

CLEAN_MARK = "DXF flat-pattern is ground truth for folding"

CLEAN_BLOCK = (
    "    part[\"dxf_augmented\"] = True\n"
    "    part[\"dxf_geometry_reliability\"] = reliability\n"
    "    part[\"dxf_raw_geometry\"] = dxf_raw\n"
    "    # DXF flat-pattern is ground truth for folding: a genuine flat-pattern part\n"
    "    # whose resolved DXF bend count is 0 does NOT fold. Strip a stale 'folding'\n"
    "    # op that a shared/document note baked into the ops upstream. Runs at the\n"
    "    # augment convergence point, so it applies regardless of which geometry\n"
    "    # branch handled the part; the downstream routing reads this ops list.\n"
    "    try:\n"
    "        _gr = part.get(\"geometry_rollup\") or {}\n"
    "        _bcx = part.get(\"bend_count_dxf\")\n"
    "        _ebl = _gr.get(\"estimated_bend_line_count\")\n"
    "        _resolved_bends = int((_bcx if _bcx is not None else (_ebl if _ebl is not None else 0)) or 0)\n"
    "        if part.get(\"flat_pattern_detected\") and _resolved_bends == 0:\n"
    "            for _k in (\"operations\", \"textual_operations\"):\n"
    "                _ops = part.get(_k)\n"
    "                if isinstance(_ops, list) and \"folding\" in _ops:\n"
    "                    part[_k] = [_o for _o in _ops if _o != \"folding\"]\n"
    "    except Exception:\n"
    "        pass\n"
)

# The full debug block as written by _apply_fold_debug_strip.py, to swap out.
DEBUG_BLOCK_START = "    part[\"dxf_augmented\"] = True\n"
DEBUG_MARK = "FOLD-DBG"

# Bare (unpatched) anchor — same three lines, no block after.
BARE = (
    "    part[\"dxf_augmented\"] = True\n"
    "    part[\"dxf_geometry_reliability\"] = reliability\n"
    "    part[\"dxf_raw_geometry\"] = dxf_raw\n"
)


def _extract_debug_block(src: str) -> str | None:
    """Return the exact FOLD-DBG block text (from dxf_augmented line to end-marker)."""
    start = src.find(DEBUG_BLOCK_START)
    if start == -1 or DEBUG_MARK not in src:
        return None
    end_marker = "    # ── end FOLD-DBG ──\n"
    end = src.find(end_marker)
    if end == -1:
        return None
    return src[start:end + len(end_marker)]


def main():
    if not TARGET.exists():
        raise SystemExit(f"Not found: {TARGET.resolve()} (run from C:\\ClaudeVision\\src)")

    src = TARGET.read_text(encoding="utf-8")

    if CLEAN_MARK in src:
        print("Already at clean version. Nothing to do.")
        return

    bak = TARGET.with_suffix(".py.bak_foldclean")

    # Case 1: the debug block is present — swap it for the clean block.
    dbg = _extract_debug_block(src)
    if dbg is not None:
        shutil.copy2(TARGET, bak)
        TARGET.write_text(src.replace(dbg, CLEAN_BLOCK), encoding="utf-8")
        mode = "swapped FOLD-DBG block for clean strip"
    else:
        # Case 2: no debug block — insert clean block at the bare anchor.
        n = src.count(BARE)
        if n == 0:
            raise SystemExit(
                "Neither the debug block nor the bare anchor found.\n"
                "Paste drawing_job_merge.py lines 291-293 so I can re-target.")
        if n > 1:
            raise SystemExit(f"Bare anchor found {n}x (expected 1) — stopping.")
        shutil.copy2(TARGET, bak)
        TARGET.write_text(src.replace(BARE, CLEAN_BLOCK), encoding="utf-8")
        mode = "inserted clean strip at convergence point"

    back = TARGET.read_text(encoding="utf-8")
    if CLEAN_MARK in back and DEBUG_MARK not in back:
        print(f"PATCHED drawing_job_merge.py — {mode} (backup: {bak.name}).")
        print("Debug prints removed; strip logic retained. Production-ready.")
        print("")
        print("Re-run 12120 to confirm unchanged behaviour (no [FOLD-DBG] noise):")
        print("  Fold rows should still be: 1.2mm (06M,08M) / 1.5mm (01M,02M) / (101)")
        print("  Labour total ~£6.51. 03M/04M/05M laser-only.")
    else:
        shutil.copy2(bak, TARGET)
        raise SystemExit("Write verification failed (marker check) — restored. No change.")


if __name__ == "__main__":
    main()
