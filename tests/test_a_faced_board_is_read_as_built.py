"""A laminated board is read as it is built, not asked about as if two readers disagreed (D-722).

11908-22-GA, 5 Nov 2026: the panels are drawn "9mm MDF + LAM BOTH SIDES". Three questions went
to the estimator that the drawing already answers:
  * "Gauge of 01J: 9 mm kept against 11 mm from solidworks_api": 9 is the core, 11 the board
    with a face each side;
  * "Folding of 02J: its drawing prints 11 degrees but states no fold": an MDF side is mitred,
    never press-folded;
  * "DXF: no face direction, grain arrow ...": each panel's own sheet prints GRAIN DIRECTION.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import costed_facts
import estimator
from construction_note import finished_over_core, is_faced_board
from dxf_llm_interpret import settle_grain_flags


def _panel(**extra):
    p = {"part_number": "T-01J", "normalized_material": "MDF", "normalized_finish": "LAMINATED",
         "normalized_thickness_mm": 9.0, "normalized_thickness_mm_source": "dxf",
         "blank_length_mm": 340.0, "blank_width_mm": 290.0, "quantity": 1,
         "_displaced": {"normalized_thickness_mm": [
             {"value": 11.0, "source": "solidworks_api", "applied": False}]}}
    p.update(extra)
    return p


def test_core_plus_two_faces_is_the_finished_board_not_a_rival():
    assert is_faced_board(_panel())
    assert finished_over_core(_panel(), 9.0, 11.0) == 11.0
    assert costed_facts.thickness_conflict(_panel()) is None


def test_an_unfaced_board_still_asks():
    plain = _panel(normalized_finish="RAW")
    assert not is_faced_board(plain)
    q = costed_facts.thickness_conflict(plain)
    assert q and "Gauge of T-01J" in q["issue"]


def test_a_faced_board_far_off_its_core_still_asks():
    assert costed_facts.thickness_conflict(_panel(_displaced={"normalized_thickness_mm": [
        {"value": 18.0, "source": "solidworks_api", "applied": False}]}))


def test_an_angle_on_mdf_is_a_mitre_not_a_fold_question():
    part = _panel(part_number="T-02J", blank_length_mm=350.0, blank_width_mm=28.0,
                  angles_deg=[11, 45], textual_operations=["cnc_routing"])
    estimator.estimate_process_times(part, 1)
    assert not any("Folding of" in str(q.get("issue"))
                   for q in part.get("manufacturing_questions") or [])
    assert any("read as mitres or chamfers" in str(f) for f in part.get("review_flags") or [])


def test_a_grain_the_sheet_prints_settles_the_dxf_warning():
    part = _panel(pages=[2], review_flags=[
        "DXF: No face direction, grain arrow, or laminate orientation is indicated."])
    summary = {"pages": [{"page_number": 2, "pdfplumber_text": "290 340 GRAIN DIRECTION"}]}
    assert settle_grain_flags([part], summary) == 1
    assert part["grain_direction_stated"] == "its own sheet (page 2)"
    assert not any(str(f).startswith("DXF:") for f in part["review_flags"])


def test_no_grain_on_the_sheet_leaves_the_warning():
    part = _panel(pages=[2], review_flags=["DXF: No grain arrow is indicated."])
    assert settle_grain_flags([part], {"pages": [{"page_number": 2,
                                                  "pdfplumber_text": "290 340"}]}) == 0
    assert part["review_flags"] == ["DXF: No grain arrow is indicated."]
