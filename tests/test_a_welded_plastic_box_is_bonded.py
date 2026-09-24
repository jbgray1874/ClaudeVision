"""On acrylic, "weld" is a solvent weld: the joint is bonded, not dropped.

12633-10-GA, a clear PMMA box of six butt panels: the weld cue on the GA was correctly stripped as
a metal process and nothing replaced it, so the box was costed with no bonding at all.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import estimator                                                  # noqa: E402


def _ga(material):
    return {"part_number": "12633-10-GA", "description": "CONSUMABLE HOLDER",
            "material": material, "normalized_material": material,
            "is_assembly_parent": True, "assembly_children": ["A", "B", "C", "D", "E", "F"],
            "quantity": 1, "textual_operations": ["welding"]}


def test_an_acrylic_assembly_with_a_weld_cue_is_glued_not_welded():
    ga = _ga("ACRYLIC")
    costs = (estimator.estimate_part(ga, job_quantity=1).get("labour_estimate") or {}).get("costs_gbp") or {}
    assert "glue" in costs and "welding" not in costs and "dress_welds" not in costs
    assert ga.get("acrylic_bonded") is True


def test_timber_keeps_the_strip_alone():
    ga = _ga("MDF")
    costs = (estimator.estimate_part(ga, job_quantity=1).get("labour_estimate") or {}).get("costs_gbp") or {}
    assert "glue" not in costs and "welding" not in costs


def test_a_plastic_assembly_of_loose_panels_is_bonded_without_a_weld_note():
    """12633-00-GA: three acrylic sub-assemblies, no fixings, no weld note anywhere."""
    ga = _ga("ACRYLIC")
    ga["textual_operations"] = []
    ga["assembly_children"] = ["12633-02-01P", "12633-02-02P", "12633-02-03P"]
    costs = (estimator.estimate_part(ga, job_quantity=1).get("labour_estimate") or {}).get("costs_gbp") or {}
    assert "glue" in costs


def test_an_assembly_with_fixings_is_screwed_not_glued():
    ga = _ga("ACRYLIC")
    ga["textual_operations"] = []
    ga["assembly_children"] = ["X-01P", "X-02P", "FIXING43"]
    costs = (estimator.estimate_part(ga, job_quantity=1).get("labour_estimate") or {}).get("costs_gbp") or {}
    assert "glue" not in costs


def test_an_assembly_of_other_material_is_left_alone():
    ga = _ga("MILD STEEL")
    ga["textual_operations"] = []
    costs = (estimator.estimate_part(ga, job_quantity=1).get("labour_estimate") or {}).get("costs_gbp") or {}
    assert "glue" not in costs
