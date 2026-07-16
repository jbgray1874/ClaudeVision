#!/usr/bin/env python3
r"""
_apply_pcoat_onerow_and_robomac.py

TWO FIXES. The first is correcting my own mistake.

------------------------------------------------------------------------------------
FIX 1 — P.Coat is ONE row per job, not one per gauge
------------------------------------------------------------------------------------
1310 currently books TWO P.Coat rows:

    P.Coat — 2mm MILD STEEL (1310-01)    £3.35
    P.Coat — 8mm MILD STEEL (1310-02)    £2.55
                                         -----
                                         £5.90        Tim: £2.00

I keyed the grouping on (operation, material, gauge) across the board. That is right for
FOLD, where the gauge IS the tooling — you set the press brake for 1.2mm, run the 1.2mm
parts, change tooling for 1.0mm. It is WRONG for POWDER: the booth does not care how thick
the metal is. One colour, one line, one oven run, ONE setup.

On this job it is more obviously wrong still: the stud is WELDED TO THE HOOK PLATE and the
assembly goes through powder as a single object. We are charging two coating setups to coat
one thing.

I raised this exact doubt before writing the patch ("does the powder line really need a
fresh setup per gauge? my instinct says no") and then keyed it on gauge anyway. Correcting
it: P.Coat moves into _ONE_ROW_PER_JOB.

Fold / Laser / Punch stay grouped by gauge — for those, gauge genuinely is the tooling.

------------------------------------------------------------------------------------
FIX 2 — Robomac never reaches the labour rows
------------------------------------------------------------------------------------
document_builder puts 'robomac' on the part's operations, and the throughput is now in
_THROUGHPUT_DEFAULTS (709/hr, measured from 34 corpus lines). But no Robomac row appears,
so the bar is cut for free — against Tim's £0.17.

Cause: the THIRD occurrence today of the two-record split. wb_populate reads operations from

    part_estimate.labour_estimate.costs_gbp        <-- the PRICING record

but document_builder wrote 'robomac' onto

    manufacturing_writeup.parts[].operations       <-- the WRITE-UP record

The op exists, on the wrong record. Rather than plumb the pricing layer (a bigger change,
and the pricing layer has no bar time model to offer anyway), inject the row directly in the
labour pass: any part whose stock_form is 'wire' gets a Robomac group.

This is the SAME class of rule as "sheet steel gets lasered" — a manufacturing route, not a
drawing reading. A solid bar is cut on the Robomac. Nobody writes that on a drawing, and the
engine already infers laser+fold for sheet on exactly this basis.

The throughput is the corpus median (709/hr), NOT back-solved from Tim's £0.17. There is a
real difference between a measured rate and a number reverse-engineered to make one job come
out right.

Usage (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _apply_pcoat_onerow_and_robomac.py
"""
from __future__ import annotations
import shutil, sys, datetime, os

TARGET = r"C:\ClaudeVision\src\wb_populate.py"
SENTINEL = "_ROBOMAC_STOCK_FORMS"


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
    if "_ONE_ROW_PER_JOB" not in src:
        sys.exit("Labour grouping not applied yet — run _apply_labour_grouping.py first.")

    # ---- FIX 1: P.Coat is one row per job -----------------------------------
    src = sub(src,
              '''    _ONE_ROW_PER_JOB = {"Assemble/pack (Metal)", "Assemble/pack (Acrylic)",
                        "Weld (CO2)", "Spotweld", "Dress Welds"}
    _PACK_OPS = {"Assemble/pack (Metal)", "Assemble/pack (Acrylic)"}''',
              '''    # P.Coat belongs here, NOT grouped by gauge. The powder booth does not care how
    # thick the metal is: one colour, one line, one oven run, ONE setup. On 1310 the stud
    # is welded to the hook plate and the assembly goes through powder as a single object —
    # grouping by gauge charged two coating setups to coat one thing (£5.90 vs Tim's £2.00).
    # Fold/Laser/Punch stay grouped by gauge, where the gauge genuinely IS the tooling.
    _ONE_ROW_PER_JOB = {"Assemble/pack (Metal)", "Assemble/pack (Acrylic)",
                        "Weld (CO2)", "Spotweld", "Dress Welds",
                        "P.Coat"}
    _PACK_OPS = {"Assemble/pack (Metal)", "Assemble/pack (Acrylic)"}
    # A solid round bar is cut on the Robomac. This is a MANUFACTURING ROUTE (material form
    # -> machine), the same class of rule as "sheet steel gets lasered" — which the engine
    # already infers without anyone writing it on a drawing. document_builder does add
    # 'robomac' to the part's operations, but wb_populate reads ops from the PRICING record
    # (part_estimate.labour_estimate.costs_gbp), and the op was written to the WRITE-UP
    # record. Rather than plumb the pricing layer — which has no bar time model to offer
    # anyway — inject the row here from stock_form.
    _ROBOMAC_STOCK_FORMS = {"wire"}''',
              "P.Coat -> one row per job; Robomac stock-form set added")

    # ---- FIX 2: inject a Robomac group for bar/wire parts --------------------
    src = sub(src,
              '''            g["qty"] += _qty_pu
            _bh = _safe(batch_hours.get(op))
            if _bh and _bh > 0:
                g["bh"] += float(_bh)
            if _pn and _pn not in g["parts"]:
                g["parts"].append(_pn)''',
              '''            g["qty"] += _qty_pu
            _bh = _safe(batch_hours.get(op))
            if _bh and _bh > 0:
                g["bh"] += float(_bh)
            if _pn and _pn not in g["parts"]:
                g["parts"].append(_pn)

        # Robomac: a solid bar has to be CUT, and no upstream record delivers that op to the
        # pricing layer. Inject it from the stock form — same manufacturing-route reasoning
        # that already gives sheet steel its laser. Throughput 709/hr is the corpus median
        # (34 lines), NOT back-solved from Tim's £0.17.
        if str(_sf or "").lower() in _ROBOMAC_STOCK_FORMS:
            _rg = _groups.setdefault(("Robomac", "", ""), {
                "wb_op": "Robomac", "material": _mat, "thickness": 0,
                "qty": 0, "bh": 0.0, "parts": [], "bends": 0, "holes": 0,
            })
            _rg["qty"] += _qty_pu
            if _pn and _pn not in _rg["parts"]:
                _rg["parts"].append(_pn)''',
              "Robomac row injected for wire/bar stock")

    # ---- FIX 3: Robomac uses the measured default, not a derived value -------
    src = sub(src,
              '        if wb_op in _ONE_ROW_PER_JOB and default_tp:',
              '        if (wb_op in _ONE_ROW_PER_JOB or wb_op == "Robomac") and default_tp:',
              "Robomac uses the measured 709/hr default (no geometry to derive from)")

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{TARGET}.bak_pcoatrobo_{ts}"
    shutil.copy2(TARGET, bak)
    open(TARGET, "w", encoding="utf-8").write(src)

    print(f"\n  backup: {bak}")
    print(f"  written: {TARGET}")
    print("""
RUN 1310 (qty 50), then 1282 (qty 10).

EXPECT ON 1310 (Tim £6.90):
    ONE P.Coat row, not two          £5.90 -> ~£2.60      (Tim £2.00)
    ONE Robomac row appears          absent -> ~£0.20     (Tim £0.17)
    unit cost                        £11.62 -> ~£8.30     (Tim £6.90)

WHAT WILL STILL BE OVER — named, not excused:
    Laser  £1.08 vs £0.34 — the batch_hours 2-min floor. A real, separate defect.
    Pack   £0.64 vs £0.29 — Tim books 5 min setup; the WB table says 15.
    P.Coat ~£2.60 vs £2.00 — corpus setup average is 6.0 min; the table says 15.

The last two are the SAME question, and it is a question for Tim, not for me:
"your dept table books 15 minutes of P.Coat setup, but across 316 historical lines you
average 6 — which is right?" Changing his template on a guess would be worse than the gap.

EXPECT ON 1282 (qty 10):
    P.Coat collapses to ONE row (was 4, would have been 9 after the powder-pointer fix)
    a Robomac row only if the job has bar parts — it has none, so NO Robomac row
    labour falls further

    MATERIALS MUST NOT MOVE. If any material number changes, revert.
""")


if __name__ == "__main__":
    main()
