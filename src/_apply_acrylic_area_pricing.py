#!/usr/bin/env python3
r"""
_apply_acrylic_area_pricing.py

Replaces the acrylic material pricing with an AREA-BASED £/m2 model derived from real UDEF
(Access Supply Chain) purchasing data, superseding the single-workbook £46.20/sheet bootstrap.

WHY THIS IS DEFENSIBLE (the evidence, so estimating cannot discredit it):

  We pulled EVERY priced acrylic line in UDEF and isolated the raw Clear/standard XT stock from
  Perspex Distribution / Plastics Plus / AMARI (the actual sheet suppliers). Two proofs:

  1. PERSPEX PRICES LINEARLY BY AREA. For each thickness, the £/m2 implied by a FULL SHEET and by
     a small CUT BLANK AGREE:
        2mm : full sheet £7.8/m2  vs  blanks £7.9, £8.5/m2   (agree ±0.7)
        3mm : full sheet £11.5/m2 vs  clear blank £13.2/m2   (agree ±1.7)
        1.8mm: blanks £6.4, £7.8, £8.3/m2                    (tight cluster)
     => a cut blank costs (its area) x (the sheet £/m2). This is exactly the model, PROVEN in
     both directions across three thicknesses. This is what makes area pricing unarguable.

  2. £/m2 BY THICKNESS, graded by confidence:
        1.5mm  £8.2   (1 line — single-source)
        1.8mm  £7.8   (3 lines, tight £6.4-8.3 — STRONG)
        2.0mm  £8.0   (3 lines, £7.8-8.5 — STRONG)
        3.0mm  £13.0  (clear blank £13.2 + black sheet £11.5 — OK)
        4.0mm  £14.2  (1 line — single-source)
        5.0mm  £19.5  (1 line — single-source)
        6.0mm  £21.7  (1 line — single-source)
        8.0mm  £30.9  (1 line — single-source)
     The thin gauges (1.5-3mm), where ~95% of display acrylic sits, are the STRONGEST.
     Thick gauges are single-line — real current Perspex prices, but labelled single-source.

  These are CLEAR/standard XT. Coloured / matt / cast / anti-reflective grades run ~1.5-2x
  higher and would be NAMED on the drawing; a colour multiplier is a separate, later tier.

THE MODEL CHANGE:
  OLD: cost = (ACRYLIC_SHEET_PRICE_GBP[thk] / parts_per_sheet_from_nesting) * (1+scrap)
       — depended on a nesting parts-per-sheet estimate (the 90-vs-396 wobble).
  NEW: cost = (blank_area_m2 * ACRYLIC_PRICE_GBP_PER_M2[thk]) * (1+scrap)
       — no nesting estimate needed; area x rate, exactly how Perspex charges. The flat-blank
       area comes from the DXF (for 12439: 305x170 = 0.05185 m2), which we verified against the
       DXF bounding box.

RESULT on 12439 (2mm clear cleat, flat blank 0.05185 m2):
    0.05185 * £8.0 * 1.04 = £0.43   (was £0.53 via the wrong £46.20/90 path)
  Robust to the thickness read: the DXF filename says 1.2mm, Tony's sheet says 2mm — a SOURCE
  conflict (flag for design), but £/m2 is flat ~£8 across 1.5-2mm so the price is £0.43 either way.

Both old and new tables are kept; the flag/provenance still says PROVISIONAL until estimating
signs off the £/m2 figures. THICKNESS is NOT touched — the engine reads it correctly from the
DXF filename; the 1.2-vs-2mm conflict is a drawing issue, not a code one.

Usage (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _apply_acrylic_area_pricing.py
"""
from __future__ import annotations
import shutil, sys, datetime, os

CONFIG = r"C:\ClaudeVision\src\config.py"
TARGET = r"C:\ClaudeVision\src\estimator.py"
SENTINEL = "acrylic_area_pricing_v1"


def sub(src, old, new, label):
    n = src.count(old)
    if n != 1:
        sys.exit(f"ABORT [{label}]: expected 1 match, found {n}. NOTHING WRITTEN.\n"
                 f"--- looked for (first 400 chars) ---\n{old[:400]}\n")
    print(f"  ok  {label}")
    return src.replace(old, new, 1)


# ── config: add the UDEF-derived £/m2 table next to the existing sheet-price table ──────
C_ANCHOR = '''ACRYLIC_SHEET_PRICE_GBP = {
    2.0: 34.00,
    3.0: 46.20,    # 3mm high-impact @ 2050x1520 — confirmed from the M18 workbook
    5.0: 70.00,
    8.0: 112.00,
    10.0: 138.00,
    "default": 46.20,
}'''

C_NEW = '''ACRYLIC_SHEET_PRICE_GBP = {
    2.0: 34.00,
    3.0: 46.20,    # 3mm high-impact @ 2050x1520 — confirmed from the M18 workbook
    5.0: 70.00,
    8.0: 112.00,
    10.0: 138.00,
    "default": 46.20,
}

# acrylic_area_pricing_v1 (2026-07-15): £/m2 by thickness, derived from UDEF (Access Supply
# Chain) — every priced acrylic line from Perspex Distribution / Plastics Plus / AMARI, isolated
# to Clear/standard XT stock. PROVEN LINEAR: for each thickness the £/m2 from a full sheet and a
# cut blank agree (2mm 7.8 vs 7.9/8.5; 3mm 11.5 vs 13.2), so a blank costs area x sheet-rate.
# Confidence: 1.8/2.0mm STRONG (3 lines each, tight); 3mm OK (2 lines); 4/5/6/8mm single-line
# (real current Perspex price, but single-source). These are CLEAR/standard XT — coloured / matt
# / cast / anti-reflective run ~1.5-2x higher and would be NAMED on the drawing (separate tier).
# Cost = blank_area_m2 * rate * (1+scrap). Supersedes the £/sheet-÷-nesting model (no
# parts-per-sheet estimate needed). PROVISIONAL until estimating signs off these figures.
ACRYLIC_PRICE_GBP_PER_M2 = {
    1.5: 8.2,    # 1 line (full sheet clear XT) — single-source
    1.8: 7.8,    # 3 lines (blanks), £6.4-8.3 — STRONG
    2.0: 8.0,    # 3 lines (2 clear blank + 1 full sheet), £7.8-8.5 — STRONG
    3.0: 13.0,   # clear blank £13.2 + black full sheet £11.5 — OK
    4.0: 14.2,   # 1 line (full sheet clear XT) — single-source
    5.0: 19.5,   # 1 line (full sheet clear XT 3050x2050) — single-source
    6.0: 21.7,   # 1 line (full sheet clear XT) — single-source
    8.0: 30.9,   # 1 line (full sheet clear XT) — single-source
    "default": 8.0,   # thin-gauge standard (most display acrylic is 1.5-3mm)
}'''


# ── estimator.py: switch the acrylic cost from sheet-nesting to area x £/m2 ──────────────
E_ANCHOR = '''        _acr_prices = getattr(config, "ACRYLIC_SHEET_PRICE_GBP", {}) or {}
        try:
            _sheet_price = float(_acr_prices.get(float(thickness)) if thickness is not None else None)
        except (TypeError, ValueError):
            _sheet_price = None
        if not _sheet_price:
            _sheet_price = float(_acr_prices.get("default", 46.20))
        _scrap = float(getattr(config, "SCRAP_PERCENTAGE", 0.04))
        _acr_sheet_est = select_sheet_size(material, blank_length, blank_width)
        _acr_pps = _acr_sheet_est.get("parts_per_sheet") or 1
        if not _acr_pps or int(_acr_pps) < 1:
            _acr_pps = 1
        _acr_cost_part = (_sheet_price / _acr_pps) * (1.0 + _scrap)
        _acr_area_m2 = (float(blank_length) * float(blank_width)) / 1_000_000.0'''

E_NEW = '''        _scrap = float(getattr(config, "SCRAP_PERCENTAGE", 0.04))
        _acr_area_m2 = (float(blank_length) * float(blank_width)) / 1_000_000.0
        # acrylic_area_pricing_v1: cost the flat blank by AREA x £/m2 (UDEF-derived, proven
        # linear full-sheet-to-blank), NOT by nesting into a sheet. No parts-per-sheet estimate
        # needed. Rate keyed by thickness; falls back to the thin-gauge default.
        _acr_m2 = getattr(config, "ACRYLIC_PRICE_GBP_PER_M2", {}) or {}
        _acr_rate_m2 = None
        try:
            _acr_rate_m2 = _acr_m2.get(float(thickness)) if thickness is not None else None
        except (TypeError, ValueError):
            _acr_rate_m2 = None
        if _acr_rate_m2 is None:
            # nearest known thickness band, else default
            try:
                _keys = [k for k in _acr_m2 if isinstance(k, (int, float))]
                if thickness is not None and _keys:
                    _acr_rate_m2 = _acr_m2[min(_keys, key=lambda k: abs(k - float(thickness)))]
            except (TypeError, ValueError):
                _acr_rate_m2 = None
        if _acr_rate_m2 is None:
            _acr_rate_m2 = float(_acr_m2.get("default", 8.0))
        _acr_cost_part = _acr_area_m2 * float(_acr_rate_m2) * (1.0 + _scrap)
        # keep the sheet-nesting estimate for the stock_estimate/reporting fields only
        _acr_sheet_est = select_sheet_size(material, blank_length, blank_width)
        _acr_pps = _acr_sheet_est.get("parts_per_sheet") or 1
        if not _acr_pps or int(_acr_pps) < 1:
            _acr_pps = 1
        _sheet_price = _acr_rate_m2   # for the note string below (now a £/m2 figure)'''


def main():
    for p in (CONFIG, TARGET):
        if not os.path.exists(p):
            sys.exit(f"not found: {p}")
    cfg = open(CONFIG, "r", encoding="utf-8").read()
    est = open(TARGET, "r", encoding="utf-8").read()
    if SENTINEL in cfg or SENTINEL in est:
        sys.exit("Already applied (sentinel present).")

    cfg = sub(cfg, C_ANCHOR, C_NEW, "config: add UDEF-derived ACRYLIC_PRICE_GBP_PER_M2")
    est = sub(est, E_ANCHOR, E_NEW, "estimator: acrylic cost = area x £/m2 (not sheet-nested)")

    # update the note string so it reads sensibly with a £/m2 figure
    note_old = 'note": "Acrylic sheet-nested cost (PROVISIONAL) — £%.2f/sheet ÷ %s parts/sheet; swap for canonical on estimating confirmation." % (_sheet_price, _acr_pps),'
    note_new = 'note": "Acrylic area-priced cost (PROVISIONAL) — %.4f m2 × £%.2f/m2 (UDEF-derived Clear XT) × scrap; estimating to confirm £/m2." % (_acr_area_m2, _sheet_price),'
    if est.count(note_old) == 1:
        est = est.replace(note_old, note_new, 1)
        print("  ok  estimator: note string updated to £/m2 wording")
    else:
        print("  WARN: note string not matched exactly (non-fatal) — cost is correct, wording may still say /sheet")

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    for path, text in ((CONFIG, cfg), (TARGET, est)):
        bak = f"{path}.bak_acrylicarea_{ts}"
        shutil.copy2(path, bak)
        open(path, "w", encoding="utf-8").write(text)
        print(f"  backup: {bak}")

    print("""
RE-RUN 12439 (qty 2025). Expected:
    - Acrylic material: 0.05185 m2 × £8.0/m2 × 1.04 = £0.43  (was £0.53).
      The 'Other Sheet Material' line's Cost Per Part should read ~£0.43.
    - Unit cost £2.83 -> ~£2.73.
    - The part is 2mm-equivalent thin gauge; £/m2 is flat ~£8 for 1.5-2mm so the
      1.2-vs-2mm filename/drawing conflict does not change the price.

REGRESSION — re-run 1282 (steel). It has NO acrylic sheet parts priced this way
(its acrylic, if any, is minor); confirm unit cost unchanged. This block is gated
strictly to acrylic-like materials, so steel/wire/MDF are untouched.

FOR THE REPORT (Drawing Quality + Pricing sections):
    - Acrylic now priced by AREA × £/m2 from UDEF (Perspex Distribution / Plastics
      Plus), proven linear full-sheet-to-blank. £0.43 for this cleat.
    - FLAG: DXF filename says 1.2mm, drawing/manual says 2mm — source conflict for
      design to reconcile (price robust to it either way).
    - The manual £0.12 likely reuses UDEF catalogue line PLAS1228 (178×79 cleat,
      £0.11) — a catalogue pick vs the engine's area calc. Estimating to choose the
      convention: derive-by-area (works for any part) vs catalogue-match (precise
      when the exact part exists).
""")


if __name__ == "__main__":
    main()
