"""One rebuild: every mapped spreadsheet from the run's extracts, then the what-changed write-up.

    python run.py <run folder> --previous <previous run's out folder> [--today 20261231]
                  [--phant usage|access] [--recent-years 2]

<run folder>/extract/ holds the saved output of each sql/extract_*.sql; the spreadsheets go to
<run folder>/out/, with WHAT_CHANGED.md and What_changed.xlsx beside them. The previous run can be
any folder of mapped spreadsheets, such as the set that was last loaded.

Each builder stops on a silent drop (a live record left out without a reason), so a run that
finishes has passed its checks. Builders are added here as they are written (README, Status).
"""
import argparse
from pathlib import Path

import changes
import costs
import product_suppliers
import products


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("run_dir")
    ap.add_argument("--previous", help="the previous run's out folder, for the what-changed write-up")
    ap.add_argument("--today", help="the run's date, yyyymmdd (default today)")
    ap.add_argument("--phant", choices=("usage", "access"), default="usage")
    ap.add_argument("--recent-years", type=int, default=2)
    ap.add_argument("--previous-costs", help="the YITC spreadsheet loaded last: its costs are kept")
    ap.add_argument("--suppliers", help="the YA004BPS spreadsheet: product-suppliers keep these suppliers")
    a = ap.parse_args()
    run = Path(a.run_dir)

    path, summary, rows, code = products.build(run, a.today, a.phant, a.recent_years)
    print(f"Products: {path.name}")
    for k, v in summary.items():
        print(f"  {k}: {v}")

    path, summary = costs.build(run, rows, code, a.previous_costs)
    print(f"Costs: {path.name}")
    for k, v in summary.items():
        print(f"  {k}: {v}")

    if (run / "extract" / "product_suppliers.txt").exists() and a.suppliers:
        path, summary = product_suppliers.build(run, rows, code, a.suppliers)
        print(f"Product-suppliers: {path.name}")
        for k, v in summary.items():
            print(f"  {k}: {v}")

    if a.previous:
        print()
        changes.main(a.previous, run / "out")
        print(f"\nWrite-up: {run / 'out' / 'WHAT_CHANGED.md'}")


if __name__ == "__main__":
    main()
