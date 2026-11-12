r"""
test_a_measurement_is_not_a_misread_date.py

A GUARD AGAINST MISREAD TEXT, APPLIED TO A MEASUREMENT, THROWS AWAY THE MEASUREMENT.

_plausible_blank_dimension_mm carried two rules, and both of them are about text:

    if 1900.0 <= value <= 2100.0: return False      # "07/04/2021" parses as 2021.0mm
    max_mm = 2500.0                                  # an OCR pick has to be bounded

Neither risk exists for a DXF flat pattern. That number is the extent of a closed profile
in a CAD file, not a string somebody's reader had a go at. Applied to it, the rules cost
real parts:

  * a 2000mm panel -- one of the commonest shopfitting heights there is -- was discarded
    as a calendar year
  * anything over 2500mm was discarded outright, on a machine whose standard sheet is 3050
    long, so a part that plainly can be cut was refused as impossible

And the part then carried no blank, priced no material, and said nothing about any of it.
A part with no blank costs nothing, which reads on the sheet as a part that is free to
make -- the same silent zero that cost the 11650 door GBP 18.69, arriving by another door.

Found looking at 11650-05, the PETG side panels, before running them. A side panel is
exactly the shape of part that is tall enough to hit both rules.

THE SPLIT IS BY EVIDENCE, NOT BY SIZE. Text keeps both rules, because a misread there is
likely and a wrong blank is worse than no blank. A measurement keeps only the physical
bound -- how big a sheet part can be at all -- and that bound comes from
blank_credibility.MAX_SHEET_PART_MM rather than a second number in a second module meaning
the same thing.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import blank_credibility as bc  # noqa: E402
import estimator as e  # noqa: E402


def _dxf(length, width=900.0):
    return {"part_number": "11650-05-01M", "description": "SIDE PANEL",
            "normalized_geometry": {"blank_length_mm": length, "blank_width_mm": width}}


# ── what the two rules were costing ─────────────────────────────────────────────────
@pytest.mark.parametrize("height", [1900.0, 1950.0, 2000.0, 2050.0, 2100.0])
def test_a_shopfitting_height_is_not_a_calendar_year(height):
    """2000mm is a panel height, not a date. The rule that refuses it exists because
    "07/04/2021" parses as 2021.0 -- which happens to TEXT, and a flat pattern is not text."""
    dims = e.infer_primary_dimensions(_dxf(height))
    assert dims["source"] == "dxf_flat_pattern", (
        f"a measured {height:g}mm blank was thrown away as a misread date")
    assert dims["overall_length_mm"] == height


@pytest.mark.parametrize("length", [2600.0, 2800.0, 3000.0, 3040.0])
def test_a_part_that_fits_the_sheet_is_not_refused_as_impossible(length):
    """The standard sheet is 3050 long. Refusing a 3000mm blank as implausible says the
    machine cannot cut something it plainly can."""
    assert e.infer_primary_dimensions(_dxf(length))["source"] == "dxf_flat_pattern"


def test_the_bound_still_exists():
    """Not "measured means anything goes". A flat pattern reading four metres is either not
    a flat pattern or not something this engine will nest, and either way it must not be
    priced as a blank."""
    assert e.infer_primary_dimensions(_dxf(bc.MAX_SHEET_PART_MM + 1))["source"] \
        == "no_dims_available"


def test_the_measured_bound_is_the_one_blank_credibility_already_decides():
    """TWO CONSTANTS FOR ONE QUESTION is how 2500 and 4000 came to disagree in the first
    place. If blank_credibility changes its mind about how big a sheet part can be, this
    moves with it rather than being found later by somebody costing a panel."""
    assert e._plausible_blank_dimension_mm(bc.MAX_SHEET_PART_MM, measured=True) is True
    assert e._plausible_blank_dimension_mm(bc.MAX_SHEET_PART_MM + 1, measured=True) is False


# ── and text keeps its guards ───────────────────────────────────────────────────────
def test_text_still_refuses_a_date():
    """The risk this rule exists for is real and unchanged: an OCR pick of 2021 from a
    drawing's date box must not become a blank."""
    assert e._plausible_blank_dimension_mm(2021.0) is False
    assert e._plausible_blank_dimension_mm(2021.0, measured=True) is True


def test_text_keeps_its_tighter_bound():
    assert e._plausible_blank_dimension_mm(2600.0) is False
    assert e._plausible_blank_dimension_mm(2600.0, measured=True) is True


def test_an_ocr_dimension_list_does_not_get_the_measured_rules():
    """The default matters: thirteen of the fifteen call sites are text, and they get the
    strict rule by NOT asking for the loose one. A default that went the other way would
    quietly relax every one of them."""
    part = {"part_number": "X", "all_dimensions_mm": [2021.0, 2600.0, 400.0]}
    dims = e.infer_primary_dimensions(part)
    assert dims["overall_length_mm"] != 2021.0
    assert dims["overall_length_mm"] != 2600.0


# ── a refused measurement is not a silent one ───────────────────────────────────────
def test_a_refused_flat_pattern_says_so_on_the_part():
    """A part with no blank prices no material, and that reads on the sheet as a part that
    is free to make. Whoever has to fix it needs to know a measurement was refused and
    which one."""
    part = _dxf(bc.MAX_SHEET_PART_MM + 200)
    e.infer_primary_dimensions(part)
    flags = [f for f in (part.get("review_flags") or [])
             if isinstance(f, dict) and f.get("flag") == "measured_blank_refused"]
    assert flags, "the flat pattern was discarded without a word"
    detail = flags[0]["detail"]
    assert "4200" in detail, "the refused reading is not named, so nobody can check it"
    assert "no measured blank" in detail


def test_it_is_said_once_however_often_the_part_is_costed():
    """infer_primary_dimensions is asked repeatedly during a run. A flag per call turns one
    fact into a wall, and a wall is not read."""
    part = _dxf(bc.MAX_SHEET_PART_MM + 200)
    for _ in range(5):
        e.infer_primary_dimensions(part)
    assert len(part.get("review_flags") or []) == 1


def test_an_accepted_flat_pattern_is_not_flagged():
    """A message that appears when nothing is wrong stops being read, and this one has to be
    trusted on the day it is right."""
    part = _dxf(2000.0)
    e.infer_primary_dimensions(part)
    assert not part.get("review_flags")


def test_a_part_with_no_flat_pattern_at_all_is_not_flagged():
    """Absence is a different check's business. Reporting "a measurement was refused" where
    there was no measurement is an invented finding."""
    part = {"part_number": "X", "all_dimensions_mm": [400.0, 300.0]}
    e.infer_primary_dimensions(part)
    assert not part.get("review_flags")
