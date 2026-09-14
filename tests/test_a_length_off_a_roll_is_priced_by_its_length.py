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
    assert out["unit_material_cost_gbp"] == 0.27          # 0.28 on the sheet with 4% waste
    assert out["cost_method"] == "roll_goods_by_length"


def test_it_is_not_three_times_the_pack():
    """The failure in one line: 3 x £4.37 = £13.11, £13.63 with waste, against 28p."""
    out = roll_goods_material(_tape())
    assert out["unit_material_cost_gbp"] < 1.00


def test_the_arithmetic_is_on_the_line():
    part = _tape()
    roll_goods_material(part)
    f = _flags(part)
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
    assert roll_goods_material(_tape(qty=6))["unit_material_cost_gbp"] == 0.54
    # 3 x 100 mm = 300 mm -> 0.135. Kept to four places rather than rounded to the penny: a
    # consumable line is often worth less than 1p a unit and rounding it to zero is how a
    # material reads as free.
    assert roll_goods_material(
        _tape(desc="TAPE 113C LENGTH: 100.00"))["unit_material_cost_gbp"] == 0.135


def test_a_whole_roll_costs_a_whole_roll():
    out = roll_goods_material(_tape(qty=1, desc="TAPE 113C LENGTH: 10000"))
    assert out["unit_material_cost_gbp"] == 4.50


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
    assert out["unit_material_cost_gbp"] == 0.27


def test_the_catalogue_entry_names_who_gave_us_the_roll():
    entry = config.ROLL_GOODS_CATALOGUE["TAPE113C"]
    assert entry["roll_length_mm"] == 10000.0 and entry["roll_price_gbp"] == 4.50
    assert "Howard Thurley" in entry["source"] and "0355255" in entry["source"]
