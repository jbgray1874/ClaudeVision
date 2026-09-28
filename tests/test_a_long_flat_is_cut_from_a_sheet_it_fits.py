"""12645 book of 28 Sep 2026 (D-314).

Eight back panels, corners, columns and covers of 2,600 to 2,975 mm carried the template's
2500 x 1250 sheet; the row's nest formula found no fit and charged no steel while the parts
were still lasered — although config stocks 3000 x 1500 mild steel. And the shelter sheet's
"12645-01GA V2" became a second part, "12645-01GAV2", priced by AI at £557 as a bought-in body
on top of the body's own fabricated lines."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import part_identity as pi  # noqa: E402
import wb_populate as wp  # noqa: E402

TEMPLATE = (2500, 1250)


def test_a_flat_that_fits_the_template_sheet_keeps_it():
    assert wp.steel_sheet_for_row(2215.08, 1051.7, "MILD_STEEL", TEMPLATE) == (None, "")
    assert wp.steel_sheet_for_row(200, 95.2, "MILD_STEEL", TEMPLATE) == (None, "")


def test_an_over_length_flat_takes_the_smallest_stocked_sheet_it_fits():
    for length, width in ((2912.54, 1087.5), (2975.08, 685.4), (2600, 88.4)):
        sheet, why = wp.steel_sheet_for_row(length, width, "MILD_STEEL", TEMPLATE)
        assert sheet == (3000.0, 1500.0), (length, width)
        assert "cannot nest it" in why


def test_a_flat_longer_than_every_stocked_sheet_is_said_not_guessed():
    sheet, why = wp.steel_sheet_for_row(3020, 727.4, "MILD_STEEL", TEMPLATE)
    assert sheet is None
    assert "every stocked sheet" in why and "3000 x 1500" in why


def test_the_fit_is_the_one_nesting_rule():
    assert wp.steel_row_fits(2480, 1100, 2500, 1250)
    assert not wp.steel_row_fits(2912.54, 1087.5, 2500, 1250)


def test_a_version_mark_does_not_make_a_second_body():
    assert pi.normalize_part_code("12645-01GA V2") == "12645-01GA"
    assert pi.normalize_part_code("12645-01GA_V2 REV A") == "12645-01GA"


def test_a_code_that_only_looks_versioned_is_left_alone():
    assert pi.normalize_part_code("ABC-V2") == "ABC-V2"
    assert pi.normalize_part_code("SCREW V2") == "SCREWV2"
