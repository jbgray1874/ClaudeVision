"""A BOARD ROW'S SHEET HOLDS ITS BLANK BY THE ROW'S OWN RULE (20 Nov 2026).

12110-04-01J, run d95c7b140e6a: a 2430 x 1210 x 6 mm MDF backing panel, priced by weight with no
sheet chosen. The Other Sheet row wrote the default 2440 x 1220 and an £18.08 sheet price; the
template's nest leaves 10 mm each side of a part and 5 mm off the width, (1220-5)/(1210+20) is 0,
so the row charged £0 material and asked nothing.

As Sheet Steel does, the row now takes the smallest stocked board sheet its rule can nest the
blank on, prices that sheet from the board's own rate, and asks whether the part is really cut
from it. A part that fits the default sheet is written exactly as before. Invented numbers.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")


def _template(path: Path) -> Path:
    import openpyxl
    book = openpyxl.Workbook()
    ws = book.active
    ws.title = "Estimate"
    for row, text in ((10, "Bill of Materials (Per Unit)"), (51, "Wire"),
                      (52, "Part Description"), (61, "Sheet Steel"), (62, "Part Description"),
                      (82, "Other Sheet Material"), (83, "Part Description"),
                      (92, "Total Material Cost"), (94, "Labour"), (95, "Operation"),
                      (168, "Total Labour Cost (Including  Downtime)")):
        ws.cell(row, 3, text)
    ws.cell(92, 13, "=(SUM(M11:M50)+SUM(M53:M60)+SUM(M63:M81)+SUM(M84:M91)+AF83)")
    book.save(path)
    return path


def _panel(pn, length, width):
    return {"part_number": pn, "description": "BACKING PANEL", "quantity": 1,
            "normalized_material": "MDF", "normalized_thickness_mm": 6.0,
            "blank_length_mm": float(length), "blank_width_mm": float(width),
            "page_roles": ["detail"]}


def _row_of(tmp_path, monkeypatch, parts, by_weight=True):
    import openpyxl
    import estimator as E
    import wb_populate
    summary = {"declared_product": "50004-GA", "drawing_number": "50004-GA",
               "manufacturing_writeup": {"parts": parts}, "document_analysis": {"bom_rows": []},
               "llm_full_extract": {}, "pages": [], "job_folder": str(tmp_path)}
    summary["estimate_summary"] = E.estimate_document(parts, summary=summary)
    summary["part_estimates"] = summary["estimate_summary"]["part_estimates"]
    if by_weight:
        # as on the real run: priced by weight, so the costing chose no sheet
        for pe in summary["part_estimates"]:
            me = pe.get("material_estimate") or {}
            me.pop("stock_estimate", None)
            me.pop("sheet_price_gbp", None)
            me.pop("parts_per_sheet", None)
    monkeypatch.setenv("SDI_WB_TEMPLATE", str(_template(tmp_path / "template.xlsx")))
    monkeypatch.setitem(wb_populate.CELL_MAP, "output_dir", str(tmp_path / "out"))
    out = wb_populate.populate_workbook(summary, "SHEETFIT")
    assert out
    ws = openpyxl.load_workbook(out)["Estimate"]
    c = wb_populate.CELL_MAP["other_sheet"]
    rows = {}
    for r in range(c["first_row"], c["last_row"] + 1):
        desc = str(ws.cell(r, c["col_desc"]).value or "")
        if desc:
            rows[desc.split()[0]] = (float(ws.cell(r, c["col_sheet_l"]).value),
                                     float(ws.cell(r, c["col_sheet_w"]).value),
                                     ws.cell(r, c["col_cost_per_sheet"]).value)
    return rows, summary


def _costed(summary, pn):
    """The part as the costed record reads it: the workbook's own published copy."""
    pes = summary["estimate_summary"].get("canonical_part_estimates") or summary["part_estimates"]
    return next(p for p in pes if p.get("part_number") == pn)


def test_a_near_full_sheet_panel_goes_on_a_sheet_the_row_can_nest_and_is_asked(tmp_path, monkeypatch):
    import costed_facts as cf
    rows, summary = _row_of(tmp_path, monkeypatch, [_panel("50004-04-01J", 2430, 1210)])
    sl, sw, price = rows["50004-04-01J"]
    assert cf.nest_on_sheet("MDF", 2430, 1210, sl, sw), (sl, sw)
    assert (sl, sw) != (2440.0, 1220.0)
    assert price and float(price) > 0, "the sheet it is written on is priced"
    pe = _costed(summary, "50004-04-01J")
    asked = " ".join(str(q.get("issue")) for q in pe.get("manufacturing_questions") or [])
    assert "does not fit a 2440 x 1220 sheet" in asked


def test_a_panel_that_fits_the_default_sheet_is_written_as_before(tmp_path, monkeypatch):
    rows, summary = _row_of(tmp_path, monkeypatch, [_panel("50004-04-02J", 1200, 600)])
    sl, sw, price = rows["50004-04-02J"]
    assert (sl, sw) == (2440.0, 1220.0)
    pe = _costed(summary, "50004-04-02J")
    assert not any("does not fit" in str(q.get("issue"))
                   for q in pe.get("manufacturing_questions") or [])
