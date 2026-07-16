#!/usr/bin/env python3
r"""
_apply_no_invented_consumable_qty.py

THE BUG (estimator.py:3218-3224)

    stub["extended_total_cost_gbp"] = round(cat["unit_price_gbp"] * _use_qty, 2)
    ...
    _qnote = (f"qty {_use_qty} from BOM table" if _qty_known
              else "qty defaulted to 1 (not in structured BOM) — estimator to confirm")

On 7670 the drawing carries the code POWDER308. The quantity is NOT on the drawing, so
_use_qty defaulted to 1 and the engine priced ONE KILOGRAM of powder at £7.72/kg -> £8.03.

The part it is coating is a wire frame with 0.023 m2 of surface. A kilo of powder covers
roughly 6 m2. We charged 300x more powder than the part can physically hold — and it became
the single largest line on the estimate, on a job whose true total is £6.74.

THE DISTINCTION THAT MATTERS

    DISCRETE item (a rivet, a junction box, a light):  "assume 1" is a defensible default.
    CONSUMABLE sold by weight/volume (powder, paint):  "assume 1" means ONE KILOGRAM.

The second is not a default. It is a fabricated number wearing a price tag, and the engine's
own flag admits it ("qty defaulted to 1 — estimator to confirm") while pricing it anyway. A
warning next to a wrong number is not the same as not producing the wrong number.

A LATENT DOUBLE-COUNT, FOUND WHILE FIXING THIS

Powder is costed TWICE in this template:
    1. the workbook's Powder Qty Calculator -> AF82/AF83 -> added into Total Material (M92)
    2. AND as a BOM line, whenever the text scan finds a powder code

On 7670 that did not double-count only by luck: the calculator returns 0 for wire parts
(they have no sheet area), so path 1 contributed nothing. A job with BOTH sheet parts AND a
powder code in the drawing text would pay for its powder twice, silently. This patch closes
that too, because the BOM line stops carrying money.

THE FIX

When the quantity is unknown AND the code is a consumable, keep the row — the code and the
colour are real, drawing-derived and useful to the estimator — but DO NOT PRICE IT. Flag it
loudly and let the estimator supply the quantity.

WHAT THIS DOES *NOT* FIX, AND MUST BE SAID

  * COLOUR. POWDER308 is RYOBI Lime Green. The job is AEG **ORANGE**. The drawing's finish
    table lists every customer variant (RYOBI green, MILWAUKEE red, ...) and the engine took
    the first one. That is a VARIANT-SELECTION failure, it is architectural, and it will bite
    on any multi-customer drawing. Not touched here.

  * QUANTITY MODEL. Tim books 0.04kg for this frame. We now book nothing, and say so. The
    workbook's calculator only understands sheet area, so wire jobs get zero powder. The
    coverage rate itself is unresolved — four manual sheets give 0.084 to 1.74 kg/m2, and
    1282 sits BELOW the calculator's theoretical 0.167, which no transfer-efficiency model
    can explain. powder_rule.sql measures it properly across 1,982 jobs. Until that lands,
    an honest zero with a loud flag beats a confident wrong number.

Usage (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _apply_no_invented_consumable_qty.py
"""
from __future__ import annotations
import shutil, sys, datetime, os

TARGET = r"C:\ClaudeVision\src\estimator.py"
SENTINEL = "_consumable_qty_unknown"

OLD = '''            _qnote = (f"qty {_use_qty} from BOM table" if _qty_known
                      else "qty defaulted to 1 (not in structured BOM) \u2014 estimator to confirm")'''

NEW = '''            _qnote = (f"qty {_use_qty} from BOM table" if _qty_known
                      else "qty defaulted to 1 (not in structured BOM) \u2014 estimator to confirm")

            # ── CONSUMABLES: never invent a quantity ─────────────────────────────────
            # For a DISCRETE item (rivet, junction box, light) "assume 1" is a defensible
            # default. For a CONSUMABLE sold by WEIGHT or VOLUME, "assume 1" means ONE
            # KILOGRAM — which is not a default, it is a fabricated number with a price on it.
            #
            # 7670: the drawing carries POWDER308 but no quantity. The engine priced 1kg at
            # £7.72 -> £8.03, to coat a wire frame with 0.023 m2 of surface. A kilo covers
            # ~6 m2. That is 300x more powder than the part can physically hold, and it became
            # the biggest line on a £6.74 job.
            #
            # Powder is ALSO costed by the workbook's own Powder Qty Calculator (AF82/AF83 ->
            # Total Material). A priced BOM line therefore risks DOUBLE-COUNTING on any job
            # with both sheet parts and a powder code in the drawing text. On 7670 that only
            # escaped because the calculator returns 0 for wire. Dropping the money from this
            # line closes that hazard too.
            #
            # Keep the ROW: the code and colour are real, drawing-derived and useful. Drop the
            # invented money and say plainly that the estimator must supply the quantity.
            if (not _qty_known) and any(
                str(code or "").upper().startswith(_cp)
                for _cp in ("POWDER", "PAINT", "LACQUER", "PRIMER",
                            "ADHESIVE", "SEALANT", "SOLVENT")
            ):
                stub["unit_cost_gbp"] = None
                stub["extended_total_cost_gbp"] = None
                stub["source"] = "sdi_bom_code_unpriced"
                stub["cost_source"] = "consumable_qty_unknown_estimator_to_price"
                stub["_consumable_qty_unknown"] = True
                stub.setdefault("review_flags", []).append(
                    f"CONSUMABLE {code}: NOT PRICED. The quantity is not on the drawing, and a "
                    f"consumable is sold by weight/volume \u2014 defaulting to 1 would mean 1kg "
                    f"(that is how this line reached \u00a38.03 on a \u00a36.74 job). Estimator to "
                    f"supply the quantity. Catalogue rate \u00a3{cat['unit_price_gbp']:.2f}/unit"
                    + (f", {cat['supplier']}" if cat.get("supplier") else "")
                    + ". NOTE: powder is also computed by the workbook's Powder Qty Calculator, "
                      "which only understands SHEET area \u2014 wire/tube parts contribute nothing, "
                      "so a wire job gets zero powder until that is fixed."
                )'''


def main():
    if not os.path.exists(TARGET):
        sys.exit(f"not found: {TARGET}")
    src = open(TARGET, "r", encoding="utf-8").read()
    if SENTINEL in src:
        sys.exit("Already applied (sentinel present).")

    n = src.count(OLD)
    if n != 1:
        sys.exit(f"ABORT: expected 1 match, found {n}. Nothing written.\n"
                 f"(Note estimator.backup.py has the same text — this patch targets "
                 f"estimator.py ONLY. There are also six copies of file_scan in src; "
                 f"the stale-copy hazard is real and still on the backlog.)")

    src = src.replace(OLD, NEW, 1)

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{TARGET}.bak_consumableqty_{ts}"
    shutil.copy2(TARGET, bak)
    open(TARGET, "w", encoding="utf-8").write(src)

    print("  ok  consumables are no longer priced on an invented quantity")
    print(f"\n  backup: {bak}")
    print(f"  written: {TARGET}")
    print("""
RUN 7670 (qty 50), then 1310 and 1282 as regressions.

EXPECT ON 7670 (Tim £6.74):
    * the POWDER308 row STAYS on the sheet, with NO price and a loud flag
    * unit cost £13.47 -> ~£5.44

    AND THAT IS *UNDER* TIM, WHICH IS THE HONEST POSITION:
        powder      £0.00  vs Tim £0.40   (not costed; wire has no sheet area)
        P.Coat      £0.00  vs Tim £1.92   (assembly-level finish, not modelled)
        poly/pallet/delivery £0.00 vs £0.84  (excluded by design)
        wire        £0.31  vs Tim £0.29   EXACT
        Robomac     £0.65  vs Tim £1.03
        Spotweld    £2.91  vs Tim £1.61   (over — weld count is Tim's judgement)
        pack        £0.64  vs Tim £0.21   (setup 15 min vs his 5)

    Every line is now either right, or a NAMED gap. No invented money anywhere.

REGRESSIONS — neither has a powder BOM line, so BOTH MUST BE UNCHANGED:
    1310: £9.07, stud £0.04
    1282: £207.16, materials frozen
    If either moves, this patch has reached further than the consumable branch: revert.

NEXT, IN ORDER OF SIZE:
    1. powder_rule.sql — measure the quantity rule across 1,982 jobs. Four manual sheets
       give 0.084 to 1.74 kg/m2 and 1282 sits BELOW the calculator's theoretical floor,
       so no transfer-efficiency model survives contact with the data. Measure it.
    2. Variant selection. POWDER308 is RYOBI's lime green on an AEG orange job, because the
       drawing's finish table lists every customer and the engine took the first. Any
       multi-customer drawing has this problem. 1282 is literally the Milwaukee variant of
       something.
    3. Assembly-level finish (raw parts, coated weldment) — Tim's £1.92.
""")


if __name__ == "__main__":
    main()
