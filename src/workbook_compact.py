"""Fold away the Estimate sheet's unused line slots — in the book we write, never the template.

James Gray, 23 Sep 2026: "Can we also find a way of removing rows not written to in the
estimating s/sheet to compress it for it to be easier to read from estimating? Not the blank
one we use as the source but the one we create."

The 11650-02 book carried about 126 empty material and labour slots between its handful of
real lines. They look blank and most are not: every slot holds the template's formulas, and
the totals, the quantity-break sweep, the report and the quote all read the sheet by ROW
ADDRESS — the labour total sums M96:M167 whatever is in it. Deleting rows would move every
one of those addresses. So nothing is deleted: each run of unused slots inside a section is
GROUPED and HIDDEN. The sheet reads short; the outline button beside it opens a group, and a
line typed into an opened slot is picked up by the formulas that were always there.

WHAT COUNTS AS A SLOT. A row carrying a formula that refers to its own row (M16 is
=(J16*K16)*…, G160 reads C160) — every line of every block has one; titles, column headers
and totals do not. A slot is UNUSED when both its description (column C) and its
quantity-per-unit cell are empty. Anything the engine or a person wrote keeps it visible.

WHY HIDING IS SAFE FOR THE ARITHMETIC. Excel's SUM and AGGREGATE(9,6,…) — what the template
totals with — include hidden rows; only SUBTOTAL(10x) and AGGREGATE options 1/3/5/7 skip them.
The function refuses to hide anything on a sheet that uses those, and says so.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

_HEADER_WORDS = ("PART DESCRIPTION", "OPERATION")
_HIDDEN_SENSITIVE = re.compile(r"SUBTOTAL\(\s*1\d\d|AGGREGATE\(\s*\d+\s*,\s*[1357]\b",
                               re.IGNORECASE)


def _own_row_formula(ws, r: int, max_col: int) -> bool:
    pat = re.compile(rf"(?<![A-Z0-9$])\$?[A-Z]{{1,3}}\$?{r}(?!\d)")
    for c in range(1, max_col + 1):
        v = ws.cell(r, c).value
        if isinstance(v, str) and v.startswith("=") and pat.search(v.upper()):
            return True
    return False


def _is_header(ws, r: int) -> bool:
    v = ws.cell(r, 3).value
    t = str(v or "").strip().upper()
    return t in _HEADER_WORDS or t.startswith("BILL OF MATERIALS")


def _qty_column(ws, header_row: int, max_col: int) -> Optional[int]:
    for c in range(3, max_col + 1):
        if str(ws.cell(header_row, c).value or "").strip().upper().startswith("QTY PER UNIT"):
            return c
    return None


def _empty(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, str):
        return not v.strip()
    return False


def _sheet_is_sensitive(wb) -> List[str]:
    hits = []
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                if isinstance(c.value, str) and _HIDDEN_SENSITIVE.search(c.value):
                    hits.append(f"{ws.title}!{c.coordinate}")
    return hits


def compact_estimate(wb, sheet_name: str = "Estimate", max_col: int = 13) -> Dict[str, Any]:
    """Group and hide unused slots on the Estimate sheet. Returns what it did, per section.

    Idempotent, and a sheet that already has manual outline levels keeps them."""
    out: Dict[str, Any] = {"hidden": 0, "sections": [], "refused": ""}
    if sheet_name not in wb.sheetnames:
        out["refused"] = f"no {sheet_name} sheet"
        return out
    sensitive = _sheet_is_sensitive(wb)
    if sensitive:
        out["refused"] = ("a formula ignores hidden rows (" + ", ".join(sensitive[:4])
                          + ") — hiding could change a total, so nothing was hidden")
        return out
    ws = wb[sheet_name]
    r = 1
    while r <= ws.max_row:
        if not _is_header(ws, r):
            r += 1
            continue
        header = r
        qcol = _qty_column(ws, header, max_col)
        title = str(ws.cell(header - 1, 3).value or ws.cell(header, 3).value or "").strip()
        rows: List[Tuple[int, bool]] = []
        r = header + 1
        while r <= ws.max_row and _own_row_formula(ws, r, max_col) and not _is_header(ws, r):
            used = not _empty(ws.cell(r, 3).value) or (
                qcol is not None and not _empty(ws.cell(r, qcol).value))
            rows.append((r, used))
            r += 1
        unused = [n for n, u in rows if not u]
        for n in unused:
            dim = ws.row_dimensions[n]
            dim.outlineLevel = max(int(dim.outlineLevel or 0), 1)
            dim.hidden = True
        if rows:
            out["sections"].append({"title": title, "first": rows[0][0], "last": rows[-1][0],
                                    "used": sum(1 for _, u in rows if u),
                                    "hidden": len(unused)})
        out["hidden"] += len(unused)
    if out["hidden"]:
        try:
            ws.sheet_properties.outlinePr.summaryBelow = True
            ws.sheet_format.outlineLevelRow = max(int(ws.sheet_format.outlineLevelRow or 0), 1)
        except Exception:                                            # noqa: BLE001
            pass
    return out
