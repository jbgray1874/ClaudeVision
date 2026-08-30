#!/usr/bin/env python3
r"""
_apply_wire_powder_v2.py

SUPERSEDES _apply_wire_powder_area.py (which was never applied — lucky, because it had a
scope bug: it looped `wire_parts` from a point in the file where that list may not have been
built yet, would have silently produced 0.0, and the powder line would have fallen through
to "withheld" without a word).

This version reads the parts from `summary`, which is in scope everywhere and carries no
ordering assumption, and anchors on `b = cm["bom"]` — a line I have actually seen — rather
than a comment I guessed at.

────────────────────────────────────────────────────────────────────────────────────────
THE HOLE

The workbook's Powder Qty Calculator derives kilograms from SHEET AREA, summed over the
Sheet Steel block. Wire and bar live in a different block with no length x width, so they
have ALWAYS contributed zero powder. It never mattered until a job (7670) was entirely wire
and the calculator returned a clean 0 against Tim's £0.40.

WHAT THIS COMPUTES — real geometry, not a guess

A wire is a CYLINDER. Its whole surface gets coated, so area = pi * d * L. (No x2 — that is
a flat SHEET, which has two faces.)

    7670-01-001   pi x 4mm x 975.4mm x1  =  0.01226 m2
    7670-01-002   pi x 4mm x 233.4mm x2  =  0.00587 m2
    7670-01-003   pi x 4mm x 424.8mm x1  =  0.00534 m2
                                            ---------
                                            0.02346 m2

Gauge and length are already on the sheet — read off a PDF with no DXF this afternoon.

WHAT IT CANNOT COMPUTE — the honest part

The COVERAGE RATE. The two candidates differ by 10x:

    template   0.1667 kg/m2  ->  0.0039 kg  ->  £0.03    (what this uses, by default)
    Tim's 7670 1.70   kg/m2  ->  0.040  kg  ->  £0.40    (his actual sheet)

0.1667 kg/m2 is 6 m2 per kilo = 100% TRANSFER EFFICIENCY. Every particle lands on the part.
On an open wire frame that is absurd — most of the cloud goes straight through the gaps.
Tim's 10x is not generosity, it is physics.

THE RATE IS WRONG FOR SHEET TOO:

    1298 bracket     0.45 kg/m2      2.7x the template
    1310 hook plate  0.82 kg/m2      4.9x    <- shipped at £0.06 vs Tim's £0.30 this morning
    7670 wire frame  1.70 kg/m2     10.2x
    template         0.167 kg/m2     1x      (physically impossible)

So this is not a wire problem. It is a template constant that is wrong on EVERY job, and
wire only made it visible by returning a clean zero instead of a quietly-wrong number.

The rate becomes a VISIBLE CONFIG LEVER with all four data points documented beside it.
Set POWDER_KG_PER_M2 = 1.70 and 7670 lands on Tim's £0.40 exactly. Deliberately NOT done:
that fits a single data point, and the next wire job would be wrong invisibly — the same
trade that produced tonight's spotweld regression. powder_rule_v2.sql q5 measures it across
the corpus, and that fix corrects every job we have ever run.

NO DOUBLE-COUNT: sheet powder stays in the workbook's own AF82/AF83. This only adds what
that calculation cannot see. The two paths do not overlap.

Usage (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _apply_wire_powder_v2.py
"""
from __future__ import annotations
import shutil, sys, datetime, os

EST = r"C:\ClaudeVision\src\estimator.py"
WBP = r"C:\ClaudeVision\src\wb_populate.py"
CFG = r"C:\ClaudeVision\src\config.py"
SENTINEL = "POWDER_KG_PER_M2"


def sub(src, old, new, label):
    n = src.count(old)
    if n != 1:
        sys.exit(f"ABORT [{label}]: expected 1 match, found {n}. NOTHING WRITTEN.\n"
                 f"--- looked for ---\n{old}\n")
    print(f"  ok  {label}")
    return src.replace(old, new, 1)


CFG_ADD = '''

# ── POWDER COVERAGE ─────────────────────────────────────────────────────────────
# Kilograms of powder per square metre of coated surface.
#
# The Excel template's Powder Qty Calculator uses 6 m2 per kilo = 0.1667 kg/m2. That is
# 100% TRANSFER EFFICIENCY — every particle lands on the part. Nothing coats at 100%.
#
# What the manual sheets actually book:
#
#     1298  bracket      0.45 kg/m2      2.7x the template
#     1310  hook plate   0.82 kg/m2      4.9x     <- we shipped 1310 5x under on 2026-07-13
#     7670  wire frame   1.70 kg/m2     10.2x     <- open frame: most of the cloud misses
#     template           0.167 kg/m2     1x
#
# The rate rises as the part gets more OPEN. That is real transfer loss, and it means this
# constant is wrong on EVERY job — not just wire.
#
# LEFT AT THE TEMPLATE'S VALUE ON PURPOSE. Setting it to 1.70 would put 7670 exactly on
# Tim's number, but that is fitting to a single data point and the next wire job would be
# wrong invisibly. powder_rule_v2.sql (query 5) measures it across the corpus. Set it from
# that, and it corrects every job at once.
POWDER_KG_PER_M2 = 0.1667
'''


EST_OLD = '''                stub["_price_explicitly_withheld"] = True'''

EST_NEW = '''                stub["_price_explicitly_withheld"] = True
                # Keep the catalogue RATE (£/kg) even though the price is withheld. We
                # withheld because we could not know the QUANTITY — not because the rate is
                # unknown. If geometry can later supply a quantity (a wire frame's coated
                # area is real, computable, and invisible to the sheet-only powder
                # calculator), the reason for withholding evaporates and we can cost it.
                try:
                    stub["_catalogue_rate_gbp"] = float(cat["unit_price_gbp"])
                except Exception:
                    pass'''


WBP_IMP_OLD = '''try:
    from config import POWDER_COST_PER_KG as _POWDER_COST_PER_KG
except Exception:
    _POWDER_COST_PER_KG = None  # fall back to whatever the template holds'''

WBP_IMP_NEW = '''try:
    from config import POWDER_COST_PER_KG as _POWDER_COST_PER_KG
except Exception:
    _POWDER_COST_PER_KG = None  # fall back to whatever the template holds
# Coverage: kg of powder per m2 of coated surface. The template's own calculator uses
# 0.1667 (= 6 m2/kg = 100% transfer efficiency, which nothing achieves). See config.py.
try:
    from config import POWDER_KG_PER_M2 as _POWDER_KG_PER_M2
except Exception:
    _POWDER_KG_PER_M2 = 0.1667'''


WBP_CALC_OLD = '''    b = cm["bom"]
    row = b["first_row"]
    for pe in bom_parts:'''

WBP_CALC_NEW = '''    # ── Powder on WIRE / BAR — the area the workbook cannot see ─────────────────
    # The Powder Qty Calculator sums SHEET area over the Sheet Steel block. Wire and bar
    # live in a different block with no length x width, so they have ALWAYS contributed
    # zero powder. It only surfaced when a job (7670) was entirely wire and the calculator
    # returned a clean 0 against Tim's £0.40.
    #
    # A wire is a CYLINDER: its whole surface is coated, so area = pi * d * L. (No x2 —
    # that is a flat sheet, which has two faces.) Gauge and length are already on the
    # sheet; we read them off the PDF.
    #
    # Read from `summary`, NOT from wire_parts: that list may not be built yet at this
    # point in the file, and an empty loop would silently produce 0.0 and drop the powder
    # line without a word. `summary` is in scope everywhere.
    #
    # Sheet powder stays in the workbook's own AF82/AF83. This adds only what that
    # calculation cannot see, so nothing is double-counted.
    _wire_powder_area_m2 = 0.0
    _wire_powder_diag = []
    _all_pes_pw = ((summary.get("estimate_summary") or {}).get("part_estimates")
                   or summary.get("parts") or [])
    for _wp in _all_pes_pw:
        _wme = _wp.get("material_estimate") or {}
        if str(_wme.get("stock_form") or "").lower() not in ("wire", "bar"):
            continue
        _wg = _safe(_wme.get("wire_gauge_mm") or _wp.get("wire_gauge_mm"))
        _wl = _safe(_wme.get("wire_length_mm") or _wp.get("wire_length_mm"))
        _wq = _safe(_wp.get("quantity"), 1) or 1
        _wire_powder_diag.append(f"{_wp.get('part_number')}(g={_wg},l={_wl},q={_wq})")
        if _wg and _wl:
            _wire_powder_area_m2 += 3.14159265 * (_wg / 1000.0) * (_wl / 1000.0) * float(_wq)
    _wire_powder_kg = round(_wire_powder_area_m2 * float(_POWDER_KG_PER_M2), 5)
    if _wire_powder_diag and _wire_powder_kg <= 0:
        # Never fail silently. If wire parts exist but the area is zero, say what they held.
        _flag(f"powder: found {len(_wire_powder_diag)} wire/bar part(s) but computed ZERO "
              f"coated area — {'; '.join(_wire_powder_diag)}. Powder NOT costed on the wire; "
              f"gauge/length missing from the pricing record.", flags)

    b = cm["bom"]
    row = b["first_row"]
    for pe in bom_parts:'''


WBP_BOM_OLD = '''        if pe.get("_price_explicitly_withheld"):
            price = None
            _flag(f"BOM {pe.get('part_number') or (str(desc)[:30])}: price WITHHELD by the "
                  f"engine (quantity not on the drawing and cannot be guessed). Row is on the "
                  f"sheet with its code and supplier — ESTIMATOR TO PRICE. Not an error.", flags)'''

WBP_BOM_NEW = '''        if pe.get("_price_explicitly_withheld"):
            _cat_rate = _safe(pe.get("_catalogue_rate_gbp"))
            _is_consumable_line = bool(pe.get("_consumable_qty_unknown")) or \\
                                  "POWDER" in str(pe.get("part_number") or "").upper()
            if _is_consumable_line and _cat_rate and _wire_powder_kg > 0:
                # We withheld because we could not know the QUANTITY. We now can: the wire's
                # coated area is real geometry (pi x d x L) that the workbook's sheet-only
                # calculator cannot see. So cost it — and say exactly how, and how wrong the
                # rate is.
                price = _cat_rate
                qty = _wire_powder_kg
                _flag(f"POWDER computed from WIRE geometry: {_wire_powder_area_m2:.5f} m2 of "
                      f"coated surface (pi x dia x length) x {_POWDER_KG_PER_M2} kg/m2 = "
                      f"{_wire_powder_kg} kg @ £{_cat_rate:.2f}/kg. "
                      f"COVERAGE RATE IS THE TEMPLATE'S {_POWDER_KG_PER_M2} kg/m2 = 100% "
                      f"TRANSFER EFFICIENCY, which nothing achieves. Tim's sheet for THIS job "
                      f"implies 1.70 kg/m2 (an open wire frame lets most of the cloud "
                      f"through) — about 10x this. His sheets imply 2.7x-4.9x even on FLAT "
                      f"parts. THIS LINE UNDER-READS until the rate is measured "
                      f"(config.POWDER_KG_PER_M2). Estimator to check.", flags)
            else:
                price = None
                _flag(f"BOM {pe.get('part_number') or (str(desc)[:30])}: price WITHHELD by the "
                      f"engine (quantity not on the drawing and cannot be guessed). Row is on "
                      f"the sheet with its code and supplier — ESTIMATOR TO PRICE. Not an "
                      f"error.", flags)'''


def main():
    for p in (EST, WBP, CFG):
        if not os.path.exists(p):
            sys.exit(f"not found: {p}")

    cfg = open(CFG, "r", encoding="utf-8").read()
    est = open(EST, "r", encoding="utf-8").read()
    wbp = open(WBP, "r", encoding="utf-8").read()

    if SENTINEL in cfg or SENTINEL in wbp:
        sys.exit("Already applied (sentinel present).")
    if "POWDER_COST_PER_KG" not in cfg:
        sys.exit("config.py: POWDER_COST_PER_KG not found — wrong file?")
    if "_price_explicitly_withheld" not in est:
        sys.exit("estimator.py: run _apply_unpriced_means_unpriced.py first.")

    # do every substitution BEFORE writing anything — an abort leaves all three files untouched
    est = sub(est, EST_OLD, EST_NEW, "estimator: keep the catalogue £/kg when withholding")
    wbp = sub(wbp, WBP_IMP_OLD,  WBP_IMP_NEW,  "wb_populate: import the coverage rate")
    wbp = sub(wbp, WBP_CALC_OLD, WBP_CALC_NEW, "wb_populate: wire coated area (pi.d.L), order-independent")
    wbp = sub(wbp, WBP_BOM_OLD,  WBP_BOM_NEW,  "wb_populate: cost the powder row from it")
    cfg = cfg.rstrip() + "\n" + CFG_ADD
    print("  ok  config: POWDER_KG_PER_M2 — a VISIBLE lever, not an orphan")

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    for path, text, tag in ((CFG, cfg, "config"), (EST, est, "estimator"), (WBP, wbp, "wbpop")):
        bak = f"{path}.bak_wirepowder2_{tag}_{ts}"
        shutil.copy2(path, bak)
        open(path, "w", encoding="utf-8").write(text)
        print(f"  backup: {bak}")

    print("""
RUN 7670 (qty 50), then 1310 and 1282.

EXPECT ON 7670:
    * flag: "POWDER computed from WIRE geometry: 0.02346 m2 ... 0.00391 kg @ £7.72/kg"
    * BOM powder row PRICED:  0.00391 kg @ £7.72  ->  ~£0.03     (Tim £0.40)
    * unit cost  £7.58 -> ~£7.62

    £0.03 vs £0.40 IS THE COVERAGE RATE, NOT THE GEOMETRY. The area (0.02346 m2) is right.
    ONE LINE:  config.POWDER_KG_PER_M2 = 1.70  ->  7670 lands on £0.40 exactly.
    Not done on purpose — one data point. Measure it (powder_rule_v2.sql q5) and every job
    we have ever run gets corrected at once, including 1310's £0.06-vs-£0.30.

    If it STILL does not fire, the console now prints every wire part with the gauge and
    length it carried. No fourth guess.

REGRESSIONS — neither has a powder BOM line, so BOTH MUST BE UNCHANGED:
    1310  £9.07     1282  £207.16
""")


if __name__ == "__main__":
    main()
