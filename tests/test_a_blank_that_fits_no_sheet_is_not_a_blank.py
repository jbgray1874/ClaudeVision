"""A blank bigger than any sheet the material comes in is a bounding box, not a part.

On 12349-02 the two LARGEST parts — a 5 mm acrylic fabrication and a 6 mm MDF packer — were
each recorded as 2120 x 2120 mm, which is the drawing sheet's own bounding box picked up as
"the largest numbers in the document text". The existing guard asks only whether a number is
between 10 mm and 4 m, so it passed.

Excel had already worked out that it was wrong. Nothing 2120 square nests on a 2050 x 1520
acrylic sheet or a 2440 x 1220 board, so Qty Per Sheet came back empty, Cost Per Part came back
empty, and both parts contributed NOTHING to the material total while appearing on the Estimate
sheet as ordinary rows. A part that silently costs nothing is worse than one that is refused,
because a refusal is at least visible.

The same bounding box then sized the packaging and the haulage — 661 kg on two pallets — so one
bad blank priced three lines.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

import blank_credibility as bc                                          # noqa: E402


def test_the_drawing_sheet_bounding_box_does_not_fit_the_material():
    """12349-02's actual numbers, on its actual materials."""
    assert bc.fits_a_stock_sheet(2120, 2120, "HIGH IMPACT ACRYLIC") is False
    assert bc.fits_a_stock_sheet(2120, 2120, "MDF") is False


def test_a_real_part_still_fits():
    """12552's large tray body — 1793 x 701 on a 2500 x 1250 sheet. It must not be refused."""
    assert bc.fits_a_stock_sheet(1793.27, 701.53, "MILD STEEL") is True
    assert bc.fits_a_stock_sheet(650.7, 178.7, "MILD STEEL") is True


def test_a_nester_rotates_and_so_does_this():
    """A 1400 x 2000 acrylic panel fits a 3050 x 2050 sheet turned round."""
    assert bc.fits_a_stock_sheet(1400, 2000, "HIGH IMPACT ACRYLIC") is True
    assert bc.fits_a_stock_sheet(2000, 1400, "HIGH IMPACT ACRYLIC") is True


def test_a_part_exactly_the_size_of_its_sheet_is_allowed():
    """One out of a sheet is a real answer, and an expensive one — not an error."""
    assert bc.fits_a_stock_sheet(2500, 1250, "MILD STEEL") is True


def test_a_material_with_no_sizes_of_its_own_is_tested_against_the_default():
    """Because DEFAULT is the sheet the NESTER falls back to. The answer has to be about the
    sheet this part will actually be costed on, not an ideal one."""
    assert bc.fits_a_stock_sheet(2400, 1200, "UNOBTAINIUM") is True
    assert bc.fits_a_stock_sheet(2600, 1300, "UNOBTAINIUM") is False


def test_no_dimensions_is_not_an_answer():
    assert bc.fits_a_stock_sheet(None, 1250, "MILD STEEL") is None
    assert bc.fits_a_stock_sheet(0, 0, "MILD STEEL") is None


def test_a_refusal_can_name_the_sheet_it_did_not_fit():
    assert bc.largest_stock_sheet("HIGH IMPACT ACRYLIC") == (3050.0, 2050.0)
    assert bc.largest_stock_sheet("MILD STEEL") == (3000.0, 1500.0)


def test_the_estimator_refuses_such_a_blank_before_trusting_it():
    """Structurally: the fit test has to run BEFORE the fallback that keeps an unstamped
    blank, or the 10 mm-to-4 m bound accepts it first and nothing else is consulted."""
    import ast
    src = (SRC / "estimator.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fits = plausible = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "fits_a_stock_sheet" and fits is None:
                fits = node.lineno
            if node.func.attr == "plausible_as_a_sheet_part" and plausible is None:
                plausible = node.lineno
    assert fits is not None, "the estimator has to ask whether the blank fits a sheet"
    assert plausible is not None
    assert fits < plausible, (
        "asked first — the looser bound would otherwise accept a 2120 square and return")


@pytest.mark.parametrize("material", ["HIGH IMPACT ACRYLIC", "MDF", "MILD STEEL"])
def test_the_reason_says_what_it_is_rather_than_only_that_it_is_wrong(material):
    """An estimator reading "not a blank" learns nothing. "It is a bounding box or a drawing
    sheet size" tells them where to look."""
    src = (SRC / "estimator.py").read_text(encoding="utf-8")
    assert "this is a bounding box or a drawing sheet size, not the " in src
    assert "does not fit " in src and "is stocked in" in src
