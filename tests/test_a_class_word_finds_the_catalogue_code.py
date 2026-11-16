r"""
test_a_class_word_finds_the_catalogue_code.py

12349-02's M4 flange button screw reached the sheet as class word FIXING, no price, "enter a
unit rate for this item" — in front of an estimator who has that exact part in his own price
book at 2.48p. So did the bumpons and the acrylic.

TWO FAULTS, ONE LINE APART.

1. The description index was built from `raw_text`, which is the whole catalogue cell:
   "FIXING2813 -M4 x 10mm FLANGE BUTTON HEAD SCREW,BLACK" — the code AND the part. Indexed
   whole, that row could only match a drawing token that already said FIXING2813, and a token
   saying that matched on code and never reached the description path at all. The route was
   dead for every row carrying its code, which is all of them, while its own docstring said it
   matched "catalogue-description inside drawing-token".

2. A size is the same size wherever the spaces fall. The catalogue says "M4 x 10mm", the
   drawing says "M4x10mm", and one space was the difference between 2.48p and nothing.

The rails are untouched: containment one way only, a minimum length, word boundaries, a
refusal when candidates disagree, and placeholders still refused outright.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import bought_in_pricing as bp                                       # noqa: E402

# Tim's own rows, spelled exactly as his sheet spells them, through the real splitter.
TIM_ROWS = [
    ("FIXING2813 -M4 x 10mm FLANGE BUTTON HEAD SCREW,BLACK", 0.0248),
    ("FIXING860 - 10.1 x 1.8mm BUMPONS", 0.02),
    ("FRMDF003 - 2440 x 1220 x 6mm", 14.90),
    ("PLAS366 - 2050 x 1520 x 3mm IM30 Acrylic", 60.45),
    ("POWDER40 - BLACK RAL9005 MATT", 3.48),
]


@pytest.fixture(scope="module")
def pricer():
    book = {}
    for raw, price in TIM_ROWS:
        code, desc = bp.split_code_desc(raw)
        book[code or raw] = {"code": code, "description": desc or raw, "raw_text": raw,
                             "prices_by_qty": {1: price}, "source": "manual_estimate:tim"}
    return bp.make_price_book_pricer(book)


def test_the_screw_finds_tims_price(pricer):
    """THE FAULT ITSELF, in the two spellings that actually appeared."""
    got = pricer("FIXING", "M4x10mm FLANGE BUTTON HEAD SCREW, BLACK")
    assert got["unit_cost_gbp"] == 0.0248


def test_the_spacing_of_a_size_does_not_decide_whether_a_part_has_a_price(pricer):
    spaced = pricer("FIXING", "M4 x 10mm FLANGE BUTTON HEAD SCREW, BLACK")
    tight = pricer("FIXING", "M4x10mm FLANGE BUTTON HEAD SCREW, BLACK")
    assert spaced["unit_cost_gbp"] == tight["unit_cost_gbp"] == 0.0248


@pytest.mark.parametrize("written", ["2050 x 1520 x 3mm IM30 Acrylic",
                                     "2050x1520x3mm IM30 Acrylic",
                                     "2050 X 1520 X 3MM IM30 ACRYLIC"])
def test_a_sheet_size_matches_however_it_is_written(pricer, written):
    assert pricer("", written)["unit_cost_gbp"] == 60.45


def test_a_code_on_the_drawing_still_wins_directly(pricer):
    """The code path is first and must be untouched — everything already priced stays priced
    by identity, not by reading its description."""
    assert pricer("FIXING2813", "anything at all")["unit_cost_gbp"] == 0.0248


# ── the rails, which is the whole reason this is safe to loosen ────────────────

def test_a_placeholder_is_still_refused(pricer):
    """"FIXING" alone means the draughtsman had not decided. It matches a large slice of any
    catalogue, and answering it invents a cost."""
    got = pricer("FIXING", "")
    assert got["unit_cost_gbp"] is None
    assert got["source"] == "price_book_vague_token"


def test_containment_still_runs_one_way_only():
    """The reverse let `FIXING` reach a fragrance cabinet's screw and put it on a Dyson
    estimate. Loosening what is INDEXED must not loosen the direction."""
    src = (ROOT / "src" / "bought_in_pricing.py").read_text(encoding="utf-8")
    assert 'f" {dkey} " in padded' in src, "containment direction changed"


def test_two_rows_that_disagree_are_refused_not_picked(pricer):
    """Picking one is a coin toss dressed up as an answer — and indexing descriptions as well
    as raw text makes collisions more likely, not less."""
    book = {}
    for raw, price in [("AAA111 - 10mm BLACK KNOB", 1.00), ("BBB222 - 10mm BLACK KNOB", 9.99)]:
        code, desc = bp.split_code_desc(raw)
        book[code] = {"code": code, "description": desc, "raw_text": raw,
                      "prices_by_qty": {1: price}, "source": "t"}
    got = bp.make_price_book_pricer(book)("", "10mm BLACK KNOB")
    assert got["unit_cost_gbp"] is None
    assert got["source"] == "price_book_ambiguous"


def test_a_part_the_catalogue_does_not_have_is_still_unpriced(pricer):
    """The honest half. Tim has no wood screw row in this workbook and the bumpon he has is
    described differently — neither may be answered by stretching a match."""
    assert pricer("STDPART", "3.5x19mm WOOD SCREW")["unit_cost_gbp"] is None


def test_both_texts_are_indexed_so_nothing_that_matched_before_stops():
    src = (ROOT / "src" / "bought_in_pricing.py").read_text(encoding="utf-8")
    i = src.index("for _text in (rec.get(\"description\"), rec.get(\"raw_text\")):")
    assert "by_desc" in src[i:i + 300]
