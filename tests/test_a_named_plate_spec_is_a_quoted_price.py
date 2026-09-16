"""Brass Harrods 01 is £250 a stand. The sheet had it as £15.83 of trade zinc.

"Line 20 – Plating stated as Zinc – Requirement is Brass Harrods 01 (£250.00 per each stand.)"
— the estimator on 7332-01, and it is the largest single error on that sheet by an order of
magnitude: a decorative brass finish priced as indicative zinc on the plated mass.

THE ENGINE ALREADY KNEW THIS COULD HAPPEN. PLATE_SUBCONTRACT_POLICY's own note says a
decorative or named "Harrods" plate spec is NOT the per-kilo rate and that the line stays
blocking until a plater quote confirms. The quote has now arrived, so the named spec is
priced as what it is — a quoted price per unit, not a rate times a mass, with no vat minimum
because that belongs to the trade-zinc card.

KEYED ON THE FINISH THE DRAWING NAMES, which is what makes it safe to ship beside another
customer's job on the same build: a finish naming no spec in the table falls through to the
mass rate exactly as before, and a job with no plating at all reaches neither. 12349-02 has
no plating and cannot be touched by this.

Matched with spaces and punctuation removed, because one finish is written "Harrods01",
"HARRODS 01" and "Harrods-01" across a single pack.
"""
from __future__ import annotations

import pytest

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import config                                                           # noqa: E402
from estimator import named_plate_spec, plating_unit_price             # noqa: E402

POLICY = config.PLATE_SUBCONTRACT_POLICY


# ── the finish is recognised however the drawing spells it ───────────────────────────────

def test_every_spelling_on_the_pack_finds_the_spec():
    for text in ("Harrods01", "HARRODS 01", "Harrods-01", "BRASS HARRODS 01 FINISH"):
        assert (named_plate_spec(text) or {}).get("requires_quote") is True, text


def test_an_unnamed_finish_names_no_spec():
    for text in ("zinc passivate", "powder coated RAL9005", "", None):
        assert named_plate_spec(text) is None, text


# ── priced as a quote, not as a mass ─────────────────────────────────────────────────────

# ── everything else is exactly as it was ─────────────────────────────────────────────────

def test_an_unnamed_finish_still_takes_the_mass_rate():
    unit, note, method = plating_unit_price(2.4, 6, POLICY, "zinc passivate", ("7332-01",))
    assert method == "subcontract_plating_indicative"
    assert "INDICATIVE zinc/passivate" in note
    assert unit == 15.83


def test_no_finish_text_at_all_names_no_process_either():
    """A plating line with no finish text is the same state as one reading "PLATED": the
    pack says this goes to a plater and does not say what for. The zinc card is not an
    approximation of an unknown process — it is a different product — so the line blocks."""
    unit, note, method = plating_unit_price(2.4, 6, POLICY)
    assert unit is None and method == "subcontract_plating_spec_unidentified"
    assert "not stated" in note


def test_a_withheld_rate_is_still_withheld():
    unit, note, method = plating_unit_price(2.4, 6, {"gbp_per_kg": None}, "zinc", ("7332-01",))
    assert unit is None and method == "estimator_to_price"


def test_no_figure_from_an_earlier_job_reaches_the_line():
    """THE RULE. Not a charge, not a fallback, not a comparator, not a note, not a
    suggestion — and the note must not so much as print the number."""
    unit, note, method = plating_unit_price(2.4, 6, POLICY, "Harrods 01", ("9001-01",))
    assert unit is None
    assert method == "subcontract_plating_quote_needed"
    assert "250" not in note, "a figure on the line is a figure somebody accepts"
    assert "independent of any other" in note


def test_what_the_earlier_job_taught_is_still_applied():
    """The knowledge survives and it is not a number: decorative, so the per-kilo zinc card
    cannot price it, and a fresh job-specific quote is required."""
    _, note, _ = plating_unit_price(2.4, 6, POLICY, "Harrods 01", ("9001-01",))
    assert "NOT the zinc/passivate card" in note
    assert "MISSING:" in note and "ASKED OF:" in note


def test_the_table_records_the_method_and_dates_the_evidence():
    """The entry teaches WHAT the finish is and HOW it is priced; the figure beside it is
    dated context. `gbp_per_unit` is deliberately absent from the entry itself, so nothing
    can charge from it by reaching one key deeper than it meant to."""
    spec = config.NAMED_PLATE_SPECS["HARRODS01"]
    assert spec["decorative"] is True, "not zinc — this is what stopped the per-kilo card"
    assert spec["requires_quote"] is True
    assert "gbp_per_unit" not in spec, "a chargeable rate must not live in source"
    assert "last_known_quote" not in spec, "nor a figure by another name"
    import price_register
    assert price_register.lookup("HARRODS01", ("7332-01",)) is None, \
        "the figure is audit-only and the resolver must not reach it"


# ── the work a plated part causes that an unplated one does not ──────────────────────────
# "There would be consideration for two ops for Packing — to and from Plater & Final Assembly
# / Pack. Manual Estimate for 4 Minutes Pack for Platers / 8 Minutes Final Assembly & Pack."
# The sheet booked ONE pack of 2 minutes for both. A part that leaves the building and comes
# back is packed twice, and the second pack is not the first one again.

from estimator import estimate_process_times                            # noqa: E402


def _part(finish):
    return {"part_number": "7332-01-101", "normalized_material": "MILD_STEEL",
            "normalized_finish": finish, "textual_operations": ["handling"]}


def test_a_plated_part_is_packed_twice():
    """As TWO operations since his 15 Sep ruling — "Two separate Operations this job" —
    4 min out to the plater on its own row, 8 min final. The same 12 minutes."""
    out = estimate_process_times(_part("zinc plated"))
    rt = out["run_times_min_per_unit"]
    assert rt["plater_pack"] == 4.0 and rt["handling"] == 8.0


def test_a_named_spec_counts_as_plating_even_though_it_names_no_process():
    """"Harrods01" is the customer's name for a brass plate, not a process word — so the
    finish classifier cannot see it, and the part whose plating costs £250 was the one part
    not recognised as plated."""
    part = _part("Harrods01")
    out = estimate_process_times(part)
    rt = out["run_times_min_per_unit"]
    assert rt["plater_pack"] + rt["handling"] == 12.0
    assert part.get("plater_pack_applied") is True


def test_an_unplated_part_keeps_its_single_handling_allowance():
    """12349-02 is powder coated and goes nowhere — it must not gain ten minutes."""
    for finish in ("powder coated RAL9005", "", "wet spray"):
        part = _part(finish)
        out = estimate_process_times(part)
        assert out["run_times_min_per_unit"]["handling"] == 0.8, finish
        assert not part.get("plater_pack_applied")


def test_the_line_says_both_packs_and_whose_figures():
    part = _part("zinc plated")
    estimate_process_times(part)
    flags = " ".join(str(f) for f in part.get("review_flags") or [])
    assert "packed TWICE" in flags and "4 min a unit pack to the plater" in flags
    assert "Howard Thurley" in flags
    # the split's own consequence is on the line too: two rows means two PACM set-ups,
    # one per occasion, with the way to halve it if the bench regards them as one
    assert "TWO set-ups" in flags and "the second comes off" in flags


def test_the_freight_is_held_per_order_and_shared():
    """£120 over the six stands it was quoted against is the £20 a unit he quotes —
    answered by the REGISTER for 7332-01 alone, because that £120 is that job's own
    transport quote. Config no longer holds it: a money figure in config was every plated
    job's freight, the £250 fault in a smaller coat."""
    from estimator import plater_freight_for_job
    entry = plater_freight_for_job(("7332-01",))
    assert entry and entry["amount"] == 120.0
    assert round(entry["amount"] / 6, 2) == 20.0
    assert "transport department" in entry["source_reference"].lower()
    assert plater_freight_for_job(("9999-01",)) is None, \
        "another job must not borrow 7332-01's quote"
    assert "freight_gbp_per_order" not in config.PLATING_LOGISTICS


# ── the drawing's own callout, not only the engine's word for it ─────────────────────────
#
# THE `or` THAT COST THE WHOLE POINT. _part_finish_text read the normalised fields and
# consulted the RAW list only when all of them were empty. A named spec is exactly the case
# where they are not: the finish classifier recognises "Harrods01" as a plate and writes its
# own word — "zinc plated" — into normalized_finish, and the drawing's actual callout stays in
# surface_finishes where nothing then looked. 7332-01-101 priced on the indicative zinc card,
# £15.83 against a quoted £250 a stand, on a live run of the build that had the named-spec
# table in it. The table was right and the text never reached it.

from estimator import _part_finish_text                                  # noqa: E402


def test_the_callout_survives_the_classifier_naming_it_something_else():
    part = {"normalized_finish": "zinc plated", "surface_finishes": ["Harrods01"]}
    text = _part_finish_text(part)
    assert "Harrods01" in text
    assert (named_plate_spec(text) or {}).get("requires_quote") is True
    assert plating_unit_price(2.4, 6, POLICY, text, ("7332-01",))[2] == \
        "subcontract_plating_quote_needed", text


def test_every_spelling_of_the_finish_fields_is_read():
    for part in (
        {"normalized_finish": "Harrods01"},
        {"finish": "HARRODS 01"},
        {"surface_finish": "Harrods-01"},
        {"surface_finishes": ["BRASS HARRODS 01 FINISH"]},
        {"normalized_finish": "plated", "finish": "brass",
         "surface_finishes": ["Harrods01", "brushed"]},
    ):
        assert named_plate_spec(_part_finish_text(part)) is not None, part


def test_an_ordinary_plated_part_is_unchanged():
    part = {"normalized_finish": "zinc plated", "surface_finishes": ["ZINC PASSIVATE"]}
    text = _part_finish_text(part)
    assert named_plate_spec(text) is None
    assert plating_unit_price(2.4, 6, POLICY, text, ("7332-01",))[0] == 15.83


def test_nothing_is_repeated_when_the_fields_agree():
    """The classifier and the drawing often say the same word. Saying it twice helps nobody
    and makes a matcher's job harder."""
    part = {"normalized_finish": "powder coated", "finish": "POWDER COATED",
            "surface_finishes": ["powder coated"]}
    assert _part_finish_text(part).lower() == "powder coated"


def test_a_part_with_no_finish_reads_empty():
    assert _part_finish_text({}) == ""
    assert _part_finish_text({"surface_finishes": []}) == ""


# ── the price is a LOOKUP, not a literal ─────────────────────────────────────────────────
#
# James Gray, 16 Sep 2026: "the engine must learn methods, conditions, and evidence, not copy
# a manual estimate's numbers into the next estimate… prices should live in a versioned,
# attributable price register or live system connector — not as numeric literals in Python
# configuration. Code should contain the pricing MECHANISM; data should contain approved
# rates, dates, scope, source, and expiry."
#
# £250 WAS a literal here, attributed and dated, which made it honest and did not make it
# right: a plater's quote for one stand in September is not a rate. What the entry teaches
# now is the METHOD — "Harrods 01" is a decorative requirement, so the per-kilo zinc card
# must not price it, and a plater quotes it per job. The figure is asked of SDI's own
# sources at run time, exactly as the tape's roll price is.

@pytest.fixture
def a_live_price(monkeypatch):
    """SDI's sources answering for the spec — what a connector or the price register does."""
    import stated_prices
    monkeypatch.setattr(stated_prices, "resolve", lambda code, desc=None: (
        {"gbp": 250.00, "basis": "system", "source": "udef_sqlserver",
         "label": "SDI Live UDEF", "disagreement": None}
        if str(code).upper() == "HARRODS01" else
        {"gbp": None, "basis": None, "source": None, "label": "", "disagreement": None}))
    return 250.00




def test_a_current_price_from_sdis_own_sources_does_price_it(a_live_price):
    unit, note, method = plating_unit_price(2.4, 6, POLICY, "Harrods 01", ("7332-01",))
    assert unit == a_live_price
    assert method == "subcontract_plating_named_spec"
    assert "SDI Live UDEF" in note
    assert "per-kilo" in note, "and it is still not the zinc card"


def test_a_live_quote_does_not_move_with_the_mass_or_the_order(a_live_price):
    """A price per stand is per stand — the kilos and the vat minimum are the zinc card's
    arithmetic and have nothing to do with it."""
    a = plating_unit_price(2.4, 6, POLICY, "Harrods 01", ("7332-01",))[0]
    b = plating_unit_price(40.0, 500, POLICY, "Harrods 01", ("7332-01",))[0]
    assert a == b == a_live_price


def test_a_live_quote_needs_no_mass_at_all(a_live_price):
    """The mass is the zinc card's input, not the quote's."""
    unit, _, method = plating_unit_price(0, 6, POLICY, "Harrods 01", ("7332-01",))
    assert unit == a_live_price and method == "subcontract_plating_named_spec"


def test_freight_is_never_folded_into_the_plating_price(a_live_price):
    """THE LINE HAS TO EQUAL WHAT THE PLATER CHARGES, or it cannot be checked against the
    plater's own quote — which is the entire reason this is priced as a quote."""
    unit, note, _ = plating_unit_price(2.4, 6, POLICY, "Harrods 01", ("7332-01",))
    assert unit == a_live_price, "the plating price is the plater's price and nothing else"
    assert "freight" not in note.lower()
    src = (ROOT / "src" / "estimator.py").read_text(encoding="utf-8")
    assert "NOT INCLUDED here: freight to and from the plater" in src
    assert "put it on the delivery" in src
    assert "plater_freight_gbp_per_unit" in src
