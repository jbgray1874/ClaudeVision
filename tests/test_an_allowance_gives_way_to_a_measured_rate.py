"""An allowance gives way to a department's measured rate, inside that rate's scope (D-667).

12203-66-GA, 3 Nov 2026 19:48 and 20:10: a faced-board tray. The joinery shop's measured rates
for faced board (SHOP_STATED: bench 2/hr, packing 20/hr) were on the Bench Work and Packing
Joinery rows' defaults, and the books still charged bench at 10/hr and packing at 75/hr: both
rows carried a "stated shop time" (the bench-fitting rule's house allowance, 2 min x 3 parts,
and the per-piece unit-fitting allowance), and a stated time is decided first and never enters
the chain where the measured rate lives. D-664 widened who counts as faced board and changed
nothing on the sheet, because this branch was the one deciding.

A measured time still wins (a weld model, a plater pack, a count off the part's own record);
only the two allowance claims give way.
"""
from __future__ import annotations

import inspect
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import wb_populate as W  # noqa: E402


def test_the_two_allowance_claims_are_named():
    assert W._ALLOWANCE_TIME_MARKERS == {"bench_work_applied", "unit_fitting_applied"}
    named = {m for m, _ops, _why in W._STATED_SHOP_TIME_MARKERS}
    assert W._ALLOWANCE_TIME_MARKERS <= named


def test_a_row_claimed_only_by_an_allowance_gives_way():
    stated = {"12203-66-GA": "the bench-fitting rule ... house allowance per part fitted"}
    assert W.allowance_only_claim({"parts": ["12203-66-GA"]}, stated, set())


def test_a_row_with_a_measured_claim_keeps_it():
    stated = {"X-101": "the welding department's stated weldment allowance"}
    assert not W.allowance_only_claim({"parts": ["X-101"]}, stated, {"X-101"})


def test_a_row_with_no_claim_is_not_this_rules_business():
    assert not W.allowance_only_claim({"parts": ["Y-01"]}, {}, set())


def test_the_measured_rate_is_asked_before_the_stated_time_branch():
    src = inspect.getsource(W.populate_workbook)
    guard = src.index("allowance_only_claim(g, _stated_time_by_pn, _measured_claim_pns)")
    stated = src.index("_stated_hours, _stated_members = stated_row_hours(")
    assert guard < stated
    assert "wb_op in _STATED_THROUGHPUT_ROWS" in src[guard - 400:guard], \
        "only a row the department's measured rate covers, in its own scope"
