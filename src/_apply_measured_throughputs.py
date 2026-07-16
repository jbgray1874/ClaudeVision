#!/usr/bin/env python3
r"""
_apply_measured_throughputs.py

Replaces the guessed/median-by-eye _THROUGHPUT_DEFAULTS with values MEASURED from the
1,982-job historical corpus, and adds Robomac (which was missing entirely, so 1310's stud
was costing NOTHING for bar-cutting against Tim's £0.17).

MEASURED (dbo.historical_quote_labour_line, read via raw_line_json — the typed columns are
mis-mapped, see note at the bottom):

    operation                lines   Tim avg/hr   old default   change
    ------------------------------------------------------------------
    Robomac                    34       709.4      (MISSING)    ADDED
    P.Coat                    316       457.7          424      424 -> 458   (was ~right)
    Laser (Metal)             305       269.3          180      180 -> 269
    Laser (Acrylic)            13       251.8          120      120 -> 252
    Manual labour (Acrylic)    13       122.5           40       40 -> 122
    Linebend                   18       117.8           40       40 -> 118
    Punch                     126       116.1          100      100 -> 116
    Salvagnini                 26       110.0           60       60 -> 110
    Saw                        10       104.6           60       60 -> 105
    Roll                       12       100.0          120      120 -> 100
    Assemble/pack (Acrylic)    15        99.1           35       35 -> 99
    Fold                      329        92.6           50       50 -> 93
    Manual labour (Metal)      23        78.8           40       40 -> 79
    Assemble/pack (Metal)     166        57.9           40       40 -> 58
    Spotweld                   41        50.8           23       23 -> 51
    Weld (CO2)                110        29.0           42       42 -> 29   *** SEE BELOW ***

A LOW throughput means MORE hours, so a default that is too LOW makes us OVER-charge.
Nearly every default was too low. We have been over-charging labour on every job.

*** WELD (CO2) GOES THE OTHER WAY ***
The default of 42/hr is FASTER than Tim's measured 29.0/hr, so we have been UNDER-charging
weld. Correcting it to 29 makes weld MORE expensive — including on 1310, where the engine
already reads £3.23 against Tim's £1.25.

That is not a contradiction, and it is worth being precise about: 1310's weld problem is
NOT the throughput. It is the SETUP being booked per part (30 min per row, £20.89 a time).
Fixing the throughput correctly will push 1310's weld UP before the grouping fix pulls it
down. Expect that, and do not read it as a regression.

I earlier claimed the defaults were "2-3x too slow across the board" from a single P.Coat
figure of 957/hr on job 1298. The corpus says P.Coat averages 458 and our 424 was close to
right. That claim was wrong; these are the measured numbers.

Usage (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _apply_measured_throughputs.py
"""
from __future__ import annotations
import shutil, sys, datetime, os

TARGET = r"C:\ClaudeVision\src\wb_populate.py"
SENTINEL = "MEASURED from 1,982 historical jobs"

OLD = '''    _THROUGHPUT_DEFAULTS = {
        "Fold":                      50,    # Tim: very consistent at 50/hr
        "Tubebend":                  30,    # tube bender, heavier setup
        "Linebend":                  40,    # acrylic heat line-bend
        "Punch":                    100,    # Tim: 60–350, median ~100
        "Laser (Metal)":            180,    # Tim: 75–400, median ~180
        "Laser (Acrylic)":          120,    # slightly slower than metal
        "P.Coat":                   424,    # Tim: very consistent at 424
        "Assemble/pack (Metal)":     40,    # Tim: 5–100, median ~40
        "Assemble/pack (Acrylic)":   35,
        "Weld (CO2)":                42,    # Tim: 25–60
        "Spotweld":                  23,    # Tim: 17–30
        "Roll":                     120,
        "Saw":                       60,
        "Tube":                      40,    # tube cutting
        "Guillotine":                80,
        "Salvagnini":                60,
        "Manual labour (Metal)":     40,
        "Manual labour (Acrylic)":   40,
        "Drill (Acrylic)":           30,
    }'''

NEW = '''    # MEASURED from 1,982 historical jobs (dbo.historical_quote_labour_line, 2026-07-13).
    # Previously these were eyeballed medians. Nearly all were TOO LOW — and a low
    # throughput means MORE hours, so we were OVER-charging labour on every single job.
    # Format: op: throughput_per_hr,   # n lines in corpus | was
    _THROUGHPUT_DEFAULTS = {
        "Robomac":                  709,    # 34 lines  | WAS MISSING ENTIRELY — bar cutting
                                            #             cost £0 (1310 stud vs Tim's £0.17)
        "P.Coat":                   458,    # 316 lines | was 424 — close; my "2-3x too slow"
                                            #             claim was wrong, this one was fine
        "Laser (Metal)":            269,    # 305 lines | was 180
        "Laser (Acrylic)":          252,    # 13 lines  | was 120
        "Manual labour (Acrylic)":  122,    # 13 lines  | was 40
        "Linebend":                 118,    # 18 lines  | was 40
        "Punch":                    116,    # 126 lines | was 100
        "Salvagnini":               110,    # 26 lines  | was 60
        "Saw":                      105,    # 10 lines  | was 60
        "Roll":                     100,    # 12 lines  | was 120
        "Assemble/pack (Acrylic)":   99,    # 15 lines  | was 35
        "Fold":                      93,    # 329 lines | was 50
        "Manual labour (Metal)":     79,    # 23 lines  | was 40
        "Assemble/pack (Metal)":     58,    # 166 lines | was 40
        "Spotweld":                  51,    # 41 lines  | was 23
        "Weld (CO2)":                29,    # 110 lines | was 42 — the ONLY one where we were
                                            #             too FAST, i.e. UNDER-charging weld.
                                            #             Correcting it makes weld dearer.
        # Not present in the corpus sample — left at the previous values, and FLAGGED as
        # unmeasured rather than quietly presented as if they were derived like the rest.
        "Tubebend":                  30,    # UNMEASURED
        "Tube":                      40,    # UNMEASURED
        "Guillotine":                80,    # UNMEASURED
        "Drill (Acrylic)":           30,    # UNMEASURED
    }'''


def main():
    if not os.path.exists(TARGET):
        sys.exit(f"not found: {TARGET}")
    src = open(TARGET, "r", encoding="utf-8").read()
    if SENTINEL in src:
        sys.exit("Already applied (sentinel present).")
    n = src.count(OLD)
    if n != 1:
        sys.exit(f"ABORT: expected 1 match for _THROUGHPUT_DEFAULTS, found {n}. Nothing written.")

    src = src.replace(OLD, NEW, 1)

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{TARGET}.bak_throughputs_{ts}"
    shutil.copy2(TARGET, bak)
    open(TARGET, "w", encoding="utf-8").write(src)

    print("  ok  _THROUGHPUT_DEFAULTS replaced with measured values; Robomac added (709/hr)")
    print(f"\n  backup: {bak}")
    print(f"  written: {TARGET}")
    print("""
RUN 1310 (qty 50) and 1282 (qty 10).

EXPECT — and note that these pull in OPPOSITE directions, which is the honest picture:

  1310:
    * a ROBOMAC row finally appears                      (Tim: £0.17)
    * Laser falls   (180 -> 269/hr = fewer hours)        (Tim: £0.34)
    * Fold falls    (50 -> 93/hr)                        (Tim: £0.85)
    * Pack falls    (40 -> 58/hr)                        (Tim: £0.29)
    * WELD RISES    (42 -> 29/hr — we were under-charging)  (Tim: £1.25)
    * P.Coat barely moves (424 -> 458)                   (Tim: £2.00)

  Weld getting WORSE is expected. 1310's weld error is the 30-min SETUP booked per part,
  not the throughput. The grouping fix is what addresses that. Do not read the weld rise
  as a regression from this change.

  1282: labour should fall substantially — most defaults were too slow. It has no verified
  manual (the £168.68 sheet still needs its revision confirmed), so treat the new number as
  better-founded, NOT as validated.

THEN: the grouping fix. Send the labour loop and I will write it —

    Select-String -Path C:\\ClaudeVision\\src\\wb_populate.py `
        -Pattern "for pe in labour_parts" -Context 2,60
""")


if __name__ == "__main__":
    main()
