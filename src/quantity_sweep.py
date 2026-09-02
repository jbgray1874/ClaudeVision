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

NOTHING IS SAVED. The workbook is opened, driven and closed with SaveChanges=False, and D6 is
put back before it closes anyway. An estimate that has been sent to an estimator must not come
back altered by a question somebody asked about it.
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


def sweep(xlsx_path: Any, quantities: List[int],
          sheet_name: str = "Estimate") -> Optional[Dict[str, Any]]:
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

        rows: List[Dict[str, Any]] = []
        for qty in wanted:
            ws.Range(cell).Value = qty
            excel.CalculateFull()
            row: Dict[str, Any] = {"quantity": qty}
            for key, needles in _TOTAL_LABELS.items():
                row[key] = _money(_scan_total(ws, needles, max_row, max_col))
            rows.append(row)

        # PUT IT BACK. The close below discards changes, but a workbook left holding a
        # quantity nobody asked for — if anything ever did save it — is the one way this
        # could corrupt an estimate that was perfectly good.
        ws.Range(cell).Value = original
        excel.CalculateFull()

        return {"workbook": str(book), "order_qty_cell": cell,
                "baseline_quantity": baseline, "rows": rows}
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


# ── what the sweep cannot answer on its own ──────────────────────────────────

def commercial_correction(result: Dict[str, Any],
                          packaging_gbp: Optional[float],
                          delivery_gbp: Optional[float]) -> List[Dict[str, Any]]:
    """Per quantity: the unit cost as the sheet computed it, and with the 1-off freight out.

    The engine prices packaging and delivery for the WHOLE ORDER and divides by it, then
    writes the result into the BOM as a flat per-unit figure. D6 does not re-price them, so
    every quantity below still carries the 1-off share — the single biggest overstatement in
    a multi-quantity sweep, and the reason this function exists rather than a footnote.

    "Unit less freight" is the honest halfway house: it is not the answer, it is the answer
    with the wrong number taken out, so a real freight figure can be added back.
    """
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
             f"letting Excel recalculate. Nothing is re-derived and nothing was saved.", ""]
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
                  f"{result['baseline_quantity']} off, which is why the last column exists. "
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
