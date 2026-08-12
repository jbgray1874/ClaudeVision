r"""
test_a_price_the_engine_declined_is_not_charged.py

TWO COMPONENTS DISAGREED ABOUT ONE FACT AND THE SHEET FOLLOWED THE WRONG ONE.

11650's workbook charged GBP 20.24 for 11650-05-02M SLIDER -- 38% of the whole material
total. The same run's invariants said, in the same console:

    BLOCKING  bom_names_a_drawing_the_pack_does_not_contain: 11650-05-02M (SLIDER).
              Nothing read those parts, so nothing costed them

Both cannot be true. tools/diagnose/why_this_price.py settled it: the part carries
page_roles ['assembly'] -- seen only on an assembly page, never on a detail drawing, because
its detail drawing is not in the pack -- and its system_cost stamp reads

    source  historical_quote_material_line     reached the total  False

estimator writes  applied_to_total = bought_in_candidate and system_unit_cost is not None.
A price is present, so system_unit_cost is not None, so bought_in_candidate was FALSE: the
engine found a figure and DELIBERATELY declined to apply it, because the part is not a
bought-in. price_provenance.stamp_affects_total documents precisely this case -- "a bought-in
unit cost can be resolved and then not added, because the part was costed as a fabrication
instead."

Nothing asked. _bom_line_price read unit_cost_gbp straight off the part record, so the
refusal was recorded, carried through the whole job, printed by the diagnostic -- and
ignored by the one component that decides what the customer is charged. Built is not wired,
with GBP 20.24 riding on it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wb_populate import _bom_line_price  # noqa: E402


def _part(*, applied_to_total, unit_cost_gbp=9.73, **extra):
    """A BOM-bound part whose whole-part price came from the system-cost lookup."""
    pe = {
        "part_number": "11650-05-02M", "description": "SLIDER", "quantity": 2,
        "unit_cost_gbp": unit_cost_gbp,
        "cost_breakdown": {"system_cost": {
            "unit_cost_gbp": unit_cost_gbp,
            "source": {"schema": "price_source.v1",
                       "source": "historical_quote_material_line", "applied": True},
        }},
    }
    if applied_to_total is not None:
        pe["cost_breakdown"]["system_cost"]["applied_to_total"] = applied_to_total
    pe.update(extra)
    return pe


def test_a_declined_price_does_not_reach_the_bom_line():
    """The exact 11650 record. GBP 9.73 x 2 = GBP 20.24 that should never have been on it."""
    assert _bom_line_price(_part(applied_to_total=False)) is None, (
        "the engine resolved this price and recorded that it did NOT apply it. Charging it "
        "anyway makes the sheet contradict the job record it was built from.")


def test_a_bought_in_the_engine_did_apply_is_still_charged():
    """The fix must not zero real money. A genuine bought-in has bought_in_candidate True and
    a resolved cost, so applied_to_total is True and nothing changes for it."""
    assert _bom_line_price(_part(applied_to_total=True)) == 9.73


def test_a_record_with_no_opinion_is_charged_as_before():
    """Only an EXPLICIT False refuses. Documents written before the flag existed carry no
    opinion, and reading a missing flag as a refusal would zero every bought-in on every
    older job -- turning one over-charge into a fleet of under-charges."""
    assert _bom_line_price(_part(applied_to_total=None)) == 9.73


def test_the_refusal_only_covers_the_price_it_was_written_about():
    """applied_to_total is a verdict on the SYSTEM COST figure. A part whose whole-part price
    came from somewhere else is not silenced by it, or one declined lookup would suppress an
    unrelated price that nobody objected to."""
    pe = _part(applied_to_total=False, unit_cost_gbp=4.10)
    pe["cost_breakdown"]["system_cost"]["unit_cost_gbp"] = 9.73   # the declined one
    assert _bom_line_price(pe) == 4.10


def test_a_declined_price_falls_through_to_a_material_figure():
    """Refusing the whole-part number must not skip the rest of the waterfall. A part with a
    real material cost of its own keeps it."""
    pe = _part(applied_to_total=False)
    pe["material_estimate"] = {"unit_material_cost_gbp": 1.25}
    assert _bom_line_price(pe) == 1.25


def test_an_assembly_is_still_priced_by_its_children():
    """Unchanged, and worth pinning beside the others: an assembly has no material line of
    its own -- M92 already sums its children -- so a whole-part figure on one is the chain
    that made an alias's market estimate 97% of a job."""
    pe = _part(applied_to_total=True)
    pe["_canonical_kind"] = "assembly"
    assert _bom_line_price(pe) is None


def test_a_leaf_never_reads_the_whole_part_figure():
    pe = _part(applied_to_total=True)
    pe["_canonical_kind"] = "leaf"
    assert _bom_line_price(pe) is None, \
        "a fabricated leaf is priced from its material estimate, never from a whole-part cost"


@pytest.mark.parametrize("withheld", [True, False])
def test_an_explicitly_withheld_line_is_unaffected(withheld):
    pe = _part(applied_to_total=True, _price_explicitly_withheld=withheld)
    assert (_bom_line_price(pe) is None) is withheld


# ── refused from the total, OFFERED to the estimator ────────────────────────────────
# A MISSING DRAWING IS THE NORMAL CASE. The standard is not "a complete pack or no price":
# it is best evidence plus explicit uncertainty. Charging the GBP 9.73 puts firm-looking
# money on the sheet that the job's own provenance rejects; silently dropping it leaves a
# blank where we hold a real, sourced figure an estimator could rule on in seconds. Those
# are two halves of one fault -- failing open into fake money, failing closed into silence --
# and this half is the one the fix above could easily have introduced.
from estimator_inputs import input_note_for_line, PLACEHOLDER_UNPRICED   # noqa: E402
import price_provenance as pp                                            # noqa: E402


def _declined_part():
    pe = _part(applied_to_total=False)
    pe["cost_breakdown"]["system_cost"]["matched_part_code"] = "SLIDER-TS15"
    return pe


def test_the_declined_figure_is_put_in_front_of_the_estimator():
    note = input_note_for_line(_declined_part())["note"]
    assert "9.73" in note, (
        "the engine found a real, sourced figure and the line that asks an estimator to "
        "price it does not mention it. A blank asks them to RESEARCH a price; a blank "
        "carrying the candidate asks them to RULE on one.")
    assert "historical quote" in note, "say where it came from or it cannot be judged"
    assert "NOT APPLIED" in note and "CONFIRM OR REPLACE" in note, (
        "the note must be unambiguous that this is not money on the sheet")


def test_the_offered_line_lands_on_the_estimator_input_list():
    """PLACEHOLDER_UNPRICED is the kind that shades the cell and lists the row from 233. As
    MATERIAL_UNPRICED it would read as 'look up a rate', which is the wrong job."""
    assert input_note_for_line(_declined_part())["kind"] == PLACEHOLDER_UNPRICED


def test_the_refusal_and_the_offer_read_the_same_rule():
    """Two readers, one function. If they could disagree about which prices were declined,
    a line could be refused by one and unexplained by the other -- which is the shape of the
    original defect, where the refusal was recorded and nothing asked."""
    pe = _declined_part()
    assert pp.declined_whole_part_price(pe)["gbp"] == 9.73
    assert _bom_line_price(pe) is None
    assert "9.73" in input_note_for_line(pe)["note"]


def test_a_part_with_nothing_declined_gets_the_ordinary_note():
    """The offer must be earned. Printed on every unpriced line it would be noise, and the
    lines that genuinely have a candidate would stop standing out."""
    note = input_note_for_line(_part(applied_to_total=True))["note"]
    assert "CONFIRM OR REPLACE" not in note


@pytest.mark.parametrize("bad", [None, {}, {"cost_breakdown": {}},
                                 {"cost_breakdown": {"system_cost": {"applied_to_total": False}}},
                                 {"cost_breakdown": {"system_cost": {
                                     "applied_to_total": False, "unit_cost_gbp": 0}}}])
def test_nothing_is_offered_where_there_is_no_figure(bad):
    """A zero, a missing cost and a malformed record are not candidates. Offering GBP 0.00
    'to confirm' is worse than saying nothing."""
    assert pp.declined_whole_part_price(bad) is None
