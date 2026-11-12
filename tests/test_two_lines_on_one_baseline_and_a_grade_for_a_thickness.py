"""12696-01, 5 Oct 17:50 book on 811560b (D-394). D-393 promised the weld row would name TIG
and no cell did. The reader was called on the right part with the right sheet; the sheet's
text was the problem: pdfplumber merges characters whose tops lie within its y-tolerance into
one line and sorts them by x, and the border prints "WELD SPECIFICATION:" and "• ALL WELDS TO
BE TIG UNLESS STATED" in 7 pt two points apart — so the text read
"LEDCSIFTICOABTEIOTNIG:UNLESSSTATED". The same interleaving hid the material legend's heading,
and its "Q195 UP TO 3mm THICK FOR POWDER COATED STEEL" put a stated thickness of 3 on the PETG
strip's quality line. And the breaks sheet's "unit cost less the spread money" took the spread
off the unit figure after the unit cell's divisor instead of before it: £37.37 at one off on a
job whose 2,500-off column falls to £13.35.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import extractor_patterns as ep                                       # noqa: E402
import weld_symbols as ws                                             # noqa: E402


class _Page:
    def __init__(self, chars):
        self.chars = chars


def _line(text, top, x0=100.0, size=7.0, step=4.5):
    return [{"text": ch, "top": top, "x0": x0 + i * step, "size": size}
            for i, ch in enumerate(text)]


def test_two_lines_two_points_apart_are_read_as_two_lines():
    page = _Page(_line("WELD SPECIFICATION:", 780.0) + _line("• ALL WELDS TO BE TIG UNLESS STATED", 782.1))
    text = ws.text_by_baseline(page)
    assert "WELD SPECIFICATION:" in text.split("\n")
    assert "• ALL WELDS TO BE TIG UNLESS STATED" in text.split("\n")
    assert ep.weld_process_stated(text)["process"] == "TIG"
    # the interleaved reading the plain extraction gives finds nothing
    assert ep.weld_process_stated("LEDCSIFTICOABTEIOTNIG:UNLESSSTATED") is None


def test_a_page_with_no_characters_reads_as_nothing():
    assert ws.text_by_baseline(_Page([])) == ""
    assert ws.text_by_baseline(object()) == ""


def test_a_grade_for_a_thickness_band_is_not_the_parts_gauge():
    legend = ("• Q195 UP TO 3mm THICK FOR POWDER COATED STEEL • SPCC UP TO 3mm THICK FOR CHROME, "
              "ZINC PLATE OR HIGH QUALITY PAINT FINISH • Q235 OVER 3MM THICK FOR POWDER COATED STEEL")
    assert ep.extract_title_block_fields(legend + " MATERIAL: PETG").get("thicknesses_mm") in (None, [])
    assert ep._extract_thickness_fallbacks(legend) == []
    # a gauge the sheet states beside it is still read
    assert ep.extract_title_block_fields(legend + ". MATERIAL: 2mm MILD STEEL").get(
        "thicknesses_mm") == ["2"]


def test_unit_cost_less_the_spread_money_goes_through_the_unit_cells_own_divisor(tmp_path):
    import pytest
    openpyxl = pytest.importorskip("openpyxl")
    from quantity_breaks_tab import SHEET_NAME, write_quantity_breaks_tab
    wb = openpyxl.Workbook()
    wb.active.title = "Estimate"
    p = tmp_path / "12696-01_estimate.xlsx"
    wb.save(p)
    swept = {"rows": [
        {"quantity": 1, "material": 19.53, "labour": 217.43, "unit": 262.29,
         "order_charges_per_unit": 17.00, "setup_per_unit": 207.92},
        {"quantity": 2500, "material": 2.54, "labour": 9.60, "unit": 13.43,
         "order_charges_per_unit": 0.00, "setup_per_unit": 0.08},
    ]}
    write_quantity_breaks_tab(p, swept)
    sh = openpyxl.load_workbook(p)[SHEET_NAME]
    labels = {str(sh.cell(row=r, column=1).value or ""): r for r in range(1, 30)}
    r = labels["Unit cost less the spread money £"]
    one, last = sh.cell(row=r, column=2).value, sh.cell(row=r, column=3).value
    assert one == round((19.53 + 217.43 - 224.92) * 262.29 / (19.53 + 217.43), 2)   # 13.33
    assert abs(one - last) < 0.10                 # the floor the 2,500 column lands on
