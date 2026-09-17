r"""A time the shop stated cannot be averaged into a department it shares.

James, from the 7332-01 six-off book, with the cells:

    Estimate!I105 is 79/hr        brushing. Should be 1.5/hr - 40 min a unit.
    Estimate!I109 is 15/hr        pack to plater. 4 min a unit. CORRECT.
    Estimate!I110 is 30/hr        final pack. 2 min a unit, where the shop stated 8.

THE NUMBERS NAME THE FAULT EXACTLY.

79/hr is the corpus default for "Manual labour (Metal)" - 23 lines of history. 30/hr is 2
minutes a unit, against a stated 8. So one stated time was replaced by a median and the
other by something that is not the stated figure, while the third - the only one with an
operation of its own - came through untouched at 15/hr.

(WHAT produced the 2 minutes is not claimed here. The department's generic allowance is
0.8 min, not 2, so the obvious answer is the wrong one; it is a banded or derived figure,
and without the run's own record naming it, picking would be a guess wearing a fact's
clothes. It does not change the fix: 2 is not 8 either way.)

That is the whole story. THE WORKBOOK EMITS ONE ROW PER DEPARTMENT, and both failing rules
were writing under a DEPARTMENT's name rather than their own:

    brushing        wrote `manual_labour_metal`, shared with deburr, bench work and
                    insert labour, so 40 minutes was pooled with all of it
    final pack      wrote `handling`, which every other part on the job also writes, so
                    8 minutes was pooled with everybody else's 2

Five branches in the emit loop can each discard a computed time, and four have been caught
doing it one run apiece. This is not a fifth branch. It is the layer above: a stated time
that shares a key with a department median has already lost before the emit loop sees it.

So each stated rule gets its own operation, its own workbook row and its own rate line -
which is what `plater_pack` already had, and precisely why it was the one that worked.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import config            # noqa: E402
import wb_populate       # noqa: E402
from department_codes import code_for  # noqa: E402


def _throughput_per_hour(minutes_per_unit: float) -> float:
    """What the sheet's rate column holds: pieces an hour, from minutes a piece.

    The emit loop computes qty / stated_hours; at one piece a unit that is 60/minutes.
    """
    return round(60.0 / minutes_per_unit, 4)


# ── the three rates James read off the book ──────────────────────────────────────────

def test_brushing_makes_the_rate_he_expects_and_not_the_corpus_median():
    minutes = config.BRUSH_BEFORE_PLATE["minutes_per_unit"]
    assert minutes == 40.0
    assert _throughput_per_hour(minutes) == 1.5, "40 minutes a unit is 1.5 an hour"
    assert _throughput_per_hour(minutes) != 79.0, (
        "79/hr is the corpus median for Manual labour (Metal) — 23 lines of history — and "
        "it is what the book carried in place of Howard's stated figure")


def test_the_two_pack_stages_make_their_stated_rates():
    pl = config.PLATING_LOGISTICS
    assert _throughput_per_hour(pl["pack_for_plater_min"]) == 15.0, "4 min a unit"
    assert _throughput_per_hour(pl["final_pack_min"]) == 7.5, "8 min a unit"


def test_the_final_pack_rate_on_the_book_was_not_the_stated_time():
    """The book carried 30/hr on that row, which is 2 minutes a unit. The shop stated 8.

    WHAT PRODUCED THE 2 IS NOT ASSERTED HERE, deliberately: it is either the department's
    generic allowance after banding or a size-banded rate, and without the run's own record
    naming one, picking is a guess. What IS certain is that 2 minutes is not 8, and that a
    row carrying the stated figure reads 7.5/hr."""
    assert _throughput_per_hour(2.0) == 30.0, "30/hr on the book IS 2 minutes a unit"
    assert config.PLATING_LOGISTICS["final_pack_min"] == 8.0
    assert _throughput_per_hour(config.PLATING_LOGISTICS["final_pack_min"]) == 7.5
    assert config.PLATING_LOGISTICS["final_pack_min"] != \
        config.LABOUR_RULES["handling"]["min_per_part"]


# ── each stated rule owns a key, a row and a rate ────────────────────────────────────

_STATED_OPS = ("brush_before_plate", "plater_pack", "plater_final_pack")


def test_every_stated_rule_has_an_operation_of_its_own():
    """The one that worked had one; the two that failed did not. That IS the difference."""
    assert config.BRUSH_BEFORE_PLATE["operation"] == "brush_before_plate"
    assert config.BRUSH_BEFORE_PLATE["operation"] not in ("manual_labour_metal", "handling")


def test_none_of_them_shares_its_key_with_a_department_wide_operation():
    """A key that other work also writes is a key whose row is an average."""
    shared = {"manual_labour_metal", "handling", "assembly", "bench_work", "deburr"}
    assert not (set(_STATED_OPS) & shared)


def test_each_one_reaches_a_workbook_row():
    """No entry in the name map means the row resolves through a last-resort lookup built
    for a model's free English, or does not resolve at all."""
    for op in _STATED_OPS:
        assert wb_populate.OP_NAME_MAP.get(op), f"{op} has no workbook row name"


def test_each_one_lands_on_the_bench_that_does_the_work():
    assert code_for("brush_before_plate") == "MANM"
    assert code_for("plater_pack") == "PACM"
    assert code_for("plater_final_pack") == "PACM"


def test_each_one_has_an_hourly_rate_because_an_op_without_one_is_dropped_silently():
    """estimate_part skips any operation whose rate lookup misses — no hours are written at
    all, and the sheet then derives from nothing. A new operation key without a rate is a
    silent deletion, which is how the tube-bender once worked for free."""
    for op in _STATED_OPS:
        rate = config.HOURLY_RATES_GBP.get(op)
        assert rate and rate > 0, f"{op} has no hourly rate and would vanish"
    assert config.HOURLY_RATES_GBP["brush_before_plate"] == \
        config.HOURLY_RATES_GBP["manual_labour_metal"], "same bench, same rate"
    assert config.HOURLY_RATES_GBP["plater_final_pack"] == \
        config.HOURLY_RATES_GBP["plater_pack"], "same bench, same rate"


def test_the_claim_still_vouches_for_the_operations_after_the_rename():
    """The stated-time markers name the operations they cover. Rename an operation without
    updating its marker and the claim stops matching — the time is computed correctly and
    then read as a median anyway, which is the failure this whole file is about."""
    covered = {}
    for marker, ops, _why in wb_populate._STATED_SHOP_TIME_MARKERS:
        covered[marker] = set(ops)
    assert "brush_before_plate" in covered["brush_before_plate_applied"]
    assert "plater_final_pack" in covered["plater_pack_applied"]
    assert "plater_pack" in covered["plater_pack_applied"]


def test_the_old_names_stay_covered_so_an_earlier_book_still_reads_right():
    """A book produced before the split still has its pack time under `handling`. Dropping
    the old name would make re-opening one read its stated time as a department median."""
    covered = dict((m, set(o)) for m, o, _ in wb_populate._STATED_SHOP_TIME_MARKERS)
    assert "handling" in covered["plater_pack_applied"]
    assert "manual_labour_metal" in covered["brush_before_plate_applied"]


# ── and the plated part is not packed three times ────────────────────────────────────

def test_a_plated_part_drops_its_generic_handling_when_it_takes_the_two_stated_packs():
    """Howard's two occasions ARE the handling on a plated part. Leaving the generic
    allowance beside them would charge a third pack nobody does."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "src" / "estimator.py"
           ).read_text(encoding="utf-8")
    start = src.index('run_times_min["plater_final_pack"]')
    block = src[start:start + 400]
    assert 'run_times_min.pop("handling", None)' in block
    assert 'setup_times_min.pop("handling", None)' in block
