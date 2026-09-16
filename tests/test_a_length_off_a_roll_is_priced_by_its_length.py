"""0355255's tape line is the whole gap between our sheet and the estimator's.

    AI      £19.50 a unit at 10 off, £18.94 at 250, £18.84 at 1000
    Manual  £7.63                     £4.65          £4.55

The provenance tab says what happened, and it is not what it looked like:

    Tape^10975-02-GA EPDM TAPE 25X1MM - TAPE 113C   LENGTH: 200.00
    qty 3 · unit £4.37 · ext £13.63
    Price source: AI market indication (config_default_material_rates) — NOT A QUOTE

£4.37 was never a roll price. It is a PER-EACH default material rate, and three strips were
charged three of them. TAPE113C is supplied on a 10 metre roll; three strips of 200 mm is
600 mm — six hundredths of whatever the roll costs. A per-each charge does not amortise
either, which is why our column barely moved across the quantity breaks while the
estimator's fell by a third.

THE RECORD KNEW ENOUGH ALL ALONG. The description carries "LENGTH: 200.00" and the quantity
is 3. What was missing is what a roll needs: how long it is (config.ROLL_GOODS_CATALOGUE, a
packaging fact) and what it costs — which is MONEY, asked of SDI's own priced sources at run
time and never held in source. James Gray, 16 Sep 2026: "A number copied from an estimator's
sheet is not a price source, even as a 'reference'" — so the stated-figure table shipped
EMPTY, and every roll price in this file is a SYNTHETIC figure a test injects as the system's
answer, to prove the arithmetic and nothing else. Where no source answers, the line is
withheld, awaiting price.

PRICED BEFORE ANY OTHER BASIS. Everything else in estimate_material prices a blank, a weight
or an each, and all three are the wrong unit for a strip of tape.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import config                                                           # noqa: E402
from estimator import estimate_material, roll_goods_material            # noqa: E402

# The line exactly as the 8 Sep workbook's provenance tab carries it.
TAPE = "Tape^10975-02-GA EPDM TAPE 25X1MM - TAPE 113C LENGTH: 200.00"

# A SYNTHETIC roll price — £5.00 is nobody's figure, invented here so the length
# arithmetic can be asserted without a sheet number living anywhere in the codebase.
SYNTH_ROLL_GBP = 5.00


@pytest.fixture()
def the_system_prices_the_roll(monkeypatch):
    """SDI Live answers — the one legitimate path. Stubbed with an invented figure."""
    import stated_prices as sp
    monkeypatch.setattr(sp, "system_price",
                        lambda c, d=None: {"gbp": SYNTH_ROLL_GBP,
                                           "source": "access_supply_chain"})


def _tape(qty=3, desc=TAPE, **over):
    p = {"part_number": "10975", "description": desc, "quantity": qty}
    p.update(over)
    return p


def _flags(part):
    return " ".join(str(f) for f in part.get("review_flags") or [])


# ── the line that was £13.63 ─────────────────────────────────────────────────────────────

def test_three_strips_price_as_a_fraction_of_the_roll(the_system_prices_the_roll):
    part = _tape()
    out = roll_goods_material(part)
    assert out["extended_material_cost_gbp"] == 0.30      # the LINE: 600 mm / 10 m x £5
    assert out["cost_per_part_gbp"] == 0.10               # ONE piece: 200 mm
    assert out["cost_method"] == "roll_goods_by_length"


def test_what_the_sheet_actually_charges_is_the_per_piece_figure(the_system_prices_the_roll):
    """THE ASSERTION THAT WAS MISSING, and the run that proved it was missing.

    These tests checked the function and never the number the Estimate prints. The per-part
    field carried the LINE cost, and the sheet's BOM formula multiplies the price column by
    Qty Per Unit — so 0355255's tape went out three lots of the whole 600 mm. Per part x
    qty x 4% waste is what the cell does. That is the number to assert."""
    out = roll_goods_material(_tape())
    assert round(out["cost_per_part_gbp"] * 3 * 1.04, 4) == \
        round(0.10 * 3 * 1.04, 4)


def test_it_is_not_three_times_the_pack(the_system_prices_the_roll):
    """The failure in one line: three per-each defaults against pennies of roll."""
    out = roll_goods_material(_tape())
    assert out["extended_material_cost_gbp"] < 1.00


def test_the_arithmetic_is_on_the_line(the_system_prices_the_roll):
    part = _tape()
    roll_goods_material(part)
    f = _flags(part)
    assert "200 mm a piece at £0.10" in f
    assert "3 x 200 mm = 600 mm" in f
    assert f"10000 mm roll at £{SYNTH_ROLL_GBP:.2f}" in f
    assert "Roll length:" in f and "Roll price:" in f


def test_the_code_is_matched_however_it_is_written(the_system_prices_the_roll):
    """The pack says "TAPE 113C"; the catalogue says "TAPE113C". A straight substring test
    misses that, and a miss here is silent — the line simply prices as an each."""
    for desc in ("TAPE 113C LENGTH: 200.00", "TAPE113C LENGTH: 200.00",
                 "TAPE-113C LENGTH: 200.00", "epdm tape 113c length: 200.00"):
        out = roll_goods_material(_tape(desc=desc))
        assert out["cost_method"] == "roll_goods_by_length", desc


def test_it_scales_with_the_pieces_and_the_length(the_system_prices_the_roll):
    """The LINE scales with the piece count; the PER PIECE figure does not, because a piece
    is a piece however many of them the drawing asks for."""
    six = roll_goods_material(_tape(qty=6))
    assert six["extended_material_cost_gbp"] == 0.60
    assert six["cost_per_part_gbp"] == 0.10
    # 3 x 100 mm = 300 mm. Kept to four places rather than rounded to the penny: a
    # consumable line is often worth less than 1p a unit and rounding it to zero is how a
    # material reads as free.
    short = roll_goods_material(_tape(desc="TAPE 113C LENGTH: 100.00"))
    assert short["extended_material_cost_gbp"] == 0.15
    assert short["cost_per_part_gbp"] == 0.05


def test_a_whole_roll_costs_a_whole_roll(the_system_prices_the_roll):
    out = roll_goods_material(_tape(qty=1, desc="TAPE 113C LENGTH: 10000"))
    assert out["extended_material_cost_gbp"] == SYNTH_ROLL_GBP
    assert out["cost_per_part_gbp"] == SYNTH_ROLL_GBP    # one piece IS the roll


# ── what it will not guess ───────────────────────────────────────────────────────────────

def test_a_roll_nobody_priced_is_withheld_awaiting_price():
    """THE SHIPPED STATE. No stated figure exists in the codebase — the table is empty by
    rule — so with SDI Live silent the line is withheld and says who is being asked."""
    part = _tape()
    out = roll_goods_material(part)
    assert out["unit_material_cost_gbp"] is None
    assert out["cost_method"] == "roll_goods_withheld_estimator_to_price"
    assert "nothing priced it" in _flags(part)
    assert "Give the roll price" in _flags(part)


def test_a_roll_code_we_do_not_hold_is_withheld_not_guessed(the_system_prices_the_roll):
    part = _tape(desc="DOUBLE SIDED TAPE 99Z LENGTH: 200.00")
    out = roll_goods_material(part)
    assert out["unit_material_cost_gbp"] is None
    assert out["cost_method"] == "roll_goods_withheld_estimator_to_price"
    assert "roll length and roll price are not known" in _flags(part)


def test_tape_with_no_stated_length_is_withheld(the_system_prices_the_roll):
    part = _tape(desc="TAPE 113C, THREE STRIPS TO BASE")
    out = roll_goods_material(part)
    assert out["unit_material_cost_gbp"] is None
    assert "length of each piece is not stated" in _flags(part)


def test_the_withheld_line_still_says_what_it_needs(the_system_prices_the_roll):
    part = _tape(desc="TAPE 99Z LENGTH: 50")
    roll_goods_material(part)
    f = _flags(part)
    assert "piece count must never multiply a pack price" in f
    assert "length used ÷ roll length × roll price" in f


# ── and it reaches nothing that is not sold off a roll ───────────────────────────────────

def test_a_fabricated_part_is_untouched(the_system_prices_the_roll):
    for desc in ("GRAVITY FEEDER FABRICATION", "LID", "FRONT COVER", "PACKER",
                 "A4 TABLE TOP GRAPHIC HOLDER"):
        assert roll_goods_material({"part_number": "X", "description": desc}) is None, desc


def test_a_screw_is_untouched(the_system_prices_the_roll):
    assert roll_goods_material(
        {"part_number": "STD PART", "description": "3.5x19mm WOOD SCREW", "quantity": 6}) is None


def test_estimate_material_asks_before_any_other_basis(the_system_prices_the_roll):
    """A blank, a weight and an each are all the wrong unit for a strip off a roll, so this
    is the first question estimate_material asks."""
    out = estimate_material(_tape())
    assert out["cost_method"] == "roll_goods_by_length"
    assert out["unit_material_cost_gbp"] == 0.10          # per piece; the line is 0.30


def test_the_catalogue_names_who_gave_us_the_roll_and_holds_no_money():
    """THE PRICE IS NOWHERE. "We can't take a number off a sheet" — James, 16 Sep. The
    LENGTH is a packaging fact and stays with its source; the stated-price table is empty
    by rule, and the price register's prices are too."""
    entry = config.ROLL_GOODS_CATALOGUE["TAPE113C"]
    assert entry["roll_length_mm"] == 10000.0
    assert "roll_price_gbp" not in entry
    assert "Howard Thurley" in entry["source"] and "0355255" in entry["source"]
    assert config.ESTIMATOR_STATED_PRICES == {}, \
        "a figure off an estimator's sheet is not a price source"


# ── and the label must not ask him to replace his own figure ─────────────────────────────

def test_a_roll_line_is_a_house_rate_not_a_market_lookup():
    """The classifier put a roll-arithmetic line in the market bucket, so the decisions
    list asked the estimator to replace a correctly derived figure with a quote. The
    figures below are synthetic — the CLASS is what is under test."""
    import costed_facts as cf
    origin = cf._price_origin(
        {"part_number": "10975", "cost_source": "roll_goods_by_length",
         "material_estimate": {"cost_method": "roll_goods_by_length",
                               "roll_length_mm": 10000.0,
                               "roll_price_gbp": SYNTH_ROLL_GBP,
                               "length_used_mm": 600.0,
                               "price_source": {"source": "roll_goods_catalogue"}}},
        kind="bought_in", block="bom", charged_unit=0.10, engine_unit=0.10,
        sheet_row=13, cross_ref=False, row_text="EPDM TAPE 25X1MM TAPE 113C")
    assert origin["firmness"] == cf.INDICATIVE_HOUSE
    assert origin["class"] == "roll_goods"
    assert "NOT A QUOTE" not in origin["label"]


def test_it_names_the_roll_so_the_arithmetic_can_be_checked():
    """What an estimator verifies here is the ROLL PRICE, not the division."""
    import costed_facts as cf
    origin = cf._price_origin(
        {"part_number": "10975", "cost_source": "roll_goods_by_length",
         "material_estimate": {"cost_method": "roll_goods_by_length",
                               "roll_length_mm": 10000.0,
                               "roll_price_gbp": SYNTH_ROLL_GBP,
                               "length_used_mm": 600.0}},
        kind="bought_in", block="bom", charged_unit=0.10, engine_unit=0.10,
        sheet_row=13, cross_ref=False, row_text="")
    assert "600 mm of a 10000 mm roll" in origin["label"]
    assert f"£{SYNTH_ROLL_GBP:.2f} a roll" in origin["label"]
    assert "verify the roll price" in origin["label"]


def test_a_real_market_line_is_still_a_market_line():
    """The branch must not swallow the lines the market bucket exists for."""
    import costed_facts as cf
    origin = cf._price_origin(
        {"part_number": "P/P", "cost_source": "market_ai_indicative",
         "material_estimate": {"cost_method": "market_ai_indicative"}},
        kind="bought_in", block="bom", charged_unit=0.35, engine_unit=0.35,
        sheet_row=14, cross_ref=False, row_text="")
    assert origin["class"] != "roll_goods"
