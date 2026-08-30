"""A single part costed on one material while a source read another — the twin of the gauge check.

The gauge disagreement was surfaced; its material twin was a registered code with no producer,
so a part costed as ABS while the drawing said PETG passed silently. Material is the more
expensive of the two — it sets the sheet rate AND whether the part has a rate at all — so a part
on the wrong material can go from a real figure to zero. This surfaces the argument without
changing the figure: the higher-ranked source still stands, but a person is told to confirm.

Handed pairs are NOT this: a pair is settled across two records with its own rules, so a part
carrying a handed settlement is skipped rather than reported twice.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import invariants  # noqa: E402
import source_precedence as sp  # noqa: E402
import engine_discoveries  # noqa: E402
import estimating_review  # noqa: E402

MAT = "normalized_material"


def _part(pn, readings):
    p = {"part_number": pn}
    for value, source in readings:
        sp.apply_field(p, MAT, value, source)
    return p


def _run(*parts):
    return invariants.check_two_sources_disagree_about_the_material({"parts": list(parts)})


# ── the disagreement it now names ────────────────────────────────────────────────────

def test_a_part_costed_one_material_while_a_source_read_another_is_flagged():
    """Model ABS (rank 90) wins over a title-block PETG (rank 70); the argument is surfaced with
    both readings so nobody costs ABS at a price PETG would never carry without being told."""
    part = _part("D1", [("ABS", "solidworks_api"), ("PETG", "drawing_deterministic")])
    assert part[MAT] == "ABS", "fixture wrong: the model should win on rank"
    vios = _run(part)
    assert len(vios) == 1
    v = vios[0]
    assert v["code"] == "two_sources_disagree_about_the_material"
    assert v["severity"] == invariants.WARNING
    assert "ABS" in v["message"] and "PETG" in v["message"]


def test_the_figure_still_stands_it_is_only_surfaced():
    """Not blocking — the invariant reports, it does not re-cost. The winning material is
    untouched."""
    part = _part("D2", [("ABS", "solidworks_api"), ("PETG", "drawing_deterministic")])
    _run(part)
    assert part[MAT] == "ABS"


def test_a_part_with_one_reading_is_not_a_disagreement():
    part = _part("D3", [("PETG", "solidworks_api")])
    assert _run(part) == []


def test_two_readings_that_agree_are_not_a_disagreement():
    """The same material from two sources is corroboration, not conflict."""
    part = _part("D4", [("PETG", "solidworks_api"), ("PETG", "drawing_deterministic")])
    assert _run(part) == []


def test_a_spelling_variant_of_one_material_is_not_a_disagreement():
    """8352 REGRESSION. The winner is stored in the engine's normalised code form 'MILD_STEEL';
    the drawing reading is the raw 'MILD STEEL'. _same_value does not collapse underscore vs
    space, so the check said 'costed as MILD_STEEL ... says MILD_STEEL' on six parts of the bag
    stand. Canonicalised through the pricing lexicon they are one material, and nothing is
    reported."""
    # The precondition that made the old check fire: these two are 'different' to _same_value.
    assert sp._same_value("MILD_STEEL", "MILD STEEL") is False
    part = {"part_number": "D4B", "normalized_material": "MILD_STEEL",
            "material_source": "solidworks_api"}
    sp._observe(part, MAT, "MILD STEEL", "drawing_deterministic", applied=False)
    assert _run(part) == [], "a spelling variant of one material was reported as a conflict"


def test_a_genuinely_different_material_still_reports_through_the_canonicaliser():
    """The fix must not silence real disagreements: MDF against TIMBER is two materials."""
    part = {"part_number": "D4C"}
    sp.apply_field(part, MAT, "MDF", "solidworks_api")
    sp._observe(part, MAT, "TIMBER", "inference", applied=False)
    vios = _run(part)
    assert len(vios) == 1 and "MDF" in vios[0]["message"] and "TIMBER" in vios[0]["message"]


# ── what it deliberately leaves to the handed-pair rules ──────────────────────────────

def test_a_handed_settled_part_is_not_reported_twice():
    """A handed pair settled on the cut file already carries its own proviso. Reporting the same
    material argument here as well would double-count it under two codes."""
    part = _part("D5-HANDED", [("PETG", "dxf_filename"), ("ABS", "solidworks_api")])
    part["_handed_settled"] = {"stock_key": {"value": ["PETG", 2.0], "displaced": ["ABS", 2.2],
                                             "basis": "cut_file"}}
    assert _run(part) == []


# ── classification and wiring ────────────────────────────────────────────────────────

def test_it_is_a_drawing_problem_in_the_confirm_bucket():
    # NOT the engine's — which is what this test is for — and specifically the estimator's:
    # two readings the evidence cannot separate, settled by whoever has the drawing open.
    assert engine_discoveries.classify("two_sources_disagree_about_the_material") != "engine"
    assert engine_discoveries.classify("two_sources_disagree_about_the_material") == "estimator"
    line = estimating_review._line({"code": "two_sources_disagree_about_the_material",
                                    "severity": "warning", "message": "x"})
    assert line["bucket"] == estimating_review.CONFIRM


def test_the_check_is_registered_and_runs_on_every_job():
    assert invariants.check_two_sources_disagree_about_the_material in invariants.CHECKS


def test_an_unreadable_summary_verifies_nothing_rather_than_passing():
    out = invariants.check_two_sources_disagree_about_the_material(None)
    assert out and out[0]["severity"] == invariants.UNVERIFIED


def test_a_part_with_no_winning_material_is_not_reported():
    """A part that never resolved a material of its own has nothing to be costed on, so a
    dissenting reading against nothing is not an argument to raise here."""
    part = {"part_number": "D8"}
    # A displaced reading with no winner: nothing is currently held, so there is no 'costed as'.
    sp._observe(part, MAT, "PETG", "drawing_deterministic", applied=False)
    assert _run(part) == []


def test_several_disputed_parts_are_summarised_in_one_violation():
    a = _part("D6", [("ABS", "solidworks_api"), ("PETG", "drawing_deterministic")])
    b = _part("D7", [("MDF", "solidworks_api"), ("ACRYLIC", "dxf_filename")])
    vios = _run(a, b)
    assert len(vios) == 1
    assert "2 part(s)" in vios[0]["message"]
    assert len(vios[0]["detail"]["parts"]) == 2
