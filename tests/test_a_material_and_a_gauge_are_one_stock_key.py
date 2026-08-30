"""You cannot buy PETG at 2.2mm, because nobody said PETG at 2.2mm.

11650-04'S SIDE PANELS ARE READ THREE WAYS. A SolidWorks model says ABS at 2.2mm. The title
block on the issued sheet says PETG. Six DXF exports across five revisions are named
`11650-04-01A_2MM PETG_REVG.DXF`, and that is the file the laser cuts from.

PROMOTING THE FILENAME FIXED HALF OF IT AND MADE THE JOB WORSE. With the export ranked as a
real observation, two independent readings outvote the model on MATERIAL — correctly, and that
is what the corroboration quorum is for. The GAUGE stayed at 2.2 on the model's authority,
because only one source had named 2.0 and a quorum needs two.

The engine then held PETG at 2.2mm. Nothing said that. The model said ABS at 2.2, the export
said PETG at 2.0, and one half was taken from each. `_plain_stock_rates_gbp_per_m2` matches the
gauge exactly — as it must, since 2.0 and 3.0 are different purchases — so a catalogue holding
37 rows of 2mm PETG returned nothing, and the panels priced at zero. Each field was defensible
on its own and the pair was a purchase order nobody could place. That is why the first attempt
at this was reverted.

THE RULE, AND IT IS NOT ABOUT SHEET. A source overruled on one half of a joint fact does not
keep its authority over the other half by default: both came from ONE reading, and that reading
has been set aside. Where the sources that won also named the companion, theirs goes with it,
because it is the reading that survived intact.

NOT A LICENCE TO MIX THE OTHER WAY. A source that never spoke about the companion has lost no
argument about it. A title block naming a material and no gauge leaves the model's gauge
exactly where it was.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import source_precedence as sp  # noqa: E402

MATERIAL = "normalized_material"
GAUGE = "normalized_thickness_mm"


def _panel(*, filename_gauge=2.0, filename_material="PETG", model_gauge=2.2,
           model_material="ABS", title_block="PETG"):
    """11650-04-01A as the pipeline actually assembles it: the model first, then the printed
    sheet, then the export the shop cuts from."""
    p = {}
    if model_material:
        sp.apply_field(p, MATERIAL, model_material, "solidworks_api")
    if model_gauge:
        sp.apply_field(p, GAUGE, model_gauge, "solidworks_api")
    if title_block:
        sp.apply_field(p, MATERIAL, title_block, "drawing_deterministic")
    if filename_material:
        sp.apply_field(p, MATERIAL, filename_material, "dxf_filename")
    if filename_gauge:
        sp.apply_field(p, GAUGE, filename_gauge, "dxf_filename")
    return p


def _key(p):
    return (p.get(MATERIAL), p.get(GAUGE))


# ── the defect, stated as the test ───────────────────────────────────────────────────

def test_the_pair_the_engine_lands_on_is_one_a_source_actually_asserted():
    """THE WHOLE POINT. Before settling, the record holds PETG at 2.2 — a stock key assembled
    from two readings that contradicted each other, and one no supplier lists."""
    p = _panel()
    assert _key(p) == ("PETG", 2.2), "the defect no longer reproduces; this test is blind"
    sp.settle_companion_facts(p)
    assert _key(p) == ("PETG", 2.0)


def test_both_halves_end_up_from_the_same_reading():
    """Not merely a pair that happens to be stocked — a pair somebody actually wrote down.
    Choosing 2.0 because the catalogue has 2.0 would be fitting the evidence to the price."""
    p = _panel()
    sp.settle_companion_facts(p)
    assert sp.source_of(p, MATERIAL) == sp.source_of(p, GAUGE) == "dxf_filename"


def test_the_gauge_that_was_set_aside_is_still_on_the_record():
    """It was a real reading by the strongest source present. Overruled is not deleted — the
    estimator has to be able to see that the model said 2.2 and why it did not win."""
    p = _panel()
    sp.settle_companion_facts(p)
    said = {(str(e["source"]), str(e["value"])) for e in sp.displaced_values(p, GAUGE)}
    assert ("solidworks_api", "2.2") in said


def test_the_move_says_why_in_words_an_estimator_can_check():
    p = _panel()
    sp.settle_companion_facts(p)
    flag = [f for f in p.get("review_flags", []) if "stock key" in f]
    assert flag, "the pair was changed and nothing on the part says so"
    assert "solidworks_api" in flag[0] and "dxf_filename" in flag[0]


def test_what_moved_is_reported_to_the_caller():
    assert sp.settle_companion_facts(_panel()) == [GAUGE]


# ── what it must NOT do ──────────────────────────────────────────────────────────────

def test_a_source_that_never_named_a_gauge_does_not_take_the_models_gauge_away():
    """THE OTHER HALF OF THE RULE. Here the material is outvoted by two readings that say
    nothing about thickness. The model lost an argument it was in; it did not lose one it was
    never in, so its gauge stands."""
    p = _panel(filename_gauge=None, filename_material=None)
    sp.apply_field(p, MATERIAL, "PETG", "llm_extract")
    assert _key(p) == ("PETG", 2.2)
    sp.settle_companion_facts(p)
    assert _key(p) == ("PETG", 2.2)


def test_a_gauge_held_by_a_source_that_lost_nothing_is_not_touched():
    """THE GUARD THAT MATTERS, AND MY FIRST TEST OF IT WAS BLIND. It used a winner that named
    no gauge, so nothing moved for want of a candidate rather than for the reason under test —
    a mutant that deleted the check passed it.

    Here a MEASURED dxf holds the gauge at 2.5 and was never in the material argument, while
    the export that won the material says 2.0. Measured geometry outranks a filename and did
    not lose anything, so its gauge stands. Only a reading that was overruled gives up what it
    carried alongside."""
    p = {}
    sp.apply_field(p, MATERIAL, "ABS", "solidworks_api")
    sp.apply_field(p, GAUGE, 2.5, "dxf")
    sp.apply_field(p, MATERIAL, "PETG", "drawing_deterministic")
    sp.apply_field(p, MATERIAL, "PETG", "dxf_filename")
    sp.apply_field(p, GAUGE, 2.0, "dxf_filename")
    assert p[MATERIAL] == "PETG", "the material quorum did not fire; this test is blind"
    assert sp.settle_companion_facts(p) == []
    assert _key(p) == ("PETG", 2.5)
    assert sp.source_of(p, GAUGE) == "dxf"


def test_agreement_is_not_a_replacement():
    """The overruled model and the winning export say the SAME gauge. Nothing has to move, and
    a flag reading "'2.0' replaced by '2.0'" would appear on every part where a model and an
    export agree on thickness and disagree on material — which is the common case, not the
    rare one."""
    p = _panel(model_gauge=2.0)
    assert p[MATERIAL] == "PETG"
    assert sp.settle_companion_facts(p) == []
    assert _key(p) == ("PETG", 2.0)
    assert not [f for f in p.get("review_flags", []) if "stock key" in f], (
        "a replacement was reported where nothing was replaced"
    )


def test_a_gauge_nobody_argued_about_is_left_alone():
    """No corroboration fired at all — the ordinary case, and by far the commonest. This must
    be a no-op on the overwhelming majority of parts or it is a new source of drift."""
    p = {}
    sp.apply_field(p, MATERIAL, "PETG", "solidworks_api")
    sp.apply_field(p, GAUGE, 2.0, "solidworks_api")
    assert sp.settle_companion_facts(p) == []
    assert _key(p) == ("PETG", 2.0)


def test_the_material_the_quorum_chose_is_not_disturbed():
    """Settling the companion must not re-open the decision that triggered it."""
    p = _panel()
    sp.settle_companion_facts(p)
    assert p[MATERIAL] == "PETG"
    assert sp.source_of(p, MATERIAL) == "dxf_filename"


def test_settling_twice_changes_nothing_the_second_time():
    """It runs per part on a pipeline that reworks records. A rule that moved the gauge again
    on a second pass would walk it down the list of readings."""
    p = _panel()
    sp.settle_companion_facts(p)
    before = (_key(p), len(p.get("review_flags", [])))
    assert sp.settle_companion_facts(p) == []
    assert (_key(p), len(p.get("review_flags", []))) == before


def test_a_winner_that_named_no_gauge_leaves_the_half_rejected_one_and_says_so():
    """Nothing to put in its place is not a reason to pretend. The model's 2.2 stays, and the
    record states that it rests on a reading that was set aside — a question for a person, not
    a number to invent."""
    p = {}
    sp.apply_field(p, MATERIAL, "ABS", "solidworks_api")
    sp.apply_field(p, GAUGE, 2.2, "solidworks_api")
    sp.apply_field(p, MATERIAL, "PETG", "drawing_deterministic")
    sp.apply_field(p, MATERIAL, "PETG", "llm_extract")
    assert sp.settle_companion_facts(p) == []
    assert p[GAUGE] == 2.2
    assert any("was set aside" in f for f in p.get("review_flags", [])), (
        "a gauge left standing on an overruled reading is reported as a clean answer")


# ── the export is an observation at all, which is what makes the quorum possible ─────

def test_the_export_the_shop_cuts_from_is_ranked_with_the_drawing_not_below_it():
    assert sp.rank("dxf_filename") == sp.rank("title_block") == 70


def test_the_printed_sheet_still_beats_the_filename_on_a_straight_tie():
    """Same rank, so the tiebreak decides: a field printed on the sheet that was ISSUED beats
    a name on a file."""
    assert sp.tiebreak_priority("title_block") > sp.tiebreak_priority("dxf_filename")


def test_a_filename_alone_still_loses_to_the_model():
    """The quorum is what changes the answer, not the promotion. One export against a model is
    still one reading against a stronger one."""
    p = {}
    sp.apply_field(p, MATERIAL, "ABS", "solidworks_api")
    sp.apply_field(p, MATERIAL, "PETG", "dxf_filename")
    assert p[MATERIAL] == "ABS"


# ── wired, not merely built ──────────────────────────────────────────────────────────

def test_the_costing_pass_actually_settles_the_pair():
    """BUILT IS NOT WIRED is a defect family this codebase keeps finding. The rule is worth
    nothing unless the pass that spends the pair runs it."""
    import estimator
    p = _panel()
    p.update({"part_number": "11650-04-01A", "quantity": 1,
              "blank_length_mm": 1250.0, "blank_width_mm": 525.0,
              "material_estimate": {}, "manufacturing_interpretation": {}})
    estimator.estimate_part(p)
    assert _key(p) == ("PETG", 2.0), "estimate_part did not settle the stock key"
