r"""
test_one_part_has_one_blank.py

A BLOCKING FLAG THAT DESCRIBED A BLANK THE ESTIMATE NEVER USED.

11650-01-05A DOOR was reported as "5 x 3.5 mm with a 3,952 mm cut path -- 225.8x more than
it could hold". It reads as a catastrophic geometry failure and two separate diagnoses were
spent on it, mine and the estimator's, both concluding the door's GBP 0.00 material was
caused by a microscopic blank.

It was not. The workbook's Other Sheet Material row carries 1202 x 689, and the same run's
own throughput flag reports "largest part 0.8282 m2" -- which is 1.202 x 0.689. The costing
used the real door size all along. The GBP 0.00 has an unrelated cause (ABS is absent from
the plastic sheet-pricing gate that contains POLYCARBONATE).

The two readers looked in different places:

    wb_populate, and the cost   material_estimate -> normalized_geometry      1202 x 689
    invariants._blank_num       part -> normalized_geometry -> geometry_rollup    5 x 3.5

_blank_num never looks at material_estimate. Its own docstring records being widened once
already after a false positive from looking in too few places -- and it was still one holder
short. So the fix is not a fourth holder in a fourth reader. It is ONE reader, preferring
the record the money came from, and REPORTING a disagreement rather than resolving it out of
sight. Two blanks on one part is a real defect; picking one quietly is how it stayed
invisible while its symptom was blamed on something else.

The fifth "two rules for one question" found in this codebase in a single day.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from costed_facts import blank_dimensions                                    # noqa: E402
from invariants import check_a_blank_and_its_cut_path_can_both_be_true as check  # noqa: E402
from invariants import BLOCKING                                              # noqa: E402


def _door():
    """The real 11650-01-05A record: the priced blank and the stale one, side by side."""
    return {"part_number": "11650-01-05A",
            "material_estimate": {"blank_length_mm": 1202, "blank_width_mm": 689},
            "normalized_geometry": {"blank_length_mm": 5, "blank_width_mm": 3.5},
            "cut_length_mm": 3952}


def _job(*parts):
    return {"estimate_summary": {"part_estimates": list(parts)}}


# ── the reader ──────────────────────────────────────────────────────────────────────
def test_the_blank_that_priced_the_job_is_the_one_returned():
    """material_estimate is what the costing wrote and the sheet was built from. The
    operative blank is the one that produced the money, not the one a later reader happens
    to find first."""
    bd = blank_dimensions(_door())
    assert (bd["length_mm"], bd["width_mm"]) == (1202.0, 689.0)
    assert bd["holder"] == "material_estimate"


def test_the_other_reading_is_reported_not_discarded():
    bd = blank_dimensions(_door())
    assert bd["conflict"] is True
    holders = {r["holder"] for r in bd["readings"]}
    assert holders == {"material_estimate", "normalized_geometry"}


def test_agreeing_holders_are_not_a_conflict():
    """A flat-pattern extractor and a title block rounding differently is not two blanks."""
    bd = blank_dimensions({"material_estimate": {"blank_length_mm": 100.0, "blank_width_mm": 50.0},
                           "normalized_geometry": {"blank_length_mm": 100.4, "blank_width_mm": 50.2}})
    assert bd["conflict"] is False, "sub-millimetre rounding must not be reported as a defect"


def test_overall_dimensions_stand_in_for_a_blank():
    bd = blank_dimensions({"normalized_geometry": {"overall_length_mm": 300, "overall_width_mm": 200}})
    assert (bd["length_mm"], bd["width_mm"]) == (300.0, 200.0)


@pytest.mark.parametrize("part", [None, {}, {"material_estimate": {}}, "not a part"])
def test_a_part_with_no_blank_says_so(part):
    bd = blank_dimensions(part)
    assert bd["length_mm"] is None and bd["readings"] == [] and bd["conflict"] is False


# ── the check that was blocking on the wrong blank ──────────────────────────────────
def test_the_door_no_longer_blocks_for_a_cut_path_that_does_fit():
    """1202 x 689 holds a 3,952 mm cut path comfortably -- the perimeter alone is 3,782 mm.
    Blocking on this told everyone the geometry was catastrophic when it was correct."""
    codes = [v.get("code") or v.get("name") for v in check(_job(_door()))]
    assert "blank_and_cut_path_disagree" not in str(codes), (
        "the check is still judging the cut path against a blank that priced nothing")


def test_the_two_blanks_are_reported_as_themselves():
    found = check(_job(_door()))
    assert len(found) == 1
    v = found[0]
    assert v["severity"] == BLOCKING
    assert "more than one blank size" in v["message"]
    assert "1202x689" in v["message"] and "5x3.5" in v["message"], \
        "name BOTH sizes and where each came from, or nobody can settle which is right"


def test_a_genuinely_impossible_blank_still_blocks():
    """The original check must survive. A single blank far too small for its cut path is a
    real unit error and is the reason this check exists."""
    part = {"part_number": "Y",
            "material_estimate": {"blank_length_mm": 5, "blank_width_mm": 3.5},
            "cut_length_mm": 3952}
    msgs = " ".join(v["message"] for v in check(_job(part)))
    assert "will not fit inside the blank" in msgs


def test_a_clean_part_raises_nothing():
    part = {"part_number": "Z",
            "material_estimate": {"blank_length_mm": 1202, "blank_width_mm": 689},
            "cut_length_mm": 3952}
    assert check(_job(part)) == []


# ── and the readers cannot drift apart again ────────────────────────────────────────
def test_the_workbook_and_the_check_read_the_same_blank():
    import ast
    body = ast.unparse(ast.parse((ROOT / "src" / "wb_populate.py").read_text(encoding="utf-8")))
    assert "blank_dimensions" in body, \
        "wb_populate has gone back to its own holder ordering"
    assert 'me.get("blank_length_mm") or ng.get' not in body, \
        "the private two-holder lookup is back in wb_populate"
    inv = ast.unparse(ast.parse((ROOT / "src" / "invariants.py").read_text(encoding="utf-8")))
    assert "blank_dimensions" in inv, "the invariant has gone back to _blank_num for the blank"
