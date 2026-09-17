r"""The road 7332-01 actually takes.

James, reviewing 5ceb04b:

    "`5ceb04b` does add `labour_group_key()`, but it only replaces grouping in the legacy
     labour loop. The 7332 record is on canonical-route cutover: estimate_summary
     .canonical_route_shadow is present and has 31 decisions, CANONICAL_ROUTE_WORKBOOK_
     CUTOVER defaults on, under cutover the workbook calls canonical_labour_groups(), and
     canonical_labour_groups() does not call labour_group_key() or check
     STATED_TIME_OPERATIONS. So the claimed 'now applies to all stated rows' is not true
     for the 7332 rerun."

He is right, and it is the worst kind of miss: the fix was real, it was tested, and it was
on the wrong road. The workbook has TWO labour paths and I patched the one this job does
not use, then predicted I105/I109/I110 off the patched one.

The canonical grouper builds a different key SHAPE, so it cannot simply call
`labour_group_key`. What must not differ between the two paths is WHICH operations refuse
to share a row, so that question now lives in one predicate — `is_stated_time_operation` —
and both graders ask it.

On the canonical path the merge was worse than on the legacy one. The generic key is
(department, material, thickness, sequence), which puts the pack out and the pack back
together; and the fallback underneath it takes a decision with NO sequence and deliberately
joins it to an existing group of the same department. For a stated rule that is the merge,
made on purpose.

These tests drive `canonical_labour_groups` itself with the three decisions.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import config          # noqa: E402
import wb_populate     # noqa: E402

_PART = "7332-01-101"


def _decision(op: str, decision_id: str, sequence=None, scope="part") -> dict:
    return {
        "decision_id": decision_id,
        "operation": op,
        "status": "required",
        "target_id": _PART,
        "participants": [_PART],
        "scope": scope,
        "sequence": sequence,
        "qty_per_unit": 1,
    }


def _summary(decisions) -> dict:
    """A canonical-route summary of the shape the cutover reads."""
    payload = {
        "nodes": [{"part_number": _PART, "qty_per_unit": 1}],
        "decisions": list(decisions),
    }
    return {
        "canonical_route_shadow": payload,
        "estimate_summary": {"canonical_route_shadow": payload},
        "parts": [{"part_number": _PART, "normalized_material": "MILD STEEL",
                   "normalized_thickness_mm": 1.0}],
    }


def _part_estimates() -> list:
    return [{
        "part_number": _PART,
        "description": "STAND WELDMENT",
        "normalized_material": "MILD STEEL",
        "normalized_thickness_mm": 1.0,
        "quantity": 1,
        "material_estimate": {"material": "MILD STEEL", "thickness_mm": 1.0},
    }]


def _groups_for(decisions):
    return wb_populate.canonical_labour_groups(
        _summary(decisions), _part_estimates(), order_qty=6)


# ── the predicate both paths ask ─────────────────────────────────────────────────────

def test_one_predicate_answers_for_both_graders():
    """The key shapes differ; which operations refuse to share a row must not."""
    for op in config.STATED_TIME_OPERATIONS:
        assert wb_populate.is_stated_time_operation(op)
    for op in ("deburr", "bench_work", "handling", "assembly", "laser_cutting", "", None):
        assert not wb_populate.is_stated_time_operation(op)


def test_the_canonical_grouper_asks_it():
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "wb_populate.py"),
               encoding="utf-8").read()
    start = src.index("def canonical_labour_groups(")
    # The next TOP-LEVEL def. Slicing at the next "def " anywhere lands on a nested one
    # and cuts the function off above the branch under test — which is how this assertion
    # failed against code that was already correct.
    end = src.index("\ndef ", start + 10)
    body = src[start:end]
    assert "is_stated_time_operation(operation)" in body, (
        "the canonical grouper — the path 7332-01 takes — does not ask which operations "
        "refuse to share a row")


# ── the three rows, out of the grouper itself ────────────────────────────────────────

def test_the_two_pack_stages_get_two_rows_under_cutover():
    """Both are "Assemble/pack (Metal)" at the same material and gauge, which is the whole
    generic canonical key."""
    groups = _groups_for([_decision("plater_pack", "d-pack-out", sequence=90),
                          _decision("plater_final_pack", "d-pack-back", sequence=90)])
    ops = sorted(str(k[-1]) for k in groups)
    assert ops == ["plater_final_pack", "plater_pack"], groups
    assert len(groups) == 2, "the pack out and the pack back still share a row"


def test_brushing_gets_a_row_of_its_own_beside_other_manual_metal_work():
    groups = _groups_for([_decision("brush_before_plate", "d-brush", sequence=50),
                          _decision("deburr", "d-deburr", sequence=50)])
    assert len(groups) == 2, "brushing pooled with deburr on the same bench"
    stated = [k for k in groups if k[0] == "canonical-stated"]
    assert len(stated) == 1 and stated[0][-1] == "brush_before_plate"


def test_all_three_stated_rules_make_three_rows():
    """The shape the six-off rerun has to produce: 40, 4 and 8 minutes, separately."""
    groups = _groups_for([
        _decision("brush_before_plate", "d-brush", sequence=50),
        _decision("plater_pack", "d-pack-out", sequence=90),
        _decision("plater_final_pack", "d-pack-back", sequence=90),
    ])
    assert len(groups) == 3, groups
    assert sorted(str(k[-1]) for k in groups) == [
        "brush_before_plate", "plater_final_pack", "plater_pack"]


def test_a_sequenceless_stated_decision_does_not_join_a_department_group():
    """The nastiest part of the canonical path: a decision with NO sequence deliberately
    joins an existing group of the same department. For a stated rule that is the merge,
    made on purpose."""
    groups = _groups_for([
        _decision("handling", "d-handling", sequence=90),
        _decision("plater_final_pack", "d-pack-back", sequence=None),
    ])
    assert len(groups) == 2, "the stated pack joined the generic pack group"
    assert any(k[0] == "canonical-stated" for k in groups)


def test_unstated_work_still_shares_its_department_row():
    """The control. If everything split, these tests would prove nothing about stated
    times — and the engine would book a set-up per decision."""
    groups = _groups_for([_decision("deburr", "d-1", sequence=50),
                          _decision("bench_work", "d-2", sequence=50)])
    assert len(groups) == 1, groups


# ── and each row still reads and bills as the department ─────────────────────────────

def test_each_stated_row_keeps_its_department_title():
    groups = _groups_for([
        _decision("brush_before_plate", "d-brush", sequence=50),
        _decision("plater_pack", "d-pack-out", sequence=90),
        _decision("plater_final_pack", "d-pack-back", sequence=90),
    ])
    titles = {str(k[-1]): g["wb_op"] for k, g in groups.items()}
    assert titles["brush_before_plate"] == "Manual labour (Metal)"
    assert titles["plater_pack"] == "Assemble/pack (Metal)"
    assert titles["plater_final_pack"] == "Assemble/pack (Metal)"


def test_the_rows_carry_the_operation_so_the_stated_lookup_can_find_them():
    """The stated-time lookup runs per row and matches on the engine operation. A row that
    does not carry its operation cannot be matched, whatever its key says."""
    groups = _groups_for([_decision("plater_final_pack", "d-pack-back", sequence=90)])
    group = next(iter(groups.values()))
    assert "plater_final_pack" in [str(o).strip().lower()
                                   for o in (group.get("engine_ops") or [])]
