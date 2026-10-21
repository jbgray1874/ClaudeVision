"""A memberless assembly is not free (D-560).

401918-01-GA, 21 Oct 2026 11:14 book: 401918-01-07M BASE FRAME - WELDMENT (x2) reached the
book as an assembly with no children and no material — "nothing to charge here — an assembly's
material is its members'" — while the review list led with a £0.75 fixing. A parent that names
no member must carry its own money by some road, or the job is blocked until it does.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import invariants  # noqa: E402

CHECK = invariants.check_a_memberless_assembly_carries_nothing


def _frame(**extra):
    p = {"part_number": "401918-01-07M", "description": "BASE FRAME - WELDMENT",
         "is_assembly_parent": True, "is_sub_assembly": True, "quantity": 2}
    p.update(extra)
    return p


def _job(*parts):
    return {"parts": [{"part_number": "401918-01-GA", "is_assembly_parent": True,
                       "assembly_children": ["401918-01-401"]},
                      {"part_number": "401918-01-401", "is_assembly_parent": True,
                       "assembly_children": ["401918-01-07M", "401918-01-08M"]},
                      {"part_number": "401918-01-08M", "normalized_material": "MILD STEEL",
                       "unit_material_cost_gbp": 1.5},
                      *parts]}


def test_a_parent_with_no_member_and_no_material_blocks():
    found = CHECK(_job(_frame()))
    assert len(found) == 1
    v = found[0]
    assert v["code"] == "memberless_assembly_carries_nothing" and v["severity"] == invariants.BLOCKING
    assert "401918-01-07M BASE FRAME - WELDMENT" in v["message"]
    assert "only when it has members" in v["message"]
    assert v["detail"]["count"] == 1 and v["detail"]["parts"][0]["quantity"] == 2


def test_a_parent_with_members_is_their_business():
    assert CHECK(_job(_frame(assembly_children=["401918-01-07M-CL1"]),
                      {"part_number": "401918-01-07M-CL1", "section_stock": {"length_mm": 703}})) == []
    assert CHECK(_job(_frame(),
                      {"part_number": "401918-01-07M-CL1", "cut_list_member_of": "401918-01-07M"})) == []
    assert CHECK(_job(_frame(),
                      {"part_number": "X", "owning_assembly": "401918-01-07M"})) == []
    assert CHECK(_job(_frame(),
                      {"part_number": "Y", "bom_parent": "401918-01-07M"})) == []


def test_a_parent_that_carries_its_own_money_by_some_road_passes():
    assert CHECK(_job(_frame(section_stock={"a": 20, "b": 50, "t": 2, "cut_lengths_mm": [703, 451, 451]}))) == []
    assert CHECK(_job(_frame(unit_material_cost_gbp=12.4))) == []
    assert CHECK(_job(_frame(material_estimate={"cost_per_part_gbp": 12.4}))) == []
    assert CHECK(_job(_frame(dxf_measured_outline=True))) == []
    assert CHECK(_job(_frame(is_bought_in=True, unit_price_gbp=3.0))) == []


def test_the_check_is_registered_and_a_bad_structure_is_unevaluated():
    assert CHECK in invariants.CHECKS
    assert CHECK("not a job")[0]["code"] == "memberless_assembly_not_evaluated"
    assert CHECK({"parts": [{"part_number": "ONLY", "is_assembly_parent": True}]}) == []
