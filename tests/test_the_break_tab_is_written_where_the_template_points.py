"""The quantity breaks go where the template's own formulas point, not to a remembered cell.

12173, 29 Sep 2026. Rows had been added to the Estimate (the Sheet Steel block, and thirty in
the BOM block), and Excel moved every reference with them: the break tab's header now read
=Estimate!F235. The writer still wrote the job's breaks to the literal F180 — eleven labour
Part No. cells came out as 1, 10, 50, 100, 200, 500 — and the break tab read the template's
defaults. Its BOM labels were not one offset either: rows 5-25 read Estimate 11-31 and rows
26-44 read 62-80.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

openpyxl = pytest.importorskip("openpyxl")
import material_price_break as mpb  # noqa: E402

_CFG = {"sheet": "Material Price Break", "estimate_sheet": "Estimate", "row_offset": -6,
        "first_bom_row": 11, "last_bom_row": 50, "qty_vector_first_cell": "F180",
        "first_price_col": 4, "last_price_col": 14}


def _book():
    wb = openpyxl.Workbook()
    est = wb.active
    est.title = "Estimate"
    est["C10"] = "Bill of Materials (Per Unit)"
    est["C81"] = "Wire"
    est["F180"] = "12173-04-02M-H"                   # a labour Part No. cell
    est["F234"] = "Qty Breaks"
    tab = wb.create_sheet("Material Price Break")
    for i in range(11):
        tab.cell(row=4, column=4 + i, value=f"=Estimate!F{235 + i}")
    for b, e in list(zip(range(5, 26), range(11, 32))) + list(zip(range(26, 45), range(62, 81))):
        tab.cell(row=b, column=3, value=f"=Estimate!C{e}:G{e}")
    tab.cell(row=45, column=3, value="=Estimate!C83:G83")     # the Wire block's label
    return wb, est, tab


def test_the_breaks_follow_the_header_formula():
    wb, est, _tab = _book()
    mpb.write_price_breaks(wb, [{"sheet_row": 11, "code": "A", "unit_gbp": 6.7}],
                           [1, 10, 50], _CFG)
    assert est["F180"].value == "12173-04-02M-H", "a labour cell was overwritten"
    assert [est.cell(row=235 + i, column=6).value for i in range(4)] == [1, 10, 50, 50]


def test_each_bom_row_prices_the_break_line_that_reads_it():
    wb, _est, tab = _book()
    done = mpb.write_price_breaks(wb, [{"sheet_row": 65, "code": "B", "unit_gbp": 2.0},
                                       {"sheet_row": 40, "code": "C", "unit_gbp": 1.0}],
                                  [1, 10], _CFG)
    assert tab["D29"].value == 2.0                   # break row 29 reads Estimate row 65
    assert tab["D34"].value is None                  # not Estimate 40's line (40 - 6)
    assert any("sheet row 40" in o for o in done["outside_table"]), done


def test_a_tab_that_states_nothing_keeps_the_configured_layout():
    ws = openpyxl.Workbook().active
    assert mpb.template_layout(ws) == {}
