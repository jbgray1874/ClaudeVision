"""A refused gauge feeds nothing downstream, and a board's model sizes its blank.

12678-01-GA, FOUR BOARDS NESTED AT THE FIGURE THEIR OWN QUESTION REFUSED (SCRUM-180). The
engine rejected 2.5 mm as below the board floor and raised "no board gauge ... Thickness
left unset — confirm the board gauge" — and then the Other Sheet rows nested at Ga 2.5,
the £/kg gap-filler priced the sheet at 2.5, and the shipping weigh weighed the boards at
2.5 x 1200 kg/m3. The refused figure had stayed on normalized_thickness_mm, where every
downstream reader found it beside the flag that disowned it.

THE RULE: a refusal moves the figure to thickness_rejected_mm. Only the re-judgement in
_safe_thickness_and_stage reads it back — the floor depends on the material, which can
resolve between calls, so the figure is offered to whatever floor stands now; accepted,
it returns home. Until then the nest, the sheet price, the market lookup and the weigh
all see an honest nothing.

AND THE SAME SHELVES WORE A CATEGORY DEFAULT WHILE THEIR MODEL MEASURED THEM. BASE and
SHELF both carried geometry_inference's "tier" default, 350 x 250 at 24 a sheet,
identical for a 520-wide shelf and a 552 x 370 plinth. For a verified plate-shaped board
the model's two larger extents are its blank — the same rectangle rule as D-402, at the
same provisional rank as the D-512 gauge, under the same question. A box-shaped board
deliberately gets nothing: its envelope is not a blank, and pretending it is would bury
the construction question.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import commercial_lines as cl  # noqa: E402
import estimator  # noqa: E402
import geometry_inference  # noqa: E402


# ── the refusal moves the figure off the record ──────────────────────────────────────

def test_a_refused_gauge_moves_off_the_record():
    part = {"part_number": "12678-01-01J", "description": "BASE",
            "normalized_material": "TIMBER", "normalized_thickness_mm": 2.5}
    t, stage = estimator._safe_thickness_and_stage(part)
    assert t is None and stage == ""
    assert part["normalized_thickness_mm"] is None
    assert part["thickness_rejected_mm"] == 2.5
    assert any("rejected below the 6 mm floor" in f for f in part["review_flags"])


def test_the_refused_figure_is_rejudged_when_the_material_resolves():
    """TIMBER's 6 mm floor refuses 4 mm; the material resolving to MDF (a 3 mm floor)
    offers the figure back, and it returns home with the refusal record gone."""
    part = {"part_number": "P", "description": "PANEL",
            "normalized_material": "TIMBER", "normalized_thickness_mm": 4.0}
    assert estimator._safe_thickness_and_stage(part)[0] is None
    assert part["normalized_thickness_mm"] is None
    part["normalized_material"] = "MDF"
    t, stage = estimator._safe_thickness_and_stage(part)
    assert t == 4.0 and stage == "normalized"
    assert part["normalized_thickness_mm"] == 4.0
    assert not part.get("thickness_rejected_mm")


def test_still_refused_under_the_new_floor_stays_unset():
    part = {"part_number": "P", "description": "PANEL",
            "normalized_material": "TIMBER", "normalized_thickness_mm": 2.5}
    estimator._safe_thickness_and_stage(part)
    part["normalized_material"] = "MDF"
    assert estimator._safe_thickness_and_stage(part)[0] is None
    assert part["normalized_thickness_mm"] is None
    assert part["thickness_rejected_mm"] == 2.5


def test_the_weigh_declines_a_refused_gauge():
    """The shipping weigh used to weigh the board at the refused 2.5 mm; with the figure
    moved off the record the part is named as unweighed instead, which is what lets the
    pack's stated weight take charge (SCRUM-178)."""
    part = {"part_number": "12678-01-01J", "description": "BASE",
            "normalized_material": "TIMBER", "quantity": 1,
            "blank_length_mm": 350.0, "blank_width_mm": 250.0,
            "normalized_thickness_mm": 2.5}
    estimator._safe_thickness_and_stage(part)
    o = cl.describe_order([part], 1)
    assert o["unit_weight_kg"] is None
    assert [r["part_number"] for r in o["left_out_parts"]] == ["12678-01-01J"]


def test_the_board_row_never_wears_the_refused_gauge():
    """Wired: the sheet writer reads the refusal beside the empty gauge and leaves the Ga
    cell and the £/kg gap-filler alone, instead of refilling from a stale copy."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "wb_populate.py"),
               encoding="utf-8").read()
    seg = src[src.index("def _write_board_row"):]
    seg = seg[:seg.index("def ", 10)]
    assert "thickness_rejected_mm" in seg
    assert "gauge unset" in seg
    # And the estimate record carries the refusal out of costing for it to read.
    esrc = open(os.path.join(os.path.dirname(__file__), "..", "src", "estimator.py"),
                encoding="utf-8").read()
    assert '"thickness_rejected_mm": (None if _t_kept else part.get("thickness_rejected_mm"))' in esrc


# ── the model's rectangle beats the category default ────────────────────────────────

def _native(title, bbox):
    from source_connectors.solidworks import normalize_native_extract
    return normalize_native_extract([{"title": title, "doctype": 1, "route_signals": {
        "material": "MDF", "is_sheet_metal": False, "bend_count": 0,
        "thickness_mm": None, "bbox_mm": bbox}}])


def test_a_plate_shaped_boards_model_extents_become_its_blank():
    from source_connectors.solidworks import apply_native_to_pre_estimate
    parts = [{"part_number": "12093-24-06J", "description": "SHELF",
              "normalized_material": "MDF"}]
    apply_native_to_pre_estimate(parts, _native("12093-24-06J", [520.0, 370.0, 18.0]))
    assert parts[0]["normalized_thickness_mm"] == 18.0
    assert parts[0]["blank_length_mm"] == 520.0
    assert parts[0]["blank_width_mm"] == 370.0
    ng = parts[0]["normalized_geometry"]
    assert ng["blank_length_mm"] == 520.0 and ng["blank_width_mm"] == 370.0


def test_a_box_shaped_board_is_not_blanked_from_its_envelope():
    """The 552 x 370 x 125 plinth is a construction, not a plate: its envelope is not the
    rectangle it is cut from, so no blank is invented and the question stands."""
    from source_connectors.solidworks import apply_native_to_pre_estimate
    parts = [{"part_number": "12678-01-01J", "description": "BASE",
              "normalized_material": "MDF"}]
    apply_native_to_pre_estimate(parts, _native("12678-01-01J", [552.0, 370.0, 125.0]))
    assert not parts[0].get("blank_length_mm")
    assert not parts[0].get("blank_width_mm")


def test_the_models_rectangle_displaces_the_category_default():
    """With the model's blank in place, geometry_inference leaves the part alone — no
    'tier' 350 x 250 dressing a 520 x 370 shelf."""
    from source_connectors.solidworks import apply_native_to_pre_estimate
    part = {"part_number": "12093-24-06J", "description": "SHELF",
            "normalized_material": "MDF"}
    apply_native_to_pre_estimate([part], _native("12093-24-06J", [520.0, 370.0, 18.0]))
    summary = {"manufacturing_writeup": {"parts": [part]}}
    geometry_inference.infer_missing_geometry(summary)
    ng = part["normalized_geometry"]
    assert (ng["blank_length_mm"], ng["blank_width_mm"]) == (520.0, 370.0)
    assert not ng.get("_inferred")
