"""A blank that cannot hold its own cut path is a wrong number, not a small part.

12392's back panel: a 16 x 3.7 mm blank with a 6,679 mm cut path. Six and a half metres
of cutting inside a rectangle the size of a staple. It priced at GBP 0.01 and the sheet
claimed 5,865 of them out of one 2500 x 1250.

Each number is plausible alone. Only the pair is impossible — which is why nothing caught
it until something compared them.
"""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import blank_credibility as bc  # noqa: E402


def test_the_12392_back_panel_is_impossible():
    v = bc.assess(16, 3.7, 6678.66)
    assert v["credible"] is False and v["evaluated"] is True
    assert v["ratio"] > 100
    assert "cannot hold" in v["reason"]


def test_the_panel_stiffener_that_was_right_is_not_flagged():
    """1405 x 143.04 with a 4,227 mm cut path — a real part, read from the model."""
    assert bc.is_credible(1405, 143.04, 4226.7) is True


def test_a_long_narrow_strip_is_unusual_not_impossible():
    """2500 x 2 is nearly all perimeter — 5,004 mm of outline in 5,000 mm2. The margin
    exists so the test fires on the impossible, not the merely dense."""
    assert bc.is_credible(2500, 2, 5004) is True


def test_a_missing_cut_path_is_not_a_pass():
    """A part nobody asked has not been shown consistent. Reporting that as credible
    would let 'we did not check' read as 'we checked'."""
    v = bc.assess(16, 3.7, None)
    assert v["evaluated"] is False


def test_a_missing_blank_is_not_a_pass():
    assert bc.assess(None, None, 6678.66)["evaluated"] is False


def test_a_bounding_box_is_offered_as_a_floor_when_the_blank_is_impossible():
    """A modelled bbox understates a developed length and is a poor blank. It is a
    defensible floor, and a defensible floor beats a number wrong by two orders."""
    got = bc.better_blank_from(
        (("recorded blank", 16, 3.7), ("solidworks bounding box", 1435, 130)), 6678.66)
    assert got is not None
    assert got["source"] == "solidworks bounding box"
    assert got["blank_length_mm"] == 1435


def test_the_recorded_blank_wins_when_it_is_credible():
    got = bc.better_blank_from(
        (("recorded blank", 1405, 143.04), ("solidworks bounding box", 1435, 130)), 4226.7)
    assert got["source"] == "recorded blank"


def test_nothing_offered_surviving_returns_nothing():
    """Then the part has no blank we can stand behind, and saying so is the only honest
    answer left. Inventing one here is how the original defect happened."""
    assert bc.better_blank_from((("recorded blank", 16, 3.7),), 6678.66) is None


def test_the_invariant_and_the_module_agree():
    """A checker that blocks a job the pricer already costed is not a check."""
    import invariants

    # invariants._parts reads the top-level `parts` list — the RAW geometry records,
    # deliberately, because that is where blank_length_mm and cut_length_mm live.
    out = invariants.check_a_blank_and_its_cut_path_can_both_be_true({
        "parts": [
            {"part_number": "12392-02-01M", "blank_length_mm": 16, "blank_width_mm": 3.7,
             "cut_length_mm": 6678.66},
            {"part_number": "12392-02-02M", "blank_length_mm": 1405,
             "blank_width_mm": 143.04, "cut_length_mm": 4226.7},
        ],
    })
    assert len(out) == 1
    assert out[0]["detail"]["parts"][0]["part_number"] == "12392-02-01M"
    assert not [p for p in out[0]["detail"]["parts"] if p["part_number"] == "12392-02-02M"]
