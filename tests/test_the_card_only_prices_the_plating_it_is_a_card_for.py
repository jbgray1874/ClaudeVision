"""£15.83 was not a reading. It was a rate applied to a word that named no process.

    "Line 20 – Plating stated as Zinc – Requirement is Brass Harrods 01 (£250.00 per each
    stand.)"                                     — Howard Thurley, SDI estimating, 9 Sep 2026

The engine never read "zinc" anywhere on 7332-01. It read "PLATED" — which is a family, not
a process — and PLATE_SUBCONTRACT_POLICY's £2.50/kg is a trade zinc-and-passivate card. The
card priced it because nothing had ever told the code which platings the card covers, even
though the config paragraph directly above the rate says in words that a decorative or named
spec is NOT this rate and that such a line stays blocking until a plater quote confirms.

So the policy holds the intent and the code ignored it, and the gap between them is sixteen
to one: £15.83 against £250.00, on a line an estimator has no reason to look at twice
because it carries a plausible figure and the reassuring word INDICATIVE.

THE RULE, WHICH IS ABOUT EVIDENCE AND NOT ABOUT THIS CUSTOMER:

  * a finish naming a process the card covers — zinc, passivate, galvanised — prices on the
    card, exactly as before;
  * a finish naming a spec we hold a quote for prices at the quote;
  * a finish naming a plate and no process — "PLATED", "NICKEL PLATE", nothing at all —
    is NOT PRICED. The card's arithmetic rides along as a candidate, every quoted spec on
    file is offered beside it, and a person rings the plater.

A blank that says what it needs beats a wrong number that looks considered. The first gets
asked about; the second gets quoted.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import config                                                            # noqa: E402
from estimator import (named_plate_spec_anywhere_on_the_pack,            # noqa: E402
                       plating_unit_price)

POLICY = config.PLATE_SUBCONTRACT_POLICY


# ── the card prices what the card is for ─────────────────────────────────────────────────

def test_zinc_and_passivate_are_still_priced_on_the_card():
    """The ordinary job is untouched. This is the whole of what £2.50/kg was ever for."""
    for text in ("zinc passivate", "ZINC PLATE & PASSIVATE", "zinc plated",
                 "GALVANISED", "electro-zinc"):
        unit, _, method = plating_unit_price(2.4, 6, POLICY, text, ("7332-01",))
        assert method == "subcontract_plating_indicative", text
        assert unit == 15.83, text


def test_a_bare_plated_is_not_zinc():
    """7332-01's actual reading, off two detail sheets. It names a family and stops."""
    unit, _, method = plating_unit_price(0.9, 6, POLICY, "PLATED", ("7332-01",))
    assert unit is None
    assert method == "subcontract_plating_spec_unidentified"


def test_nor_is_a_plating_the_card_does_not_cover():
    """Nickel and chrome classify as plate and cost multiples of zinc. The config note names
    nickel specifically as not this rate; now the code agrees with the note."""
    for text in ("NICKEL PLATE", "CHROME PLATED", "BRASS PLATE", "Harrods 02"):
        assert plating_unit_price(2.4, 6, POLICY, text, ("7332-01",))[0] is None, text


def test_a_quoted_spec_still_wins_over_the_zinc_card():
    """THE ORIGINAL DEFECT, and the part that must never come back: £2.50/kg is a trade
    zinc card and a decorative brass is a different product, sixteen to one. A named spec
    stops the card dead — it just no longer charges a figure from source instead."""
    unit, _, method = plating_unit_price(0.9, 6, POLICY, "PLATED Harrods01", ("7332-01",))
    assert method == "subcontract_plating_historical_comparator"
    assert unit == 250.00, "and emphatically not the £15.83 the zinc card would have charged"


# ── and a blocked line hands over everything needed to settle it ─────────────────────────

def test_the_candidate_figure_is_carried_not_thrown_away():
    """The card's arithmetic is still worth having — an estimator who knows it IS zinc must
    be able to accept it without recomputing it. It is offered, not charged."""
    _, note, _ = plating_unit_price(0.9, 6, POLICY, "PLATED", ("7332-01",))
    assert "£15.83" in note
    assert "CANDIDATE and is NOT charged" in note
    assert "£2.50/kg card is trade zinc/passivate" in note


def test_the_quoted_specs_on_file_are_offered_beside_it():
    _, note, _ = plating_unit_price(0.9, 6, POLICY, "PLATED", ("7332-01",))
    assert "Brass — Harrods 01 £250.00 per unit" in note
    assert "Howard Thurley" in note


def test_the_line_says_what_the_drawing_actually_said():
    """Not "no finish" — the drawing said something, and the something is the reason the
    line exists at all. Quoting it is what lets a person recognise the callout."""
    _, note, _ = plating_unit_price(0.9, 6, POLICY, "PLATED", ("7332-01",))
    assert "'PLATED'" in note
    _, note2, _ = plating_unit_price(0.9, 6, POLICY, "", ("7332-01",))
    assert "not stated" in note2


def test_an_unconfigured_rate_is_still_its_own_answer():
    """Withholding the rate entirely is a different state from not knowing the process, and
    it keeps its own wording."""
    unit, _, method = plating_unit_price(2.4, 6, {"gbp_per_kg": None}, "PLATED", ("7332-01",))
    assert unit is None and method == "estimator_to_price"


def test_a_policy_with_no_rate_covers_list_behaves_exactly_as_before():
    """The gate is config-driven, so an installation that has not filled the list in is not
    silently switched to blocking on every plated job."""
    old = {k: v for k, v in POLICY.items() if k != "rate_covers"}
    unit, _, method = plating_unit_price(2.4, 6, old, "PLATED")
    assert unit == 15.83 and method == "subcontract_plating_indicative"


# ── the spec is looked for on the PACK, never in the customer's name ─────────────────────
#
# "Line 85 – … Grey area as drawing only nominates a finish as Harrods01." The callout is on
# the drawing set. It is not on the weldment record or on any member record, which is all the
# plating line had ever read — so the widened search is the pack's own text and stops there.

def test_a_spec_on_another_sheet_of_the_same_pack_is_found():
    recs = [{"part_number": "7332-01-101", "normalized_finish": "PLATED"},
            {"part_number": "7332-01-GA", "surface_finishes": ["Harrods01"]}]
    spec, found_on, text = named_plate_spec_anywhere_on_the_pack(recs)
    assert spec["last_known_quote"]["gbp_per_unit"] == 250.00
    assert found_on == "7332-01-GA"                  # named, so the estimator can check it
    assert "Harrods01" in text


def test_a_pack_naming_no_registered_spec_finds_nothing():
    """Every job but the ones we hold a quote for. This must not become a guess."""
    recs = [{"part_number": "12349-02-69-04M", "normalized_finish": "POWDER COATED RAL9005"},
            {"part_number": "12349-02-69-01A", "normalized_finish": "RAW"},
            {"part_number": "X", "surface_finishes": ["ZINC PLATE & PASSIVATE"]}]
    assert named_plate_spec_anywhere_on_the_pack(recs) == (None, "", "")


def test_the_customer_name_alone_buys_nothing():
    """THE LINE THIS MUST NOT CROSS. The job is for Harrods and the spec is called Harrods 01,
    and binding £250 to a client name would have made tonight's sheet right for a reason that
    is not evidence. Only the pack's own finish text counts."""
    recs = [{"part_number": "7332-01-101", "normalized_finish": "PLATED",
             "customer": "Harrods", "client": "Harrods", "description": "Harrods A3 stand"}]
    assert named_plate_spec_anywhere_on_the_pack(recs)[0] is None


def test_a_non_dict_in_the_list_does_not_break_the_search():
    recs = [None, "7332-01-101", 42, {"part_number": "G", "surface_finishes": ["HARRODS 01"]}]
    assert named_plate_spec_anywhere_on_the_pack(recs)[0]["last_known_quote"]["gbp_per_unit"] == 250.00
