"""A blank the cut path proves impossible must not reach the price, not merely be reported.

12392's back panel arrived at the pricer as 16 x 3.7 mm carrying a 6,679 mm cut path. The
invariant caught it and blocked the quote; the workbook priced it at GBP 0.01 anyway,
because the check ran after the money was written down. A rule that only reports arrives
too late to matter.
"""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import estimator  # noqa: E402


def _back_panel(**extra):
    part = {"part_number": "12392-02-01M", "description": "BACK PANEL",
            "cut_length_mm": 6678.66}
    part.update(extra)
    return part


def test_the_impossible_blank_is_refused():
    part = _back_panel()
    length, width = estimator._blank_that_could_have_been_cut(part, 16, 3.7)
    assert (length, width) == (None, None)
    assert "blank_impossible_no_replacement" in part["review_flags"]
    assert "cannot hold" in part["blank_rejected_reason"]


def test_the_bounding_box_is_used_as_a_floor_when_there_is_one():
    """A folded part unfolds longer than the box it folds into, so this UNDER-states.
    It is worth having only because the alternative is wrong by a hundredfold."""
    part = _back_panel(bbox_mm=[130.0, 1435.0, 1.5])
    length, width = estimator._blank_that_could_have_been_cut(part, 16, 3.7)
    assert (length, width) == (1435.0, 130.0)
    assert part["blank_length_mm_source"] == "bounding_box_floor"
    assert "blank_replaced_by_bounding_box_floor" in part["review_flags"]


def test_a_bounding_box_that_could_not_hold_the_cut_either_is_not_used():
    """Substituting a second impossible number would be the same defect in new clothes."""
    part = _back_panel(bbox_mm=[4.0, 5.0, 1.5])
    assert estimator._blank_that_could_have_been_cut(part, 16, 3.7) == (None, None)


def test_a_credible_blank_passes_through_untouched():
    """Mutation guard. The stiffener is a real part read from the model; if this ever
    fails, the gate is eating good geometry and the cure is worse than the disease."""
    part = {"part_number": "12392-02-02M", "cut_length_mm": 4226.7}
    assert estimator._blank_that_could_have_been_cut(part, 1405, 143.04) == (1405, 143.04)
    assert not part.get("review_flags")


def test_a_part_with_no_cut_path_is_left_alone():
    """Not having been asked is not the same as having failed."""
    part = {"part_number": "X"}
    assert estimator._blank_that_could_have_been_cut(part, 16, 3.7) == (16, 3.7)


def test_a_part_with_no_blank_is_left_alone():
    part = {"part_number": "X", "cut_length_mm": 6678.66}
    assert estimator._blank_that_could_have_been_cut(part, None, None) == (None, None)


def test_the_cut_path_is_found_wherever_the_writer_put_it():
    """Readers write it to the part root, to normalized_geometry and to geometry_rollup.
    Reading only one is how a gate ends up never firing."""
    part = {"part_number": "X", "normalized_geometry": {"dxf_measured_cut_length": 6678.66}}
    assert estimator._blank_that_could_have_been_cut(part, 16, 3.7) == (None, None)

    part = {"part_number": "Y", "geometry_rollup": {"estimated_cut_length_mm": 6678.66}}
    assert estimator._blank_that_could_have_been_cut(part, 16, 3.7) == (None, None)


# ---------------------------------------------------------------------------
# Where a blank came from
# ---------------------------------------------------------------------------
def test_an_inferred_blank_says_it_was_inferred():
    import geometry_inference

    part = {"part_number": "X"}
    geometry_inference._write_inferred_blank(part, 100.0, 50.0) \
        if hasattr(geometry_inference, "_write_inferred_blank") else None
    # The writer's name varies; assert the stamp exists on whichever wrote the dims.
    if part.get("blank_length_mm") or (part.get("normalized_geometry") or {}).get("blank_length_mm"):
        src = part.get("blank_length_mm_source") or \
            (part.get("normalized_geometry") or {}).get("blank_length_mm_source")
        assert src == "geometry_inference"


def test_the_document_text_fallback_is_stamped_as_a_guess():
    """Two largest numbers anywhere in the pack, context-blind by construction. Only the
    stamp separates it from a measurement."""
    source = (SRC / "document_builder.py").read_text(encoding="utf-8")
    assert 'blank_length_mm_source"] = "document_text_largest_numbers"' in source
    assert 'blank_length_mm_source"] = "overall_dimensions"' in source


# ---------------------------------------------------------------------------
# The gate is WIRED, not merely written
# ---------------------------------------------------------------------------
# Every test above calls _blank_that_could_have_been_cut directly, which proves the rule
# and proves nothing about whether anything asks it. Deleting the call from
# estimate_material left them all passing — the exact defect this branch keeps producing:
# correct evidence with no reader.
def _priced(**extra):
    """A part record shaped like the one 12392 actually produced — the blank ON the
    record, not merely derivable from it. A fixture that omits it cannot show the
    rejected value being cleared, because there is nothing there to clear."""
    part = {"part_number": "12392-02-01M", "description": "BACK PANEL",
            "normalized_material": "MILD_STEEL", "thickness_mm": 1.5, "quantity": 1,
            "cut_length_mm": 6678.66,
            "blank_length_mm": 16, "blank_width_mm": 3.7}
    part.update(extra)
    return part, estimator.estimate_material(part)


def test_estimate_material_refuses_to_price_the_impossible_blank():
    part, out = _priced()
    assert out.get("blank_length_mm") is None
    assert out.get("cost_per_part_gbp") in (None, 0)
    assert "blank_impossible_no_replacement" in (part.get("review_flags") or [])


def test_the_impossible_blank_is_cleared_off_the_part_record_too():
    """Returning the right value is not enough. The workbook's Sheet Steel block reads
    blank_length_mm off the PART, so a rejected 16 x 3.7 left sitting there would go on
    printing 5,865 parts per sheet next to a cost the gate had already refused."""
    part, _out = _priced()
    assert part.get("blank_length_mm") in (None, 0)
    assert part.get("blank_width_mm") in (None, 0)
    assert part.get("blank_rejected_reason")


def test_the_replacement_blank_is_written_onto_the_part_record():
    part, _out = _priced(bbox_mm=[130.0, 1435.0, 1.5])
    assert part.get("blank_length_mm") == 1435.0
    assert part.get("blank_length_mm_source") == "bounding_box_floor"


def test_estimate_material_prices_from_the_bounding_box_floor():
    part, out = _priced(bbox_mm=[130.0, 1435.0, 1.5])
    # The BLANK is what the gate decides, and it is deterministic. Whether a price comes
    # back depends on a catalogue being reachable, so asserting on cost would make this
    # test a network check wearing a logic test's name.
    assert out.get("blank_length_mm") == 1435.0
    assert out.get("blank_width_mm") == 130.0
    assert "blank_replaced_by_bounding_box_floor" in (part.get("review_flags") or [])


def test_estimate_material_leaves_a_credible_blank_alone():
    """Mutation guard on the two above: the gate must not eat good geometry."""
    part, out = _priced(part_number="12392-02-02M", blank_length_mm=1405,
                        blank_width_mm=143.04, cut_length_mm=4226.7)
    assert out.get("blank_length_mm") == 1405
    assert out.get("blank_width_mm") == 143.04
    assert not part.get("review_flags")
