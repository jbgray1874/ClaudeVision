#!/usr/bin/env python3
r"""
_apply_acrylic_area_pricing_v2.py

Corrected against the LIVE estimator.py (my first attempt anchored on a stale snapshot and
aborted cleanly — nothing was written to estimator.py; the config £/m2 table DID land).

KEY REALISATION from the live code: the deliverable £/part is computed by the WORKBOOK, not
Python. The block exposes to the WB:
    sheet_price_gbp -> col L 'Cost per sheet'
    parts_per_sheet -> col J 'Qty Per Sheet'
and the WB formula is  M (Cost Per Part) = (L / J) × (1 + K[scrap]) × D.
So £0.53 = (46.20 / 90) × 1.04. To move the workbook to area-pricing I must feed it the right
L and J — changing the Python _acr_cost_part alone would not change the deliverable.

THE MODEL (area pricing, expressed through the WB's own L/J so estimators still read a sensible
'sheet price + parts per sheet'):
    L = full_sheet_area_m2 × rate_per_m2        (the REAL full-sheet price at the UDEF £/m2)
    J = full_sheet_area_m2 / part_area_m2       (geometric parts per sheet)
Then the WB computes:
    L/J = (full_area × rate) / (full_area / part_area) = rate × part_area
The full-sheet area CANCELS — so the cost is exactly (area × rate), robust to whatever standard
sheet is assumed. WB then applies scrap: (rate × part_area) × 1.04.

For 12439 (2mm clear cleat, flat blank 305×170 = 0.05185 m2, rate £8.0/m2):
    L = 6.2525 m2 (3050×2050) × £8.0 = £50.02   (verifiable against a Perspex invoice)
    J = 6.2525 / 0.05185 = 120                    (geometric)
    WB: (50.02 / 120) × 1.04 = £0.43              (was £0.53)

Why this presentation is defensible to estimating:
  - L is the REAL full-sheet price at the UDEF-derived £/m2 — checkable against supplier invoices.
  - J is the clean geometric parts-per-sheet; real nesting yields fewer, and the 4% scrap covers
    that waste. Stated openly in the note.
  - The £/m2 itself is PROVEN LINEAR (UDEF full-sheet vs cut-blank prices agree per thickness).

THICKNESS is NOT touched. The engine reads it correctly from the DXF filename (1.2mm here); the
drawing/manual says 2mm — a SOURCE conflict for design to reconcile, flagged in the report. The
price is robust to it (£/m2 flat ~£8 across 1.5–2mm), so 12439 is £0.43 either way.

Only the acrylic block changes. Steel/wire/MDF untouched. PROVISIONAL flag/provenance retained
until estimating signs off the £/m2 figures.

Usage (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _apply_acrylic_area_pricing_v2.py
"""
from __future__ import annotations
import shutil, sys, datetime, os

TARGET = r"C:\ClaudeVision\src\estimator.py"
SENTINEL = "acrylic_area_pricing_v2"


def sub(src, old, new, label):
    n = src.count(old)
    if n != 1:
        sys.exit(f"ABORT [{label}]: expected 1 match, found {n}. NOTHING WRITTEN.\n"
                 f"--- looked for (first 600 chars) ---\n{old[:600]}\n")
    print(f"  ok  {label}")
    return src.replace(old, new, 1)


# Anchor: the exact live block from the paste (sheet-price lookup + pps + cost line).
ANCHOR = '''        _acr_prices = getattr(config, "ACRYLIC_SHEET_PRICE_GBP", {}) or {}
        try:
            _sheet_price = float(_acr_prices.get(float(thickness)) if thickness is not None else None)
        except (TypeError, ValueError):
            _sheet_price = None
        if not _sheet_price:
            _sheet_price = float(_acr_prices.get("default", 46.20))
        _acr_sheet_est = select_sheet_size(material, blank_length, blank_width)
        _acr_pps = _acr_sheet_est.get("parts_per_sheet") or 1
        if not _acr_pps or int(_acr_pps) < 1:
            _acr_pps = 1
        _acr_cost_part = (_sheet_price / _acr_pps) * (1.0 + _scrap)'''

NEW = '''        # acrylic_area_pricing_v2 (2026-07-15): price the flat blank by AREA × £/m2 (UDEF-derived
        # Clear XT, PROVEN LINEAR full-sheet-to-blank), expressed through the workbook's own L/J so
        # estimators still read a real sheet price and parts-per-sheet. L = full-sheet price at the
        # £/m2 rate; J = geometric parts-per-sheet; the WB computes (L/J)×scrap = rate×part_area×scrap.
        # The full-sheet area cancels in L/J, so the cost is exactly area×rate regardless of sheet size.
        _acr_m2 = getattr(config, "ACRYLIC_PRICE_GBP_PER_M2", {}) or {}
        _acr_rate_m2 = None
        try:
            _acr_rate_m2 = _acr_m2.get(float(thickness)) if thickness is not None else None
        except (TypeError, ValueError):
            _acr_rate_m2 = None
        if _acr_rate_m2 is None:
            try:
                _mkeys = [k for k in _acr_m2 if isinstance(k, (int, float))]
                if thickness is not None and _mkeys:
                    _acr_rate_m2 = _acr_m2[min(_mkeys, key=lambda k: abs(k - float(thickness)))]
            except (TypeError, ValueError):
                _acr_rate_m2 = None
        if _acr_rate_m2 is None:
            _acr_rate_m2 = float(_acr_m2.get("default", 8.0))
        _acr_rate_m2 = float(_acr_rate_m2)

        _acr_sheet_est = select_sheet_size(material, blank_length, blank_width)
        # full-sheet area from the standard sheet the nester picked (falls back to 3050×2050)
        _acr_sheet_dims = _acr_sheet_est.get("candidate_sheet_size_mm") or [3050.0, 2050.0]
        try:
            _full_sheet_area_m2 = (float(_acr_sheet_dims[0]) * float(_acr_sheet_dims[1])) / 1_000_000.0
        except (TypeError, ValueError, IndexError):
            _full_sheet_area_m2 = (3050.0 * 2050.0) / 1_000_000.0
        # L = real full-sheet price at the UDEF £/m2 (verifiable against a supplier invoice)
        _sheet_price = round(_full_sheet_area_m2 * _acr_rate_m2, 2)
        # J = geometric parts-per-sheet (full area / part area); real nesting yields fewer and
        # the scrap % covers that waste. Cost is robust to J because full-sheet area cancels in L/J.
        _part_area_m2 = _acr_area_m2 if _acr_area_m2 and _acr_area_m2 > 0 else (_full_sheet_area_m2 or 1.0)
        _acr_pps = int(_full_sheet_area_m2 / _part_area_m2) if _part_area_m2 > 0 else 1
        if not _acr_pps or _acr_pps < 1:
            _acr_pps = 1
        # Python's own per-part figure (JSON summary) = the exact area price incl scrap.
        _acr_cost_part = _acr_area_m2 * _acr_rate_m2 * (1.0 + _scrap)'''


def main():
    if not os.path.exists(TARGET):
        sys.exit(f"not found: {TARGET}")
    src = open(TARGET, "r", encoding="utf-8").read()
    if SENTINEL in src:
        sys.exit("Already applied (sentinel present).")

    # Guard: confirm the config £/m2 table from the first run is present.
    # (It lives in config.py, not here, so just warn — not fatal.)
    src = sub(src, ANCHOR, NEW, "estimator: acrylic cost via area×£/m2 through WB L/J")

    # Update the note + cost_method + basis strings to reflect area pricing.
    note_old = '"note": "Acrylic sheet-nested cost (PROVISIONAL) â€” Â£%.2f/sheet Ã· %s parts/sheet; swap for canonical on estimating confirmation." % (_sheet_price, _acr_pps),'
    note_new = '"note": "Acrylic area-priced (PROVISIONAL) â€” %.4f m2 Ã— Â£%.2f/m2 (UDEF Clear XT); WB sheet Â£%.2f Ã· %s geometric parts, scrap covers nesting waste; estimating to confirm Â£/m2." % (_acr_area_m2, _acr_rate_m2, _sheet_price, _acr_pps),'
    if src.count(note_old) == 1:
        src = src.replace(note_old, note_new, 1)
        print("  ok  estimator: note string updated to area/£/m2 wording")
    else:
        print("  WARN: note string not matched (non-fatal). Trying ASCII-dash fallback...")
        # fallback without the exact em-dash bytes
        import re
        pat = re.compile(r'"note": "Acrylic sheet-nested cost \(PROVISIONAL\).*?parts/sheet\." % \(_sheet_price, _acr_pps\),')
        if pat.search(src):
            src = pat.sub('"note": "Acrylic area-priced (PROVISIONAL) - %.4f m2 x GBP%.2f/m2 (UDEF Clear XT); WB sheet GBP%.2f / %s geometric parts, scrap covers nesting waste; estimating to confirm rate." % (_acr_area_m2, _acr_rate_m2, _sheet_price, _acr_pps),', src, count=1)
            print("  ok  estimator: note string updated via fallback")
        else:
            print("  WARN: note left as-is (cost is still correct; only the note wording is stale).")

    for a, b, lbl in [
        ('"cost_method": "acrylic_sheet_provisional",', '"cost_method": "acrylic_area_per_m2_provisional",', "cost_method"),
        ('applied=True, applied_basis="acrylic_sheet_price_per_sheet_provisional",',
         'applied=True, applied_basis="acrylic_area_per_m2_provisional",', "price_source basis"),
        ('fallback_source="acrylic_sheet_provisional",', 'fallback_source="acrylic_area_per_m2_provisional",', "fallback_source"),
    ]:
        if src.count(a) == 1:
            src = src.replace(a, b, 1)
            print(f"  ok  estimator: {lbl} updated")
        else:
            print(f"  note: {lbl} string not found (non-fatal)")

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{TARGET}.bak_acrylicareav2_{ts}"
    shutil.copy2(TARGET, bak)
    open(TARGET, "w", encoding="utf-8").write(src)
    print(f"  backup: {bak}")

    print("""
PRE-CHECK: confirm the config £/m2 table landed in the earlier run:
    Select-String -Path config.py -Pattern "ACRYLIC_PRICE_GBP_PER_M2"
  If it's NOT there, tell me — the estimator now reads it and would fall back to
  the £8.0 default without it (still ~correct for thin gauge, but confirm).

RE-RUN 12439 (qty 2025). Expected:
    - 'Other Sheet Material': Cost per sheet ~£50.02, Qty Per Sheet ~120,
      Cost Per Part ~£0.43  (was £46.20 / 90 / £0.53).
    - Total Material ~£0.43. Unit cost £2.83 -> ~£2.73.

REGRESSION — re-run 1282 (steel). Unit cost unchanged (this block is acrylic-only).

FOR THE REPORT:
    - Acrylic now area-priced: £/m2 from UDEF (Perspex Distribution / Plastics Plus),
      proven linear full-sheet-to-blank. WB shows real sheet price + geometric parts.
    - FLAG: DXF filename 1.2mm vs drawing/manual 2mm — source conflict (price robust).
    - Manual £0.12 ≈ UDEF catalogue line PLAS1228 (178×79 cleat, £0.11): catalogue
      pick vs the engine's area calc. Estimating to choose the convention.
""")


if __name__ == "__main__":
    main()
