#!/usr/bin/env python3
r"""Write the estimate explanation for one job, from the command line.

THE DOCUMENT ITSELF LIVES IN src/estimate_explained.py, because it is no longer only a
document. The same rows become the workbook's Explanation tab, the HTML report's provenance
sections and the body of the estimate email — and three programs that each go and ask the
workbook their own questions are three programs that disagree by the tenth change. One
builder, several renderings; this file is the rendering that runs from a terminal.

    python tools/handover_note.py --workbook <estimate.xlsx> --scan-json <12552-00.json>

The scan JSON is the run's own output/json/<job>.json. It supplies the drawing pages, and —
through `final_estimate` — the rows as Excel calculated them, which is what lets the document
hold its own lines against the sheet's totals. Without it the tool still runs and says which
sections it could not build, rather than guessing at them.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Re-exported so anything that imported this script by name keeps working.
from estimate_explained import build, json                       # noqa: E402,F401


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workbook", required=True, type=Path)
    ap.add_argument("--scan-json", type=Path,
                    help="output/json/<job>.json — the drawing pages, and the rows as "
                         "Excel calculated them")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    text = build(args.workbook, args.scan_json)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
