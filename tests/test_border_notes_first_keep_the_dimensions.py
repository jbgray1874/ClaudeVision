"""A drawing whose border notes come first in its text keeps its dimensions.

The border filter cuts everything after a named specification heading. That is
right when the drawing's figures come first (the M&S sheets), and would drop every
real dimension on a sheet whose text lists the border notes before the figures.
"""
from extractor_patterns import dimension_text_without_border


MS_SHEET = ("384 50 92° 18 2.5 14.5 100.2 Flat Pattern 2026/11/4 STEVE KIRTON 31/48 "
            "WATERSIDE COLUMN B REV FINISH SPECIFICATIONS: POWDERCOATING: BETWEEN 80 - 120 "
            "MICRON THICKNESS GENERAL TOLERANCES: OVER 1000mm UP TO 2000mm +/-1.5mm "
            "Q195 UP TO 3mm THICK")

BORDER_FIRST = ("DRAWING No 7001-02 SHEET 1/2 SCALE 1:5 2025/03/14 GENERAL TOLERANCES: "
                "LINEAR +/-0.5 ANGLES +/-1 DEGREE 642 318 R12 45° 2 HOLES 8.5")


def test_figures_before_the_border_survive_and_the_border_goes():
    out = dimension_text_without_border(MS_SHEET)
    assert "384" in out and "100.2" in out
    assert "2026" not in out              # the date is not a size
    assert "Q195" not in out and "2000mm" not in out


def test_a_border_printed_first_does_not_take_the_dimensions_with_it():
    out = dimension_text_without_border(BORDER_FIRST)
    for figure in ("642", "318", "R12", "8.5"):
        assert figure in out
    assert "2025" not in out              # dates still go


def test_a_real_year_sized_dimension_is_kept():
    assert "2026" in dimension_text_without_border("2026 x 400 Flat Pattern")
