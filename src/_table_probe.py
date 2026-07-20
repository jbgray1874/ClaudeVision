#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
_table_probe.py — READ-ONLY diagnostic. Shows how pdfplumber recovers the BOM
tables from a drawing PDF, so we build the extractor on what the tools ACTUALLY
get (not a guess).

CAD-drawing BOM tables are often UNBORDERED (aligned text, no ruled cells), so
this tries multiple strategies per page and reports which one recovers clean
ITEM / DWG NO / DESCRIPTION / QTY rows:

  1. extract_tables() with 'lines'  strategy (needs ruled cell borders)
  2. extract_tables() with 'text'   strategy (aligns by word x/y — borderless)
  3. raw words with x/y positions   (fallback: reconstruct columns from geometry)

Point it at the JOB FOLDER; it finds the .pdf itself. No changes made.

Run (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _table_probe.py --pdf-dir "K:\Estimating\Completed\AI Estimating\Live Enquiry\12120-01-GA- DIGITAL TICKETING BRACKET"
"""
from __future__ import annotations
import argparse
import glob
import os
import sys


def find_pdf(pdf_dir):
    pdfs = glob.glob(os.path.join(pdf_dir, "*.pdf")) + glob.glob(os.path.join(pdf_dir, "*.PDF"))
    return sorted(pdfs)


def show_table(tbl, max_rows=30):
    if not tbl:
        print("      (empty)")
        return
    for r in tbl[:max_rows]:
        cells = [("" if c is None else str(c).replace("\n", " ").strip()) for c in r]
        # only show non-empty rows
        if any(cells):
            print("      | " + " | ".join(cells))
    if len(tbl) > max_rows:
        print(f"      ... (+{len(tbl) - max_rows} more rows)")


def looks_like_bom(tbl):
    """Heuristic: a BOM table row set that mentions ITEM/QTY/DWG or part codes."""
    flat = " ".join(
        str(c).upper() for r in (tbl or []) for c in r if c
    )
    hits = [k for k in ("ITEM", "QTY", "DWG", "DESCRIPTION", "THUM", "FIXING", "12120-") if k in flat]
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf-dir", required=True, help="Job folder containing the PDF")
    ap.add_argument("--pdf", default=None, help="Explicit PDF path (overrides --pdf-dir search)")
    args = ap.parse_args()

    try:
        import pdfplumber
    except ImportError:
        print("pdfplumber not importable in this venv. Install or check the venv.")
        sys.exit(1)

    if args.pdf:
        pdf_path = args.pdf
    else:
        pdfs = find_pdf(args.pdf_dir)
        if not pdfs:
            print(f"No .pdf found in {args.pdf_dir}")
            sys.exit(1)
        if len(pdfs) > 1:
            print(f"Multiple PDFs found — using the first. All: {[os.path.basename(p) for p in pdfs]}")
        pdf_path = pdfs[0]

    print("=" * 78)
    print(f"TABLE PROBE: {os.path.basename(pdf_path)}")
    print("=" * 78)

    settings_lines = {"vertical_strategy": "lines", "horizontal_strategy": "lines"}
    settings_text = {"vertical_strategy": "text", "horizontal_strategy": "text",
                     "snap_tolerance": 4, "join_tolerance": 4}

    with pdfplumber.open(pdf_path) as pdf:
        print(f"\nPages: {len(pdf.pages)}\n")
        for pi, page in enumerate(pdf.pages):
            print("#" * 78)
            print(f"PAGE {pi}  (size {page.width:.0f} x {page.height:.0f})")
            print("#" * 78)

            # Strategy 1: lines
            try:
                t_lines = page.extract_tables(table_settings=settings_lines)
            except Exception as e:
                t_lines = []
                print(f"  [lines] error: {e}")
            print(f"\n  STRATEGY 1 — 'lines' (ruled borders): {len(t_lines)} table(s)")
            for ti, tbl in enumerate(t_lines):
                hits = looks_like_bom(tbl)
                tag = f"  <-- BOM-like ({','.join(hits)})" if hits else ""
                print(f"    table {ti}: {len(tbl)} rows x {len(tbl[0]) if tbl else 0} cols{tag}")
                if hits:
                    show_table(tbl)

            # Strategy 2: text
            try:
                t_text = page.extract_tables(table_settings=settings_text)
            except Exception as e:
                t_text = []
                print(f"  [text] error: {e}")
            print(f"\n  STRATEGY 2 — 'text' (word alignment, borderless): {len(t_text)} table(s)")
            for ti, tbl in enumerate(t_text):
                hits = looks_like_bom(tbl)
                tag = f"  <-- BOM-like ({','.join(hits)})" if hits else ""
                print(f"    table {ti}: {len(tbl)} rows x {len(tbl[0]) if tbl else 0} cols{tag}")
                if hits:
                    show_table(tbl)

            # Strategy 3: raw words w/ positions — only dump if the page mentions BOM terms
            words = page.extract_words()
            page_text_up = " ".join(w["text"] for w in words).upper()
            if any(k in page_text_up for k in ("ITEM", "QTY", "THUM", "FIXING", "DESCRIPTION")):
                print(f"\n  STRATEGY 3 — raw words w/ positions (page has BOM terms; "
                      f"{len(words)} words):")
                # show words sorted by (top, x0) so column structure is visible
                rows = {}
                for w in words:
                    key = round(w["top"] / 3) * 3  # cluster into ~3px row bands
                    rows.setdefault(key, []).append((w["x0"], w["text"]))
                shown = 0
                for top in sorted(rows):
                    line = sorted(rows[top])
                    txt = "  ".join(t for _, t in line)
                    up = txt.upper()
                    # only print rows near the BOM (item/qty/code/desc/fixing)
                    if any(k in up for k in ("ITEM", "QTY", "DWG", "DESCRIPTION",
                                             "THUM", "FIXING", "12120-", "MUSHROOM",
                                             "KNURLED", "THUMBSCREW", "KNOB")):
                        # show x0 of each word so column boundaries are visible
                        detail = " | ".join(f"{x:.0f}:{t}" for x, t in line)
                        print(f"    y={top:>4}: {detail}")
                        shown += 1
                    if shown > 40:
                        print("    ... (truncated)")
                        break
            else:
                print("\n  STRATEGY 3 — skipped (no BOM terms on this page)")

            print()


if __name__ == "__main__":
    main()
