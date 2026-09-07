#!/usr/bin/env python3
r"""Put the explanation into the workbook itself, as a tab the estimator can read.

WHY IT IS NOT A SEPARATE FILE ANY MORE. The explanation shipped as a markdown document
alongside the workbook, and a document that travels beside a spreadsheet is a document that
arrives without it — forwarded on its own, saved to a different folder, out of date the moment
the estimator edits a rate. The answer to "where did that figure come from" belongs in the
same file as the figure.

STYLED LIKE AI PROVENANCE, ON PURPOSE. The first version wrote the document as a flat block
of text cells through Excel COM — column A at width 34, everything else at 18, no wrapping,
no banners — and Tim's reviewer read the result: "the rendered action table clips
descriptions, assumptions and instructions." The two AI tabs are one product and should look
like one product, so this writer uses the same palette, the same banner rows, the same
wrapped bordered tables and the same computed row heights as add_provenance_sheet. Nothing
about the CONTENT changes: it is still estimate_explained.build's document, rendered.

WRITTEN THROUGH openpyxl, NOT COM. The COM route existed to avoid openpyxl rewriting the
template — but main.py loads and saves this same workbook through openpyxl one step later to
add AI Provenance, so that ship has sailed: whatever a wholesale rewrite would break is
already broken or already fine. Dropping COM buys three real things: the tab can be styled
(COM styling cell-by-cell is thousands of round trips), the writer runs on any machine
rather than only under Windows Excel, and a failed run can no longer leave a headless
EXCEL.EXE holding the workbook open.

AFTER THE READ-BACK, NOT BEFORE. The tab prints Estimate!M63:M77 and the sheet's own totals,
and none of those exist until Excel has calculated the populated template and the read-back
has recorded what it found. Running earlier would produce a tab full of blanks that looked
like an answer.

FAILURE-ISOLATED. Everything here is a nicety compared with the estimate itself. Any failure
prints its reason and leaves the workbook exactly as the run made it — and if the styled
layout itself fails, the document is still written as plain rows rather than not at all.
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any, List, Optional

SHEET_NAME = "AI Explanation"

# Excel's own limit, and the point past which a tab stops being readable anyway. A document
# that overflows says so on its last row rather than stopping mid-table.
_MAX_ROWS = 5000

# ~characters that fit one Excel width unit in 10pt Calibri. Used for row heights only, so
# an estimate is fine — too low wastes a little space, too high clips.
_CHARS_PER_UNIT = 1.05
_LINE_HEIGHT = 13.5

_MONEY = re.compile(r"^\(?-?£\s?\d[\d,]*(\.\d+)?\)?$")
_NUMBER = re.compile(r"^-?\d[\d,]*(\.\d+)?%?$")


def _grid_width(parsed: List[dict]) -> int:
    """One column grid for the whole tab — the widest table wins, prose merges across it."""
    width = 2
    for section in parsed:
        for table in section.get("tables") or []:
            width = max(width, len(table.get("columns") or []))
            for row in table.get("rows") or []:
                width = max(width, len(row))
    return min(width, 12)


def _column_widths(parsed: List[dict], grid: int) -> List[float]:
    """Width per column, from the content that will sit in it. Long prose columns (issue,
    assumption, action) land wide and wrapped; codes and money stay narrow."""
    longest = [0] * grid
    for section in parsed:
        for table in section.get("tables") or []:
            for cells in [table.get("columns") or []] + (table.get("rows") or []):
                for i, cell in enumerate(cells[:grid]):
                    longest[i] = max(longest[i], len(str(cell)))
    widths: List[float] = []
    for i, ln in enumerate(longest):
        w = min(max(12.0, ln * 0.9 + 2), 46.0)
        if i == 0:
            w = max(w, 22.0)
        widths.append(w)
    # ONE SCREEN, NOT A SCROLL. Sections share one grid, so a long cell anywhere widens a
    # column everywhere; unchecked, seven columns landed at the cap and the tab was wider
    # than the Estimate sheet itself. Text wraps and rows grow instead — scale the grid
    # down to roughly a screen and let the row heights absorb the length.
    total = sum(widths)
    if total > 210.0:
        scale = 210.0 / total
        widths = [max(12.0, w * scale) for w in widths]
    return widths


def _lines_needed(text: str, width_units: float) -> int:
    per_line = max(8.0, width_units * _CHARS_PER_UNIT)
    return max(1, math.ceil(len(str(text)) / per_line))


def add_explanation_sheet(wb, markdown: str, sheet_name: str = SHEET_NAME):
    """Render the explanation document onto `wb` in AI Provenance's visual language.
    Returns the worksheet. Pure openpyxl; raises on failure so the caller can fall back."""
    import estimate_explained
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    from estimation_report import (C_ALT_ROW, C_HEADER_BG, C_HEADER_FG, C_SECTION,
                                   replace_generated_sheet)

    parsed = estimate_explained.sections(markdown)
    plain = estimate_explained.plain
    grid = _grid_width(parsed)
    widths = _column_widths(parsed, grid)
    total_width = sum(widths)

    ws = replace_generated_sheet(wb, sheet_name)
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    last = get_column_letter(grid)
    thin = Side(style="thin", color="BBBBBB")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)

    def put(r: int, c: int, value: str, *, bold=False, italic=False, bg=None,
            fg="000000", size=10, wrap=True, align="left", border=False):
        cell = ws.cell(row=r, column=c, value=value)
        cell.font = Font(name="Calibri", bold=bold, italic=italic, color=fg, size=size)
        if bg:
            cell.fill = PatternFill("solid", fgColor=bg)
        cell.alignment = Alignment(horizontal=align, vertical="top", wrap_text=wrap)
        cell.number_format = "@"
        if border:
            cell.border = box
        return cell

    def banner(r: int, text: str, *, bg, size=11, height=20.0, bold=True):
        ws.merge_cells(f"A{r}:{last}{r}")
        put(r, 1, text, bold=bold, bg=bg, fg=C_HEADER_FG, size=size, wrap=False,
            align="left")
        ws.row_dimensions[r].height = height

    def prose(r: int, text: str, *, italic=False, bg=None) -> None:
        ws.merge_cells(f"A{r}:{last}{r}")
        put(r, 1, text, italic=italic, bg=bg)
        ws.row_dimensions[r].height = min(
            120.0, _LINE_HEIGHT * _lines_needed(text, total_width) + 3)

    row = 1
    ws.merge_cells(f"A1:{last}1")
    put(1, 1, "SDI Intelligence — The estimate, explained",
        bold=True, bg=C_HEADER_BG, fg=C_HEADER_FG, size=13, wrap=False, align="center")
    ws.row_dimensions[1].height = 28
    row = 2
    prose(row, "Every figure below reconciles to the Estimate sheet's own totals. "
               "Decisions first; the full audit of sources is the AI Provenance tab.",
          italic=True, bg=C_ALT_ROW)
    row += 1

    for section in parsed:
        if row >= _MAX_ROWS:
            break
        row += 1                                                    # breathing row
        banner(row, plain(section["title"]).upper(), bg=C_SECTION)
        row += 1
        for line in section.get("intro") or []:
            prose(row, plain(line))
            row += 1
        for table in section.get("tables") or []:
            headers = [plain(c) for c in table.get("columns") or []]
            for i, h in enumerate(headers[:grid], start=1):
                put(row, i, h, bold=True, bg=C_SECTION, fg=C_HEADER_FG, border=True)
            ws.row_dimensions[row].height = _LINE_HEIGHT + 4
            row += 1
            for n, cells in enumerate(table.get("rows") or []):
                texts = [plain(c) for c in cells[:grid]]
                lines = 1
                for i, t in enumerate(texts, start=1):
                    numeric = bool(_MONEY.match(t) or _NUMBER.match(t))
                    put(row, i, t, border=True,
                        bg=C_ALT_ROW if n % 2 else None,
                        align="right" if numeric else "left")
                    lines = max(lines, _lines_needed(t, widths[i - 1]))
                ws.row_dimensions[row].height = min(90.0, _LINE_HEIGHT * lines + 2)
                row += 1
                if row >= _MAX_ROWS:
                    break
            row += 1                                                # gap after a table
        for note in section.get("notes") or []:
            prose(row, plain(note), italic=True, bg=C_ALT_ROW)
            row += 1

    if row >= _MAX_ROWS:
        prose(row, f"This tab stops at {_MAX_ROWS} rows. The complete explanation is the "
                   f"markdown document filed with this run.")
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = "A2"
    return ws


def write_tab(xlsx_path: Any, scan_json: Any = None,
              sheet_name: str = SHEET_NAME) -> Optional[str]:
    """Add (or replace) the explanation tab on a populated workbook. Returns the sheet name
    written, or None with a printed reason."""
    book = Path(xlsx_path)
    if not book.is_file():
        print(f"   [explanation-tab] workbook not found: {book} — skipped.", flush=True)
        return None

    try:
        import estimate_explained
        markdown = estimate_explained.build(book, Path(scan_json) if scan_json else None)
    except Exception as exc:                                     # noqa: BLE001
        print(f"   [explanation-tab] the explanation could not be built "
              f"({type(exc).__name__}: {exc}) — workbook left as it was.", flush=True)
        return None
    if not str(markdown or "").strip():
        print("   [explanation-tab] the explanation came back empty — nothing written.",
              flush=True)
        return None

    wb = None
    try:
        import openpyxl
        wb = openpyxl.load_workbook(str(book))
        try:
            ws = add_explanation_sheet(wb, markdown, sheet_name)
        except Exception as exc:                                 # noqa: BLE001
            # THE DOCUMENT STILL TRAVELS. A styling failure must not cost the estimator the
            # explanation, so the flat rendering is the fallback rather than nothing.
            print(f"   [explanation-tab] styled layout failed ({type(exc).__name__}: "
                  f"{exc}) — written as plain rows instead.", flush=True)
            import estimate_explained
            rows = estimate_explained.worksheet_rows(
                estimate_explained.sections(markdown))[:_MAX_ROWS]
            from estimation_report import replace_generated_sheet
            ws = replace_generated_sheet(wb, sheet_name)
            for r, cells in enumerate(rows, start=1):
                for c, value in enumerate(cells, start=1):
                    ws.cell(row=r, column=c, value=value).number_format = "@"
        wb.save(str(book))
        print(f"   [explanation-tab] '{ws.title}' written — {ws.max_row} row(s)",
              flush=True)
        return str(ws.title)
    except Exception as exc:                                     # noqa: BLE001
        print(f"   [explanation-tab] not written ({type(exc).__name__}: {exc}) — the "
              f"workbook is unchanged and the estimate is unaffected.", flush=True)
        return None
    finally:
        # RELEASE THE FILE. openpyxl holds no lock after save, but a half-loaded workbook
        # object keeps the zip handle open on Windows until collected — and the very next
        # step of the run reopens this same file to add AI Provenance.
        try:
            if wb is not None:
                wb.close()
        except Exception:                                        # noqa: BLE001
            pass
