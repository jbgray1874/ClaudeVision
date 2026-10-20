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


def test_ruling_the_fold_out_does_not_bend_the_tube_for_free():
    """THE REGRESSION THIS EXISTS TO STOP. Under the cutover a labour row exists only where a
    REQUIRED decision does. Ruling folding not_applicable on a tube removed the only claim
    wb_populate._TUBE_OP_REMAP had to relabel as Tubebend, so the bend left the sheet entirely
    and 7332-01's leg was bent for free — £8.70 of labour lost, labour £36.00 -> £27.30.

    A tube that states a bend must ALWAYS come out of the compiler with a required bending
    operation; only which machine does it changes."""
    part = _leg()
    part["textual_operations"] = ["folding"]        # the drawing's word, no tubebend hint
    e.estimate_part(part, job_quantity=6)
    decs = {d["operation"]: d for d in rc.compile_job_route([part], {})["decisions"]}
    bends = [op for op, d in decs.items()
             if op in ("folding", "fold", "linebend", "line_bend", "tubebend")
             and d["status"] == "required"]
    assert bends == ["tubebend"], f"the tube must still be bent, by the bender: {decs}"


def test_a_flat_sheet_part_still_folds_and_gets_no_tubebend():
    """The remap is keyed on the stock form, never a part number — sheet is unaffected."""
    part = {"part_number": "7332-01-005", "description": "CHANNEL",
            "normalized_material": "MILD STEEL", "quantity": 1,
            "blank_length_mm": 441.0, "blank_width_mm": 24.7, "thickness_mm": 1.5,
            "textual_operations": ["folding"]}
    e.estimate_part(part, job_quantity=6)
    decs = {d["operation"]: d for d in rc.compile_job_route([part], {})["decisions"]}
    assert decs["folding"]["status"] == "required"       # a press brake folds sheet
    assert "tubebend" not in decs
