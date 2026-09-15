"""0355255's tape line is the whole gap between our sheet and the estimator's.

    AI      £19.50 a unit at 10 off, £18.94 at 250, £18.84 at 1000
    Manual  £7.63                     £4.65          £4.55

The provenance tab says what happened, and it is not what it looked like:

    Tape^10975-02-GA EPDM TAPE 25X1MM - TAPE 113C   LENGTH: 200.00
    qty 3 · unit £4.37 · ext £13.63
    Price source: AI market indication (config_default_material_rates) — NOT A QUOTE

£4.37 was never a roll price. It is a PER-EACH default material rate, and three strips were
charged three of them. TAPE113C is supplied on a 10 metre roll at £4.50; three strips of
200 mm is 600 mm, six hundredths of a roll, twenty-eight pence with the estimator's own 4%
waste. £13.35 of an £11.87 difference — one line, and the whole of it. A per-each charge does
not amortise either, which is why our column barely moves across the quantity breaks while the
estimator's falls by a third.

THE RECORD KNEW ENOUGH ALL ALONG. The description carries "LENGTH: 200.00" and the quantity is
3. What was missing is the only thing a roll needs: how long the roll is and what it costs.
That is a buying fact, so it lives in config.ROLL_GOODS_CATALOGUE with the buyer's name on it,
and a code that is not in that table is withheld rather than guessed at.

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


def _tape(qty=3, desc=TAPE, **over):
    p = {"part_number": "10975", "description": desc, "quantity": qty}
    p.update(over)
    return p


def _flags(part):
    return " ".join(str(f) for f in part.get("review_flags") or [])


# ── the line that was £13.63 ─────────────────────────────────────────────────────────────

def test_three_strips_of_tape_cost_twenty_seven_pence():
    part = _tape()
    out = roll_goods_material(part)
    assert out["extended_material_cost_gbp"] == 0.27      # the LINE: 600 mm of the roll
    assert out["cost_per_part_gbp"] == 0.09               # ONE piece: 200 mm
    assert out["cost_method"] == "roll_goods_by_length"


def test_what_the_sheet_actually_charges_is_howards_figure():
    """THE ASSERTION THAT WAS MISSING, and the run that proved it was missing.

    These tests checked the function and never the number the Estimate prints. The per-part
    field carried the LINE cost, and the sheet's BOM formula multiplies the price column by
    Qty Per Unit — so 0355255's tape went out as price 0.27, qty 3, total 0.8424. Three lots
    of the whole 600 mm: 1,800 mm of tape against Howard's 28p, on a book whose other
    figures had all come right.

    Per part x qty x 4% waste is what the cell does. That is the number to assert."""
    out = roll_goods_material(_tape())
    assert round(out["cost_per_part_gbp"] * 3 * 1.04, 4) == 0.2808


def test_it_is_not_three_times_the_pack():
    """The failure in one line: 3 x £4.37 = £13.11, £13.63 with waste, against 28p."""
    out = roll_goods_material(_tape())
    assert out["extended_material_cost_gbp"] < 1.00


def test_the_arithmetic_is_on_the_line():
    part = _tape()
    roll_goods_material(part)
    f = _flags(part)
    assert "200 mm a piece at £0.09" in f
    assert "3 x 200 mm = 600 mm" in f
    assert "10000 mm roll at £4.50" in f
    assert "Howard Thurley" in f


def test_the_code_is_matched_however_it_is_written():
    """The pack says "TAPE 113C"; the catalogue says "TAPE113C". A straight substring test
    misses that, and a miss here is silent — the line simply prices as an each."""
    for desc in ("TAPE 113C LENGTH: 200.00", "TAPE113C LENGTH: 200.00",
                 "TAPE-113C LENGTH: 200.00", "epdm tape 113c length: 200.00"):
        out = roll_goods_material(_tape(desc=desc))
        assert out["cost_method"] == "roll_goods_by_length", desc


def test_it_scales_with_the_pieces_and_the_length():
    """The LINE scales with the piece count; the PER PIECE figure does not, because a piece
    is a piece however many of them the drawing asks for."""
    six = roll_goods_material(_tape(qty=6))
    assert six["extended_material_cost_gbp"] == 0.54
    assert six["cost_per_part_gbp"] == 0.09
    # 3 x 100 mm = 300 mm -> 0.135. Kept to four places rather than rounded to the penny: a
    # consumable line is often worth less than 1p a unit and rounding it to zero is how a
    # material reads as free.
    short = roll_goods_material(_tape(desc="TAPE 113C LENGTH: 100.00"))
    assert short["extended_material_cost_gbp"] == 0.135
    assert short["cost_per_part_gbp"] == 0.045


def test_a_whole_roll_costs_a_whole_roll():
    out = roll_goods_material(_tape(qty=1, desc="TAPE 113C LENGTH: 10000"))
    assert out["extended_material_cost_gbp"] == 4.50
    assert out["cost_per_part_gbp"] == 4.50          # one piece IS the roll


# ── what it will not guess ───────────────────────────────────────────────────────────────

def test_a_roll_code_we_do_not_hold_is_withheld_not_guessed():
    part = _tape(desc="DOUBLE SIDED TAPE 99Z LENGTH: 200.00")
    out = roll_goods_material(part)
    assert out["unit_material_cost_gbp"] is None
    assert out["cost_method"] == "roll_goods_withheld_estimator_to_price"
    assert "roll length and roll price are not known" in _flags(part)


def test_tape_with_no_stated_length_is_withheld():
    part = _tape(desc="TAPE 113C, THREE STRIPS TO BASE")
    out = roll_goods_material(part)
    assert out["unit_material_cost_gbp"] is None
    assert "length of each piece is not stated" in _flags(part)


def test_the_withheld_line_still_says_what_it_needs():
    part = _tape(desc="TAPE 99Z LENGTH: 50")
    roll_goods_material(part)
    f = _flags(part)
    assert "piece count must never multiply a pack price" in f
    assert "length used ÷ roll length × roll price" in f


# ── and it reaches nothing that is not sold off a roll ───────────────────────────────────

def test_a_fabricated_part_is_untouched():
    for desc in ("GRAVITY FEEDER FABRICATION", "LID", "FRONT COVER", "PACKER",
                 "A4 TABLE TOP GRAPHIC HOLDER"):
        assert roll_goods_material({"part_number": "X", "description": desc}) is None, desc


def test_a_screw_is_untouched():
    assert roll_goods_material(
        {"part_number": "STD PART", "description": "3.5x19mm WOOD SCREW", "quantity": 6}) is None


def test_estimate_material_asks_before_any_other_basis():
    """A blank, a weight and an each are all the wrong unit for a strip off a roll, so this
    is the first question estimate_material asks."""
    out = estimate_material(_tape())
    assert out["cost_method"] == "roll_goods_by_length"
    assert out["unit_material_cost_gbp"] == 0.09          # per piece; the line is 0.27


def test_the_catalogue_entry_names_who_gave_us_the_roll():
    entry = config.ROLL_GOODS_CATALOGUE["TAPE113C"]
    assert entry["roll_length_mm"] == 10000.0 and entry["roll_price_gbp"] == 4.50
    assert "Howard Thurley" in entry["source"] and "0355255" in entry["source"]


# ── and the label must not ask him to replace his own figure ─────────────────────────────

def test_a_roll_line_is_a_house_rate_not_a_market_lookup():
    """THE PLATER-FREIGHT DEFECT AGAIN, on the one line of the job the estimator had
    already priced by hand.

    10975-02's tape is costed from config.ROLL_GOODS_CATALOGUE — TAPE113C, a 10 m roll at
    £4.50, sourced to "Howard Thurley (SDI estimating/buying), 0355255 review". The
    classifier put it in the market bucket, so the decisions list read

        AI market indication (AI/market lookup) — NOT A QUOTE, replace it

    asking him to replace his own roll price with a quote. The figure was right; a wrong
    label on a right number costs an estimator the time he spends checking it."""
    import costed_facts as cf
    origin = cf._price_origin(
        {"part_number": "10975", "cost_source": "roll_goods_by_length",
         "material_estimate": {"cost_method": "roll_goods_by_length",
                               "roll_length_mm": 10000.0, "roll_price_gbp": 4.50,
                               "length_used_mm": 600.0,
                               "price_source": {"source": "roll_goods_catalogue"}}},
        kind="bought_in", block="bom", charged_unit=0.09, engine_unit=0.09,
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
                               "roll_length_mm": 10000.0, "roll_price_gbp": 4.50,
                               "length_used_mm": 600.0}},
        kind="bought_in", block="bom", charged_unit=0.09, engine_unit=0.09,
        sheet_row=13, cross_ref=False, row_text="")
    assert "600 mm of a 10000 mm roll" in origin["label"]
    assert "£4.50 a roll" in origin["label"]
    assert "verify the roll price" in origin["label"]


def test_a_real_market_line_is_still_a_market_line():
    """The branch must not swallow the lines the market bucket exists for."""
    import costed_facts as cf
    origin = cf._price_origin(
        {"part_number": "P/P", "cost_source": "market_ai_indicative",
         "material_estimate": {"cost_method": "market_ai_indicative"}},
        kind="bought_in", block="bom", charged_unit=0.35, engine_unit=0.35,
        sheet_row=22, cross_ref=False, row_text="")
    assert origin["firmness"] == cf.INDICATIVE_MARKET
