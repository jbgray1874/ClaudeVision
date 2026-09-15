"""Every quantity break on one sheet, beside the estimate it came from.

    "Brief requests quantity break for 10, 50, 250 and 1000 ... For ease of process / check
     can all quantity breaks be on one sheet / show formulas selected."
                                      — Howard Thurley, SDI estimating, 0355255, 9 Sep 2026

The sweep already prices every break. It saves A WORKBOOK PER QUANTITY, each opening on a page
saying which quantity it is — which is right for sending one out, and wrong for the job Howard
is actually doing. Comparing four quantities meant four files open, four tabs, and reading the
unit cost out of each by eye; the comparison he wants to make is the one thing the deliverable
would not let him make.

So the breaks also land as COLUMNS ON ONE SHEET in the estimate itself, the way an estimator
lays them out by hand: quantity across the top, material, labour and unit cost down the side,
and underneath each one what it is against the smallest break — because the question a break
table exists to answer is "what does the volume buy me", and that is a subtraction nobody
should be doing in their head.

IT REPORTS, IT DOES NOT RE-PRICE. Every figure here was read off the recalculated sheet by the
sweep; nothing on this tab computes a price. If a number here disagrees with a variant
workbook, the variant is right and this is stale — so it carries the run's own stamp and says
where each figure came from.

THE VARIANT WORKBOOKS STAY. They are what gets sent; this is what gets read.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

SHEET_NAME = "Quantity Breaks"


def _money(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None                                  # NaN is not a price


def _rows_of(swept: Any) -> List[Dict[str, Any]]:
    if not isinstance(swept, dict):
        return []
    out = []
    for r in (swept.get("rows") or []):
        if not isinstance(r, dict):
            continue
        try:
            q = int(r.get("quantity") or 0)
        except (TypeError, ValueError):
            continue
        if q >= 1:
            out.append(r)
    return sorted(out, key=lambda r: int(r["quantity"]))


def write_quantity_breaks_tab(xlsx_path: Any, swept: Any,
                              requested: Optional[List[int]] = None) -> Optional[str]:
    """Add (or replace) the one-sheet break table. Returns the sheet name, or None.

    Never raises into a run: this reports on an estimate and may not damage it.
    """
    rows = _rows_of(swept)
    if not rows:
        return None
    try:
        import openpyxl                                           # noqa: PLC0415
        from openpyxl.styles import Alignment, Font               # noqa: PLC0415

        wb = openpyxl.load_workbook(str(xlsx_path))
        if SHEET_NAME in wb.sheetnames:
            del wb[SHEET_NAME]
        ws = wb.create_sheet(SHEET_NAME)

        bold = Font(bold=True)
        ws["A1"] = "Quantity breaks"
        ws["A1"].font = Font(bold=True, size=14)
        ws["A2"] = ("Read off this estimate at each quantity. Prices nothing itself — every "
                    "figure was taken from the recalculated sheet.")
        ws["A2"].font = Font(italic=True, size=9)

        # WHAT WAS ASKED FOR AND WHAT CAME BACK ARE TWO FACTS. Howard asked for 10, 50, 250
        # and 1000 and got 50, 100, 250 and 1000 — a break he did not want and, more to the
        # point, one missing that he did. A table that simply prints what it produced cannot
        # show that; this one names the difference where he is already looking.
        _got = [int(r["quantity"]) for r in rows]
        if requested:
            _want = sorted({int(q) for q in requested if int(q) >= 1})
            _missing = [q for q in _want if q not in _got]
            _extra = [q for q in _got if q not in _want]
            if _missing or _extra:
                bits = []
                if _missing:
                    bits.append("asked for and NOT priced: "
                                + ", ".join(str(q) for q in _missing))
                if _extra:
                    bits.append("priced but not asked for: "
                                + ", ".join(str(q) for q in _extra))
                ws["A3"] = " · ".join(bits)
                ws["A3"].font = Font(bold=True, color="B3261E", size=10)

        head = 5
        ws.cell(row=head, column=1, value="Quantity").font = bold
        labels = (("material", "Material £/unit"), ("labour", "Labour £/unit"),
                  ("unit", "Unit cost £"))
        for i, (_key, _label) in enumerate(labels, start=1):
            ws.cell(row=head + i, column=1, value=_label).font = bold
        ws.cell(row=head + 4, column=1, value="Order value £").font = bold

        base_unit = _money(rows[0].get("unit"))
        ws.cell(row=head + 6, column=1,
                value=f"Against {rows[0]['quantity']} off").font = bold
        # ONLY WHEN THERE ARE FILES TO NAME. Since the one sheet took over, no per-quantity
        # copies are filed — a row headed "Workbook" over four empty cells reads as four
        # files that failed to save, and the closing sentence recommended sending them.
        _any_wbk = any(str(r.get("workbook") or "") for r in rows)
        if _any_wbk:
            ws.cell(row=head + 7, column=1, value="Workbook").font = bold

        for col, r in enumerate(rows, start=2):
            q = int(r["quantity"])
            ws.cell(row=head, column=col, value=q).font = bold
            for i, (key, _label) in enumerate(labels, start=1):
                ws.cell(row=head + i, column=col, value=_money(r.get(key)))
            _u = _money(r.get("unit"))
            if _u is not None:
                ws.cell(row=head + 4, column=col, value=round(_u * q, 2))
            # THE SAVING, SUBTRACTED HERE SO NOBODY DOES IT IN THEIR HEAD. Against the
            # smallest break asked for, which is the comparison a break table is for.
            if _u is not None and base_unit:
                _d = _u - base_unit
                ws.cell(row=head + 6, column=col,
                        value=(f"{_d:+.2f}  ({_d / base_unit * 100:+.1f}%)"
                               if col > 2 else "—"))
            _wbk = str(r.get("workbook") or "")
            if _wbk:
                ws.cell(row=head + 7, column=col, value=_wbk.rsplit("\\", 1)[-1]
                        .rsplit("/", 1)[-1])

        ws.column_dimensions["A"].width = 22
        for col in range(2, len(rows) + 2):
            ws.column_dimensions[ws.cell(row=head, column=col).column_letter].width = 17
        for _r in range(head, head + 8):
            for _c in range(2, len(rows) + 2):
                ws.cell(row=_r, column=_c).alignment = Alignment(horizontal="right")

        _n = ws.max_row + 2
        ws.cell(row=_n, column=1, value=(
            "Each column is this estimate recalculated at that quantity. The per-quantity "
            "workbooks named above are the ones to send; this sheet is the comparison."
            if _any_wbk else
            # THE SENTENCE MUST MATCH WHAT THE RUN DID. The 16:07 book carried the old
            # wording over an empty Workbook row — advising the reader to send files that
            # were deliberately not filed.
            "Each column is this estimate recalculated at that quantity. There are no "
            "per-quantity copies: set the order quantity in Estimate D6 and the sheet "
            "prices itself — the Material Price Break tab carries each line across the "
            "breaks. This sheet is the comparison."))
        ws.cell(row=_n, column=1).font = Font(italic=True, size=9)

        wb.save(str(xlsx_path))
        return SHEET_NAME
    except Exception as exc:                                      # noqa: BLE001
        print(f"   [qty-breaks] could not write the one-sheet break table "
              f"({type(exc).__name__}: {exc}) — the estimate is unchanged.", flush=True)
        return None


def select_show_formulas(xlsx_path: Any, sheets: Any = ("Estimate",)) -> List[str]:
    """Open the named sheets with Excel's Show Formulas already selected.

    "show formulas selected" — Howard, and Tim asked for the same thing in his own words.
    The sheet has held live formulas all along; what neither of them could do was SEE them
    without knowing that Ctrl+` exists. This is that toggle, saved into the file.

    It is a VIEW, not a change to a single cell: the formulas, the values and the totals are
    all exactly as they were, and anyone who wants the numbers back presses Ctrl+` once. That
    is why it is safe to ship and why it is reversible by the person looking at it.
    """
    done: List[str] = []
    try:
        import openpyxl                                           # noqa: PLC0415
        wb = openpyxl.load_workbook(str(xlsx_path))
        for name in (sheets or ()):
            if name not in wb.sheetnames:
                continue
            ws = wb[name]
            try:
                ws.sheet_view.showFormulas = True
                done.append(name)
            except Exception:                                     # noqa: BLE001
                continue
        if done:
            wb.save(str(xlsx_path))
    except Exception as exc:                                      # noqa: BLE001
        print(f"   [show-formulas] could not set the view ({type(exc).__name__}: {exc}) — "
              f"the estimate is unchanged.", flush=True)
        return []
    return done
