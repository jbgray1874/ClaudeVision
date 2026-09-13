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
        assert (named_plate_spec(text) or {}).get("gbp_per_unit") == 250.00, text


def test_an_unnamed_finish_names_no_spec():
    for text in ("zinc passivate", "powder coated RAL9005", "", None):
        assert named_plate_spec(text) is None, text


# ── priced as a quote, not as a mass ─────────────────────────────────────────────────────

def test_the_named_spec_is_two_hundred_and_fifty_a_stand():
    unit, note, method = plating_unit_price(2.4, 6, POLICY, "Harrods 01")
    assert unit == 250.00
    assert method == "subcontract_plating_named_spec"


def test_it_does_not_move_with_the_mass_or_the_order():
    """A quoted price per stand is per stand — the kilos and the vat minimum are the zinc
    card's arithmetic and have nothing to do with it."""
    a = plating_unit_price(2.4, 6, POLICY, "Harrods 01")[0]
    b = plating_unit_price(40.0, 500, POLICY, "Harrods 01")[0]
    assert a == b == 250.00


def test_the_line_says_it_is_a_quote_and_whose():
    _, note, _ = plating_unit_price(2.4, 6, POLICY, "Harrods 01")
    assert "quoted price for the named spec" in note
    assert "Howard Thurley" in note and "7332-01" in note
    assert "per-kilo" in note


# ── everything else is exactly as it was ─────────────────────────────────────────────────

def test_an_unnamed_finish_still_takes_the_mass_rate():
    unit, note, method = plating_unit_price(2.4, 6, POLICY, "zinc passivate")
    assert method == "subcontract_plating_indicative"
    assert "INDICATIVE zinc/passivate" in note
    assert unit == 15.83


def test_no_finish_text_at_all_is_unchanged():
    assert plating_unit_price(2.4, 6, POLICY)[2] == "subcontract_plating_indicative"


def test_a_withheld_rate_is_still_withheld():
    unit, note, method = plating_unit_price(2.4, 6, {"gbp_per_kg": None}, "zinc")
    assert unit is None and method == "estimator_to_price"


def test_a_named_spec_prices_even_where_no_mass_resolved():
    """The mass is the zinc card's input, not the quote's — a named spec does not need it."""
    unit, _, method = plating_unit_price(0, 6, POLICY, "Harrods 01")
    assert unit == 250.00 and method == "subcontract_plating_named_spec"


def test_the_table_records_where_the_price_came_from():
    spec = config.NAMED_PLATE_SPECS["HARRODS01"]
    assert "plater quote" in spec["source"] and "7332-01" in spec["source"]


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
    out = estimate_process_times(_part("zinc plated"))
    assert out["run_times_min_per_unit"]["handling"] == 12.0      # 4 to the plater + 8 final


def test_a_named_spec_counts_as_plating_even_though_it_names_no_process():
    """"Harrods01" is the customer's name for a brass plate, not a process word — so the
    finish classifier cannot see it, and the part whose plating costs £250 was the one part
    not recognised as plated."""
    part = _part("Harrods01")
    out = estimate_process_times(part)
    assert out["run_times_min_per_unit"]["handling"] == 12.0
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
    assert "packed twice" in flags and "4 min to the plater" in flags
    assert "transport department" in flags.lower() or "Howard Thurley" in flags


def test_the_freight_is_held_per_order_and_shared():
    """£120 over the six stands it was quoted against is the £20 a unit he quotes."""
    lg = config.PLATING_LOGISTICS
    assert lg["freight_gbp_per_order"] == 120.0
    assert round(lg["freight_gbp_per_order"] / 6, 2) == 20.0
    assert "transport department" in lg["source"].lower()


def test_the_freight_is_not_added_to_the_plating_price():
    """THE LINE HAS TO EQUAL WHAT THE PLATER CHARGES.

    Freight to and from the plater is real money, but folding it into a line labelled
    "plating" makes that line impossible to check against the plater's own quote — which is
    the entire reason a named spec is priced as a quote rather than a rate. So the figure is
    stated in the note and carried on the record for the delivery line, and the plating price
    stays plating. The two existing plated-weldment tests pin the arithmetic."""
    unit, note, _ = plating_unit_price(2.4, 6, POLICY, "Harrods 01")
    assert unit == 250.00, "the plating price is the plater's price and nothing else"
    assert "freight" not in note.lower()
    # The statement of what is missing is added where the order quantity is known — the
    # placeholder pricing pass — and says where the money belongs instead.
    src = (ROOT / "src" / "estimator.py").read_text(encoding="utf-8")
    assert "NOT INCLUDED here: freight to and from the plater" in src
    assert "put it on the delivery" in src
    assert "plater_freight_gbp_per_unit" in src
