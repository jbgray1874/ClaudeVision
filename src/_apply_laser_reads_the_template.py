#!/usr/bin/env python3
r"""
_apply_laser_reads_the_template.py

DAVE: "it's a tiny part - the throughput can be a lot higher than we're suggesting."

He is right, and the proof was already on our own sheet. The template has a LASER RATE
CALCULATOR built into the Sheet Steel block, and we WRITE ITS INPUTS on every run:

    P63 = 60/K63           load/unload, divided across parts-per-sheet
    Q63 = LOOKUP(gauge)    cutting speed  -> 2mm = 75 mm/sec
    R63 = (F63+G63)*2/Q63  profile cut    -> perimeter / speed
    U63 = T63/Q63 + S63    internal cuts + hole count
    V63 = P63+R63+U63      TOTAL SECONDS  -> 11.57
    W63 = 3600/V63         PIECES PER HOUR -> 311.1

The estimators' own calculator says 311/hr for 1310-01. Tim books 300.
And then our labour block overwrites it with 80/hr from a second, worse time model.

    ours:      45 seconds a part
    template:  12 seconds a part
    Tim:       12 seconds a part

Nearly 4x slow, and it is the single biggest error on 1310: laser GBP 1.08 vs Tim's 0.34.

THIS IS THE SAME DISEASE AS THE POWDER RATE AND THE STEEL RATE

The template already knew. We substituted a guess. Contrast Fold: there is NO fold
calculator in the template, so Tim judges it (90/hr) and we derive it from bend count
(93.76) - and we agree. Where the geometry carries the answer we are right. Where the
TEMPLATE carries the answer we were ignoring it.

THE FIX

Write the laser throughput as a FORMULA referencing the calculator's own output, instead
of a number from our model. For a single part that is simply 3600/V. For a group of parts
sharing one setup, it is the correctly weighted rate:

    throughput = 3600 * SUM(qty) / SUM(qty x seconds)

which for one part collapses to 3600/V = the W column exactly.

Two things fall out of this for free:
  * it tracks any change the estimators make to their cutting speeds, forever
  * it is visibly THEIR number on the sheet, not ours

NOT TOUCHED: Laser (Acrylic). The template has a separate CNC Rate Calculator for the
Other Sheet block and I have not read its columns yet. One change at a time. 12439 will
need it.

Usage (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _apply_laser_reads_the_template.py
"""
from __future__ import annotations
import shutil, sys, datetime, os

TARGET = r"C:\ClaudeVision\src\wb_populate.py"
SENTINEL = "_steel_row_by_pn"


def sub(src, old, new, label):
    n = src.count(old)
    if n != 1:
        sys.exit(f"ABORT [{label}]: expected 1 match, found {n}. NOTHING WRITTEN.\n"
                 f"--- looked for ---\n{old}\n")
    print(f"  ok  {label}")
    return src.replace(old, new, 1)


# 1. Remember which sheet-steel row each part landed on.
OLD_1 = '''        ws.cell(row=row, column=s["col_length"], value=length)
        ws.cell(row=row, column=s["col_width"],  value=width)
        ws.cell(row=row, column=s["col_gauge"],  value=gauge)'''

NEW_1 = '''        ws.cell(row=row, column=s["col_length"], value=length)
        ws.cell(row=row, column=s["col_width"],  value=width)
        ws.cell(row=row, column=s["col_gauge"],  value=gauge)
        # Which row did this part land on? The template's own Laser Rate Calculator
        # computes a throughput on THIS row (col W = 3600/V). The labour block should
        # READ that, not substitute our own model — ours is ~4x slow on small parts.
        _steel_row_by_pn[str(pe.get("part_number") or "")] = row'''


# 2. Declare the map before the steel loop runs.
OLD_2 = '''    # ── Steel block: desc, qty, length, width, gauge ───────────────────────'''

NEW_2 = '''    # part_number -> the Sheet Steel row it was written to. Used below so the Laser
    # labour row can reference the template's OWN rate calculator instead of our model.
    _steel_row_by_pn = {}

    # ── Steel block: desc, qty, length, width, gauge ───────────────────────'''


# 3. The laser labour row reads the calculator.
OLD_3 = '''        if (wb_op in _ONE_ROW_PER_JOB or wb_op in _PER_PART_OPS) and default_tp:
            ws.cell(row=row, column=lb["col_throughput"], value=float(default_tp))
        else:
            bh = g["bh"]'''

NEW_3 = '''        # ── THE TEMPLATE ALREADY COMPUTES THE LASER RATE. READ IT. ──────────────────
        # Sheet Steel block, per row:  V = total seconds,  W = 3600/V = pieces per hour.
        # Every input to it (blank L/W, gauge, hole count, internal cut) is written by
        # THIS module on every run. For 1310-01 it computes 311.1/hr; Tim books 300.
        # We were writing 80 — our own second, worse time model — and over-charging the
        # laser by 3-4x on small parts.
        #
        # For a group of parts sharing one setup, the correct combined rate is
        #     3600 * SUM(qty) / SUM(qty * seconds)
        # which for a single part collapses to 3600/V, i.e. exactly the W column.
        #
        # Written as a FORMULA, not a value, so it tracks any change the estimators make
        # to their own cutting speeds — and so it is visibly THEIR number, not ours.
        _laser_formula = None
        if wb_op == "Laser (Metal)":
            _rws = [_steel_row_by_pn.get(str(_p)) for _p in (g.get("parts") or [])]
            _rws = [_r for _r in _rws if _r]
            if _rws:
                _qs = "+".join("E%d" % _r for _r in _rws)
                _ts = "+".join("E%d*V%d" % (_r, _r) for _r in _rws)
                _fb = float(default_tp or 269)
                _laser_formula = "=IFERROR(3600*(%s)/(%s),%s)" % (_qs, _ts, _fb)

        if _laser_formula:
            ws.cell(row=row, column=lb["col_throughput"], value=_laser_formula)
            _flag(f"laser throughput now READS THE TEMPLATE'S OWN Laser Rate Calculator "
                  f"(rows {_rws}) instead of the engine's time model. The calculator uses "
                  f"the estimators' cutting speeds, the blank size, the hole count and the "
                  f"internal cut distance — all of which we already write into it. On 1310 "
                  f"it computes 311/hr where our model said 80 (Tim books 300).", flags)
        elif (wb_op in _ONE_ROW_PER_JOB or wb_op in _PER_PART_OPS) and default_tp:
            ws.cell(row=row, column=lb["col_throughput"], value=float(default_tp))
        else:
            bh = g["bh"]'''


def main():
    if not os.path.exists(TARGET):
        sys.exit(f"not found: {TARGET}")
    src = open(TARGET, "r", encoding="utf-8").read()
    if SENTINEL in src:
        sys.exit("Already applied (sentinel present).")

    src = sub(src, OLD_2, NEW_2, "declare the part -> steel-row map")
    src = sub(src, OLD_1, NEW_1, "record each part's steel row as it is written")
    src = sub(src, OLD_3, NEW_3, "laser labour row reads the template's rate calculator")

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{TARGET}.bak_laserreadstemplate_{ts}"
    shutil.copy2(TARGET, bak)
    open(TARGET, "w", encoding="utf-8").write(src)

    print(f"\n  backup: {bak}")
    print("""
RUN 1310 (qty 50), THEN 1282 (qty 10).

EXPECT ON 1310:
    * Laser (Metal) throughput cell now holds a FORMULA, not 80
    * Excel resolves it to ~311/hr on open           (Tim books 300)
    * Laser  GBP 1.08 -> ~GBP 0.35                   (Tim GBP 0.34)
    * unit cost ~8.29 -> ~7.55                       (Tim 6.90)

1282 WILL MOVE, AND IT SHOULD:
    Its Laser (Metal) 1.2mm row groups SIX parts at a derived 77.7/hr. The calculator
    will price each part on its own geometry and weight them properly. Expect laser to
    DROP — we have been over-charging it there too. Diff the workbook and read every
    changed cell; the ONLY cells that may move are the two laser throughputs and the
    totals that follow from them. Anything else moving is a bug.

        C:\\ClaudeVision\\.venv\\Scripts\\python.exe _1282_diff.py ^
            "...1282...20260714_121930.xlsx" "...<new>.xlsx"

WHAT THIS DOES NOT FIX
    Laser (Acrylic) still uses our model — the template has a SEPARATE CNC Rate
    Calculator for the Other Sheet block and I have not read its columns. 12439 needs it.
    Assemble/pack and P.Coat still substitute a default; the size-band medians
    (90/hr and 638/hr for small parts) are the measured answer there.
    Weld still needs a weld count that is in no drawing. Only Tim has that.
""")


if __name__ == "__main__":
    main()
