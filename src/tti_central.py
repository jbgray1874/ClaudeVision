"""The AI cost on the central TTI tracker in SharePoint, as well as the copy on K: (JG, 11 Nov 2026).

"can we add the same AICost column to the sharepoint s/sheet ... this is the same s/sheet we're
saving the AI cost to which is the central s/sheet."

The batch (src/tti_pricer.py) runs on the estimating laptop, where Excel is signed in to the
company's Microsoft 365. Excel opens the central workbook from SharePoint with that sign-in, so no
app registration or stored token is needed: the same Excel that writes the K: copy writes this.

ONE ROW, FOUND BY ITS DRAWING NUMBER, NEVER BY POSITION. The central sheet is edited by other
people; its row 7 need not be the K: copy's row 7. The row is the one whose drawing cell carries
the same drawing number. Two rows with it: the K: copy's row number decides, if it is one of them;
otherwise nothing is written and the reason is said.

THE COLUMN IS "AI Cost". Where the sheet has none, one is added: as a new column of the table the
header sits in (Table1 on the Milwaukee tab), or after the last header if there is no table.
Nothing else on the sheet is touched, and the cell is read back after the save.

    SDI_TTI_CENTRAL_SHEET   the central workbook: its SharePoint address as Excel's
                            File > Info > Copy path gives it (https://sdidisplays.sharepoint.com/
                            sites/.../TRACKER - MILWAUKEE AMSTERDAM CONFERENCE 2027.xlsx), or a
                            local path. Empty: the central sheet is not written.
"""
from __future__ import annotations

import re
import time
from typing import Any, Callable, Dict, List, Optional, Sequence

COST_HEADER = "AI Cost"
EXCEL_TRIES = 4
EXCEL_WAIT_S = 6.0


def _busy(said: Any) -> bool:
    t = str(said or "").lower()
    return "-2147418111" in t or "rejected by callee" in t or "busy" in t
_DRAWING_HEAD = re.compile(r"^\s*(drawing|dwg)\s*(no\.?|number|#)?\s*$", re.IGNORECASE)
_COST_HEAD = re.compile(r"^\s*ai\s*cost\b", re.IGNORECASE)


_QTY_HEAD = re.compile(r"^\s*(qty|quantity)\b", re.IGNORECASE)


def _whole(v: Any) -> Optional[int]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return int(f) if f == int(f) else None


def plan(grid: Sequence[Sequence[Any]], drawing: str, row_hint: Optional[int],
         ref: Callable[[str], str], first_row: int = 1, first_col: int = 1,
         quantity: Any = None) -> Dict[str, Any]:
    """Where the cost goes on the central sheet. `grid` is the sheet's used range as rows of
    values; `first_row`/`first_col` are the sheet coordinates of grid[0][0]. Returns
    {header_row, drawing_col, cost_col (None: to be added), next_col, row} in sheet
    coordinates, or {error}."""
    header = dcol = None
    for i, vals in enumerate(list(grid)[:25]):
        for j, v in enumerate(vals or ()):
            if _DRAWING_HEAD.match(str(v or "")):
                header, dcol = i, j
                break
        if header is not None:
            break
    if header is None:
        return {"error": "no column headed Drawing Number in the first 25 rows"}
    heads = list(grid[header] or ())
    cost = next((j for j, v in enumerate(heads) if _COST_HEAD.match(str(v or ""))), None)
    last = max((j for j, v in enumerate(heads) if str(v or "").strip()), default=dcol)
    want = ref(drawing).upper()
    hits = [first_row + i for i, vals in enumerate(grid) if i > header and len(vals or ()) > dcol
            and ref(str(vals[dcol] or "")).upper() == want and want]
    if not hits:
        return {"error": f"no row on the central sheet carries {drawing}"}
    # THE ROW MUST BE FOR THE QUANTITY THAT WAS PRICED (reviewer, 13 Nov 2026: "validate
    # drawing and quantity"). Where the sheet has a Quantity column and the price was worked
    # at a known quantity, a row for another quantity is not this price's row.
    qcol = next((j for j, v in enumerate(heads) if _QTY_HEAD.match(str(v or ""))), None)
    want_q = _whole(quantity)
    if qcol is not None and want_q is not None:
        def _row_q(sheet_row: int) -> Optional[int]:
            vals = grid[sheet_row - first_row] or ()
            return _whole(vals[qcol]) if len(vals) > qcol else None
        same_q = [h for h in hits if _row_q(h) == want_q]
        if not same_q:
            seen = ", ".join(f"row {h}: {_row_q(h)}" for h in hits)
            return {"error": f"{drawing} was priced at {want_q} off and the central sheet carries "
                             f"it at another quantity ({seen}): not written"}
        hits = same_q
    if len(hits) > 1:
        if row_hint in hits:
            hits = [row_hint]
        else:
            return {"error": f"{drawing} is on rows {', '.join(map(str, hits))} of the central "
                             f"sheet, none of them row {row_hint}: not written, say which"}
    return {"header_row": first_row + header, "drawing_col": first_col + dcol,
            "cost_col": None if cost is None else first_col + cost,
            "next_col": first_col + last + 1, "row": hits[0]}


def _same(a: Any, b: float) -> bool:
    try:
        return abs(float(a) - float(b)) < 0.005
    except (TypeError, ValueError):
        return False


def write(target: str, tab: str, drawing: str, row_hint: Optional[int], value: float,
          ref: Callable[[str], str], quantity: Any = None) -> Dict[str, Any]:
    """Write `value` as the AI Cost of `drawing`'s row on the central sheet. Returns {ok, said}."""
    target = str(target or "").strip()
    if not target:
        return {"ok": False, "said": "no central sheet set (SDI_TTI_CENTRAL_SHEET)"}
    if target.lower().startswith("http"):
        # Excel's Copy path can end "?web=1", which opens the browser view; the file is before it.
        # A BUSY EXCEL IS ASKED AGAIN ("Call was rejected by callee", 11 Nov 2026).
        res: Dict[str, Any] = {}
        for i in range(EXCEL_TRIES):
            res = _write_excel(target.split("?")[0], tab, drawing, row_hint, value, ref, quantity)
            if res.get("ok") or not _busy(res.get("said")):
                return res
            time.sleep(EXCEL_WAIT_S * (i + 1))
        return res
    return _write_openpyxl(target, tab, drawing, row_hint, value, ref, quantity)


def _write_excel(target: str, tab: str, drawing: str, row_hint: Optional[int], value: float,
                 ref: Callable[[str], str], quantity: Any = None) -> Dict[str, Any]:
    try:
        import win32com.client
    except Exception:                                                # noqa: BLE001
        return {"ok": False, "said": "Excel is not on this machine; the central sheet is written "
                                     "from the estimating laptop"}
    xl = win32com.client.DispatchEx("Excel.Application")
    xl.DisplayAlerts = False
    wb = None
    try:
        wb = xl.Workbooks.Open(target)
        ws = wb.Worksheets(tab) if tab else wb.ActiveSheet
        used = ws.UsedRange
        vals = used.Value
        grid = [list(r) for r in (vals if isinstance(vals, tuple) else ((vals,),))]
        p = plan(grid, drawing, row_hint, ref, used.Row, used.Column, quantity)
        if p.get("error"):
            return {"ok": False, "said": p["error"]}
        col = p["cost_col"]
        added = ""
        if col is None:
            table = None
            for i in range(1, ws.ListObjects.Count + 1):
                lo = ws.ListObjects(i)
                if lo.HeaderRowRange.Row == p["header_row"]:
                    table = lo
                    break
            if table is not None:
                lc = table.ListColumns.Add()
                lc.Name = COST_HEADER
                col = lc.Range.Column
                added = f"; added the {COST_HEADER} column to {table.Name}"
            else:
                col = p["next_col"]
                ws.Cells(p["header_row"], col).Value = COST_HEADER
                added = f"; added the {COST_HEADER} header"
        ws.Cells(p["row"], col).Value = float(value)
        wb.Save()
        back = ws.Cells(p["row"], col).Value
        if not _same(back, value):
            return {"ok": False, "said": f"row {p['row']} reads {back!r} after saving, not {value}"}
        return {"ok": True, "row": p["row"],
                "said": f"central sheet row {p['row']} AI Cost = {value}{added}"}
    except Exception as exc:                                         # noqa: BLE001
        return {"ok": False, "said": f"the central sheet could not be written ({exc})"}
    finally:
        try:
            if wb is not None:
                wb.Close(SaveChanges=False)
        finally:
            xl.Quit()


def _write_openpyxl(target: str, tab: str, drawing: str, row_hint: Optional[int], value: float,
                    ref: Callable[[str], str], quantity: Any = None) -> Dict[str, Any]:
    import openpyxl
    try:
        wb = openpyxl.load_workbook(target)
    except Exception as exc:                                         # noqa: BLE001
        return {"ok": False, "said": f"the central sheet could not be opened ({exc})"}
    ws = wb[tab] if tab and tab in wb.sheetnames else wb.active
    grid: List[List[Any]] = [[c.value for c in row] for row in ws.iter_rows()]
    p = plan(grid, drawing, row_hint, ref, quantity=quantity)
    if p.get("error"):
        return {"ok": False, "said": p["error"]}
    col, added = p["cost_col"], ""
    if col is None:
        col = p["next_col"]
        ws.cell(p["header_row"], col).value = COST_HEADER
        added = f"; added the {COST_HEADER} header"
    ws.cell(p["row"], col).value = float(value)
    wb.save(target)
    back = openpyxl.load_workbook(target)[ws.title].cell(p["row"], col).value
    if not _same(back, value):
        return {"ok": False, "said": f"row {p['row']} reads {back!r} after saving, not {value}"}
    return {"ok": True, "row": p["row"], "said": f"central sheet row {p['row']} AI Cost = {value}{added}"}
