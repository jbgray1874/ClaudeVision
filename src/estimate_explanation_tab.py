#!/usr/bin/env python3
r"""Put the explanation into the workbook itself, as a tab the estimator can read.

WHY IT IS NOT A SEPARATE FILE ANY MORE. The explanation shipped as a markdown document
alongside the workbook, and a document that travels beside a spreadsheet is a document that
arrives without it — forwarded on its own, saved to a different folder, out of date the moment
the estimator edits a rate. The answer to "where did that figure come from" belongs in the
same file as the figure.

WRITTEN THROUGH EXCEL, NOT openpyxl. This template carries the estimators' own blocks,
conditional formatting, named ranges and a page of formulas, and openpyxl rewrites a workbook
wholesale when it saves one. Adding a sheet through Excel touches the sheet it adds and
nothing else. The cost is one more Excel open per run; the alternative is a class of damage
that would not show up until somebody opened a sheet weeks later.

AFTER THE READ-BACK, NOT BEFORE. The tab prints Estimate!M63:M77 and the sheet's own totals,
and none of those exist until Excel has calculated the populated template and the read-back
has recorded what it found. Running earlier would produce a tab full of blanks that looked
like an answer.

FAILURE-ISOLATED. Everything here is a nicety compared with the estimate itself. Any failure
prints its reason and leaves the workbook exactly as the run made it.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

SHEET_NAME = "AI Explanation"

# Excel's own limit, and the point past which a tab stops being readable anyway. A document
# that overflows says so on its last row rather than stopping mid-table.
_MAX_ROWS = 5000


def _rows_for(workbook: Path, scan_json: Optional[Path]) -> List[List[str]]:
    """The document, rendered as spreadsheet rows. Imported late so a machine without the
    engine's dependencies can still import this module."""
    import estimate_explained

    text = estimate_explained.build(workbook, scan_json)
    return estimate_explained.worksheet_rows(estimate_explained.sections(text))


def write_tab(xlsx_path: Any, scan_json: Any = None,
              sheet_name: str = SHEET_NAME) -> Optional[str]:
    """Add (or replace) the explanation tab on a populated workbook. Returns the sheet name
    written, or None with a printed reason."""
    if sys.platform != "win32":                                  # pragma: no cover
        print(f"   [explanation-tab] not Windows — no Excel to write through; "
              f"the markdown document is unaffected.", flush=True)
        return None

    book = Path(xlsx_path)
    if not book.is_file():
        print(f"   [explanation-tab] workbook not found: {book} — skipped.", flush=True)
        return None

    try:
        rows = _rows_for(book, Path(scan_json) if scan_json else None)
    except Exception as exc:                                     # noqa: BLE001
        print(f"   [explanation-tab] the explanation could not be built "
              f"({type(exc).__name__}: {exc}) — workbook left as it was.", flush=True)
        return None
    if not rows:
        print("   [explanation-tab] the explanation came back empty — nothing written.",
              flush=True)
        return None

    truncated = False
    if len(rows) > _MAX_ROWS:
        rows = rows[:_MAX_ROWS]
        truncated = True

    excel = com_wb = None
    try:
        import win32com.client                                   # pragma: no cover
        excel = win32com.client.DispatchEx("Excel.Application")
        excel.Visible = False
        excel.DisplayAlerts = False
        com_wb = excel.Workbooks.Open(str(book.resolve()))

        # REPLACED, NOT APPENDED. A second run on the same workbook would otherwise leave
        # "AI Explanation" and "AI Explanation1" side by side, one of them stale, and the
        # estimator with no way to tell which.
        for existing in list(com_wb.Worksheets):
            if str(existing.Name).strip().lower() == sheet_name.strip().lower():
                existing.Delete()
                break

        ws = com_wb.Worksheets.Add(After=com_wb.Worksheets(com_wb.Worksheets.Count))
        ws.Name = sheet_name[:31]

        # WRITTEN AS ONE BLOCK, NOT CELL BY CELL. A cell-at-a-time write of two thousand rows
        # is two thousand COM round trips and minutes of wall clock on a machine that is
        # already the bottleneck of every run.
        width = max(len(r) for r in rows) or 1
        padded = [list(r) + [""] * (width - len(r)) for r in rows]
        ws.Range(ws.Cells(1, 1), ws.Cells(len(padded), width)).Value = padded

        # Text, not numbers. "£11.48" and "p.6" are already formatted the way the document
        # means them, and letting Excel reinterpret them turns a page reference into a date.
        ws.Columns.NumberFormat = "@"
        ws.Columns(1).ColumnWidth = 34
        for col in range(2, min(width, 12) + 1):
            ws.Columns(col).ColumnWidth = 18

        if truncated:
            ws.Cells(len(padded) + 2, 1).Value = (
                f"This tab stops at {_MAX_ROWS} rows. The complete explanation is the "
                f"markdown document filed with this run.")

        com_wb.Save()
        print(f"   [explanation-tab] '{ws.Name}' written — {len(padded)} row(s)"
              + (" (truncated)" if truncated else ""), flush=True)
        return str(ws.Name)
    except Exception as exc:                                     # noqa: BLE001
        print(f"   [explanation-tab] not written ({type(exc).__name__}: {exc}) — the "
              f"workbook is unchanged and the estimate is unaffected.", flush=True)
        return None
    finally:
        try:
            if com_wb is not None:
                com_wb.Close(SaveChanges=False)
        except Exception:                                        # noqa: BLE001
            pass
        try:
            if excel is not None:
                excel.Quit()
        except Exception:                                        # noqa: BLE001
            pass
