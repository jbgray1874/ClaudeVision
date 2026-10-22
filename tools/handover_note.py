#!/usr/bin/env python3
r"""Write the estimate explanation for one job, from the command line.

THE DOCUMENT ITSELF LIVES IN src/estimate_explained.py, because it is no longer only a
document. The same rows become the workbook's Explanation tab, the HTML report's provenance
sections and the body of the estimate email — and three programs that each go and ask the
workbook their own questions are three programs that disagree by the tenth change. One
builder, several renderings; this file is the rendering that runs from a terminal.

    python tools/handover_note.py --workbook <estimate.xlsx> --scan-json <12552-00.json>

Add --email to render the COVERING NOTE instead of the full document — the same seven
sections that get sent, from the same reading. That is the fast way to check a change
against a real job: it takes a second, where re-running the estimate takes the best part of
an hour, and it renders from files the last run already wrote.

    python tools/handover_note.py --workbook <estimate.xlsx> --scan-json <job>.json ^
        --email --out note.html

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
from estimate_explained import (build, covering_email, json, plain,   # noqa: E402,F401
                                sections, worksheet_rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workbook", required=True, type=Path)
    ap.add_argument("--scan-json", type=Path,
                    help="output/json/<job>.json — the drawing pages, and the rows as "
                         "Excel calculated them")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--email", action="store_true",
                    help="render the covering note that gets sent, not the full document")
    ap.add_argument("--client", default="",
                    help="the client name, as it appears in the note's header")
    ap.add_argument("--text", action="store_true",
                    help="with --email, the plain-text alternative rather than the HTML")
    args = ap.parse_args()

    if args.email:
        note = covering_email(args.workbook, args.scan_json, client=args.client)
        print(f"SUBJECT: {note['subject']}\n", file=sys.stderr)
        text = note["text"] if args.text else note["html"]
    else:
        text = build(args.workbook, args.scan_json)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
