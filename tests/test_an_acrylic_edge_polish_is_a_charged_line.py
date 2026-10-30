"""An acrylic part's edge polish is a charged line, not a silent drop.

7332-01-007 is an acrylic lens. The estimator's acrylic route adds Diamond Polish (the finish —
acrylic is never powder coated), Peel and, when lasered, the laser cut — writing them straight
into the process time-map, because they are the acrylic route itself rather than words read off
the drawing. Under the canonical-route cutover a REQUIRED OperationDecision is the only thing
that becomes a labour row, and the compiler only raises a decision for an operation the part
actually carries. So the polish was priced by the estimator (£31.60/hr) and then dropped from
the sheet — a lens quoted with no edge finish at all.

estimate_part now RECORDS each surviving acrylic op onto the part, so the compiler raises a
required decision for it and the cutover charges exactly what was costed.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import estimator as e  # noqa: E402
import route_compiler as rc  # noqa: E402


def _lens(**over):
    part = {"part_number": "7332-01-007", "description": "LENS",
            "normalized_material": "ACRYLIC",
            "overall_length_mm": 200.0, "overall_width_mm": 100.0,
            "hole_count": 0, "bend_count_dxf": 0, "is_laser_cut": True}
    part.update(over)
    return part


def test_the_estimator_records_the_polish_on_the_part():
    part = _lens()
    pe = e.estimate_part(part, job_quantity=1)
    ops = list(part.get("inferred_operations") or []) + list(part.get("textual_operations") or [])
    assert "diamond_polish" in ops, f"polish not recorded: {ops}"
    # and it is priced, not zero
    costs = (pe.get("cost_breakdown", {}).get("labour", {}).get("costs_gbp") or {})
    assert costs.get("diamond_polish", 0) > 0


def test_the_compiler_raises_a_required_decision_for_the_polish():
    part = _lens()
    e.estimate_part(part, job_quantity=1)
    graph = rc.compile_job_route([part], {})
    decs = {d["operation"] + "@" + str(d.get("target_id")): d for d in graph["decisions"]}
    dec = decs.get("diamond_polish@7332-01-007")
    assert dec is not None, f"no polish decision: {sorted(decs)}"
    assert dec["status"] == "required"


def test_a_metal_part_gets_no_diamond_polish():
    # the recording is inside the acrylic branch only — steel is never diamond polished
    part = {"part_number": "7332-01-101", "description": "BRACKET",
            "normalized_material": "MILD STEEL",
            "overall_length_mm": 200.0, "overall_width_mm": 100.0,
            "hole_count": 2, "bend_count_dxf": 1}
    e.estimate_part(part, job_quantity=1)
    ops = list(part.get("inferred_operations") or []) + list(part.get("textual_operations") or [])
    assert "diamond_polish" not in ops
