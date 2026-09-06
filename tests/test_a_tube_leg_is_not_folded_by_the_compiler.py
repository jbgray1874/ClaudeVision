"""A tube leg the estimator recognises is not called 'folding required' by the compiler.

7332-01-002 is a 12.7×1.2 tube leg. The sheet charged Tubebend (right), but the route compiler
still carried folding = required against it — because the tube-fold impossibility rule reads the
part record's stock_form, and estimate_part had tagged 'tube' only on the material estimate, not
on the part. So the four surfaces disagreed: sheet said Tubebend, compiler said folding.

estimate_part now writes stock_form onto the part itself when it costs a hollow section, so the
compiler's impossibility gate sees the tube and rules folding out, exactly as the sheet does.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import estimator as e  # noqa: E402
import route_compiler as rc  # noqa: E402


def _leg():
    return {"part_number": "7332-01-002", "description": "LEG - 12.7 x 1.2 CHS TUBE",
            "normalized_material": "MILD STEEL", "quantity": 2,
            "section_stock": {"a": 12.7, "b": 12.7, "t": 1.2, "profile_form": "CHS",
                              "length_mm": 1400.0},
            "textual_operations": ["folding", "tubebend"]}


def test_the_estimator_tags_the_part_a_tube():
    part = _leg()
    e.estimate_part(part, job_quantity=6)
    assert part.get("stock_form") == "tube"


def test_the_compiler_rules_folding_out_and_keeps_tubebend():
    part = _leg()
    e.estimate_part(part, job_quantity=6)
    decs = {d["operation"]: d for d in rc.compile_job_route([part], {})["decisions"]}
    assert decs["folding"]["status"] == "not_applicable"
    assert "tube" in str(decs["folding"].get("reason") or "").lower()
    assert decs["tubebend"]["status"] == "required"
