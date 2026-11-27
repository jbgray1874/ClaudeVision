r"""Five test files used to prove the opposite of this one. That is the point.

James, on the 7332-01 six-off book, 18 September 2026:

    "P/P felt pads priced from config. Four pads at £0.20 each; report calls them
     indicative. Remove the literal entirely. Retain the BOM identity and quantity, but
     hold it as awaiting a current SDI Live/supplier source."

    "The £0.20 felt-pad rate is still contrary to the agreed policy, so this workbook
     should not go out."

WHAT THIS REPLACES, AND WHY IT IS NOT A LOSS.

`STANDARD_COMMODITY_PRICE_GBP` held five figures — a pallet at £12.00, a perforated-panel
clip at £1.20, a felt pad at £0.20, a wood screw at 3p, an M4 at 8p. Five test files proved
they reached the sheet: test_a_screw_has_a_price_and_the_price_has_an_owner,
test_a_standard_pallet_is_a_stable_bought_in, test_the_fifth_call_site,
test_a_class_word_commodity_still_prices, test_a_class_word_item_is_priced_not_zero. They
were good tests of a policy that has been revoked, and they are in the history.

Every one of those figures was somebody working a number out once and typing it here. The
table's own `source` fields say so: "derived from a retail pack", "market rate ... no
supplier quote on file", "provisional set when 11762-17 surfaced the line". D-078 is exact
about this — "unless there is a re-useable / understandable calculation we can't use it" —
and being labelled INDICATIVE on the sheet does not make a guess into a price. It makes it
a guess wearing a disclaimer, and it was reaching estimates as money.

THE REASON THEY EXISTED IS STILL REAL, AND IS NOT ANSWERED BY A ZERO. James, the same day:

    "we should have a price for everything.. why would a price be 0 when we have so many
     layers including llm"

Right, and that is the other half. These entries were put in because the line came back
£0.00 and "a zero on a quote is a free part". The answer is not a typed figure and it is
not a zero either: it is the rung below — a researched indicative price, dated, labelled,
with its evidence kept — and failing that, a line the estimate refuses to total around.

So what is tested here is the seam: the identity survives, the money does not, and the
lookup gets out of the way of the rungs that can actually answer.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import config             # noqa: E402
from pricing_service import standard_commodity_price  # noqa: E402

_TABLE = config.STANDARD_COMMODITY_PRICE_GBP


# ── the money is gone ────────────────────────────────────────────────────────────────

def test_no_entry_in_the_table_carries_a_price_any_more():
    offenders = {}
    for token, entry in _TABLE.items():
        value = (entry or {}).get("price_gbp")
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = 0.0
        if numeric > 0:
            offenders[token] = value
    assert not offenders, (
        f"source-code prices are back in the commodity table: {offenders}. A figure typed "
        f"into this file is not a price, whatever it is labelled — D-078.")


def test_the_felt_pad_james_named_is_the_one_to_check_first():
    """Four pads at £0.20 on the 7332-01 book, which is what stopped it going out."""
    assert _TABLE["FELT+PAD"]["price_gbp"] is None


def test_the_others_went_with_it_because_the_policy_is_not_about_one_line():
    for token in ("PALLET", "PERFO+CLIP"):
        assert _TABLE[token]["price_gbp"] is None, token


# ── the identity stays ───────────────────────────────────────────────────────────────

def test_every_entry_still_says_what_the_item_is():
    """The keys, labels and sources are the line's IDENTITY — what it is, how it is
    recognised in a description, and what was once believed about it. That costs nothing,
    and it is what lets the next rung search for the right thing."""
    for token, entry in _TABLE.items():
        assert entry.get("label"), f"{token} lost its label with its price"
        assert entry.get("source"), f"{token} lost the record of where its figure came from"


def test_the_felt_pad_is_still_recognisable_from_a_drawing_description():
    """7332-01 prints the class word "P/P" and the description "BLACK FELT PAD,
    SELF-ADHESIVE, 25mm DIA". The engine must still know what that line IS in order to ask
    anyone about it."""
    assert "FELT+PAD" in _TABLE
    assert "felt pad" in _TABLE["FELT+PAD"]["label"].lower()


# ── and the lookup gets out of the way ───────────────────────────────────────────────

def _part(desc: str, code: str = "P/P") -> dict:
    return {"part_number": code, "description": desc, "quantity": 4}


def test_the_felt_pad_line_no_longer_prices_from_config():
    assert standard_commodity_price(
        _part("BLACK FELT PAD, SELF-ADHESIVE, 25mm DIA")) is None


def test_neither_does_any_other_entry():
    for desc in ("EURO PALLET 1200x1000", "PERFO PLASTIC LOCKING CLIP",
                 "3.5x19mm WOOD SCREW", "M4 x 8mm PEM STUD"):
        assert standard_commodity_price(_part(desc)) is None, desc


def test_a_description_that_never_matched_still_does_not():
    """The control: the lookup returning None everywhere would prove nothing if it had
    always returned None for these."""
    assert standard_commodity_price(_part("LASER CUT BRACKET 2mm MS")) is None


def test_returning_none_is_what_lets_the_next_rung_answer():
    """standard_commodity_price is consulted as a LAST RESORT before the market rung. It
    returning None is not the line giving up — it is the line being handed on to SDI Live,
    the supplier catalogue, a current quote, and then a researched indicative figure."""
    import inspect
    src = inspect.getsource(standard_commodity_price)
    assert "if _price <= 0:" in src and "continue" in src, (
        "the lookup must skip an entry with no price rather than returning a zero, or a "
        "withdrawn figure becomes a free part instead of an unanswered question")
