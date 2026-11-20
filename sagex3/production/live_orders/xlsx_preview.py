"""Preview a spreadsheet for the portal: its tabs and the first rows of one tab, as JSON. Written 20 Nov 2026.

    python xlsx_preview.py <file.xlsx|xlsm|xls> [--sheet NAME] [--rows 300] [--cols 60]

Read-only, values only (what Excel last saved), hidden tabs and the chart-data tab left out. Used by the portal's
Live Orders → Workbooks list so a workbook in K:\\Operations\\Reporting\\LiveOrders - generated or saved by Production,
with their typed notes - can be looked at without opening Excel. Prints {"sheets": [...], "sheet": ..., "rows": [[...]],
"total_rows": n, "truncated": bool} or {"error": ...}.
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path


def cell(v):
    if v is None:
        return ""
    if isinstance(v, dt.datetime):
        return v.strftime("%d/%m/%Y" if (v.hour, v.minute) == (0, 0) else "%d/%m/%Y %H:%M")
    if isinstance(v, dt.date):
        return v.strftime("%d/%m/%Y")
    if isinstance(v, float):
        return int(v) if v == int(v) else round(v, 3)
    return v if isinstance(v, (int, str, bool)) else str(v)


def trim(rows):
    while rows and not any(c != "" for c in rows[-1]):
        rows.pop()
    width = max((max((i + 1 for i, c in enumerate(r) if c != ""), default=0) for r in rows), default=0)
    return [r[:width] for r in rows]


def from_xlsx(path, sheet, nrows, ncols):
    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=True, data_only=True)
    names = [ws.title for ws in wb.worksheets if ws.sheet_state == "visible" and not ws.title.startswith("_")]
    name = sheet if sheet in names else (names[0] if names else None)
    if not name:
        return dict(sheets=[], sheet=None, rows=[], total_rows=0, truncated=False)
    ws = wb[name]
    rows = [[cell(v) for v in r[:ncols]] for r in ws.iter_rows(max_row=nrows + 1, values_only=True)]
    total = ws.max_row or len(rows)
    return dict(sheets=names, sheet=name, rows=trim(rows[:nrows]), total_rows=total, truncated=total > nrows)


def from_xls(path, sheet, nrows, ncols):
    import xlrd
    book = xlrd.open_workbook(str(path))
    names = [s.name for s in book.sheets() if s.visibility == 0 and not s.name.startswith("_")]
    name = sheet if sheet in names else (names[0] if names else None)
    if not name:
        return dict(sheets=[], sheet=None, rows=[], total_rows=0, truncated=False)
    s = book.sheet_by_name(name)
    rows = []
    for r in range(min(s.nrows, nrows)):
        out = []
        for c in range(min(s.ncols, ncols)):
            x = s.cell(r, c)
            v = x.value
            if x.ctype == xlrd.XL_CELL_DATE:
                v = xlrd.xldate.xldate_as_datetime(v, book.datemode)
            elif x.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                v = None
            elif x.ctype == xlrd.XL_CELL_ERROR:
                v = xlrd.error_text_from_code.get(v, "#ERR")
            out.append(cell(v))
        rows.append(out)
    return dict(sheets=names, sheet=name, rows=trim(rows), total_rows=s.nrows, truncated=s.nrows > nrows)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("file")
    ap.add_argument("--sheet", default="")
    ap.add_argument("--rows", type=int, default=300)
    ap.add_argument("--cols", type=int, default=60)
    a = ap.parse_args(argv)
    p = Path(a.file)
    try:
        res = (from_xls if p.suffix.lower() == ".xls" else from_xlsx)(p, a.sheet, min(a.rows, 2000), min(a.cols, 120))
    except Exception as e:                                     # noqa: BLE001 - shown on the page
        res = dict(error=f"{e.__class__.__name__}: {e}"[:300])
    sys.stdout.write(json.dumps(res, default=str))
    return 0 if "error" not in res else 1


if __name__ == "__main__":
    sys.exit(main())
