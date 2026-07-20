#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
_apply_flat_fold_strip_v2.py — strip a stale 'folding' op at the FLAT-PATTERN
BRANCH (drawing_job_merge.py ~191), which runs UNCONDITIONALLY for every part
that has a genuine DXF flat pattern.

WHY v2 (the previous fold-strip didn't bite):
  The earlier patch stripped 'folding' inside the DXF-augment RE-INFER block
  (~line 313-316). That block is gated by a condition 03M does not satisfy, so
  it never ran for the flat parts — 'folding' survived. Proof from the live run:
  03M has fold_count_textual=0, fold_values_mm=[], yet textual_operations still
  contains 'folding' (baked in at extraction time from a shared note), and the
  strip did not remove it.

WHERE 'folding' comes from: extraction-time note inference put 'folding' into
every part's textual_operations. Nothing downstream removes it for flat parts.

THE FIX: at the flat-pattern branch (line 177 body, right after line 191 sets
flat_pattern_detected=True), when the flat pattern shows 0 bends, remove
'folding' from BOTH part['operations'] and part['textual_operations']. This
branch:
  - RUNS for 03M/04M/05M/02M/06M (they have genuine flat patterns — their flat
    geometry is in the estimate), and is NOT gated by the skip that bypassed the
    re-infer block;
  - is UPSTREAM of the re-infer block, and that block passes has_fold_geometry=
    (bends>0)=False for these parts, so it will NOT re-add 'folding' afterwards;
  - writes the same textual_operations list the downstream routing consumes.

Parts with real bends (01M flat bend_count=2, 08M=1) do NOT enter the strip
(guarded on flat['bend_count']==0) and keep folding. Non-flat parts never enter
this branch.

ONE exact-string edit. Self-tests. .bak. Idempotent. Verifies write.

Run (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _apply_flat_fold_strip_v2.py
"""
from __future__ import annotations
import shutil
from pathlib import Path

TARGET = Path("drawing_job_merge.py")

# Anchor: lines 191-194 exactly as in the live file (from the grep).
OLD = (
    "        part[\"flat_pattern_detected\"] = True\n"
    "        part[\"overall_length_mm\"] = flat[\"blank_length_mm\"]\n"
    "        part[\"overall_width_mm\"] = flat[\"blank_width_mm\"]\n"
    "        reliability = 1.0\n"
)

NEW = (
    "        part[\"flat_pattern_detected\"] = True\n"
    "        part[\"overall_length_mm\"] = flat[\"blank_length_mm\"]\n"
    "        part[\"overall_width_mm\"] = flat[\"blank_width_mm\"]\n"
    "        reliability = 1.0\n"
    "        # DXF flat-pattern is what the press brake bends from — ground truth.\n"
    "        # If it shows 0 bends, this part does NOT fold, even if a shared/document\n"
    "        # 'fold' note baked 'folding' into textual_operations at extraction time.\n"
    "        # Strip it here — this branch runs for every genuine flat-pattern part and\n"
    "        # is upstream of (and not gated by) the conditional re-infer block. The\n"
    "        # downstream routing reads this exact list to emit the Fold op.\n"
    "        if int(flat.get(\"bend_count\") or 0) == 0:\n"
    "            for _k in (\"operations\", \"textual_operations\"):\n"
    "                _ops = part.get(_k)\n"
    "                if isinstance(_ops, list) and \"folding\" in _ops:\n"
    "                    part[_k] = [_o for _o in _ops if _o != \"folding\"]\n"
)


def _selftest():
    """Mirror the strip logic on the 12120 cases."""
    def strip(bend_count, part):
        # emulate the patched block
        if int(bend_count or 0) == 0:
            for k in ("operations", "textual_operations"):
                ops = part.get(k)
                if isinstance(ops, list) and "folding" in ops:
                    part[k] = [o for o in ops if o != "folding"]
        return part

    cases = [
        ("03M flat, bend_count=0, note-folding in both lists",
         0, {"operations": ["laser_cutting", "folding", "handling"],
             "textual_operations": ["laser_cutting", "folding", "handling"]},
         lambda p: "folding" not in p["textual_operations"] and "folding" not in p["operations"]),
        ("05M flat, bend_count=0",
         0, {"operations": ["laser_cutting", "folding"],
             "textual_operations": ["laser_cutting", "folding", "handling"]},
         lambda p: "folding" not in p["textual_operations"]),
        ("01M flat, bend_count=2 -> KEEP folding",
         2, {"operations": ["laser_cutting", "folding"],
             "textual_operations": ["laser_cutting", "folding", "handling"]},
         lambda p: "folding" in p["textual_operations"]),
        ("08M flat, bend_count=1 -> KEEP folding",
         1, {"operations": ["laser_cutting", "folding"],
             "textual_operations": ["laser_cutting", "folding"]},
         lambda p: "folding" in p["textual_operations"]),
        ("flat 0 bends, also welding -> strip only folding",
         0, {"operations": ["folding", "welding"],
             "textual_operations": ["folding", "welding", "handling"]},
         lambda p: "folding" not in p["textual_operations"] and "welding" in p["textual_operations"]),
        ("flat 0 bends, no folding present -> no-op, lists intact",
         0, {"operations": ["laser_cutting"],
             "textual_operations": ["laser_cutting", "handling"]},
         lambda p: p["textual_operations"] == ["laser_cutting", "handling"]),
    ]
    print("Self-test (flat-pattern-branch strip logic):")
    ok = True
    for name, bc, part, check in cases:
        r = strip(bc, dict((k, list(v)) for k, v in part.items()))
        good = check(r)
        if not good:
            ok = False
        print(f"  {('OK ' if good else 'BAD')}  txt={r['textual_operations']}   {name}")
    return ok


def main():
    if not TARGET.exists():
        raise SystemExit(f"Not found: {TARGET.resolve()} (run from C:\\ClaudeVision\\src)")

    if not _selftest():
        raise SystemExit("Self-test FAILED — not patching.")
    print("  Self-test PASSED.\n")

    src = TARGET.read_text(encoding="utf-8")
    if "DXF flat-pattern is what the press brake bends from — ground truth." in src:
        print("Already patched (v2 marker present). Nothing to do.")
        return
    n = src.count(OLD)
    if n == 0:
        raise SystemExit(
            "Anchor not found — lines 191-194 differ from expected.\n"
            "Paste drawing_job_merge.py lines 191-194 so I can re-target.")
    if n > 1:
        raise SystemExit(f"Anchor found {n}x (expected 1) — stopping to avoid a wrong edit.")

    bak = TARGET.with_suffix(".py.bak_flatfoldv2")
    shutil.copy2(TARGET, bak)
    TARGET.write_text(src.replace(OLD, NEW), encoding="utf-8")

    back = TARGET.read_text(encoding="utf-8")
    if "DXF flat-pattern is what the press brake bends from — ground truth." in back:
        print(f"PATCHED drawing_job_merge.py (backup: {bak.name}).")
        print("")
        print("VERIFY IN TWO STEPS after re-running 12120:")
        print("  1. JSON one-liner: 03M/05M textual_operations should NO LONGER contain")
        print("     'folding' (01M should still contain it — bend_count=2).")
        print("  2. Labour section: if 'folding' is gone from 03M/05M ops AND the Fold")
        print("     rows lose 02M/03M/04M/05M/06M -> FIXED (labour drops below £6.72).")
        print("     If 'folding' is gone from ops but the Fold row STILL lists them ->")
        print("     the labour sheet reads ops from a DIFFERENT source (not textual_")
        print("     operations) — that's the next (and final) place to trace.")
    else:
        shutil.copy2(bak, TARGET)
        raise SystemExit("Write verification failed — restored from backup. No change.")


if __name__ == "__main__":
    main()
