#!/usr/bin/env python3
r"""
_apply_unpriced_means_unpriced.py

WHY THE LAST FIX HALF-FIRED

The estimator honoured it: the JSON total moved £110.02 -> £102.30, exactly £7.72, and the
credibility ratio fell to 0% because powder had been the only "credible" cost. The decision
was made correctly.

Then wb_populate put the price back.

    wb_populate.py ~478:

        price = _safe(pe.get("unit_cost_gbp")            # <- I cleared this
                      or pe.get("unit_material_cost_gbp")     # <- but not this
                      or me.get("unit_material_cost_gbp"))    # <- or this
        if price is None:
            ext = _safe(pe.get("extended_total_cost_gbp"))
            if ext is not None and qty > 0:
                price = round(ext / qty, 4)                   # <- or this

FOUR PLACES HOLD THE SAME NUMBER, and the chain is built to KEEP LOOKING UNTIL IT FINDS ONE.
That is exactly the wrong behaviour for a part that has been DELIBERATELY unpriced. "Not
priced" is not a missing value to be recovered from a neighbouring field — it is a decision,
and the workbook was overriding it.

THIS IS THE FOURTH TIME TODAY. Same root cause every time: a value with no single home.
    1310 stud        stock_form written to the writeup record; pricing reads part_estimates
    Robomac          op written to the writeup record;         labour  reads costs_gbp
    7670 wire sched  parsed doc-level;                          attached to the powder line
    powder unpricing unit_cost_gbp cleared;                     BOM read material_estimate

TWO FIXES, BECAUSE EITHER ALONE WOULD LEAVE THE HAZARD

  A. estimator.py — clear EVERY price field on the record, not just the two I knew about.

  B. wb_populate.py — an explicit "this is unpriced" marker that SHORT-CIRCUITS the fallback
     chain entirely. This is the one that matters: it makes unpriced mean unpriced no matter
     what stale numbers survive elsewhere on the record. Without it, the next unpricing we do
     will fail the same way and we will not notice.

The BOM row still appears, with the code, the colour and the supplier — all real,
drawing-derived, and exactly what the estimator needs to price it. Only the invented money
is gone.

Usage (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _apply_unpriced_means_unpriced.py
"""
from __future__ import annotations
import shutil, sys, datetime, os

EST = r"C:\ClaudeVision\src\estimator.py"
WBP = r"C:\ClaudeVision\src\wb_populate.py"
SENTINEL = "_price_explicitly_withheld"


def sub(src, old, new, label):
    n = src.count(old)
    if n != 1:
        sys.exit(f"ABORT [{label}]: expected 1 match, found {n}. Nothing written.\n"
                 f"--- looked for ---\n{old}\n")
    print(f"  ok  {label}")
    return src.replace(old, new, 1)


# ───────────────────────── estimator.py ─────────────────────────
EST_OLD = '''                stub["unit_cost_gbp"] = None
                stub["extended_total_cost_gbp"] = None
                stub["source"] = "sdi_bom_code_unpriced"
                stub["cost_source"] = "consumable_qty_unknown_estimator_to_price"
                stub["_consumable_qty_unknown"] = True'''

EST_NEW = '''                # Clear EVERY field that holds this price. The last attempt cleared two of
                # four and wb_populate's BOM fallback chain simply moved to the next one and
                # re-priced it at £7.72. One value living in four places is the root cause of
                # four separate bugs today; until that is fixed properly, unprice defensively.
                for _pk in ("unit_cost_gbp", "unit_material_cost_gbp", "cost_per_part_gbp",
                            "extended_total_cost_gbp", "extended_material_cost_gbp",
                            "unit_total_cost_gbp"):
                    stub[_pk] = None
                _me_c = stub.get("material_estimate")
                if isinstance(_me_c, dict):
                    for _pk in ("unit_material_cost_gbp", "cost_per_part_gbp",
                                "extended_material_cost_gbp"):
                        _me_c[_pk] = None
                    _me_c["cost_method"] = "consumable_qty_unknown_estimator_to_price"
                stub["source"] = "sdi_bom_code_unpriced"
                stub["cost_source"] = "consumable_qty_unknown_estimator_to_price"
                stub["_consumable_qty_unknown"] = True
                # The explicit marker. wb_populate must honour this and NOT go hunting for a
                # price in some other field. "Not priced" is a DECISION, not a missing value.
                stub["_price_explicitly_withheld"] = True'''


# ───────────────────────── wb_populate.py ─────────────────────────
WBP_OLD = '''        qty = int(_safe(pe.get("quantity"), 1))
        price = _safe(pe.get("unit_cost_gbp")
                      or pe.get("unit_material_cost_gbp")
                      or me.get("unit_material_cost_gbp"))
        if price is None:
            ext = _safe(pe.get("extended_total_cost_gbp"))
            if ext is not None and qty > 0:
                price = round(ext / qty, 4)'''

WBP_NEW = '''        qty = int(_safe(pe.get("quantity"), 1))
        # ── "Not priced" is a DECISION, not a missing value ──────────────────────────
        # The chain below is built to KEEP LOOKING until it finds a number: four candidate
        # fields, then a division as a last resort. That is right for a part whose price is
        # merely recorded somewhere unexpected. It is WRONG for a part the estimator layer
        # has DELIBERATELY refused to price.
        #
        # 7670: the engine correctly refused to invent a powder quantity (a consumable is
        # sold by weight — "assume 1" means 1kg, and 1kg would coat 6 m2 of a 0.023 m2 wire
        # frame). It cleared unit_cost_gbp. The chain moved to unit_material_cost_gbp, found
        # £7.72 still sitting there, and put the £8.03 straight back on the sheet.
        #
        # Honour the marker and short-circuit. Whatever stale numbers survive elsewhere on
        # the record, unpriced means unpriced.
        if pe.get("_price_explicitly_withheld"):
            price = None
            _flag(f"BOM {pe.get('part_number') or (str(desc)[:30])}: price WITHHELD by the "
                  f"engine (quantity not on the drawing and cannot be guessed). Row is on the "
                  f"sheet with its code and supplier — ESTIMATOR TO PRICE. Not an error.", flags)
        else:
            price = _safe(pe.get("unit_cost_gbp")
                          or pe.get("unit_material_cost_gbp")
                          or me.get("unit_material_cost_gbp"))
            if price is None:
                ext = _safe(pe.get("extended_total_cost_gbp"))
                if ext is not None and qty > 0:
                    price = round(ext / qty, 4)'''


def main():
    for p in (EST, WBP):
        if not os.path.exists(p):
            sys.exit(f"not found: {p}")

    est = open(EST, "r", encoding="utf-8").read()
    wbp = open(WBP, "r", encoding="utf-8").read()

    if SENTINEL in est or SENTINEL in wbp:
        sys.exit("Already applied (sentinel present).")
    if "_consumable_qty_unknown" not in est:
        sys.exit("Run _apply_no_invented_consumable_qty.py first — its block is the anchor.")

    est = sub(est, EST_OLD, EST_NEW, "estimator: clear ALL price fields + explicit marker")
    wbp = sub(wbp, WBP_OLD, WBP_NEW, "wb_populate: honour the marker, short-circuit the chain")

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    for path, text, tag in ((EST, est, "estimator"), (WBP, wbp, "wbpopulate")):
        bak = f"{path}.bak_unpriced_{tag}_{ts}"
        shutil.copy2(path, bak)
        open(path, "w", encoding="utf-8").write(text)
        print(f"  backup: {bak}")

    print("""
RUN 7670 (qty 50), then 1310 and 1282.

EXPECT ON 7670 (Tim £6.74):
    * BOM row for TLP-J125-T stays, with code + supplier, and NO PRICE
    * flag: "price WITHHELD by the engine ... ESTIMATOR TO PRICE. Not an error."
    * Total Material  £8.34 -> £0.31   (the wire, and only the wire)
    * Unit Cost      £13.47 -> ~£5.44

    UNDER TIM, AND EVERY LINE ACCOUNTED FOR:
        wire      £0.31  vs £0.29   EXACT — read from a PDF, no DXF
        Robomac   £0.65  vs £1.03
        Spotweld  £2.91  vs £1.61   over (weld count is Tim's judgement, not in the geometry)
        pack      £0.64  vs £0.21   over (setup 15 min vs his 5)
        powder    £0.00  vs £0.40   NAMED GAP — wire has no sheet area
        P.Coat    £0.00  vs £1.92   NAMED GAP — assembly-level finish not modelled
        delivery  £0.00  vs £0.84   excluded by design

    No invented money anywhere on the sheet. That is the whole point.

REGRESSIONS — neither has a withheld price, so BOTH MUST BE UNCHANGED:
    1310  £9.07   (stud £0.04)
    1282  £207.16 (materials frozen)
""")


if __name__ == "__main__":
    main()
