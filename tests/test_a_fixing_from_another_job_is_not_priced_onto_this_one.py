"""A short token must not reach across the price book and pull in somebody else's part.

On the 10575-02 Dyson pack the engine costed `FIXING591` — a catalogue line whose description
reads "BE2030-10 FRAGRANCE CABINET — TEST TRAY SCREW", £3.76. There is no fragrance cabinet on
that job. The part came from a different customer's estimate entirely.

It was not a data leak. The price book is shared across jobs by design — that is what makes it
worth having. The fault was in how a token was matched to it:

    for dkey, drec in by_desc.items():
        if dkey and (dkey in nd or nd in dkey):
            rec, match_kind = drec, "description"
            break

Three separate things are wrong in those four lines.

`nd in dkey` matches in the WRONG DIRECTION. `dkey in nd` is defensible — the catalogue
description appears inside a longer drawing token. The reverse lets a six-character token like
FIXING match any catalogue row that happens to contain the letters F-I-X-I-N-G anywhere in it,
including in the middle of another word.

There is NO MINIMUM LENGTH. The shorter the token, the more rows it matches — which is exactly
backwards. A vague token should match less confidently than a specific one, not more freely.

And `break` takes the FIRST hit in dictionary order. When forty rows match, the one that gets
priced is whichever was inserted first, which depends on the order workbooks were loaded. Nothing
anywhere records that thirty-nine others matched equally well.

The docstring on this function already states the intended contract — "Returns a None-style dict
on a miss so the line is flagged, never guessed." An ambiguous containment match IS a miss. It
was being answered as though it were a hit.

WHAT WAS REJECTED: raising the confidence penalty on containment matches and leaving the match
in place. A cheap wrong number is still a wrong number, and 0.55 confidence on a £3.76 line is
not a signal any estimator is going to act on. The line must be flagged so somebody prices it.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.append(str(_ROOT / "src"))

_spec = importlib.util.spec_from_file_location("bip", _ROOT / "src" / "bought_in_pricing.py")
bip = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bip)


def _book(*rows):
    """Build a price book the way load_price_book_from_workbook does."""
    out = {}
    for code, raw, price in rows:
        out[code or raw] = {
            "code": code,
            "description": raw,
            "raw_text": raw,
            "prices_by_qty": {1: price},
            "source": "manual_estimate:test",
            "n_jobs": 1,
        }
    return out


# The real shape of the fault: two unrelated jobs, both with fixings in the book.
_CROSS_JOB = _book(
    ("FIXING591", "BE2030-10 FRAGRANCE CABINET - TEST TRAY SCREW", 3.76),
    ("FIXING5", "4.0 X 10 POP RIVET FIXING", 0.01),
    ("FIXING1081", "ESSENTRA REF 466122 LEVELLING FOOT FIXING", 1.05),
)


def test_a_bare_fixing_token_is_not_given_somebody_elses_part():
    """The 10575-02 fault, reproduced. A vague token must be flagged, not answered."""
    pricer = bip.make_price_book_pricer(_CROSS_JOB, order_quantity=1)
    got = pricer("FIXING", "")
    assert got["unit_cost_gbp"] is None, (
        f"a bare FIXING token was priced at £{got['unit_cost_gbp']} from "
        f"{got.get('matched_part_code')!r} — this is the fragrance-cabinet screw fault"
    )


def test_the_flag_says_why_rather_than_just_no():
    """An estimator seeing a blank line needs to know it was ambiguous, not absent."""
    pricer = bip.make_price_book_pricer(_CROSS_JOB, order_quantity=1)
    got = pricer("FIXING", "")
    blob = f"{got.get('source','')} {got.get('reason','')}".lower()
    assert "ambiguous" in blob or "too many" in blob or "vague" in blob, (
        f"the miss must explain itself; got {got.get('source')!r} / {got.get('reason')!r}")


def test_an_exact_code_still_prices():
    """The fix must not cost us the matches that were right. This is the common case."""
    pricer = bip.make_price_book_pricer(_CROSS_JOB, order_quantity=1)
    got = pricer("FIXING591", "")
    assert got["unit_cost_gbp"] == 3.76
    assert got["match_kind"] == "code"


def test_an_exact_description_still_prices():
    pricer = bip.make_price_book_pricer(_CROSS_JOB, order_quantity=1)
    got = pricer("", "4.0 x 10 pop rivet fixing")
    assert got["unit_cost_gbp"] == 0.01
    assert got["match_kind"] == "description"


def test_a_long_specific_token_may_still_match_by_containment():
    """Containment is not the enemy — unbounded containment is. A drawing token carrying the
    whole catalogue description plus a quantity suffix should still find its row."""
    pricer = bip.make_price_book_pricer(_CROSS_JOB, order_quantity=1)
    got = pricer("", "ESSENTRA REF 466122 LEVELLING FOOT FIXING X 4 OFF")
    assert got["unit_cost_gbp"] == 1.05, (
        "a token that contains the full catalogue description must still match")


def test_containment_does_not_run_the_other_way():
    """The reversed test — `nd in dkey` — is what let short tokens reach long rows."""
    pricer = bip.make_price_book_pricer(_CROSS_JOB, order_quantity=1)
    got = pricer("", "SCREW")
    assert got["unit_cost_gbp"] is None, (
        "a five-letter token sitting inside a catalogue description must not price from it")


def test_two_rows_that_match_equally_well_are_refused_not_raced():
    """When the token genuinely fits more than one row, first-in-dict-order is not an answer."""
    book = _book(
        ("A1", "M6 X 20 SOCKET CAP SCREW STAINLESS", 0.40),
        ("A2", "M6 X 20 SOCKET CAP SCREW STAINLESS", 0.95),   # same text, different price
    )
    pricer = bip.make_price_book_pricer(book, order_quantity=1)
    got = pricer("", "M6 X 20 SOCKET CAP SCREW STAINLESS A2 70 GRADE")
    assert got["unit_cost_gbp"] is None, (
        f"two rows disagreed on price and one was picked anyway (£{got['unit_cost_gbp']})")


def test_two_rows_that_agree_on_price_are_not_refused():
    """Ambiguity only matters when it changes the number. Duplicate rows at the same price are
    not a reason to flag a line — refusing those would be its own kind of noise."""
    book = _book(
        ("B1", "M6 X 20 SOCKET CAP SCREW STAINLESS", 0.40),
        ("B2", "M6 X 20 SOCKET CAP SCREW STAINLESS", 0.40),
    )
    pricer = bip.make_price_book_pricer(book, order_quantity=1)
    got = pricer("", "M6 X 20 SOCKET CAP SCREW STAINLESS A2 70 GRADE")
    assert got["unit_cost_gbp"] == 0.40


def test_a_containment_match_is_less_confident_than_an_exact_one():
    pricer = bip.make_price_book_pricer(_CROSS_JOB, order_quantity=1)
    exact = pricer("FIXING591", "")
    loose = pricer("", "ESSENTRA REF 466122 LEVELLING FOOT FIXING X 4 OFF")
    assert loose["confidence"] < exact["confidence"]


def test_the_vague_tokens_are_named_where_somebody_will_find_them():
    """These strings appear on real drawings and mean 'not decided yet'. They are recorded in
    one place so the next person adding one does not have to rediscover the list."""
    assert hasattr(bip, "VAGUE_TOKENS")
    vague = {str(v).upper() for v in bip.VAGUE_TOKENS}
    assert {"FIXING", "STD PART", "TBC"} <= vague
