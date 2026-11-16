#!/usr/bin/env python3
r"""Ask a finished estimate what it would cost at other quantities.

    python tools/quantity_sweep.py --workbook <estimate.xlsx> --quantities 10 25 50 100

Reads Total Material, Total Labour and Total Unit Cost out of the Estimate sheet at each
quantity, by setting the order-quantity cell and letting Excel recalculate. The workbook is
closed without saving; the estimate is not altered.

Give --packaging and --delivery (the per-unit figures on the BOM at the quantity the estimate
was run for) and the table gains a column with that 1-off freight taken back out — because the
sheet does not re-price freight when the quantity changes, and at 100 off it is the single
biggest thing wrong with the raw number.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from quantity_sweep import commercial_correction, sweep, to_markdown   # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workbook", required=True, type=Path)
    ap.add_argument("--quantities", nargs="+", type=int, default=[10, 25, 50, 100])
    ap.add_argument("--packaging", type=float,
                    help="override the PACKAGING figure to take back out; read off the "
                         "sheet when not given")
    ap.add_argument("--delivery", type=float,
                    help="override the DELIVERY figure to take back out; read off the "
                         "sheet when not given")
    ap.add_argument("--save-variants", action="store_true",
                    help="also save a workbook per quantity, each opening on a page that "
                         "says what did not re-price")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    result = sweep(args.workbook, args.quantities,
                   save_variants=args.save_variants)
    if result is None:
        raise SystemExit(1)

    corrected = commercial_correction(result, args.packaging, args.delivery)
    text = to_markdown(result, corrected)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(text)
    for path in result.get("variants") or []:
        print(f"variant: {path}")


if __name__ == "__main__":
    main()
