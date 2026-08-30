"""
The cut path has to fit inside the blank it was cut from.

On job 12392 the engine held both numbers and compared them to nothing. The back panel was
recorded as a 16 x 3.7 blank and a 6,678mm cut path — six and a half metres of cutting inside
a rectangle the size of a staple. It priced at GBP 0.01, the workbook claimed 5,865 parts out
of one 2500 x 1250 sheet, and the material total for a steel panel job came to GBP 1.54.

Nothing said a word, because each number is plausible alone and only the pair is absurd. That
is the shape of every defect in this repository: two figures in front of the engine and no
comparison between them.

WHY AREA AND NOT PERIMETER. Comparing cut length to the bounding perimeter is wrong in both
directions — a disc's outline is shorter than its bounding box, and a legitimately busy panel
has far more internal cutting than perimeter. What cannot happen is a cut path that will not
FIT: a length of line needs width to live in, so area divided by cut length is the average
spacing between cuts, and below about a millimetre that is not a part.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import invariants


def _check(part_number="P1", length=None, width=None, cut=None, **extra):
    part = {"part_number": part_number, "blank_length_mm": length,
            "blank_width_mm": width, "cut_length_mm": cut}
    part.update(extra)
    return invariants.check_a_blank_and_its_cut_path_can_both_be_true({"parts": [part]})


def test_the_real_12392_blanks_are_caught():
    """The two numbers exactly as the run recorded them: the Sheet Steel block's part size
    and the cut length the laser calculator was driven from."""
    found = _check("12392-02-01M", 16, 3.7, 6678.66)
    assert len(found) == 1
    assert found[0]["severity"] == invariants.BLOCKING
    assert found[0]["code"] == "blank_and_cut_path_disagree"

    detail = found[0]["detail"]["parts"][0]
    assert detail["blank_area_mm2"] == 59.2
    # 113x more cutting than the blank could hold, at 0.009mm between cuts. A laser kerf is
    # 0.2mm, so this is not a dense part — it is two readings of different things.
    assert detail["times_too_long"] > 100
    assert detail["implied_cut_spacing_mm"] < 0.01


def test_the_bracket_too():
    found = _check("12392-04-01M", 4.3, 2, 6936.41)
    assert len(found) == 1
    assert found[0]["detail"]["parts"][0]["times_too_long"] > 500


def test_it_does_not_fire_on_parts_that_are_merely_busy():
    """A false positive here blocks a firm quote, so the margin has to be generous enough
    that unusual geometry survives. Each of these is a real shape."""
    assert _check("busy panel", 500, 300, 5_000) == []
    assert _check("perforated sheet", 1000, 500, 100_000) == []
    assert _check("small bracket", 50, 30, 200) == []
    # 100 metres of cutting inside a 300 x 200 panel — denser than anything SDI cuts.
    assert _check("dense grid", 300, 200, 100_000) == []


def test_it_does_not_fire_on_degenerate_but_real_geometry():
    """A long narrow strip is nearly all perimeter: 2500 x 2 has 5,004mm of outline in
    5,000mm2 of room, so a bare "over one" would fire on geometry that is unusual rather
    than impossible. That is what the margin is for."""
    assert _check("long strip", 2500, 2, 5_100) == []
    assert _check("thin strip", 2000, 3, 4_100) == []
    # A disc's outline is SHORTER than its bounding box — the reason this is not a
    # perimeter test at all.
    assert _check("disc", 100, 100, 314) == []


def test_absence_is_not_a_contradiction():
    """Nothing to compare is not a failure. A part with no blank, or no cut length, is
    another check's business — claiming here would report a defect for a missing datum."""
    assert _check("no cut", 500, 300, None) == []
    assert _check("no blank", None, None, 5_000) == []
    assert _check("nothing", None, None, None) == []
    assert invariants.check_a_blank_and_its_cut_path_can_both_be_true({"parts": []}) == []


def test_the_cut_length_is_read_from_wherever_it_was_written():
    """Four writers, four names. A check that knows one of them reports a clean pass on a
    job it never examined — the defect this module exists to catch, committed by the module
    itself."""
    for field in ("cut_length_mm", "dxf_measured_cut_length",
                  "estimated_cut_length_mm", "total_cut_length_mm"):
        part = {"part_number": "P1", "blank_length_mm": 16, "blank_width_mm": 3.7,
                field: 6678.66}
        assert invariants.check_a_blank_and_its_cut_path_can_both_be_true(
            {"parts": [part]}), f"{field} was not read"


def test_it_says_the_two_disagree_rather_than_which_one_is_wrong():
    """The blank may be in the wrong unit, or the cut length may have come from a different
    part. Both are real causes, the repair differs, and the engine cannot tell from here."""
    message = _check("12392-02-01M", 16, 3.7, 6678.66)[0]["message"]
    assert "one of the two is wrong" in message
    assert "16 x 3.7" in message and "6,679" in message


def test_the_check_reports_that_it_verified_nothing_when_it_cannot_run():
    found = invariants.check_a_blank_and_its_cut_path_can_both_be_true("not a job")
    assert len(found) == 1
    assert found[0]["severity"] == invariants.UNVERIFIED


def test_the_check_is_registered():
    assert invariants.check_a_blank_and_its_cut_path_can_both_be_true in invariants.CHECKS
