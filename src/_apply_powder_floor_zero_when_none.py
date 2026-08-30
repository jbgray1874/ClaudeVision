#!/usr/bin/env python3
r"""
_apply_powder_floor_zero_when_none.py

The acrylic powder line SURVIVED the coated-area exclusion — but the output proves the
area fix worked: the label now reads "coated surface area (0.0000 m2)" (was 0.1153). The
£0.30 is now coming from the PER-PIECE FLOOR, not the area.

THE CHAIN:
    _powder_by_area_kg  = 0.0000 * 0.20 = 0.0   (acrylic excluded — the area fix worked)
    _powder_by_floor_kg = _coated_pieces * 0.03
    _powder_kg_total    = max(area, floor)      -> floor wins
    _coated_pieces      = 1 if _job_welds_pw else max(1, _fab_pieces)
                                                    ^^^^^^^^^^^^^^^^^^^^
The previous patch correctly made _fab_pieces = 0 for a pure-acrylic job (no coatable
parts). BUT max(1, 0) = 1 forces a minimum of one coated piece anyway, so the floor books
0.03 kg * £9.73 = £0.30. The max(1, ...) is a floor-of-the-floor that guarantees at least
one coated object even when the job has NONE.

THE FIX: a job with ZERO coatable pieces gets ZERO powder, not a forced minimum of one.

    _coated_pieces = 1 if _job_welds_pw else max(1, _fab_pieces)
      ->
    _coated_pieces = (0 if _fab_pieces == 0 else (1 if _job_welds_pw else _fab_pieces))

Truth table (only the _fab_pieces == 0 case changes):
    steel, welded      _fab_pieces>=1 -> 1   (unchanged)
    steel, not welded  _fab_pieces=N  -> N   (unchanged; was max(1,N)=N)
    pure acrylic       _fab_pieces=0  -> 0   (was 1 -> the fix; no coatable part = no powder)

With _coated_pieces = 0: floor = 0, area = 0, _powder_kg_total = 0, the BOM write gate
(if _powder_kg_total > 0) is skipped, and NO powder row is written.

Steel jobs are completely unaffected — they always have _fab_pieces >= 1.

Usage (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _apply_powder_floor_zero_when_none.py
"""
from __future__ import annotations
import shutil, sys, datetime, os

TARGET = r"C:\ClaudeVision\src\wb_populate.py"
SENTINEL = "powder_floor_zero_when_no_coated"


def sub(src, old, new, label):
    n = src.count(old)
    if n != 1:
        sys.exit(f"ABORT [{label}]: expected 1 match, found {n}. NOTHING WRITTEN.\n"
                 f"--- looked for ---\n{old}\n")
    print(f"  ok  {label}")
    return src.replace(old, new, 1)


ANCHOR = '''    _coated_pieces = 1 if _job_welds_pw else max(1, _fab_pieces)'''

NEW = '''    # powder_floor_zero_when_no_coated (2026-07-15): a job with ZERO coatable pieces gets
    # ZERO powder, not a forced minimum of one. The old max(1, _fab_pieces) guaranteed at
    # least one coated object even when nothing in the job is coatable (e.g. a pure-acrylic
    # job — acrylic is excluded from _fab_pieces upstream), so the per-piece floor booked
    # 0.03 kg of phantom powder. Now: no coatable parts -> 0 pieces -> floor 0 -> no powder.
    # Steel jobs are unaffected (they always have _fab_pieces >= 1).
    _coated_pieces = (0 if _fab_pieces == 0
                      else (1 if _job_welds_pw else _fab_pieces))'''


def main():
    if not os.path.exists(TARGET):
        sys.exit(f"not found: {TARGET}")
    src = open(TARGET, "r", encoding="utf-8").read()
    if SENTINEL in src:
        sys.exit("Already applied (sentinel present).")
    src = sub(src, ANCHOR, NEW, "wb_populate: powder floor -> 0 when no coatable parts")

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{TARGET}.bak_powderfloor_{ts}"
    shutil.copy2(TARGET, bak)
    open(TARGET, "w", encoding="utf-8").write(src)
    print(f"  backup: {bak}")

    print("""
RE-RUN 12439 (qty 2025). Expected — powder FINALLY gone:
    - NO POWDER BOM line.
    - Material £0.84 -> ~£0.54 (still the oversized acrylic sheet £0.53).
    - Unit cost £3.16 -> ~£2.86.
    - Operations unchanged (Diamond Polish + Peel + Linebend + Assemble/pack).

REGRESSION — re-run 1282 (steel, real powder). Its POWDER line MUST remain and unit cost
MUST be unchanged. 1282 has multiple coated steel parts (_fab_pieces >= 1), so this patch
does not touch it. If 1282's powder is intact, the fix cuts only the pure-acrylic case.

After this, 12439's remaining gaps vs Tony are just the two non-powder items:
    - acrylic sheet 317x182 @ £46.20 -> £0.53 vs Tony 311x101 @ £0.12  (size + rate)
    - assemble/pack band 30/hr vs Tony 120  (acrylic pack size-banding)
    - linebend qty 2 vs 1  (bend over-read or per-part booking)
""")


if __name__ == "__main__":
    main()
