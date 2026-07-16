#!/usr/bin/env python3
r"""
_apply_weldment_is_one_object.py

DAVE (estimator, 2026-07-14):
    "I would focus on why AI has picked up 2 items to be powder coated —
     it needs to recognise it's 1 welded assembly."

He is right, and Tim's own 1310 sheet confirms it: P.Coat qty 1, £2.00. We book qty 2, £3.33.

WHY THE EXISTING RULE DID NOT FIRE

We built the assembly-level rule yesterday for 7670 and gated it on:

    if not any(_powder_ok.values()):      # "does NOTHING in the job qualify for powder?"

On 1310 BOTH parts carry finish 'SEE ASSEMBLY DRAWING'. The pointer resolver correctly
resolves that to POWDER — so _powder_ok is True for both, the guard fails, and the whole
block is skipped. P.Coat stays at qty 2 and we hang one object twice.

The gate asks the wrong question. "Does anything else qualify" was a hack to protect 1282.
The real question is the one Dave asked:

    IS THIS ONE WELDED OBJECT?

THE DISCRIMINATOR

    every fabricated part points to the assembly for its finish   (none carries its own)
    AND the job contains a weld                                   (they are joined)
    -> they are ONE OBJECT. It hangs on the booth line ONCE.

Why this is safe on 1282 — which is the whole reason the old hack existed:

    1310   1310-01, 1310-02              ALL pointers   + weld  -> qty 2 -> 1   (Dave/Tim)
    7670   3 wire forms                  all RAW + assembly POWDER -> existing rule, qty 1
    1282   1449-01C, 1450-01C, 2621-01C carry POWDER on their OWN drawings;
           1448-01/02, 3886-02/03 are pointers; 1455-C-00x are RAW
           -> MIXED, not all pointers    -> rule STANDS DOWN -> qty 16 UNCHANGED

    1282's peg panels are coated individually and then bolted. Not one object. Correct as-is.

AND IF THE PARTS ALL POINT TO THE ASSEMBLY BUT NOTHING WELDS?

    Then we do NOT know they are one object — they could be bolted together after individual
    coating. We do NOT fire, and we say so. A flag that explains why a rule did NOT fire is
    worth more than one celebrating when it does; that is what caught the tin-of-paint bug.

WHAT THIS DOES NOT TOUCH

    Throughput. Ours is 458/hr against Tim's 957 — about 2x slow, like every other
    substituted default on this job (pack 58 vs 120, weld 29 vs 50). That is the corpus
    median problem and it is a separate, bigger fix. ONE CHANGE AT A TIME.

Usage (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _apply_weldment_is_one_object.py
"""
from __future__ import annotations
import shutil, sys, datetime, os

TARGET = r"C:\ClaudeVision\src\wb_populate.py"
SENTINEL = "_weldment_is_one_object"

OLD = '''            else:
                # Loud, specific, and it prints what it actually saw. No third blind attempt.
                _flag(f"assembly drawing says POWDER and nothing else in the job qualifies, "
                      f"but no part's finish reads RAW. Finishes seen: "
                      f"{ {k: (v[:24] or '<empty>') for k, v in _fin_by_pn.items()} }. "
                      f"NOT coating anything. Check the drawing finish fields.", flags)'''

NEW = '''            else:
                # Loud, specific, and it prints what it actually saw. No third blind attempt.
                _flag(f"assembly drawing says POWDER and nothing else in the job qualifies, "
                      f"but no part's finish reads RAW. Finishes seen: "
                      f"{ {k: (v[:24] or '<empty>') for k, v in _fin_by_pn.items()} }. "
                      f"NOT coating anything. Check the drawing finish fields.", flags)

    # ── A WELDMENT IS ONE OBJECT (Dave, 2026-07-14) ──────────────────────────────
    # The branch above only fires when NOTHING in the job qualifies for powder. That was a
    # hack to protect 1282, and it asks the wrong question.
    #
    # On 1310 both parts read 'SEE ASSEMBLY DRAWING'. The pointer resolver correctly turns
    # that into POWDER — so _powder_ok is True, the guard fails, the block is skipped, and
    # P.Coat stays at qty 2. We hang ONE OBJECT TWICE. Tim books qty 1, £2.00; we book
    # qty 2, £3.33.
    #
    # The right question is the one the estimator asked: IS THIS ONE WELDED OBJECT?
    #
    #     no part carries its OWN finish (all point at the assembly)   AND   the job welds
    #        -> they are joined into one thing, and one thing hangs once.
    #
    # 1282 is untouched: its peg panels carry POWDER on their own drawings, so the finishes
    # are MIXED, not all pointers — they are coated individually and then bolted. Correct
    # at qty 16, and this rule stands down.
    _weldment_is_one_object = False
    if not _assembly_level_powder:
        _fab_pns = [str(_p.get("part_number") or "") for _p in labour_parts
                    if _p.get("part_number")]
        _all_point_at_assembly = bool(_fab_pns) and all(
            "SEE ASS" in str(_fin_by_pn.get(_pn, "")).upper() for _pn in _fab_pns
        )
        _job_welds = any(
            "weld" in str(_o).lower()
            for _mp in _mw_parts
            for _o in (_mp.get("textual_operations") or _mp.get("operations") or [])
        )
        if _all_point_at_assembly and _job_welds:
            _weldment_is_one_object = True
            _assembly_level_powder = True          # the P.Coat qty already reads this flag
            _flag(f"WELDMENT IS ONE OBJECT: no part carries its own finish — every one points "
                  f"at the assembly ({', '.join(_fab_pns)}) — and the job welds. They are "
                  f"joined into a single object, and a single object hangs on the booth line "
                  f"ONCE. P.Coat qty 1, not one per component.", flags)
        elif _all_point_at_assembly and not _job_welds:
            # Do NOT guess. Pointing at the assembly does not by itself mean welded — the
            # parts could be coated separately and then bolted. Say why we did not fire.
            _flag(f"every part points at the assembly for its finish "
                  f"({', '.join(_fab_pns)}) but NOTHING WELDS on this job. They may be one "
                  f"object, or coated separately and bolted. NOT collapsing P.Coat to qty 1 "
                  f"— charging one coat per part. Estimator to check.", flags)'''


def main():
    if not os.path.exists(TARGET):
        sys.exit(f"not found: {TARGET}")
    src = open(TARGET, "r", encoding="utf-8").read()
    if SENTINEL in src:
        sys.exit("Already applied (sentinel present).")

    n = src.count(OLD)
    if n != 1:
        sys.exit(f"ABORT: expected 1 match, found {n}. Nothing written.")

    src = src.replace(OLD, NEW, 1)

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{TARGET}.bak_weldment_{ts}"
    shutil.copy2(TARGET, bak)
    open(TARGET, "w", encoding="utf-8").write(src)

    print("  ok  a weldment is ONE object — P.Coat hangs it once")
    print("  ok  fires only when EVERY part points at the assembly AND the job welds")
    print("  ok  says so out loud when it does NOT fire, and why")
    print(f"\n  backup: {bak}")
    print("""
RUN 1310 (qty 50), THEN 1282 (qty 10).

EXPECT ON 1310:
    * flag: "WELDMENT IS ONE OBJECT: ... (1310-01, 1310-02) ... P.Coat qty 1"
    * P.Coat   qty 2 -> qty 1      £3.33 -> ~£2.55        (Tim: qty 1, £2.00)
    * unit cost  £9.07 -> ~£8.29

    The remaining ~55p on that line is THROUGHPUT: we use 458/hr, Tim books 957. Every
    substituted default on this job is about 2x too slow — pack 58 vs Tim's 120, weld 29
    vs 50 — while FOLD, which we DERIVE from bend count, lands at 93.76 against his 90.
    When we compute from geometry we are right. When we substitute a corpus median we are
    consistently half. That is the next fix, and it is one query, not one job.

1282 MUST BE UNCHANGED — this is the whole point of the discriminator:
    * P.Coat stays qty 16
    * unit cost stays £206.65
    * diff must show ZERO literal cells changed (BI-MAINSCABLE may drift — known)

        C:\\ClaudeVision\\.venv\\Scripts\\python.exe _1282_diff.py ^
            "...1282...20260714_121930.xlsx" "...<the new one>.xlsx"
""")


if __name__ == "__main__":
    main()
