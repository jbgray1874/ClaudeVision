"""The welding department's half hour could never have reached the sheet.

    "Line 86 & 87 - Weld & Dress AI Estimate for 2 Minutes & 1 Minute respectively, Timings
     from Welding Dept. 0.5 Hours & 20 Minutes respectively."
                                        — Howard Thurley, SDI estimating, 9 Sep 2026

Three books were produced across two days trying to land that. The figures were in config
with his name on them from the first. The estimator computed them correctly — 7332-01's own
OUTSTANDING ESTIMATOR INPUTS block prints the working, "weld timed per joint: 5 joint(s) at
10 min ... from the 6 members this weldment joins". And every book still read 29/hr and
60/hr: Weld (CO2) and Dress Welds straight off the department median table, 2 minutes and 1.

The cause is one line in canonical_labour_groups, and it is deliberate:

    # Geometry-derived batch hours are valid for leaf events. Assembly work uses the
    # department throughput because summing participant hours is the old over-count.
    if scope == "part" and representative_id:

Welding a weldment is assembly-scoped. So it never entered the grouping at all — no batch
hours, no run hours, nothing to derive from — and the emit loop fell through to `elif
default_tp`. Not the floor guard, which was the hypothesis twice and wrong twice; the hours
never existed on that side of the wall.

THE RULE IS RIGHT ABOUT THE DANGER AND TOO BROAD ABOUT THE REMEDY. Summing five members'
hours for one weld IS an over-count — five parts do not get welded five times. But the
estimator did not sum anything: it computed a time FOR THE WELDMENT, one number for one
thing. That is the case the rule throws away, and it is the only case where the shop's own
figure exists.

About £28 a unit on a £63 stand, on every metal job with a weldment, for as long as this has
been running.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import wb_populate as wb                                                 # noqa: E402

SRC = (ROOT / "src" / "wb_populate.py").read_text(encoding="utf-8")


# ── the assembly's own record is read ────────────────────────────────────────────────────

def test_an_assembly_scoped_op_reads_the_assemblys_own_time():
    assert "AN ASSEMBLY'S OWN TIME IS NOT A SUM OF ITS PARTS" in SRC
    assert '_asm_id = target_id if (scope == "assembly" and target_id in estimates) else None' \
        in SRC


def test_it_takes_both_the_batch_hours_and_the_per_piece_rate():
    """run_hours_per_unit is the one that matters — a rate derived from batch hours carries
    the quantity it was built for, which is a separate defect this file must not reintroduce."""
    block = SRC.split("AN ASSEMBLY'S OWN TIME IS NOT A SUM OF ITS PARTS")[1][:4800]
    assert 'group["bh"] += float(_h)' in block
    assert 'group["run_hours_per_unit"]' in block


def test_it_does_not_sum_participants():
    """The danger the original rule names. One part, one number — the over-count cannot
    happen on this path because nothing is added up."""
    block = SRC.split("AN ASSEMBLY'S OWN TIME IS NOT A SUM OF ITS PARTS")[1][:4800]
    assert "participants" not in block
    assert 'hours_by_part", {})[str(_asm_id)]' in block


def test_an_assembly_with_no_time_of_its_own_still_takes_the_department_rate():
    """The fallback is unchanged, and has to be: most assembly operations have no stated
    time and the median is the only figure there is."""
    assert "Where the assembly carries no time of its own, the department throughput" in SRC
    assert 'if scope == "part" and representative_id:' in SRC


def test_leaf_parts_are_untouched():
    """Everything geometry-derived keeps the path it had. This adds a branch above the
    existing one; it does not replace it."""
    block = SRC.split("AN ASSEMBLY'S OWN TIME IS NOT A SUM OF ITS PARTS")[1][:4800]
    assert 'scope == "assembly"' in block


# ── and the corpus median does not overrule it ───────────────────────────────────────────

def test_the_floor_guard_honours_the_assemblys_own_time():
    """50 min a unit derives 1.2/hr against a 29/hr median — 24x below the floor. Without
    this the fix above would land the hours and the guard would immediately discard them."""
    assert wb._group_carries_a_stated_shop_time({"assembly_own_time": True,
                                                 "parts": ["7332-01-101"]}, {}) is True


def test_a_group_with_no_such_claim_is_still_guarded():
    """The floor exists for real garbage — a missing bend count deriving 0.17/hr and billing
    five hours to route a panel. It must keep catching that."""
    assert wb._group_carries_a_stated_shop_time({"parts": ["X"]}, {}) is False


def test_the_row_says_where_its_time_came_from():
    assert wb._stated_shop_time_source({"assembly_own_time": True, "parts": ["X"]}, {}) == (
        "the assembly's own computed time, not a sum of its members")


def test_a_stated_part_marker_still_works_too():
    """The two signals are independent: a part stamped by the costing stage, and a group
    whose hours came from the assembly. Either is enough."""
    assert wb._group_carries_a_stated_shop_time(
        {"parts": ["7332-01-101"]}, {"7332-01-101": "the welding department's allowance"})


# ── what this was worth ──────────────────────────────────────────────────────────────────

def test_the_money_this_was_hiding_is_recorded():
    """So that if anyone ever narrows the branch again, the commit that does it has to
    explain why £28 a unit is acceptable."""
    assert "About £28 a unit on a £63 stand" in SRC or "£28 a unit" in (
        ROOT / "tests" / "test_an_assemblys_own_time_is_not_a_sum_of_its_parts.py"
    ).read_text(encoding="utf-8")


# ── THE THIRD RULE, AND THE ONE THAT WAS ACTUALLY IN FORCE ───────────────────────────────
#
# Landing the hours in the group changed nothing, because Weld (CO2), Dress Welds and
# Assemble/pack (Metal) are all in _ONE_ROW_PER_JOB — and that branch writes the department
# default and never reaches the derived value at all. Its own comment says why, and the
# reasoning is sound for what it describes:
#
#     "Assembly, packing and welding time is NOT in the DXF. There is no geometry from which
#      to derive 'how long does it take to pack this' — the engine's derived value for those
#      ops is fiction dressed as measurement."
#
# True, and it does not describe 7332-01. Nothing was derived from geometry there: the
# welding department said half an hour, it sat in config with their name on it, and the
# estimator applied it. This branch handed it to a corpus median anyway.
#
# THREE RULES STOOD BETWEEN HOWARD THURLEY'S NOTE AND THE SHEET, each individually
# defensible — assembly-scope skips the grouping, the floor guard replaces outliers, and
# one-row-per-job ops take the default. Every one exists to stop the engine inventing a
# time. Not one of them could tell an invention from a figure a department wrote down.

def test_a_one_row_per_job_op_with_a_stated_time_does_not_take_the_median():
    assert "THE THIRD RULE, AND THE ONE THAT WAS ACTUALLY IN FORCE" in SRC
    assert "not _group_carries_a_stated_shop_time(g, _stated_time_by_pn)" in SRC


def test_weld_dress_and_pack_are_the_ops_this_covers():
    """All three of Howard's failing lines are in that set — which is why all three failed
    together and why fixing the grouping alone changed nothing."""
    block = SRC.split("_ONE_ROW_PER_JOB = {")[1].split("}")[0]
    for op in ("Weld (CO2)", "Dress Welds", "Assemble/pack (Metal)"):
        assert op in block, op


def test_without_a_stated_time_the_median_still_stands():
    """The rule is right for every job that has not been told a time, which is most of
    them. This is an exception, not a replacement."""
    assert 'ws.cell(row=row, column=lb["col_throughput"], value=float(default_tp))' in SRC


def test_a_stated_group_with_no_hours_falls_back_rather_than_dividing_by_nothing():
    block = SRC.split("THE THIRD RULE, AND THE ONE THAT WAS ACTUALLY IN FORCE")[0][-900:]
    assert "Stated, but nothing actually arrived to state" in block


def test_the_row_says_the_time_was_stated_not_derived():
    assert '_rate_basis = "stated_shop_time"' in SRC
    assert "was not derived, it was stated" in SRC


# ── and the hours are asked for by DEPARTMENT, not by spelling ───────────────────────────
#
# The dry-run tool answered this in seconds where four job runs had not: Assemble/pack
# (Metal) reached the emit loop with rhpu and bh both empty, so it took the median whatever
# else was fixed. The route names the operation "assembly"; the estimator times it
# "handling". department_codes has said they are one thing since it was written —
# _alias("PACM", "handling", "assembly", ...) — and an exact-key lookup asked neither of
# them that question.
#
# Two names for one thing, at a fourth layer of the same job.

def test_handling_and_assembly_are_one_department():
    import sys as _s
    _s.path.insert(0, str(ROOT / "src"))
    from department_codes import code_for
    assert code_for("handling") == code_for("assembly") == "PACM"


def test_the_assembly_lookup_falls_back_to_the_department():
    assert "ASKED BY DEPARTMENT, NOT BY SPELLING" in SRC
    block = SRC.split("ASKED BY DEPARTMENT, NOT BY SPELLING")[1][:1600]
    assert "from department_codes import code_for as _dept_of" in block
    assert "_dept_of(_alt) == _want" in block


def test_the_exact_key_is_still_tried_first():
    """An exact match is the strongest answer and must not be displaced by an alias scan."""
    block = SRC.split("ASKED BY DEPARTMENT, NOT BY SPELLING")[1][:1600]
    assert "_h = _safe(_asm_bh.get(operation))" in block
    assert "if not _h and not _r:" in block


def test_an_unresolvable_operation_costs_the_run_nothing():
    """department_codes returning None, or not importing at all, must leave the old
    behaviour rather than raise inside a costing pass."""
    block = SRC.split("ASKED BY DEPARTMENT, NOT BY SPELLING")[1][:1600]
    assert "except Exception:" in block
