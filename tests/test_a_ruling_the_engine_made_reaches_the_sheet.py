r"""An operation the engine ruled out does not come back through another record.

James, on the 7332-01 six-off rerun: "Suppress the erroneous Tubebend operation on leg 002."

It had already been suppressed. Howard ruled it in his 15 September reply — "Line 103 -
Tube Bending Op. - Not Required" — the gate went in as D-069, and the leg still arrived at
the estimator with a Tubebend row on it: TBEN at its own hourly rate with a 45-minute
set-up, on a leg that is sawn.

THE GATE WAS NOT WRONG. IT WAS WRITING TO THE WRONG NAME.

Suppression cleaned the COSTED record — ops, textual_operations, inferred_operations and
both timing dicts. The sheet does not read that record. wb_populate.route_operations_by_part
rebuilds the operation list from summary["parts"], and route_compiler builds its claims from
the same place; both honour a ruling under ONE name, `operations_ruled_out`, and the gate
was recording under another, `removed_operations`. Two names for one fact — which is the
fault the change register exists to catch, and it had produced a real charge on a real book.

So the test is not "does the gate remove it" (it did) but "does the ruling survive the trip
to the record the sheet actually reads". It is driven through the engine's own function on
a part built here, so it holds for ANY square section whose only bend evidence is an angle
callout — not for 7332-01-002.

The second half covers the same class on the labour side: a stated shop time whose
operation key had no entry in the workbook's own name map and reached the sheet only
through a last-resort lookup built for a model's free English.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import wb_populate  # noqa: E402


# ── the ruling travels ───────────────────────────────────────────────────────────────

def _summary_with(part: dict) -> dict:
    return {"parts": [part]}


def test_a_ruled_out_operation_is_not_rebuilt_by_the_route_reader():
    """The exact shape the leg arrives in: the costed record is clean, the raw record still
    lists the operation, and the ruling is what has to cancel it."""
    part = {
        "part_number": "TEST-002",
        # The raw record still carries the word — this is what route_operations_by_part
        # walks, and why a ruling that lives only on the costed record never reaches it.
        "textual_operations": ["tube_cut", "tubebend"],
        "operations_ruled_out": {
            "tubebend": "square section, angle callouts describe the saw cut, not a bend",
        },
    }
    route = wb_populate.route_operations_by_part(_summary_with(part))
    assert "tube_cut" in route["TEST-002"], "the real operation must survive"
    assert "tubebend" not in route["TEST-002"], (
        "the sheet re-added the operation the engine ruled out")


def test_without_the_ruling_the_route_keeps_the_operation():
    """The control. If this passed too, the test above would be proving nothing."""
    part = {"part_number": "TEST-002", "textual_operations": ["tube_cut", "tubebend"]}
    route = wb_populate.route_operations_by_part(_summary_with(part))
    assert "tubebend" in route["TEST-002"]


def test_the_gate_records_its_ruling_under_the_name_the_readers_read():
    """The join between the two halves: the suppression must write `operations_ruled_out`,
    not only `removed_operations`, or the route reader above never sees it.

    Read from source deliberately — estimate_part cannot be driven without a full costing
    context, and what is being asserted is which KEY the gate writes, which is exactly the
    thing that was wrong.
    """
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "src" / "estimator.py"
           ).read_text(encoding="utf-8")
    start = src.index("if not _keep_tb:")
    block = src[start:start + 2000]
    assert "operations_ruled_out" in block, (
        "the tube-bend gate strips the costed record but records no ruling, so the route "
        "rebuilds the operation")
    assert "removed_operations" in block, "the human-facing list is still published"


def test_a_ruling_and_a_removal_are_both_kept_because_they_answer_different_readers():
    """`removed_operations` is what a person reads; `operations_ruled_out` is what the route
    obeys. Collapsing them into one would lose either the reason or the audience."""
    part = {
        "part_number": "TEST-002",
        "textual_operations": ["tubebend"],
        "removed_operations": ["tubebend"],
        "operations_ruled_out": {"tubebend": "nothing states a bend"},
    }
    route = wb_populate.route_operations_by_part(_summary_with(part))
    assert route["TEST-002"] == [], "the ruling cancels it"
    assert part["removed_operations"] == ["tubebend"], "the list a person reads is intact"


# ── the stated labour row has a name of its own ──────────────────────────────────────

def test_the_brushing_operation_names_its_own_workbook_row():
    """BRUSH_BEFORE_PLATE emits `manual_labour_metal`. Its acrylic twin has been in the map
    since the acrylic split; the metal one was reaching the sheet only through the
    last-resort department lookup at the bottom of _wb_op_name."""
    assert wb_populate.OP_NAME_MAP.get("manual_labour_metal") == "Manual labour (Metal)"


def test_both_hands_of_the_manual_labour_pair_are_mapped():
    """The asymmetry itself is the defect — one of a pair present, the other absent."""
    assert wb_populate.OP_NAME_MAP.get("manual_labour_metal")
    assert wb_populate.OP_NAME_MAP_ACRYLIC.get("manual_labour_acrylic")


def test_the_brushing_rule_still_points_at_that_operation():
    """A map entry is only worth anything while the rule still emits the key it maps."""
    import config
    assert (config.BRUSH_BEFORE_PLATE.get("operation")
            in wb_populate.OP_NAME_MAP), (
        "BRUSH_BEFORE_PLATE emits an operation the workbook has no row name for")
