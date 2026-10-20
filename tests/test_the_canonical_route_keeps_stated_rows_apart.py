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


# ── two plated parts, one finished stand ─────────────────────────────────────────────
#
# James, 18 Sep: "The canonical test uses one target. The saved job has plater_pack and
# plater_final_pack each on both 008 and 101. Therefore the grouped rows will carry
# quantity 2, and the shown throughput will not simply be 15/hr and 7.5/hr. The route must
# first state whether the 4- and 8-minute actions are once per finished stand or once per
# plated component."
#
# Right, and the one-target test could not have seen it. The two graders had also been
# disagreeing about this without anybody noticing: the legacy loop forces qty 1 for the
# pack DEPARTMENTS, the canonical grouper takes the accumulated group quantity — same job,
# same rule, two answers, and the canonical one is the road 7332-01 travels.
#
# The basis is now declared per operation rather than inferred from the department.

_OTHER = "7332-01-008"


def _summary_two_plated(decisions) -> dict:
    payload = {
        "nodes": [{"part_number": _PART, "qty_per_unit": 1},
                  {"part_number": _OTHER, "qty_per_unit": 1}],
        "decisions": list(decisions),
    }
    return {
        "canonical_route_shadow": payload,
        "estimate_summary": {"canonical_route_shadow": payload},
        "parts": [{"part_number": _PART, "normalized_material": "MILD STEEL",
                   "normalized_thickness_mm": 1.0},
                  {"part_number": _OTHER, "normalized_material": "MILD STEEL",
                   "normalized_thickness_mm": 1.0}],
    }


def _decision_on(part: str, op: str, decision_id: str, sequence=None) -> dict:
    return {"decision_id": decision_id, "operation": op, "status": "required",
            "target_id": part, "participants": [part], "scope": "part",
            "sequence": sequence, "qty_per_unit": 1}


def _two_plated_groups():
    pes = _part_estimates() + [{
        "part_number": _OTHER, "description": "BRACKET",
        "normalized_material": "MILD STEEL", "normalized_thickness_mm": 1.0,
        "quantity": 1,
        "material_estimate": {"material": "MILD STEEL", "thickness_mm": 1.0},
    }]
    decisions = [
        _decision_on(_PART, "plater_pack", "d-po-101", sequence=90),
        _decision_on(_OTHER, "plater_pack", "d-po-008", sequence=90),
        _decision_on(_PART, "plater_final_pack", "d-pb-101", sequence=90),
        _decision_on(_OTHER, "plater_final_pack", "d-pb-008", sequence=90),
    ]
    return wb_populate.canonical_labour_groups(
        _summary_two_plated(decisions), pes, order_qty=6)


def test_two_plated_parts_still_make_exactly_two_pack_rows():
    groups = _two_plated_groups()
    assert len(groups) == 2, groups
    assert sorted(str(k[-1]) for k in groups) == ["plater_final_pack", "plater_pack"]


def test_both_parts_are_recorded_on_the_row_they_share():
    """The occasion is one; the participants are two, and the row has to say so or nobody
    can check the basis."""
    for group in _two_plated_groups().values():
        assert sorted(group["parts"]) == sorted([_OTHER, _PART]), group


def test_each_row_is_marked_as_one_occasion_for_the_finished_unit():
    """The flag the emit loop reads to choose the quantity. Without it the group's own
    accumulated qty is 2 and the throughput doubles."""
    groups = _two_plated_groups()
    for group in groups.values():
        assert group["stated_once_per_finished_unit"] is True, group
        assert group["assembly_scoped"] is True, (
            "a figure stated per finished unit is assembly-scoped in fact, whatever scope "
            "the individual decisions carry")


def test_the_group_really_did_accumulate_two_and_is_overridden_deliberately():
    """The control, and the point of the whole fix: the quantity IS 2 on the group, and the
    emit loop must choose 1 anyway because the shop's figure is per finished unit. If the
    group had accumulated 1 this test would be proving nothing."""
    for group in _two_plated_groups().values():
        assert group["qty"] == 2, (
            "two plated parts each take the operation — that is the input the emit loop "
            "has to override, not a number to fix here")


def test_the_basis_is_declared_not_inferred_from_the_department():
    """A rule whose minutes really are per component must be able to say so and be
    believed, and the answer must not depend on which department it bills to."""
    assert wb_populate.stated_time_is_once_per_finished_unit("plater_pack")
    assert wb_populate.stated_time_is_once_per_finished_unit("plater_final_pack")
    assert wb_populate.stated_time_is_once_per_finished_unit("brush_before_plate")
    assert not wb_populate.stated_time_is_once_per_finished_unit("handling")
    assert not wb_populate.stated_time_is_once_per_finished_unit("laser_cutting")
    assert config.STATED_TIME_OPERATIONS["plater_pack"] == config.PER_FINISHED_UNIT


def test_both_graders_ask_the_same_question_about_quantity():
    """The fault that produced this one: the legacy loop answered by DEPARTMENT and the
    canonical grouper did not answer at all."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "wb_populate.py"),
               encoding="utf-8").read()
    assert src.count("stated_time_is_once_per_finished_unit(") >= 3, (
        "the basis must be recorded by BOTH graders and read by the emit loop")
    assert 'if _stated_once:' in src and '_qty = 1' in src


def test_the_run_names_the_parts_when_one_occasion_covers_several():
    """Howard has to be able to overrule this. A quantity chosen silently cannot be."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "wb_populate.py"),
               encoding="utf-8").read()
    assert "booked ONCE for the finished unit, not once per" in src
    assert "config.STATED_TIME_OPERATIONS" in src


# ── an estimator-confirmed nesting group shares one set-up ───────────────────────────
#
# James, 18 Sep, settling it: "For 7332-01-003 and -004, share one 10-minute laser set-up.
# Howard's explicit statement is the proof for this job. Keep separate laser rows and their
# own cutting rates. For every other job, shared set-up requires either a proven combined
# nest or an estimator-confirmed nesting group. SAME GAUGE ALONE IS NEVER ENOUGH."
#
# The arithmetic proof needs `parts_per_sheet`, which the nester did not produce on 7332-01
# — so 003 and 004 each kept a full 10-minute set-up and the job booked 20 minutes where
# the shop runs one program. A person who knows the job is the other proof, and the
# stronger one. It arrives in the job's own answers file so it governs this drawing only.

def _summary_with_groups(groups) -> dict:
    return {"estimator_decisions": {"nesting_groups": groups}}


def test_a_confirmed_group_covering_both_parts_is_recognised():
    assert wb_populate._confirmed_nesting_group(
        _summary_with_groups({"003 and 004 on one program":
                              ["7332-01-003", "7332-01-004"]}),
        ["7332-01-003", "7332-01-004"]) == "003 and 004 on one program"


def test_a_third_component_not_in_the_group_is_not_covered():
    """A ruling about 003 and 004 says nothing about a part that merely shares their
    gauge. "Same gauge alone is never enough"."""
    assert wb_populate._confirmed_nesting_group(
        _summary_with_groups({"003 and 004": ["7332-01-003", "7332-01-004"]}),
        ["7332-01-003", "7332-01-004", "7332-01-005"]) == ""


def test_no_answers_file_means_no_confirmed_group():
    """The control. Without it, every job would silently share set-ups."""
    assert wb_populate._confirmed_nesting_group({}, ["7332-01-003", "7332-01-004"]) == ""
    assert wb_populate._confirmed_nesting_group(
        _summary_with_groups({}), ["7332-01-003"]) == ""


def test_the_match_is_case_and_whitespace_tolerant():
    """An estimator typing part numbers by hand should not have a ruling silently ignored
    over a trailing space — the fault that made operations_off do nothing."""
    assert wb_populate._confirmed_nesting_group(
        _summary_with_groups({"g": [" 7332-01-003 ", "7332-01-004"]}),
        ["7332-01-003", "7332-01-004"]) == "g"


def test_the_grouper_consults_it_only_when_the_arithmetic_has_not_already_proven_it():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "src" / "wb_populate.py"
           ).read_text(encoding="utf-8")
    assert "_confirmed_nesting_group(summary" in src
    assert "if _confirmed and not _proven:" in src, (
        "a confirmed group must not overwrite a nest result that already decided the "
        "question — it is the second proof, not a louder one")


def test_the_answers_file_key_is_accepted_by_the_validator():
    """A key the validator does not know is reported as 'that line did nothing', which is
    how a ruling gets silently ignored."""
    import estimator_confirmed
    assert "nesting_groups" in estimator_confirmed._DECISION_KEYS


def test_a_group_of_one_is_rejected_because_it_shares_nothing():
    import estimator_confirmed
    out, problems = estimator_confirmed._read_decisions(
        {"estimator_decisions": {"nesting_groups": {"solo": ["7332-01-003"]}}}, "x")
    assert "nesting_groups" not in out
    assert any("at least two parts" in p for p in problems)


def test_the_example_answers_file_carries_howards_two_rulings_and_no_price():
    """The example is what the next person copies. It used to teach a policy breach —
    plating_gbp_per_unit: 250.0, Howard's own figure off his own sheet.

    READ FROM config, WHICH IS WHERE THE EXAMPLE LIVES NOW (D-111). It used to read
    `docs/7332-01_confirmed.example.json`, a file the blanket `*.json` rule meant git never
    carried — so the test was green on the one machine that happened to have it and failed
    on every other, including a fresh checkout. That is the same fault D-111 was about, in
    a test rather than a ruling: a file nobody can diff is not evidence of anything, and a
    test that depends on one is asserting about local state.
    """
    import json
    import config
    dec = (config.JOB_DECISIONS["7332-01"].get("estimator_decisions") or {})
    assert dec["operations_off"]["7332-01-002"] == ["tube_bending"]
    assert list(dec["nesting_groups"].values())[0] == ["7332-01-003", "7332-01-004"]
    assert "plating_gbp_per_unit" not in dec, (
        "a price typed into the answers file is still a price typed into a file")
    assert "250" not in json.dumps(dec)


# ── the laser floor: nobody loads a part in one second ───────────────────────────────
#
# James, 18 Sep: "Correct 004's laser calculation and shared set-up allocation."
#
# The estimators' template times the CUT — blank size, hole count, internal cut distance,
# at their own cutting speeds — and on a part where cutting dominates it is the best basis
# on the sheet: 7332-01-003, a 441 x 10 strap, computed 236/hr against Howard's 235.
#
# It has no floor. 7332-01-004 is a 15.88 mm square cap, and the same formula returned
# 3,340/hr where he books 900. At 3,340 an hour a part is loaded, pierced, cut and taken
# off in 1.08 seconds.

def test_the_floor_reproduces_howards_own_figure_for_the_cap():
    floor = config.LASER_MIN_SECONDS_PER_PART
    assert round(3600 / floor) == 900, (
        "four seconds a part IS his 900/hr read back — a throughput, which the pricing "
        "policy allows us to log, not a price")


def test_the_strap_is_untouched_because_cutting_really_does_dominate_it():
    """The control, and the reason this is a floor rather than a cap on the rate: where the
    calculator is right it must keep governing."""
    seconds_for_003 = 3600 / 236.0
    assert seconds_for_003 > config.LASER_MIN_SECONDS_PER_PART


def test_the_floor_is_applied_inside_the_templates_own_formula():
    """With MAX(), so the calculator is still visibly doing the work and still tracks any
    change the estimators make to their cutting speeds. Replacing the formula with a number
    would take their calculator off the sheet."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "wb_populate.py"),
               encoding="utf-8").read()
    assert 'E%d*MAX(V%d,%g)' in src
    assert "LASER_MIN_SECONDS_PER_PART" in src


def test_no_floor_configured_leaves_the_formula_exactly_as_it_was():
    """A floor of zero is how this gets switched off without editing the writer."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "wb_populate.py"),
               encoding="utf-8").read()
    assert "if _floor > 0:" in src
    assert '_ts = "+".join("E%d*V%d" % (_r, _r) for _r in _rws)' in src


# ── and Howard's rulings, in the form the live run reads ─────────────────────────────

def test_the_job_answers_file_parses_with_no_complaints():
    """Held in config.JOB_DECISIONS, where a decision arrives with a pull rather than being
    copied to the share by hand. If the engine reports a problem with it, the ruling
    silently did nothing — which is how the tube bend survived two reruns."""
    import estimator_confirmed
    got, problems = estimator_confirmed.decisions_from_config("7332-01")
    out = got.get("estimator_decisions") or {}
    assert problems == [], problems
    assert out["operations_off"]["7332-01-002"] == ["tube_bending"]
    assert out["nesting_groups"]["003 and 004 on one laser program"] == [
        "7332-01-003", "7332-01-004"]
    assert out["throughput_per_hour"]["Laser (Acrylic)"] == 95


def test_a_comment_key_is_not_reported_as_a_decision_that_did_nothing():
    """The example file teaches writing "_why_..." beside a ruling to record why it was
    made. The validator complained about every one — and an estimator reading three
    complaints about their own notes learns to stop writing them, or to distrust the list."""
    import estimator_confirmed
    _out, problems = estimator_confirmed._read_decisions(
        {"estimator_decisions": {"_why_this": "because Howard said so",
                                 "operations_off": {"X-1": ["tubebend"]}}}, "x")
    assert problems == []
    assert _out["operations_off"] == {"X-1": ["tubebend"]}


def test_the_answers_file_carries_no_price():
    """Plating and plater freight are real costs and both are open — and a figure off
    Howard's own sheet is not a price source."""
    import json
    import config
    dec = (config.JOB_DECISIONS["7332-01"].get("estimator_decisions") or {})
    assert "plating_gbp_per_unit" not in dec
    assert "250" not in json.dumps(dec)
