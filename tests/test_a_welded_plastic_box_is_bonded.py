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
