"""A size the part's own stated weight confirms is not overruled by its assembly (D-652).

12684-02-GA, 3 Nov 2026 (SCRUM-180). 12684-02-M04 BASEPLATE is drawn 504 x 313 x 3 mm and
states 3.68 kg. The run read 504 x 313 off its own sheet, then costed it on 39.7 x 30 mm,
because its frame 12684-02-102SA carried that outline: the arm bracket's size, not the frame's.
Material charged: GBP 0.06 for a 3.7 kg plate, and its laser timed on the same wrong blank.

D-508's check stays for what it was written for: a reading with nothing behind it, such as the
acrylic back plate read at 1737 x 1684.7 inside a 400 x 251.5 fascia, is still costed on the
assembly and asked. What changes is only this: when the part's own printed weight agrees with
the size read, the read stands, and the parent's outline is the figure said to be in doubt.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import detail_page_geometry as dpg  # noqa: E402
import source_precedence as sp  # noqa: E402


def _frame_job(stated_kg=3.68, provisional=None):
    frame = {"part_number": "12684-02-102SA", "description": "FRAME",
             "_sheet_envelope_mm": {"length": 39.7, "width": 30.0}}
    plate = {"part_number": "12684-02-M04", "description": "BASEPLATE",
             "bom_parent": "12684-02-102SA", "normalized_material": "MILD_STEEL",
             "normalized_thickness_mm": 3.0}
    if stated_kg is not None:
        plate["stated_weight_kg"] = stated_kg
    sp.apply_field(plate, "blank_length_mm", 504.0, dpg.PROVISIONAL_SOURCE)
    sp.apply_field(plate, "blank_width_mm", 313.0, dpg.PROVISIONAL_SOURCE)
    if provisional is not None:
        plate["_blank_provisional"] = provisional
    summary = {"document_analysis": {"bom_rows": [
        {"part_number": "12684-02-M04", "bom_parent": "12684-02-102SA"}]}}
    return frame, plate, summary


def test_the_baseplate_its_own_weight_confirms_keeps_its_size():
    frame, plate, summary = _frame_job()
    assert dpg.check_parts_against_their_assembly([frame, plate], summary) == []
    assert (plate["blank_length_mm"], plate["blank_width_mm"]) == (504.0, 313.0)
    assert sp.source_of(plate, "blank_length_mm") == dpg.PROVISIONAL_SOURCE
    assert not plate.get("_blank_capped_to_assembly")
    assert not plate.get("manufacturing_questions"), "nothing to ask: the weight settles it"
    kept = plate["_blank_kept_over_assembly"]
    assert kept["assembly"] == "12684-02-102SA" and kept["read_mm"] == [504.0, 313.0]
    assert "1.01x the stated 3.68 kg" in kept["weight"]


def test_the_parents_outline_is_the_figure_said_to_be_in_doubt():
    frame, plate, summary = _frame_job()
    dpg.check_parts_against_their_assembly([frame, plate], summary)
    doubt = [f for f in frame.get("review_flags") or [] if "OUTLINE IN DOUBT" in f]
    assert len(doubt) == 1 and "39.7 x 30 mm" in doubt[0] and "12684-02-M04" in doubt[0]
    dpg.check_parts_against_their_assembly([frame, plate], summary)
    assert len([f for f in frame["review_flags"] if "OUTLINE IN DOUBT" in f]) == 1, \
        "said once, however often the check runs"


def test_a_provisional_blank_already_judged_on_this_size_is_taken_at_its_word():
    frame, plate, summary = _frame_job(
        stated_kg=None, provisional={"length": 504.0, "width": 313.0, "weight_agrees": True})
    assert dpg.check_parts_against_their_assembly([frame, plate], summary) == []
    assert plate["_blank_kept_over_assembly"]["weight"] == \
        "judged when the blank was read off its sheet"


def test_a_judgement_on_another_size_does_not_carry_over():
    frame, plate, summary = _frame_job(
        stated_kg=None, provisional={"length": 600.0, "width": 400.0, "weight_agrees": True})
    assert dpg.check_parts_against_their_assembly([frame, plate], summary) == ["12684-02-M04"]


def test_a_read_its_own_weight_disproves_is_still_costed_on_the_assembly():
    """0.3 kg cannot be a 504 x 313 x 3 mm steel plate: the read is not its size."""
    frame, plate, summary = _frame_job(stated_kg=0.3)
    assert dpg.check_parts_against_their_assembly([frame, plate], summary) == ["12684-02-M04"]
    assert plate["_blank_capped_to_assembly"]["read_mm"] == [504.0, 313.0]
    assert not frame.get("review_flags")


def test_a_read_far_heavier_than_its_part_is_still_costed_on_the_assembly():
    """Above the band the provisional blank is judged by, the weight confirms nothing."""
    frame, plate, summary = _frame_job(stated_kg=1.5)
    assert dpg.check_parts_against_their_assembly([frame, plate], summary) == ["12684-02-M04"]


def test_with_no_weight_at_all_the_check_is_unchanged():
    frame, plate, summary = _frame_job(stated_kg=None)
    assert dpg.check_parts_against_their_assembly([frame, plate], summary) == ["12684-02-M04"]
    assert (plate["blank_length_mm"], plate["blank_width_mm"]) == (39.7, 30.0)
