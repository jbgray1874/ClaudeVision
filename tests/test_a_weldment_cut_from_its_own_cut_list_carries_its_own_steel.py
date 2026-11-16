"""A weldment whose sheet lists the pieces it is cut from is priced on those pieces (D-439).

8188-29-001 COMMON HEADER GOALPOST: its own sheet's table lists 2 x 300 and 1 x 1,272 of
25.4 x 25.4 x 1.22 SHS, and its note says WELD AND DRESS THE CORNERS. The merge marks it a
weldment parent (it is: three pieces welded), and the parent branch of estimate_material hands
the steel to "the children" — which it does not have. Once the 300 mm catalogue row rightly
stopped matching a 1,872 mm cut list (D-429), the goalpost's tube was £0.00 on the replay.
The pieces ARE its stock: 1,872 mm of the section, 1.73 kg, priced as a section. The weld is
still the parent's work. A parent with children of its own still defers to them.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import estimator                                                      # noqa: E402


def _goalpost(**over):
    part = {
        "part_number": "8188-29-001", "description": "COMMON HEADER GOALPOST", "quantity": 1,
        "pages": [16], "page_roles": ["detail"], "normalized_material": "MILD STEEL",
        "is_assembly_parent": True,
        "manufacturing_interpretation": {"stock_form": "unknown", "requires_flat_blank": True,
                                         "process_family": "fabrication",
                                         "setup_driven_operations": ["welding"],
                                         "run_driven_operations": ["handling"], "routing": []},
        "section_stock": {"a": 25.4, "b": 25.4, "t": 1.22, "length_mm": 1272.0,
                          "profile_form": "SHS", "keyword": "TUBE",
                          "detection_path": "canonical_profile",
                          "cut_lengths_mm": [300.0, 300.0, 1272.0],
                          "cut_lengths_mm_source": "drawing_deterministic",
                          "source": "drawing_deterministic"},
    }
    part.update(over)
    return part


def test_the_goalposts_steel_is_its_three_pieces_not_nothing():
    part = _goalpost()
    me = estimator.estimate_material(part)
    assert me["cost_method"] != "weldment_parent_material_in_children", me["cost_method"]
    assert me["stock_form"] in ("section", "tube"), me["stock_form"]
    se = me["stock_estimate"]
    assert abs(float(se["section_length_mm"]) - 1872.0) < 0.5, se
    assert se["section_length_reader"] == "cut_list_sum", se
    assert se["cut_lengths_mm"] == [300.0, 300.0, 1272.0], se
    # 1,872 mm of 25.4 x 25.4 x 1.22 SHS is about 1.73 kg — not the 1,272 mm long piece alone
    assert abs(float(me["unit_material_mass_kg"]) - 1.734) < 0.03, me["unit_material_mass_kg"]
    assert float(me.get("unit_material_cost_gbp") or 0) > 0, "the money follows the 1,872 mm"


def test_the_money_is_on_the_cut_list_length_not_the_longest_piece():
    whole = estimator.estimate_material(_goalpost())
    one_piece = estimator.estimate_material(_goalpost(
        section_stock=dict(_goalpost()["section_stock"], cut_lengths_mm=[1272.0])))
    assert float(whole["unit_material_cost_gbp"]) > float(one_piece["unit_material_cost_gbp"]) > 0
    ratio = float(whole["unit_material_cost_gbp"]) / float(one_piece["unit_material_cost_gbp"])
    assert abs(ratio - 1872.0 / 1272.0) < 0.05, ratio


def test_the_part_says_why_it_was_priced_as_a_section():
    part = _goalpost()
    estimator.estimate_material(part)
    flags = " ".join(str(f) for f in part.get("review_flags") or [])
    assert "own section cut list" in flags, flags


def test_a_parent_with_children_of_its_own_still_defers_to_them():
    part = _goalpost(assembly_children=[{"part_number": "8188-29-001-01"},
                                        {"part_number": "8188-29-001-02"}])
    me = estimator.estimate_material(part)
    assert me["cost_method"] == "weldment_parent_material_in_children", me["cost_method"]


def test_a_parent_with_no_cut_list_is_unchanged():
    part = _goalpost()
    del part["section_stock"]
    me = estimator.estimate_material(part)
    assert me["cost_method"] == "weldment_parent_material_in_children", me["cost_method"]
