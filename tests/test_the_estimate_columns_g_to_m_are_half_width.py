"""The Estimate sheet's columns G to M are written at half the template's width.

James Gray, 4 Nov 2026: "halve the column widths from G to M in the estimating sheet". The
template carries them at 42 to 73 characters. Each column keeps its own proportion; the
template on the share is not touched.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import config                                                          # noqa: E402
import wb_populate as wbp                                              # noqa: E402

TEMPLATE = {"C": 25.0, "F": 14.57, "G": 45.43, "H": 60.14, "I": 42.57, "J": 48.86,
            "K": 72.71, "L": 45.29, "M": 65.29}


def _sheet():
    import openpyxl
    ws = openpyxl.Workbook().active
    for letter, width in TEMPLATE.items():
        ws.column_dimensions[letter].width = width
    return ws


def test_the_setting_is_g_to_m_at_half():
    assert config.ESTIMATE_COLUMN_WIDTH_SCALE == ("G", "M", 0.5)


def test_each_column_from_g_to_m_is_half_its_own_width():
    ws = _sheet()
    done = wbp.scale_estimate_columns(ws, ("G", "M", 0.5))
    assert done == list("GHIJKLM")
    for letter in "GHIJKLM":
        assert abs(ws.column_dimensions[letter].width - TEMPLATE[letter] / 2) < 0.01


def test_the_columns_either_side_are_untouched():
    ws = _sheet()
    wbp.scale_estimate_columns(ws, ("G", "M", 0.5))
    assert ws.column_dimensions["C"].width == 25.0
    assert ws.column_dimensions["F"].width == 14.57


def test_a_width_set_for_a_range_reaching_outside_is_left_alone():
    import openpyxl
    ws = openpyxl.Workbook().active
    ws.column_dimensions["M"].width = 40.0
    ws.column_dimensions.group("M", "O", hidden=False)
    before = {k: (d.min, d.max, d.width) for k, d in ws.column_dimensions.items()}
    wbp.scale_estimate_columns(ws, ("G", "M", 0.5))
    assert {k: (d.min, d.max, d.width) for k, d in ws.column_dimensions.items()} == before


def test_no_setting_changes_nothing():
    ws = _sheet()
    assert wbp.scale_estimate_columns(ws, None) == []
    assert ws.column_dimensions["G"].width == TEMPLATE["G"]


def test_the_book_is_scaled_before_it_is_saved():
    src = (ROOT / "src" / "wb_populate.py").read_text(encoding="utf-8")
    body = src[src.index("def populate_workbook("):]
    assert body.index("scale_estimate_columns(wb[cm[\"estimate_sheet\"]]") < body.index(
        "wb.save(out_path)")
