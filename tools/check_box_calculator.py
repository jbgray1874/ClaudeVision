"""Run the box calculator against the Harley's order extract and report how it compares.

The BOX TEST SHEET is 327 real Harleys Corrugated Cases orders out of SDI Live: order
number, part code, description, quantity ordered and the price actually paid. Most
descriptions carry the box's outside size and its FEFCO style code; the calculator prices
only the plain six-panel 0201 carton (config.BOX_COSTING["styles_priced"]), so every other
style is reported as out of scope rather than silently mispriced.

Usage (from the repo root; the user's copy of the sheets lives in
C:\\ClaudeVision\\chatgptdropoff\\AICalculator):

    python tools\\check_box_calculator.py "chatgptdropoff\\AICalculator\\BOX TEST SHEET.xlsx"
    python tools\\check_box_calculator.py <sheet.xlsx> --write-back out.xlsx

With --write-back the calculator's answer goes in column G and the % difference in H,
exactly where the sheet reserves them; the original file is never touched.
"""
from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import box_costing  # noqa: E402
import config  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("sheet", help="BOX TEST SHEET .xlsx (the SDI Live Harley's extract)")
    ap.add_argument("--write-back", default="",
                    help="write a copy with Calculator Price in G and %% difference in H")
    args = ap.parse_args()

    import openpyxl
    wb = openpyxl.load_workbook(args.sheet, data_only=True)
    ws = wb.worksheets[0]

    styles_priced = set((getattr(config, "BOX_COSTING", {}) or {})
                        .get("styles_priced") or ("0201",))
    rows, priced, no_dims, out_of_scope, declined = [], [], 0, {}, 0
    for r in ws.iter_rows(min_row=2):
        desc = r[3].value
        if not desc:
            continue
        qty = r[4].value
        paid = r[5].value
        read = box_costing.parse_box_description(desc)
        style = read.get("style") or "(none)"
        if not read.get("dims_mm"):
            no_dims += 1
            rows.append((r[0].row, None, None))
            continue
        if style not in styles_priced:
            out_of_scope[style] = out_of_scope.get(style, 0) + 1
            rows.append((r[0].row, None, None))
            continue
        L, W, H = read["dims_mm"]
        res = box_costing.price_box(L, W, H, qty or 1)
        if not res.get("priced"):
            declined += 1
            rows.append((r[0].row, None, None))
            continue
        calc = res["unit_gbp"]
        diff = ((float(paid) - calc) / float(paid)) if paid else None
        priced.append((r[0].row, desc, qty, paid, calc, diff))
        rows.append((r[0].row, round(calc, 2), round(diff, 4) if diff is not None else None))

    print(f"rows read:            {len(rows) + no_dims and len(rows)}")
    print(f"priced (0201):        {len(priced)}")
    print(f"no L x W x H in text: {no_dims}")
    print(f"out-of-scope styles:  {sum(out_of_scope.values())}  {dict(sorted(out_of_scope.items()))}")
    print(f"declined (oversize/bad dims): {declined}")
    diffs = [d for *_x, d in priced if d is not None]
    if diffs:
        print(f"\n% difference (paid vs calculator), {len(diffs)} comparable rows:")
        print(f"  median {statistics.median(diffs):+.1%}   "
              f"mean {statistics.fmean(diffs):+.1%}")
        within = sum(1 for d in diffs if abs(d) <= 0.25)
        print(f"  within +/-25%: {within} ({within / len(diffs):.0%})")
        worst = sorted(priced, key=lambda t: -abs(t[5] or 0))[:10]
        print("\n  largest differences (paid vs calculated):")
        for row, desc, qty, paid, calc, d in worst:
            print(f"   row {row}: paid £{float(paid):.2f}  calc £{calc:.2f}  "
                  f"({d:+.0%})  x{qty}  {str(desc)[:70]}")

    if args.write_back:
        for row, calc, diff in rows:
            if calc is not None:
                ws.cell(row=row, column=7, value=calc)
                ws.cell(row=row, column=8, value=diff)
        wb.save(args.write_back)
        print(f"\nwritten: {args.write_back} (G = calculator price, H = % difference; "
              f"the original is untouched)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
