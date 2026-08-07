"""A blank must be refused before it prices, not merely reported after.

12392's back panel reached the pricer as 16 x 3.7 mm and came out at GBP 0.01 — almost
certainly the largest part in the job. The invariant named it and blocked the quote; the
workbook priced it anyway, because the rule ran after the money was written down.

These tests cover the REFUSAL and the fallbacks. The sizing policy itself — measured, then
the drawing's overalls, then nothing — is covered in test_blank_from_drawing.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import estimator  # noqa: E402


def _measured(**extra):
    """A part whose blank something actually measured — the case that must pass through."""
    part = {"part_number": "12392-02-02M", "normalized_material": "MILD_STEEL",
            "normalized_thickness_mm": 1.5, "quantity": 1,
            "blank_length_mm": 1405, "blank_width_mm": 143.04,
            "cut_length_mm": 4226.7,
            "geometry_source": "solidworks_api",
            "blank_length_mm_source": "solidworks_api"}
    part.update(extra)
    return part


def _unmeasured(**extra):
    """The 12392 back-panel shape: a blank with no provenance and no printed overalls."""
    part = {"part_number": "12392-02-01M", "description": "BACK PANEL",
            "normalized_material": "MILD_STEEL", "normalized_thickness_mm": 1.5,
            "quantity": 1, "blank_length_mm": 16, "blank_width_mm": 3.7}
    part.update(extra)
    return part


# ---------------------------------------------------------------------------
# Refusal
# ---------------------------------------------------------------------------
def test_a_blank_that_is_not_the_size_of_a_part_is_refused():
    """Provenance alone was too blunt: refusing every unstamped blank stopped a credible
    120 x 80 bracket costing at all. What separates the two is whether the numbers could
    be the overall size of something we cut. 3.7 mm could not."""
    part = _unmeasured()
    assert estimator._blank_that_could_have_been_cut(part, 16, 3.7) == (None, None)
    assert "blank_impossible_no_replacement" in part["review_flags"]
    assert "not the size of a sheet fabrication" in part["blank_rejected_reason"]


def test_a_credible_unstamped_blank_is_kept_and_flagged():
    """The regression the provenance rule caused. 120 x 80 with a 400 mm cut path is a
    real bracket; nothing contradicts it, and refusing it prices nothing at all."""
    part = {"part_number": "GUARD-01", "normalized_material": "MILD STEEL",
            "normalized_thickness_mm": 1.5, "quantity": 1,
            "blank_length_mm": 120, "blank_width_mm": 80, "cut_length_mm": 400}
    assert estimator._blank_that_could_have_been_cut(part, 120, 80) == (120, 80)
    assert "blank_source_not_recorded" in part["review_flags"]


def test_a_measured_blank_contradicted_by_its_own_cut_path_is_refused():
    """Both measured, and still impossible: 16 x 3.7 cannot hold 6,679 mm of cutting."""
    part = _measured(part_number="X", blank_length_mm=16, blank_width_mm=3.7,
                     cut_length_mm=6678.66)
    assert estimator._blank_that_could_have_been_cut(part, 16, 3.7) == (None, None)
    assert "cannot hold" in part["blank_rejected_reason"]


def test_a_measured_blank_that_holds_its_cut_path_passes_through_untouched():
    """Mutation guard. If this fails the gate is eating good geometry, and the cure is
    worse than the disease."""
    part = _measured()
    assert estimator._blank_that_could_have_been_cut(part, 1405, 143.04) == (1405, 143.04)
    assert not part.get("review_flags")


def test_a_part_with_no_blank_at_all_is_left_alone():
    """Absence is another check's business, and reasoning about a value that is not there
    is how this function once formatted None as a number."""
    part = {"part_number": "X"}
    assert estimator._blank_that_could_have_been_cut(part, None, None) == (None, None)
    assert not part.get("review_flags")


# ---------------------------------------------------------------------------
# The measured bounding box, as a floor
# ---------------------------------------------------------------------------
def test_the_bounding_box_is_used_as_a_floor():
    """A folded part unfolds longer than the box it folds into, so this UNDER-states.
    Worth having only because the alternative was wrong by a hundredfold."""
    part = _unmeasured(bbox_mm=[130.0, 1435.0, 1.5])
    assert estimator._blank_that_could_have_been_cut(part, 16, 3.7) == (1435.0, 130.0)
    assert part["blank_length_mm_source"] == "bounding_box_floor"
    assert "blank_replaced_by_bounding_box_floor" in part["review_flags"]


def test_a_bounding_box_that_could_not_hold_the_measured_cut_is_not_used():
    """Substituting a second impossible number is the same defect in new clothes."""
    part = _measured(part_number="X", blank_length_mm=16, blank_width_mm=3.7,
                     cut_length_mm=6678.66, bbox_mm=[4.0, 5.0, 1.5])
    assert estimator._blank_that_could_have_been_cut(part, 16, 3.7) == (None, None)


# ---------------------------------------------------------------------------
# The refusal has to reach every copy
# ---------------------------------------------------------------------------
def test_the_rejected_blank_is_cleared_off_the_part_record():
    """The Sheet Steel block reads blank_length_mm off the PART. A rejected 16 x 3.7 left
    sitting there would go on printing 5,865 per sheet beside a cost already refused."""
    part = _unmeasured(overall_length_mm=16, overall_width_mm=3.7)
    estimator._blank_that_could_have_been_cut(part, 16, 3.7)
    assert part.get("blank_length_mm") in (None, 0)
    assert part.get("overall_length_mm") in (None, 0)


def test_the_rejected_blank_stops_blocking_the_job():
    """Clearing blank_length_mm alone moved which copy got believed: the invariant falls
    back to overall_length_mm, so the job went on blocking on a value already refused."""
    import invariants

    part = _unmeasured(overall_length_mm=16, overall_width_mm=3.7)
    estimator.estimate_material(part)
    assert invariants.check_a_blank_and_its_cut_path_can_both_be_true({"parts": [part]}) == []


# ---------------------------------------------------------------------------
# WIRED, not merely written
# ---------------------------------------------------------------------------
# Every test above calls the gate directly, which proves the rule and nothing about
# whether anything asks it. Deleting the call from estimate_material once left them all
# passing — the exact defect this branch keeps producing: correct evidence, no reader.
def test_estimate_material_refuses_the_unmeasured_blank():
    part = _unmeasured()
    out = estimator.estimate_material(part)
    assert out.get("blank_length_mm") is None
    assert out.get("cost_per_part_gbp") in (None, 0)


def test_estimate_material_uses_the_bounding_box_floor():
    part = _unmeasured(bbox_mm=[130.0, 1435.0, 1.5])
    out = estimator.estimate_material(part)
    assert out.get("blank_length_mm") == 1435.0
    assert out.get("blank_width_mm") == 130.0


def test_estimate_material_leaves_a_measured_blank_alone():
    part = _measured()
    out = estimator.estimate_material(part)
    assert out.get("blank_length_mm") == 1405.0
    assert not part.get("review_flags")


# ---------------------------------------------------------------------------
# The model keeps its box
# ---------------------------------------------------------------------------
def test_the_model_keeps_its_bounding_box_for_every_part():
    """It was read for every part and kept for one thing — a tube's cut length. A part
    whose blank turns out unusable then had nothing measured to fall back on."""
    source = (SRC / "source_connectors" / "solidworks.py").read_text(encoding="utf-8")
    assert 'part["bbox_mm"] = list(_bbox_all)' in source
    assert 'part["bbox_mm_source"]' in source
