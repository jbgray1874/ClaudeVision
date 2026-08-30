# -*- coding: utf-8 -*-
"""FIX (#7): relabel mislabelled 'VINYL' graphic-size callouts as DISPLAY BOARD and give them a
PROVISIONAL area-based price, instead of a mislabelled £0 vinyl line.

Context (PROVEN): _recognise_vinyl_callouts (estimator.py ~2797) scans "GRAPHIC SIZE: 668 x 200 mm"
callouts. When dims don't match a UDEF vinyl SKU (these are display boards, not vinyl), it makes a
VINYL-668X200 stub with unit_cost_gbp=None -> £0 line labelled "Vinyl/logo ... estimator to price".
Drawing pages 23/24/25 confirm MATERIAL: DISPLAY BOARD, PRINTED FULL COLOUR - CUSTOMER SUPPLIED
ARTWORK. So the substrate has a cost; the print artwork is customer free-issue.

FIX: in the ambiguous/else branch, compute a PROVISIONAL price = area(m²) × DISPLAY_BOARD_PRICE_GBP_PER_M2
(£25/m², midpoint of the £15–£40 industry range for printed foam/PVC board — Foamex/Correx/Dibond),
relabel the stub as DISPLAY BOARD, and flag it clearly PROVISIONAL for the estimator to confirm the
substrate + rate + whether print is in-house or sub-contract. The £/m² is a documented provisional
placeholder (mirrors the acrylic_sheet_provisional pattern), NOT a silent guess — the review flag
tells the estimator to swap it.

SAFE: exact-string match-or-refuse on the else-branch. Only affects callouts that DON'T match a real
vinyl SKU (the genuine vinyl-priced branch above is untouched). Regression: 1282 has no GRAPHIC-size
display-board callouts -> unaffected.

BEFORE APPLYING, confirm anchor:
  Select-String -Path C:\ClaudeVision\src\estimator.py -Pattern "Ambiguous .0 or many SKUs" -Context 1,10

Run from C:\ClaudeVision\src :
  C:\ClaudeVision\.venv\Scripts\python.exe _apply_display_board_provisional.py

AFTER: re-run Recipe Card — the VINYL-668X200 / VINYL-150X1504 lines should become
"DISPLAY BOARD 668x200mm (PROVISIONAL @ £25/m²)" with a real provisional price (668x200 -> ~£3.34,
150x1504 -> ~£5.64), flagged for estimator verification. NOT silent £0.
"""
from pathlib import Path

TARGET = Path(r"C:\ClaudeVision\src\estimator.py")

ANCHOR = '''        else:
            # Ambiguous (0 or many SKUs at these dims) — recognise + flag, do NOT guess a price.
            pn = f"VINYL-{w}X{h}"
            if pn in existing_pns:
                continue
            stub = _bought_in_part_stub(pn, f"Vinyl/logo {w}x{h}mm (referenced on drawing)", 1)
            stub["unit_cost_gbp"] = None
            stub["extended_total_cost_gbp"] = None
            stub["source"] = "sdi_bom_code_unpriced"      # reuse the unpriced-passthrough guard
            stub["cost_source"] = "estimator_to_price"
            stub["price_verified"] = False
            stub.setdefault("review_flags", []).append(
                f"Vinyl/logo {w}x{h}mm referenced on drawing — "
                f"{verdict.get('candidate_count', 0)} catalogue match(es), not unique — estimator to price")
            found.append(stub)'''

REPLACEMENT = '''        else:
            # Ambiguous (0 or many SKUs at these dims). These "GRAPHIC SIZE" callouts are typically
            # DISPLAY BOARD (printed foam/PVC substrate; artwork customer free-issue) — NOT vinyl.
            # Give a PROVISIONAL area-based price (documented placeholder, mirrors acrylic_sheet_
            # provisional) so the line carries a real number, flagged for the estimator to confirm
            # substrate + rate + in-house-vs-subcontract. Not a silent guess: the flag says PROVISIONAL.
            pn = f"VINYL-{w}X{h}"
            if pn in existing_pns:
                continue
            _DISPLAY_BOARD_PRICE_GBP_PER_M2 = 25.0   # provisional midpoint of £15–£40 printed board
            _area_m2 = (w / 1000.0) * (h / 1000.0)
            _prov_price = round(_area_m2 * _DISPLAY_BOARD_PRICE_GBP_PER_M2, 2)
            stub = _bought_in_part_stub(
                pn, f"DISPLAY BOARD {w}x{h}mm (PROVISIONAL @ \u00a3{_DISPLAY_BOARD_PRICE_GBP_PER_M2:.0f}/m\u00b2)", 1)
            stub["unit_cost_gbp"] = _prov_price
            stub["unit_material_cost_gbp"] = _prov_price
            stub["extended_total_cost_gbp"] = _prov_price
            stub["source"] = "sdi_bom_code_udef_priced"   # price-preserving guard (has a price now)
            stub["cost_source"] = "display_board_provisional_area"
            stub["price_verified"] = False
            stub.setdefault("review_flags", []).append(
                f"DISPLAY BOARD {w}x{h}mm ({_area_m2:.3f} m\u00b2) priced PROVISIONALLY at "
                f"\u00a3{_DISPLAY_BOARD_PRICE_GBP_PER_M2:.0f}/m\u00b2 = \u00a3{_prov_price:.2f} — "
                f"VERIFY substrate + rate; confirm in-house print vs sub-contract; artwork is "
                f"customer free-issue per drawing")
            found.append(stub)'''

src = TARGET.read_text(encoding="utf-8")
if ANCHOR not in src:
    print("REFUSED: anchor not found exactly. Paste the else-branch (estimator.py ~2839-2853) so I can re-key.")
    raise SystemExit(1)
if src.count(ANCHOR) != 1:
    print(f"REFUSED: anchor found {src.count(ANCHOR)} times (need 1).")
    raise SystemExit(1)
src = src.replace(ANCHOR, REPLACEMENT)
TARGET.write_text(src, encoding="utf-8")
print("APPLIED: ambiguous graphic callouts now priced as DISPLAY BOARD (PROVISIONAL @ £25/m²), flagged.")
print("Fingerprint:")
print('  Select-String -Path C:\\ClaudeVision\\src\\estimator.py -Pattern "display_board_provisional_area"')
