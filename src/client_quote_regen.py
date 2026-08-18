"""Regenerate a client quote from an estimator's AMENDED workbook — the manual-override path.

THE SPREADSHEET IS THE SOURCE OF TRUTH HERE, NOT THE ENGINE. The estimator opens the AI Estimate
workbook, edits it (fills a missing rate, corrects a price, sets a margin), saves it, and — hours
or days later — uploads that amended sheet and re-enters three facts a saved sheet cannot be
trusted to still carry: the number of units, the drawing number, and the client. This reads the
estimator's OWN figure straight off that sheet (Excel has already recomputed it) and re-renders
ONLY the client quote, through the same we.are.sdi template the engine uses. The job report and the
provenance tab are deliberately NOT touched — this is the estimator's number now, not the engine's.

Any drawings uploaded alongside are ignored: this path never re-reads a drawing or re-runs the
engine. It turns an amended sheet + three fields into a fresh, correctly-headed client quote.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

# The labels on the Estimate sheet whose row carries the figure we want, weakest-preferred last.
# Read by LABEL, not by cell address, so a template that shifts a row down does not silently read
# the wrong number. "Sell Price" is what the customer pays (post-margin); "Total Unit Cost Price"
# is the fallback when no margin has been set and the two are equal.
_PRICE_LABELS = ("Sell Price", "Total Unit Cost Price", "Unit Cost")
_QTY_LABELS = ("Quantity",)


def _num(value: Any) -> Optional[float]:
    """A number from a cell that may be a float, an int, or '£146.00' text."""
    if isinstance(value, (int, float)):
        return float(value) if value == value else None      # reject NaN
    if value is None:
        return None
    s = re.sub(r"[^0-9.\-]", "", str(value))
    try:
        return float(s) if s not in ("", "-", ".") else None
    except ValueError:
        return None


def _find_value_in_row(ws, row_idx: int, label_col: int) -> Optional[float]:
    """The first credible number to the RIGHT of a label cell, on the same row."""
    for col in range(label_col + 1, ws.max_column + 1):
        v = _num(ws.cell(row=row_idx, column=col).value)
        if v is not None:
            return v
    return None


def read_estimate_figures(workbook_path: str | Path) -> Dict[str, Any]:
    """The amended sheet's own numbers: {sell_price, unit_cost, quantity, price, source_label}.

    Reads the CACHED values Excel wrote when the estimator saved (openpyxl data_only), so it sees
    the recomputed figure, not the formula. If the sheet was never opened-and-saved in Excel the
    cache is empty — that is reported as a clear error, not a silent zero, because a quote built on
    a blank is worse than no quote."""
    from openpyxl import load_workbook

    path = Path(workbook_path)
    if not path.exists():
        raise FileNotFoundError(f"amended workbook not found: {path}")
    wb = load_workbook(str(path), data_only=True, read_only=True)
    try:
        ws = wb["Estimate"] if "Estimate" in wb.sheetnames else wb[wb.sheetnames[0]]
        found: Dict[str, float] = {}
        qty: Optional[float] = None
        wanted = {lbl.lower(): lbl for lbl in _PRICE_LABELS}
        qty_wanted = {lbl.lower() for lbl in _QTY_LABELS}
        for row in ws.iter_rows():
            for cell in row:
                if not isinstance(cell.value, str):
                    continue
                text = cell.value.strip().lower()
                if text in wanted and wanted[text] not in found:
                    v = _find_value_in_row(ws, cell.row, cell.column)
                    if v is not None:
                        found[wanted[text]] = v
                elif text in qty_wanted and qty is None:
                    qty = _find_value_in_row(ws, cell.row, cell.column)
    finally:
        wb.close()

    # The customer price, weakest-preferred last — Sell Price first.
    price = None
    source_label = ""
    for lbl in _PRICE_LABELS:
        if lbl in found and found[lbl] > 0:
            price, source_label = found[lbl], lbl
            break
    if price is None:
        raise ValueError(
            f"no Unit Cost / Sell Price figure could be read from {path.name}. Open the workbook "
            f"in Excel, let it recalculate, and Save before uploading — the figures are formulas "
            f"and are only stored once Excel has computed them.")
    return {
        "sell_price": found.get("Sell Price"),
        "unit_cost": found.get("Total Unit Cost Price") or found.get("Unit Cost"),
        "quantity": int(qty) if qty else None,
        "price": price,
        "source_label": source_label,
    }


def _summary_from_figures(figures: Dict[str, Any], *, units: int, drawing_number: str,
                          client: str, job_stem: str) -> Dict[str, Any]:
    """The minimal summary the quote renderer understands, carrying the estimator's own price and
    the three re-entered facts. Only the fields build_quote_html actually reads are set."""
    return {
        "job_output_stem": job_stem,
        "manual_estimator_override": True,
        "llm_full_extract": {"drawing_info": {"drawing_number": drawing_number}},
        "estimate_summary": {
            "workbook_equivalent_pricing": {"m105_total_unit_cost_gbp": figures["price"]},
            "estimate_workbook_inputs": {"assumed_job_quantity": int(units)},
        },
    }


def regenerate_quote_from_workbook(workbook_path: str | Path, *, units: int, drawing_number: str,
                                   client: str, out_dir: Optional[str | Path] = None,
                                   job_stem: Optional[str] = None) -> Tuple[str, Dict[str, Any]]:
    """Read an amended workbook + three re-entered fields and write a fresh client quote HTML.

    Returns (quote_html_path, figures). Reuses build_quote_html so the override quote is
    pixel-identical to an engine quote — same branding, layout and provisional labelling — it
    just carries the estimator's number. Nothing else is regenerated."""
    from client_quote_html import build_quote_html

    path = Path(workbook_path)
    stem = job_stem or re.sub(r"[^\w\- ]", "", str(drawing_number or path.stem)).strip() or "quote"
    figures = read_estimate_figures(path)
    if not str(client or "").strip():
        raise ValueError("client is required — it heads the quotation and picks the logo")
    if not int(units or 0) > 0:
        raise ValueError("units must be a positive whole number")

    summary = _summary_from_figures(figures, units=int(units), drawing_number=str(drawing_number),
                                    client=str(client), job_stem=stem)
    html = build_quote_html(summary, job_stem=stem, manual_workbook=str(path), customer=str(client))

    out_dir_p = Path(out_dir) if out_dir else path.parent
    out_dir_p.mkdir(parents=True, exist_ok=True)
    out_path = out_dir_p / f"{stem}_quote.html"
    out_path.write_text(html, encoding="utf-8")
    return str(out_path), figures
