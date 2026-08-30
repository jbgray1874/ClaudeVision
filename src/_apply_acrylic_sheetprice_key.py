# -*- coding: utf-8 -*-
"""FIX #6 part 1/2: expose the raw acrylic SHEET PRICE in the material result so wb_populate can
write it into the WB 'Other Sheet' block's 'Cost per sheet' cell (col L), which is currently blank ->
Cost Per Part computes £0.

PROVEN root cause: estimate_material acrylic branch returns cost_per_part_gbp=0.75 correctly, but NO
raw sheet-price key. The WB Other Sheet formula is M(Cost Per Part) = (L/J)*(1+K)*D where L='Cost per
sheet' (currently blank), J=qty per sheet (nesting formula), K=scrap, D=qty. wb_populate writes desc/
qty/dims/sheet-size but NEVER writes L -> L blank -> £0. Add L input.

This adds "sheet_price_gbp": _sheet_price to the acrylic result. _sheet_price is the PRE-scrap sheet
cost (£46.20 for 3mm) — correct because the WB applies scrap itself via col K. wb_populate part 2/2
writes this into col L.

SAFE: exact-string match-or-refuse, adds ONE key to an existing dict literal. No behaviour change to
any other material path; steel/wire/1282 don't hit this branch.

BEFORE: Select-String -Path C:\ClaudeVision\src\estimator.py -Pattern "acrylic_sheet_provisional" -Context 6,2
Run from C:\ClaudeVision\src :
  C:\ClaudeVision\.venv\Scripts\python.exe _apply_acrylic_sheetprice_key.py
"""
from pathlib import Path
TARGET = Path(r"C:\ClaudeVision\src\estimator.py")

ANCHOR = '''            "extended_sheet_material_cost_gbp": _acr_ext,
            "powder_consumable": None,
            "extended_material_cost_gbp": _acr_ext,
            "stock_estimate": _acr_sheet_est,
            "cost_method": "acrylic_sheet_provisional",'''

REPLACEMENT = '''            "extended_sheet_material_cost_gbp": _acr_ext,
            "powder_consumable": None,
            "extended_material_cost_gbp": _acr_ext,
            "stock_estimate": _acr_sheet_est,
            # Raw PRE-scrap sheet price (£/sheet) so wb_populate can fill the WB Other Sheet
            # 'Cost per sheet' cell (col L). The WB formula M=(L/J)*(1+K)*D applies scrap (K)
            # and qty-per-sheet (J) itself, so we expose the sheet price, NOT the per-part cost.
            "sheet_price_gbp": round(float(_sheet_price), 2),
            "parts_per_sheet": int(_acr_pps),
            "cost_method": "acrylic_sheet_provisional",'''

src = TARGET.read_text(encoding="utf-8")
if ANCHOR not in src:
    print("REFUSED: anchor not found. Paste estimator.py ~1320-1332 so I can re-key.")
    raise SystemExit(1)
if src.count(ANCHOR) != 1:
    print(f"REFUSED: anchor found {src.count(ANCHOR)} times (need 1).")
    raise SystemExit(1)
src = src.replace(ANCHOR, REPLACEMENT)
TARGET.write_text(src, encoding="utf-8")
print("APPLIED part 1/2: acrylic result now exposes sheet_price_gbp + parts_per_sheet.")
print("Fingerprint: Select-String -Path C:\\ClaudeVision\\src\\estimator.py -Pattern \"sheet_price_gbp\"")
