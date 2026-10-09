"""A wire part with no sheet of its own takes its stated gauge and outline off the sheet that
draws it, before any default (D-437).

8188-08-004 WIRE WORK MESH FRAME is drawn on the grill assembly's sheet: a callout "6 WIRE WORK
FRAME" and the frame's outline "1081 EXT." by "206 EXT.". The 14:50 and 17:37 books priced it
as an ASSUMED Ø8 × 900 mm — the config default gauge and the "formed" developed-length band —
and the report said the outline was not used.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import wire_sheet_reader as wsr                                       # noqa: E402
from source_precedence import source_of                               # noqa: E402

_GRILL_SHEET = """ 500
45°
MESH
 45.50
 115
 290.50
 1081 EXT.
 206 EXT.
 6 WIRE WORK FRAME
 30
25MM X 25MM WIRE MESH TAC'D TO REAR OF
WIREWORK FRAME ALL ROUND
ITEM NO. PartNo Description QTY.
1 8188-08-004 WIRE WORK MESH FRAME 1
2 8188-08-009 25X25MM WIRE MESH PANEL 1
"""


def test_the_gauge_is_the_callout_beside_the_parts_own_words():
    got = wsr.wire_callouts_on_sheet("WIRE WORK MESH FRAME", _GRILL_SHEET)
    assert got["gauge_mm"] == 6.0, got
    assert "6 WIRE WORK FRAME" in got["gauge_text"]


def test_a_mesh_pitch_is_not_a_wire_gauge():
    """25MM X 25MM WIRE MESH: a pitch, refused twice over — it follows an X, and it is past the
    largest gauge a callout can state."""
    got = wsr.wire_callouts_on_sheet("WIRE MESH PANEL", "25MM X 25MM WIRE MESH PANEL")
    assert got["gauge_mm"] is None


def test_the_outline_is_the_pair_of_ext_figures():
    got = wsr.wire_callouts_on_sheet("WIRE WORK MESH FRAME", _GRILL_SHEET)
    assert got["outline_mm"] == (1081.0, 206.0), got


def test_three_ext_figures_name_no_outline():
    got = wsr.wire_callouts_on_sheet("WIRE FRAME", "1081 EXT. 206 EXT. 400 EXT. 6 WIRE FRAME")
    assert got["outline_mm"] is None and got["gauge_mm"] == 6.0


def test_two_different_gauges_name_none():
    got = wsr.wire_callouts_on_sheet("WIRE FRAME", "6 WIRE FRAME ... 8 WIRE FRAME")
    assert got["gauge_mm"] is None


def _frame():
    return {"part_number": "8188-08-004", "description": "WIRE WORK MESH FRAME", "quantity": 1,
            "pages": [3], "page_roles": ["assembly"], "_bar_recognised": True}


def _pages():
    return [{"page_number": "3", "pypdf_text": _GRILL_SHEET, "pdfplumber_text": "EMARF KROW ERIW 6"}]


def test_a_frames_developed_length_is_its_outlines_perimeter_said_as_derived():
    part = _frame()
    n = wsr.apply_wire_callouts_to_parts([part], _pages())
    assert n == 1
    assert part["wire_gauge_mm"] == 6.0
    assert source_of(part, "wire_gauge_mm") == "drawing_deterministic"
    assert "wire_length_mm" not in part, "a derived length is never the schedule length"
    assert part["wire_length_derived_mm"] == 2 * (1081.0 + 206.0)
    assert part["wire_outline_mm"] == [1081.0, 206.0]
    assert "perimeter" in part["wire_length_derived_from"]


def test_a_stated_schedule_length_is_never_overwritten():
    part = dict(_frame(), wire_gauge_mm=6.0, wire_length_mm=2600.0)
    assert wsr.apply_wire_callouts_to_parts([part], _pages()) == 0
    assert part["wire_length_mm"] == 2600.0


def test_a_bought_mesh_panel_and_a_sheet_part_are_left_alone():
    mesh = {"part_number": "8188-08-009", "description": "25X25MM WIRE MESH PANEL",
            "pages": [3], "is_bought_in": True, "page_roles": ["bought_in"]}
    plate = {"part_number": "8188-08-007", "description": "TRAPPER BRACKET", "pages": [3]}
    assert wsr.apply_wire_callouts_to_parts([mesh, plate], _pages()) == 0
    assert "wire_gauge_mm" not in mesh and "wire_gauge_mm" not in plate


def test_the_costing_uses_the_read_gauge_and_the_derived_length_and_says_so():
    import estimator
    part = dict(_frame(), normalized_material="MILD STEEL",
                manufacturing_interpretation={"stock_form": "wire"})
    wsr.apply_wire_callouts_to_parts([part], _pages())
    me = estimator.estimate_material(part)
    assert me["stock_form"] == "wire"
    assert me["wire_gauge_mm"] == 6.0 and me["wire_length_mm"] == 2574.0
    assert me["cost_method"] == "wire_tonne_rate_outline_length"
    assert me["estimator_input_required"] is True
    assert me["stock_estimate"]["length_assumed"] is False
    assert "perimeter" in me["stock_estimate"]["length_derived_from"]
    flags = " ".join(str(f) for f in part.get("review_flags") or [])
    assert "DERIVED" in flags and "ASSUMED" not in flags
    # Ø6 x 2,574 mm of steel wire: about 0.57 kg, not Ø8 x 900's 0.36 kg
    assert abs(me["unit_material_mass_kg"] - 0.571) < 0.01, me["unit_material_mass_kg"]


def test_with_no_sheet_text_the_old_assumption_still_stands_and_says_so():
    import estimator
    part = dict(_frame(), normalized_material="MILD STEEL",
                manufacturing_interpretation={"stock_form": "wire"})
    wsr.apply_wire_callouts_to_parts([part], [])
    me = estimator.estimate_material(part)
    assert me["cost_method"] == "wire_tonne_rate_assumed_length"
    assert me["stock_estimate"]["length_assumed"] is True
