r"""Why a page will not say which drawing it is.

Run this when a job reports rows that "state no hierarchy". Every BOM row hangs off the
drawing whose title block names it; when that read comes back empty, the rows are not
attached to the wrong place, they are attached to nowhere — and nothing downstream can
build a hierarchy from them.

It prints, per page: what the reader concluded, what the title-block band actually
contains, and which adjacent word-runs in that band were tested against the drawing
number shape. That is enough to tell a title block we cannot see from one whose format
we do not yet recognise.

    C:\ClaudeVision\.venv\Scripts\python.exe C:\ClaudeVision\tools\diagnose_title_block.py "<job folder or pdf>"
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import _bom_words_reader as wr  # noqa: E402
import part_code_conventions as pcc  # noqa: E402


def _pdfs(target: str):
    p = Path(target)
    if p.is_dir():
        return sorted(str(f) for f in p.iterdir()
                      if f.is_file() and f.suffix.lower() == ".pdf")
    return [str(p)]


def _report(page, page_index: int) -> None:
    try:
        words = page.extract_words(x_tolerance=1.5, y_tolerance=1.5) or []
    except Exception as exc:
        print(f"    no text layer ({type(exc).__name__}: {exc}) — a raster sheet")
        return
    if not words:
        print("    no words on this page — a raster sheet")
        return

    verdict = wr.survey_page(page)
    parent = wr._title_block_dwg_no(words)
    print(f"    survey: text={verdict['has_text']} header_row={verdict['header_found']} "
          f"header_words={verdict['header_words']} rows={verdict['rows_parsed']}")
    print(f"    parent read: {parent!r}")

    top = min(w["top"] for w in words)
    bottom = max(w["top"] for w in words)
    cutoff = top + (bottom - top) * 0.6
    band = [w for w in words if w["top"] >= cutoff]
    print(f"    page y-range {top:.0f}..{bottom:.0f}; title-block band starts at {cutoff:.0f} "
          f"({len(band)} of {len(words)} words)")

    if parent:
        return

    # No parent. Show what the band holds and what was tried, so the difference between
    # "we cannot see the title block" and "we do not recognise this format" is visible.
    print("    --- words in the title-block band, by row ---")
    for row in wr._cluster_rows(band):
        row = sorted(row, key=lambda w: w["x0"])
        print(f"      y={row[0]['top']:.0f}  " + " | ".join(w["text"] for w in row))

    print("    --- adjacent runs tested against the drawing-number shape ---")
    shown = 0
    for row in wr._cluster_rows(band):
        row = sorted(row, key=lambda w: w["x0"])
        for length in range(min(len(row), 4), 0, -1):
            for start in range(0, len(row) - length + 1):
                run = row[start:start + length]
                joined = "".join(w["text"] for w in run).strip()
                if not joined or len(joined) < 4:
                    continue
                if any(ch.isdigit() for ch in joined) and shown < 40:
                    ok = pcc.looks_like_a_drawing_number(joined)
                    print(f"      {'MATCH ' if ok else '      '} {joined!r}")
                    shown += 1

    # And whether the number is anywhere on the page at all — if it is, the band is wrong;
    # if it is not, the title block has no text layer or spells it another way.
    print("    --- drawing-number-shaped tokens ANYWHERE on the page ---")
    anywhere = []
    for row in wr._cluster_rows(words):
        row = sorted(row, key=lambda w: w["x0"])
        for length in range(min(len(row), 4), 0, -1):
            for start in range(0, len(row) - length + 1):
                run = row[start:start + length]
                joined = "".join(w["text"] for w in run).strip()
                if pcc.looks_like_a_drawing_number(joined):
                    anywhere.append((run[0]["top"], joined))
                    break
    for y, tok in sorted(set(anywhere))[:20]:
        where = "IN BAND" if y >= cutoff else "above band"
        print(f"      y={y:.0f} {where}: {tok!r}")
    if not anywhere:
        print("      none — no token on this page has the shape of a drawing number")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    import pdfplumber

    for path in _pdfs(sys.argv[1]):
        print("=" * 78)
        print(os.path.basename(path))
        print("=" * 78)
        try:
            with pdfplumber.open(path) as pdf:
                for i, page in enumerate(pdf.pages):
                    print(f"  page {i + 1}:")
                    _report(page, i)
        except Exception as exc:
            print(f"  could not open: {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
