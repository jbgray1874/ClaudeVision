r"""
test_the_argument_about_the_gauge_is_not_thrown_away.py

ARBITRATION PICKS A WINNER AND USED TO DISCARD THE ARGUMENT.

11650-01-05A DOOR is a 6mm polycarbonate panel by its flat pattern --
11650-01-05A_6MM POLYCARB_REVC.DXF, the file the router is actually set from -- and its
detail drawing reads 3. The DXF outranks drawing text, so 6mm won and 6mm is almost
certainly right. Nothing on the sheet, in the reports or in the checks said that something
on the drawing says half that.

Gauge is the most leveraged number on a sheet part. Material scales with it directly and
the cut rate steps with it, so being wrong by a factor of two is being wrong about the part
twice over. The engine's precedence is sound and the figure stands -- what was missing is
that anybody was told there had been an argument at all.

The data was already being kept. source_precedence records every displaced value with the
source that supplied it, for every field, and nothing was reading it for thickness.

TWO WAYS THIS CHECK COULD BE WORSE THAN NOTHING, both guarded below. Firing on every
hairline difference between two readings of the same gauge trains people to ignore it --
that has already happened once here, with an unpriceable-material check that flagged four
priced fixings. And reporting a disagreement that never happened, from a record where
nothing was displaced, is the same fault facing the other way.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import invariants as iv  # noqa: E402


def _part(won, other, *, won_from="dxf_flat_pattern", other_from="drawing_deterministic",
          pn="11650-01-05A"):
    part = {"part_number": pn, "normalized_thickness_mm": won, "thickness_source": won_from}
    if other is not None:
        part["_displaced"] = {"normalized_thickness_mm":
                              [{"value": other, "source": other_from}]}
    return {"part_estimates": [part]}


def _codes(summary):
    return {v["code"] for v in iv.check_two_sources_disagree_about_the_gauge(summary)}


def test_the_door_disagreement_is_reported():
    """6mm from the flat pattern, 3mm from the drawing. Twice the material on a 1202 x 689
    panel, and until now silent."""
    out = iv.check_two_sources_disagree_about_the_gauge(_part(6.0, 3.0))
    assert len(out) == 1
    v = out[0]
    assert v["code"] == "two_sources_disagree_about_the_gauge"
    assert "6.0mm" in v["message"] and "3.0mm" in v["message"]
    assert "dxf_flat_pattern" in v["message"] and "drawing_deterministic" in v["message"], (
        "naming the two gauges without naming who said each is not enough to act on")
    assert v["detail"]["parts"][0]["ratio"] == 2.0


def test_it_does_not_block():
    """The precedence is right and the number stands. Blocking a job over an argument the
    engine resolved correctly would make the blocker list worthless."""
    assert iv.check_two_sources_disagree_about_the_gauge(_part(6.0, 3.0))[0]["severity"] \
        == iv.WARNING


def test_agreement_is_silent():
    assert _codes(_part(2.0, 2.0)) == set()


def test_float_noise_is_not_a_disagreement():
    """Two readings of the same gauge that differ in the last decimal are one reading."""
    assert _codes(_part(1.5, 1.5000001)) == set()
    assert _codes(_part(1.5, 1.53)) == set()


def test_a_difference_too_small_to_move_money_is_not_worth_saying():
    """SHEET COMES IN A DISCRETE LADDER and nothing sits between the rungs, so a 4% gap is
    not two gauges -- it is noise dressed as a finding. A check that fires on those gets
    ignored on the day it is right, which is exactly how the unpriceable-material check
    came to flag four correctly-priced fixings this morning."""
    assert _codes(_part(3.0, 3.1)) == set()
    assert _codes(_part(1.2, 1.5)) == {"two_sources_disagree_about_the_gauge"}


def test_nothing_displaced_is_not_an_argument():
    """A record where one source spoke and nobody contradicted it must not produce a
    finding. An invented disagreement is the same defect facing the other way."""
    assert _codes(_part(6.0, None)) == set()


def test_a_missing_or_unreadable_reading_is_skipped_not_guessed():
    for bad in (None, "", "six", 0, -1):
        assert _codes(_part(6.0, bad)) == set(), bad
    for bad in (None, "", "six", 0):
        assert _codes(_part(bad, 3.0)) == set(), bad


def test_an_unreadable_summary_is_declared_unverified():
    """A check that could not run has proved nothing, and must not be counted as a pass."""
    out = iv.check_two_sources_disagree_about_the_gauge("not a summary")
    assert out and out[0]["severity"] == iv.UNVERIFIED


def test_every_disputed_part_is_counted_even_if_not_every_one_is_named():
    """The message lists the first few; the COUNT has to be all of them, or a pack with
    twenty arguments reads as a pack with six."""
    parts = [{"part_number": f"P{i}", "normalized_thickness_mm": 6.0,
              "thickness_source": "dxf_flat_pattern",
              "_displaced": {"normalized_thickness_mm": [{"value": 3.0, "source": "llm"}]}}
             for i in range(9)]
    v = iv.check_two_sources_disagree_about_the_gauge({"part_estimates": parts})[0]
    assert "9 part(s)" in v["message"]
    assert len(v["detail"]["parts"]) == 9


def test_the_check_is_actually_run():
    """THE REGISTRY, NOT THE FUNCTION. A check that nothing calls is indistinguishable from
    a check that always passes, and this codebase has shipped that more than once."""
    assert iv.check_two_sources_disagree_about_the_gauge in iv.CHECKS
