#!/usr/bin/env python3
r"""What the same estimate costs at other quantities, asked of the spreadsheet itself.

WHY THIS IS NOT FOUR RUNS. Almost nothing upstream of the Estimate sheet depends on how many
we are making: the drawings, the SOLIDWORKS flats, the blanks, the gauges, the nest and the
route are identical at 1 off and at 100. What moves is inside the workbook, and the workbook
already knows how to move it — the throughput the engine writes into the labour block is
pieces per hour and carries no quantity, so the sheet computes
`hours = set-up + (D6 x qty per unit) / throughput` itself. Set D6, let Excel recalculate, and
the labour curve is the template's own arithmetic rather than a model of it.

Four full runs is two to three hours of a runner that can only do one job at a time. This is
minutes, and it is more defensible: nothing here is re-derived.

WHAT THE SHEET WILL NOT DO FOR US, AND WHICH THIS SAYS OUT LOUD RATHER THAN HIDING:

  * Packaging and delivery are priced by the engine for the whole order and divided by it,
    then written into the BOM as flat per-unit figures. Changing D6 does not re-price them,
    so at 25 off the sheet still charges the 1-off share. Reported as a correction against
    every quantity, with the total to subtract, so the estimator can drop a real freight
    figure in.
  * Bought-in prices do not step down. The template's price cell holds
    `LOOKUP($D$6, 'Material Price Break'!$D$4:$N$4, ...)` and wb_populate writes a literal
    over it, so the eleven-band break table never reaches the sheet. At 100 off that is a
    discount we are not showing. Named at every quantity; it is a defect, not a finding.

THE ESTIMATE ITSELF IS NEVER WRITTEN TO. The workbook is opened, driven, and closed with
SaveChanges=False, and the order cell is put back before it closes anyway. An estimate that has
gone to an estimator must not come back altered by a question somebody asked about it.

Asked for variants, it saves a workbook per quantity under its own name — and each one opens on
a page that says what it is, because a quantity variant looks exactly like a finished estimate
and the first thing that happens to an unmarked one is that somebody forwards it.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# The order-quantity cell, from the populator's own map, so the two cannot disagree about
# which cell drives the sheet.
_DEFAULT_ORDER_QTY_CELL = "D6"


def _order_qty_cell() -> str:
    try:
        from wb_populate import CELL_MAP
        return str(CELL_MAP["header"]["order_qty"])
    except Exception:                                            # noqa: BLE001
        return _DEFAULT_ORDER_QTY_CELL


def _money(value: Any) -> Optional[float]:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


_FREIGHT_CODES = ("PACKAGING", "DELIVERY")


def _freight_on_sheet(ws, max_row: int) -> Dict[str, Optional[float]]:
    """The commercial lines as this workbook actually carries them.

    THE BASELINE IS NOT ALWAYS ONE. Packaging and delivery are priced by the engine for the
    whole order and divided by it, so a run at 40 off already carries a realistic per-unit
    figure and a run at 1 carries the whole pallet. Subtracting an assumed GBP 170 from a
    sweep of a 40-off estimate would take out money that was never in it. So the figures come
    off the sheet, whatever they are.

    Read from column M — the line's own total, the figure that is inside Total Material Cost
    — rather than the unit price beside it, because M is what the total contains.
    """
    found: Dict[str, Optional[float]] = {}
    for row in range(1, min(max_row, 120) + 1):
        code = str(ws.Cells(row, 8).Value or "").strip().upper()
        if not code:
            code = str(ws.Cells(row, 3).Value or "").strip().upper()[:9]
        for wanted in _FREIGHT_CODES:
            if code.startswith(wanted) and wanted not in found:
                found[wanted] = _money(ws.Cells(row, 13).Value)
    return found


def sweep(xlsx_path: Any, quantities: List[int],
          sheet_name: str = "Estimate",
          save_variants: bool = False,
          order_freight: Optional[Dict[str, float]] = None) -> Optional[Dict[str, Any]]:
    """Total Material, Total Labour and Unit Cost at each quantity, read from the sheet.

    Returns None with a printed reason rather than raising: this answers a question about an
    estimate, and it may not damage the estimate or the run that asked.
    """
    if sys.platform != "win32":                                  # pragma: no cover
        print("   [qty-sweep] not Windows — Excel is what does the arithmetic here, so "
              "there is nothing to ask.", flush=True)
        return None

    book = Path(xlsx_path)
    if not book.is_file():
        print(f"   [qty-sweep] workbook not found: {book}", flush=True)
        return None

    wanted = sorted({int(q) for q in quantities if int(q) >= 1})
    if not wanted:
        print("   [qty-sweep] no quantities asked for.", flush=True)
        return None

    from wep_readback_from_xlsx import (_TOTAL_LABELS, _close_excel, _open_xlsx_excel_com,
                                        _scan_total, _used_bounds)

    cell = _order_qty_cell()
    excel = com_wb = None
    try:
        excel, com_wb = _open_xlsx_excel_com(book, prime_sheet=sheet_name)
        try:
            ws = com_wb.Worksheets(sheet_name)
        except Exception:                                        # noqa: BLE001
            ws = com_wb.ActiveSheet
        max_row, max_col = _used_bounds(ws)

        original = ws.Range(cell).Value
        baseline = int(_money(original) or 1)
        freight = _freight_on_sheet(ws, max_row)

        rows: List[Dict[str, Any]] = []
        saved: List[str] = []
        for qty in wanted:
            ws.Range(cell).Value = qty
            # Freight BEFORE the recalculation, so the totals this reads are the corrected
            # ones. Reading first and re-pricing after would report a number the saved
            # workbook does not contain.
            _repriced = (_reprice_freight(ws, max_row, qty, order_freight or {})
                         if save_variants else {})
            excel.CalculateFull()
            row: Dict[str, Any] = {"quantity": qty}
            for key, needles in _TOTAL_LABELS.items():
                row[key] = _money(_scan_total(ws, needles, max_row, max_col))
            rows.append(row)
            if save_variants:
                # SaveAs RE-POINTS THE OPEN WORKBOOK at the new file, so from here on the
                # session is editing the variant and not the estimate. That is the property
                # that matters: the original on disk is never written to, by anything, on any
                # path through this function. Each variant deletes and rewrites the banner, so
                # one derived from another still says the right quantity.
                _path = _save_variant(com_wb, book, qty, baseline, freight, row,
                                      repriced=_repriced)
                if _path:
                    saved.append(_path)
                    row["workbook"] = _path

        # PUT IT BACK. The close below discards changes, but a workbook left holding a
        # quantity nobody asked for — if anything ever did save it — is the one way this
        # could corrupt an estimate that was perfectly good.
        ws.Range(cell).Value = original
        excel.CalculateFull()

        return {"workbook": str(book), "order_qty_cell": cell,
                "baseline_quantity": baseline, "rows": rows,
                "freight_on_sheet": freight, "variants": saved,
                "freight_repriced": bool(order_freight)}
    except Exception as exc:                                     # noqa: BLE001
        print(f"   [qty-sweep] failed ({type(exc).__name__}: {exc}) — the workbook is "
              f"unchanged.", flush=True)
        return None
    finally:
        try:
            if com_wb is not None:
                com_wb.Close(SaveChanges=False)
        except Exception:                                        # noqa: BLE001
            pass
        try:
            if excel is not None:
                _close_excel(excel, None)
        except Exception:                                        # noqa: BLE001
            pass


# ── saved copies, and why each one shouts about itself ───────────────────────

_BANNER_SHEET = "READ THIS FIRST"


def _reprice_freight(ws, max_row: int, qty: int,
                     order_freight: Dict[str, float]) -> Dict[str, float]:
    """Divide the ORDER's packaging and delivery by THIS quantity, in this variant.

    THE ONE THING A RECALCULATED SHEET GETS PLAINLY WRONG. Packaging and delivery are asked
    for the whole order and divided per unit at run time, so a variant made from a 1-off
    estimate carries the whole pallet on every one of 500 units — £37.14 a unit that should
    be about £0.07. It is the single biggest error in a variant and it swamps the saving the
    variant exists to show.

    The engine knows the ORDER-level figure, and dividing it is arithmetic, not a new
    estimate. So where the run hands those figures down, each variant carries freight priced
    for its own quantity; where it does not, the banner says the freight is still the
    baseline's, exactly as before. Nothing is invented either way.
    """
    written: Dict[str, float] = {}
    if not order_freight:
        return written
    for row in range(1, min(max_row, 120) + 1):
        code = str(ws.Cells(row, 8).Value or "").strip().upper()
        if not code:
            continue
        for wanted, order_gbp in order_freight.items():
            if not code.startswith(wanted):
                continue
            per_unit = round(float(order_gbp) / max(1, qty), 2)
            ws.Cells(row, 10).Value = per_unit          # J — the line's unit price
            written[wanted] = per_unit
    return written


def _save_variant(com_wb, book: Path, qty: int, baseline: int,
                  freight: Dict[str, Optional[float]],
                  row: Dict[str, Any],
                  repriced: Optional[Dict[str, float]] = None) -> Optional[str]:
    """Save the recalculated workbook as its own file, opening on a page that says what it is.

    A QUANTITY VARIANT LOOKS EXACTLY LIKE A FINISHED ESTIMATE, which is the danger. It has the
    right drawings, the right blanks, a plausible unit cost and the SDI template around it —
    and it carries freight priced at a quantity nobody is quoting and bought-ins that never
    took their price break. Left unmarked, the first thing that happens to it is somebody
    forwards it.

    So the banner is a sheet, placed first and activated before the save, and Excel opens the
    file on it. Not a cell comment, not a footnote on a tab nobody opens: the page you land on.
    Nothing on the Estimate sheet is touched, because guessing at a free cell on the
    estimators' own template is how you overwrite something that mattered.
    """
    try:
        out = book.with_name(f"{book.stem}_qty{qty}{book.suffix}")

        for existing in list(com_wb.Worksheets):
            if str(existing.Name).strip().upper() == _BANNER_SHEET:
                existing.Delete()
                break
        ws = com_wb.Worksheets.Add(Before=com_wb.Worksheets(1))
        ws.Name = _BANNER_SHEET

        carried = round(sum(v for v in freight.values() if v), 2)
        lines = [
            [f"QUANTITY VARIANT — {qty} OFF. NOT A QUOTE."],
            [""],
            [f"This is {book.name} recalculated at {qty} off. It was estimated at "
             f"{baseline} off, and two things did not re-price when the quantity changed."],
            [""],
            ([f"1. FREIGHT HAS BEEN RE-PRICED FOR {qty} OFF."]
             if repriced else
             ["1. FREIGHT IS STILL PRICED AT " + str(baseline) + " OFF."]),
            ([f"   Packaging and delivery are worked out for the whole order and divided "
              f"by it. The order figures from the {baseline}-off run have been divided by "
              f"{qty} instead: "
              + ", ".join(f"{k} GBP {v:,.2f}/unit" for k, v in sorted(repriced.items()))
              + ". That is arithmetic on a figure the engine already had, not a new "
                "estimate — the ORDER cost of boxing and hauling is assumed unchanged, "
                "which is close enough to compare quantities and is not a quotation."]
             if repriced else
             [f"   Packaging and delivery are worked out for the whole order and divided by "
              f"it, by the engine, at run time. This sheet still carries "
              f"GBP {carried:,.2f} per unit from the {baseline}-off run. At {qty} off the "
              f"real figure is lower, and it has to come from a proper run."]),
            [""],
            ["2. BOUGHT-IN PRICES DID NOT STEP DOWN."],
            ["   The template has a quantity price-break lookup and the engine writes a "
             "fixed price over it, so every bought-in line costs the same at 100 off as at "
             "1. This sheet therefore understates the discount available."],
            [""],
            ["Both overstate this variant. Use it to see the shape of the curve, and run the "
             "job properly at the quantity you intend to quote."],
            [""],
            ["What this sheet reads at " + str(qty) + " off:"],
            ["   Total Material Cost", f"GBP {row.get('material') or 0:,.2f}"],
            ["   Total Labour Cost", f"GBP {row.get('labour') or 0:,.2f}"],
            ["   Total Unit Cost Price", f"GBP {row.get('unit') or 0:,.2f}"],
        ]
        width = max(len(r) for r in lines)
        padded = [list(r) + [""] * (width - len(r)) for r in lines]
        ws.Range(ws.Cells(1, 1), ws.Cells(len(padded), width)).Value = padded
        ws.Columns(1).ColumnWidth = 96
        ws.Columns(2).ColumnWidth = 22
        ws.Rows(1).Font.Bold = True
        ws.Rows(1).Font.Size = 14

        # The sheet that is active at save time is the sheet Excel opens on.
        ws.Activate()
        com_wb.SaveAs(str(out))
        print(f"   [qty-sweep] wrote {out.name}", flush=True)
        return str(out)
    except Exception as exc:                                     # noqa: BLE001
        print(f"   [qty-sweep] variant for {qty} off not saved "
              f"({type(exc).__name__}: {exc}) — the table above is unaffected.", flush=True)
        return None


# ── what the sweep cannot answer on its own ──────────────────────────────────

def commercial_correction(result: Dict[str, Any],
                          packaging_gbp: Optional[float] = None,
                          delivery_gbp: Optional[float] = None) -> List[Dict[str, Any]]:
    """Per quantity: the unit cost as the sheet computed it, and with the 1-off freight out.

    The engine prices packaging and delivery for the WHOLE ORDER and divides by it, then
    writes the result into the BOM as a flat per-unit figure. D6 does not re-price them, so
    every quantity below still carries the 1-off share — the single biggest overstatement in
    a multi-quantity sweep, and the reason this function exists rather than a footnote.

    "Unit less freight" is the honest halfway house: it is not the answer, it is the answer
    with the wrong number taken out, so a real freight figure can be added back.
    """
    # WHAT THE SHEET CARRIES, unless the caller names something better. Read from the
    # workbook it swept, so a sweep of a 40-off estimate subtracts the 40-off freight rather
    # than an assumed pallet nobody paid for.
    on_sheet = result.get("freight_on_sheet") or {}
    if packaging_gbp is None:
        packaging_gbp = on_sheet.get("PACKAGING")
    if delivery_gbp is None:
        delivery_gbp = on_sheet.get("DELIVERY")
    carried = round((packaging_gbp or 0.0) + (delivery_gbp or 0.0), 2)
    out: List[Dict[str, Any]] = []
    for row in result.get("rows") or []:
        unit = _money(row.get("unit"))
        # Freight sits in material, and material passes through the same absorption divisor
        # the unit cell applies — so removing it at unit level has to travel the same way, or
        # the corrected figure is out by the divisor.
        divisor = None
        material, labour = _money(row.get("material")), _money(row.get("labour"))
        if unit and material is not None and labour is not None and (material + labour):
            divisor = (material + labour) / unit
        out.append({
            "quantity": row.get("quantity"),
            "material": material, "labour": labour, "unit": unit,
            "freight_carried_gbp": carried,
            "unit_less_freight": (round(unit - (carried / divisor), 2)
                                  if unit and divisor and carried else None),
        })
    return out


def to_markdown(result: Optional[Dict[str, Any]],
                corrected: Optional[List[Dict[str, Any]]] = None) -> str:
    if not result or not result.get("rows"):
        return "No quantity sweep was produced."
    lines = [f"## What {Path(result['workbook']).stem} costs at other quantities", "",
             f"Read from the Estimate sheet by setting `{result['order_qty_cell']}` and "
             f"letting Excel recalculate. It was estimated at "
             f"{result['baseline_quantity']} off. Nothing is re-derived, and the estimate "
             f"itself was not written to.", ""]
    if corrected:
        lines += ["| Order qty | Material | Labour | Unit cost | Unit less 1-off freight |",
                  "|---|---|---|---|---|"]
        for row in corrected:
            lines.append(
                f"| {row['quantity']} | £{row['material']:,.2f} | £{row['labour']:,.2f} "
                f"| **£{row['unit']:,.2f}** "
                + (f"| £{row['unit_less_freight']:,.2f} |"
                   if row.get("unit_less_freight") is not None else "| — |"))
        lines += ["",
                  "> **Two corrections this sweep cannot make for you.** Packaging and "
                  "delivery are priced by the engine for the whole order and divided by it, "
                  f"then written in as a flat per-unit figure — every row above still carries "
                  f"the £{corrected[0]['freight_carried_gbp']:,.2f} computed at "
                  f"{result['baseline_quantity']} off — read off this workbook, not assumed "
                  f"— which is why the last column exists. "
                  "And bought-in prices do not step down at any quantity, because the "
                  "template's price-break lookup is overwritten with a literal. Both "
                  "overstate the higher quantities."]
    else:
        lines += ["| Order qty | Material | Labour | Unit cost |", "|---|---|---|---|"]
        for row in result["rows"]:
            lines.append(f"| {row['quantity']} | £{row.get('material') or 0:,.2f} "
                         f"| £{row.get('labour') or 0:,.2f} "
                         f"| **£{row.get('unit') or 0:,.2f}** |")
    return "\n".join(lines)
