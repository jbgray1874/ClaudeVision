#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
_apply_dxf_fold_strip.py — strip a stale 'folding' op when the DXF flat-pattern
confirms the part is flat (0 bends).

ROOT CAUSE (traced through the pipeline):
  - process_router.build_process_routing adds the Fold labour op iff 'folding'
    is in part['textual_operations'] (it reads ONLY that list, never bend_count).
  - A blanket document/note-level inference put 'folding' into every part's
    textual_operations (proof: even geometry-less phantoms D-M4/B-03 carry it).
  - drawing_job_merge's DXF-augment block correctly passes has_fold_geometry=
    (bends>0) to _infer_ops, but at line ~314 it only ADDS inferred ops to the
    existing set — it never REMOVES the stale 'folding'. So flat parts keep it,
    and the earlier bend_count fix (infer_bend_count) can't help: the fold op
    doesn't read bend_count.

FIX: at the merge (line ~314-316), when the part has a genuine flat-pattern DXF
AND bends==0, drop 'folding' from the merged ops before they overwrite
textual_operations. The DXF (what the press brake bends from) overrides the note.

This lands in the exact list process_router reads, and that list is OVERWRITTEN
here — so stripping 'folding' removes the Fold op. Gated on flat_pattern_detected
+ bends==0, so only genuine-DXF-flat parts are affected; parts with real bends
(01M=2, 08M=1) keep folding; no-DXF parts never enter this block.

ONE exact-string edit. Self-tests the logic. .bak. Idempotent. Verifies write.

Run (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _apply_dxf_fold_strip.py
"""
from __future__ import annotations
import shutil
from pathlib import Path

TARGET = Path("drawing_job_merge.py")

# Anchor: the exact merge+overwrite (from the live grep, lines 313-316).
OLD = (
    "                if inferred:\n"
    "                    merged = sorted(_ops_now | set(inferred))\n"
    "                    part[\"operations\"] = merged\n"
    "                    part[\"textual_operations\"] = merged\n"
)

NEW = (
    "                if inferred:\n"
    "                    merged = sorted(_ops_now | set(inferred))\n"
    "                    # DXF flat-pattern is what the press brake bends from — ground\n"
    "                    # truth. If it shows 0 bends, this part does NOT fold, even if a\n"
    "                    # shared/document 'fold' note put 'folding' in the ops upstream.\n"
    "                    # The merge above only ADDs, so a stale 'folding' would survive;\n"
    "                    # strip it here. process_router reads this exact list to emit the\n"
    "                    # Fold op, so removing it here removes the phantom fold.\n"
    "                    if part.get(\"flat_pattern_detected\") and bends == 0:\n"
    "                        merged = [op for op in merged if op != \"folding\"]\n"
    "                    part[\"operations\"] = merged\n"
    "                    part[\"textual_operations\"] = merged\n"
)


def _selftest():
    """Mirror the patched merge logic on the 12120 cases."""
    def merged_ops(flat_pattern_detected, bends, ops_now, inferred):
        merged = sorted(set(ops_now) | set(inferred))
        if flat_pattern_detected and bends == 0:
            merged = [op for op in merged if op != "folding"]
        return merged

    cases = [
        ("03M flat DXF, 0 bends, note added folding",
         True, 0, ["laser_cutting", "folding", "handling"], ["laser_cutting"],
         lambda r: "folding" not in r and "laser_cutting" in r),
        ("05M flat DXF, 0 bends",
         True, 0, ["laser_cutting", "folding", "handling"], ["laser_cutting"],
         lambda r: "folding" not in r),
        ("06M flat DXF, 0 bends",
         True, 0, ["laser_cutting", "folding", "handling"], ["laser_cutting"],
         lambda r: "folding" not in r),
        ("01M flat DXF, 2 bends -> KEEP folding",
         True, 2, ["laser_cutting", "folding", "handling"], ["laser_cutting", "folding"],
         lambda r: "folding" in r),
        ("08M flat DXF, 1 bend -> KEEP folding",
         True, 1, ["laser_cutting", "folding", "handling"], ["laser_cutting", "folding"],
         lambda r: "folding" in r),
        ("no flat_pattern (e.g. bbox-only dxf), 0 bends -> DON'T strip (not confirmed flat)",
         False, 0, ["laser_cutting", "folding"], ["laser_cutting"],
         lambda r: "folding" in r),
        ("flat DXF 0 bends but also welding -> strip only folding, keep welding",
         True, 0, ["folding", "welding", "handling"], ["welding"],
         lambda r: "folding" not in r and "welding" in r),
    ]
    print("Self-test (patched merge/strip logic):")
    ok = True
    for name, fpd, bends, ops_now, inferred, check in cases:
        r = merged_ops(fpd, bends, ops_now, inferred)
        good = check(r)
        if not good:
            ok = False
        print(f"  {('OK ' if good else 'BAD')}  {r}   {name}")
    return ok


def main():
    if not TARGET.exists():
        raise SystemExit(f"Not found: {TARGET.resolve()} (run from C:\\ClaudeVision\\src)")

    if not _selftest():
        raise SystemExit("Self-test FAILED — not patching.")
    print("  Self-test PASSED: flat DXFs (0 bends) lose 'folding'; real-bend parts keep\n"
          "  it; non-flat-confirmed parts untouched; other ops (welding) preserved.\n")

    src = TARGET.read_text(encoding="utf-8")
    if "DXF flat-pattern is what the press brake bends from" in src:
        print("Already patched. Nothing to do.")
        return
    n = src.count(OLD)
    if n == 0:
        raise SystemExit(
            "Anchor not found — the live merge block differs from expected.\n"
            "Paste drawing_job_merge.py lines 313-317 so I can re-target.")
    if n > 1:
        raise SystemExit(f"Anchor found {n}x (expected 1) — stopping to avoid a wrong edit.")

    bak = TARGET.with_suffix(".py.bak_foldstrip")
    shutil.copy2(TARGET, bak)
    TARGET.write_text(src.replace(OLD, NEW), encoding="utf-8")

    back = TARGET.read_text(encoding="utf-8")
    if "DXF flat-pattern is what the press brake bends from" in back:
        print(f"PATCHED drawing_job_merge.py (backup: {bak.name}).")
        print("Re-run 12120. Expect in the LABOUR section:")
        print("  - 02M/03M/04M/05M/06M GONE from the Fold rows (now Laser-only)")
        print("  - 01M and 08M STILL folded (they have real bends)")
        print("  - fold labour drops; unit cost ticks down accordingly")
    else:
        shutil.copy2(bak, TARGET)
        raise SystemExit("Write verification failed — restored from backup. No change.")


if __name__ == "__main__":
    main()
