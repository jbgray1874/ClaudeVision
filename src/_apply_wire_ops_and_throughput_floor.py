#!/usr/bin/env python3
r"""
_apply_wire_ops_and_throughput_floor.py

TWO CHANGES. The first is local to bars. The second affects EVERY job.

---------------------------------------------------------------------------------------
CHANGE 1 — you cannot laser, fold or punch a solid round bar
---------------------------------------------------------------------------------------
1310-02 STUD is now correctly priced as wire (£0.04 material — exactly Tim's figure), but
it is still carrying LASER (£4.91) from the original 8mm-sheet misread:

    Laser (Metal) — Stud, 8mm MILD STEEL    £4.91      <- lasering a round bar
    Weld (CO2)    — Stud                    £3.23      (Tim £1.25)
    Assemble/pack — Stud                    £0.52
    Robomac                                 ABSENT     (Tim £0.17)

Labour operations come from part_estimate.labour_estimate.costs_gbp (wb_populate:685) —
NOT from the manufacturing_writeup record where document_builder wrote 'robomac'. Two
part records again. The bar's ops were fixed on the writeup record; the pricing record
still thinks it is sheet.

The mechanism to fix this ALREADY EXISTS in wb_populate (line ~197):

    _SPURIOUS_OPS_BY_STOCK_FORM = {
        "tube": {"punch", "punching"},   # tubes are not punched (no flat blank to punch)
    }

Add "wire". A solid bar has no flat blank: laser, fold, punch, linebend, guillotine and
diamond-polish are all physically impossible. This is a pure REMOVAL — it invents nothing.

    £12.48  -  £4.91 laser  =  £7.57      (Tim: £6.90)

Robomac is NOT injected here. Tim charges £0.17 and we have no ROBO throughput from the
rate card — back-solving one from a single number is fitting, not measuring. It stays a
known, named gap until the rate is confirmed.

---------------------------------------------------------------------------------------
CHANGE 2 — the throughput guard only catches rates that are too FAST
---------------------------------------------------------------------------------------
wb_populate has:

    _THROUGHPUT_CEILING_MULTIPLIER = 5   # derived > default x 5 -> use default

A derived throughput that is too HIGH is caught. A derived throughput that is too LOW
sails straight through — and a low throughput means more hours, which INFLATES labour.

On 1310 the weld throughput derived as 14.85/hr against a default of 42 (Tim's sheet
implies ~50). That is 2.8x too slow, nothing stopped it, and it cost £3.23 against Tim's
£1.25 — the single biggest remaining labour error on the job.

This is NOT a 1310 bug. An unguarded floor inflates labour on EVERY job, and it is a
strong candidate for the derived-laser and flat-P.Coat over-reads we have been attributing
elsewhere all week.

Add the symmetric floor:

    _THROUGHPUT_FLOOR_DIVISOR = 5        # derived < default / 5 -> use default

Deliberately conservative — the same 5x that the ceiling already uses, so it only fires on
implausible outliers, not on genuine slow parts. Every substitution is FLAGGED with both
numbers so the effect is auditable rather than silent.

EXPECTED IMPACT: 1310 weld 14.85/hr is 2.8x slow — INSIDE the 5x floor, so it will NOT be
substituted. The floor does not fix 1310. It is a guard against the pathological cases
(derived 2/hr against a default of 180) that would otherwise ship enormous silent labour.
Say so plainly rather than claiming a win the change does not deliver.

Usage (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _apply_wire_ops_and_throughput_floor.py
"""
from __future__ import annotations
import shutil, sys, datetime, os

TARGET = r"C:\ClaudeVision\src\wb_populate.py"
SENTINEL = "_THROUGHPUT_FLOOR_DIVISOR"


def sub(src, old, new, label):
    n = src.count(old)
    if n != 1:
        sys.exit(f"ABORT [{label}]: expected 1 match, found {n}. Nothing written.\n"
                 f"--- looked for ---\n{old}\n")
    print(f"  ok  {label}")
    return src.replace(old, new, 1)


def main():
    if not os.path.exists(TARGET):
        sys.exit(f"not found: {TARGET}")

    src = open(TARGET, "r", encoding="utf-8").read()
    if SENTINEL in src:
        sys.exit("Already applied (sentinel present).")

    # ---- 1. wire/bar spurious ops --------------------------------------------
    src = sub(src,
              '''_SPURIOUS_OPS_BY_STOCK_FORM = {
    "tube": {"punch", "punching"},   # tubes are not punched (no flat blank to punch)
}''',
              '''_SPURIOUS_OPS_BY_STOCK_FORM = {
    "tube": {"punch", "punching"},   # tubes are not punched (no flat blank to punch)
    # A solid round bar has NO FLAT BLANK. It cannot be lasered, folded, punched,
    # line-bent, guillotined or diamond-polished. It is cut (Robomac / Saw) and welded.
    # 1310-02 STUD (8mm dia x 65) was carrying Laser £4.91 from the original misread
    # that treated its DIAMETER as an 8mm sheet THICKNESS.
    "wire": {
        "laser", "laser_cutting", "laser_metal",
        "fold", "folding",
        "punch", "punching",
        "linebend", "line_bend",
        "guillotine",
        "diamond_polish",
    },
}''',
              "spurious ops for wire/bar stock")

    # ---- 2. throughput floor --------------------------------------------------
    src = sub(src,
              '    _THROUGHPUT_CEILING_MULTIPLIER = 5   # derived > default × 5 → use default',
              '''    _THROUGHPUT_CEILING_MULTIPLIER = 5   # derived > default × 5 → use default
    # The ceiling above only catches derived throughputs that are too FAST. A derived
    # throughput that is too SLOW sails through — and slow means MORE HOURS, which
    # INFLATES labour. On 1310 the stud's weld derived at 14.85/hr against a default of
    # 42 (Tim's sheet implies ~50): 2.8x too slow, unguarded, £3.23 vs Tim's £1.25.
    # Symmetric, and deliberately as conservative as the ceiling: only implausible
    # outliers are substituted, and every substitution is FLAGGED with both numbers.
    _THROUGHPUT_FLOOR_DIVISOR = 5        # derived < default ÷ 5 → use default''',
              "throughput floor constant")

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{TARGET}.bak_wireops_{ts}"
    shutil.copy2(TARGET, bak)
    open(TARGET, "w", encoding="utf-8").write(src)

    print(f"\n  backup: {bak}")
    print(f"  written: {TARGET}")
    print("""
NOTE — the floor CONSTANT is in, but it is not yet WIRED IN, because the code that applies
_THROUGHPUT_CEILING_MULTIPLIER has not been read. Send this and it will be finished in one
more exact patch:

    Select-String -Path C:\\ClaudeVision\\src\\wb_populate.py `
        -Pattern "_THROUGHPUT_CEILING_MULTIPLIER" -Context 4,18

Applying a floor by guessing at the surrounding code is exactly how the last two half-
applied changes happened. One grep, then it lands properly.

MEANWHILE the wire-ops fix IS live. Run 1310 (qty 50):

    Get-Process EXCEL -ErrorAction SilentlyContinue | Stop-Process -Force
    $env:ESTIMATE_DEFAULT_JOB_QUANTITY="50"
    C:\\ClaudeVision\\.venv\\Scripts\\python.exe -u main.py --search-root "K:\\Estimating\\Completed\\AI Estimating\\Live Enquiry\\1310 Drill Stud Holder (Rev C)" --folder-as-job

EXPECT:
  * "dropped spurious op 'laser_cutting' on 1310-02" in the flags
  * NO Laser row on the Stud
  * unit cost ~£7.57  (Tim £6.90)
  * still missing, and still named: Robomac £0.17, P.Coat £2.00
  * weld still £3.23 vs Tim £1.25 — the floor will NOT fix this (14.85 vs 42 is 2.8x, inside
    the 5x guard). It is a separate, real defect.

THEN regress 1282 (qty 10) — no bars, no wire parts, so it MUST stay at £278.93.
""")


if __name__ == "__main__":
    main()
