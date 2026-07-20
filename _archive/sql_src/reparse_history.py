"""
Re-parse all historical estimate workbooks under a folder.

Regenerates *.formula_parse.json using the current spreadsheet_formula_parser
(plain-text col C/G capture) and estimate_template_parser (key_cells ranges).

Does not load SQL — run load_historical_quotes.py after this.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bulk_parse_and_load_history import _parse_all


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-parse historical estimate workbooks to formula_parse.json")
    parser.add_argument("--root", required=True, help="Folder to scan recursively for spreadsheets")
    parser.add_argument(
        "--extensions",
        default=".xlsx,.xlsm,.xls",
        help="Comma-separated spreadsheet extensions",
    )
    args = parser.parse_args()
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"Not a directory: {root}", file=sys.stderr)
        sys.exit(1)
    src_dir = Path(__file__).resolve().parent
    exts = [e.strip().lower() for e in args.extensions.split(",") if e.strip()]
    ok = _parse_all(root, src_dir, exts)
    print(f"Re-parsed {ok} workbook(s) under {root}")


if __name__ == "__main__":
    main()
