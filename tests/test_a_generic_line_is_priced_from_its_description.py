"""Having refused FIXING as a code, the question is what actually prices row 29 instead.

test_a_category_is_not_a_part_code.py stopped the class word being used as an identifier. That
is only half an answer. The half that matters to an estimator is: so what DOES happen to

    29  FIXING            M6x16.0mm SOCKET CAP SCREW, BZP         16
    30  SPRING WASHER     M6 SPRING WASHER                        16

— do we find them, and what do we hand back? This file answers that with the numbers the engine
actually computes rather than a description of what it ought to do.

TWO THINGS THIS FOUND, both of which changed the code.

FIRST, THE GUARD WAS IN THE WRONG PLACE TO DO THE WHOLE JOB. It lived in
supplier_reference.lookup_keys, which feeds the two manufacturer-reference arms of
_get_udef_anchor. The query at the BOTTOM of that method takes part["part_number"] raw, so
`[Part code] = 'FIXING'` was still being asked on every generic fixing line.

That never produced a wrong price — the catch-all FIXING row in UDEF is £0.00 and the price
check refuses it. It did something quieter. The query is TOP 1 ordered exact-code-first, so the
£0.00 row is the ONE row returned, and the description arm OF THE SAME QUERY never gets to
answer. The line left UDEF empty-handed whether or not its description matched anything. The
~900 MISC rows, every one £0.00, do the same to every line coded MISC. Blinded, not mispriced,
which is why nothing ever looked wrong.

SECOND, AND THIS ONE COULD HAVE COST MONEY: _get_pma_purchased has the same raw-code arm, and
its SQL filters PMA_COST_MAT > 0. So a catch-all in Access Supply Chain is not saved by being
priced zero — a zero-priced one is excluded, and a priced one is taken on the exact-code branch
at score 1.0 and returned at confidence 0.88. Every generic fixing on every drawing at one
figure, with the strongest confidence the chain can express. Whether such a row exists in PMA is
a question for the database; the engine should not depend on the answer.

WHAT NOW HAPPENS, which is the estimator-facing answer. The code is dropped, the description is
kept, and the line falls to historical RAG — which is the one source in the chain that fetches
per-token and scores, rather than requiring the whole description as a contiguous substring. The
scores below are computed by the engine's own tokeniser, not asserted from memory.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from pricing_service import PricingService  # noqa: E402

# The two rows off the M&S till podia BOM (402179-01-GA, page 8).
ROW_29 = {"part_number": "FIXING", "description": "M6x16.0mm SOCKET CAP SCREW, BZP"}
ROW_30 = {"part_number": "SPRING WASHER", "description": "M6 SPRING WASHER"}


class _Spy:
    """A PricingService with no database behind it, recording what it would have asked.

    object.__new__ skips the constructor deliberately: the point is to read the parameters
    handed to the driver, and a real connection would be the only thing standing between this
    test and the live SDILive box.
    """

    def __init__(self, one=None, many=None):
        self.svc = object.__new__(PricingService)
        self.asked: list = []
        self.svc._fetch_one_with_retry = self._record(one)
        self.svc._fetch_all_with_retry = self._record(many if many is not None else [])

    def _record(self, result):
        def go(query, params=None):
            self.asked.append((query, list(params or [])))
            return result() if callable(result) else result
        return go

    def params(self) -> list:
        return [p for _, params in self.asked for p in params]


# ── the class word does not reach the database as a code ───────────────────────

@pytest.mark.parametrize("part", [ROW_29, ROW_30], ids=["row29-FIXING", "row30-SPRING WASHER"])
def test_udef_is_never_asked_for_a_part_coded_with_a_class_word(part):
    """THE ASSERTION. Not "it returns None" — that was already true, and for the wrong
    reason. The code must not be in the query at all."""
    spy = _Spy()
    spy.svc._get_udef_anchor(part)
    assert part["part_number"] not in spy.params(), (
        f"{part['part_number']!r} was still sent to UDEF as a code")


@pytest.mark.parametrize("part", [ROW_29, ROW_30], ids=["row29-FIXING", "row30-SPRING WASHER"])
def test_the_parts_master_is_never_asked_for_one_either(part):
    """The arm that could genuinely have returned a wrong figure, because its SQL filters
    PMA_COST_MAT > 0 and so cannot be rescued by a zero price."""
    spy = _Spy()
    spy.svc._get_pma_purchased(part)
    assert part["part_number"] not in spy.params()


@pytest.mark.parametrize("part", [ROW_29, ROW_30], ids=["row29", "row30"])
def test_the_description_is_still_asked_about(part):
    """Dropping the code must not drop the line. Refusing an identifier and suppressing a
    part are opposite outcomes and only one of them is wanted."""
    spy = _Spy()
    spy.svc._get_udef_anchor(part)
    assert part["description"] in spy.params()


def test_a_real_code_on_the_same_bom_is_still_sent_exactly():
    """Rows 31 to 33 carry real SDI codes. A guard that caught those would take three priced
    lines and make them unpriceable — the opposite error, and the worse one."""
    spy = _Spy()
    spy.svc._get_udef_anchor({"part_number": "FIXING41",
                              "description": "M6x16.0mm BUTTON HEAD SCREW; BZP"})
    assert "FIXING41" in spy.params()


def test_the_zero_priced_catch_all_no_longer_swallows_the_only_row_we_get():
    """The blinding, demonstrated. UDEF's last query is TOP 1 ordered exact-code-first, so
    while 'FIXING' was in it the £0.00 catch-all was the single row returned and the
    description arm of the same query could never answer. Here the fake returns a priced
    description match; before the fix the query that produced it would not have been asked
    for the description at all, because the code arm had already claimed the one slot."""
    row = ("FIXING1081", "M6x16.0mm SOCKET CAP SCREW, BZP", "Elite Sourcing",
           0.0450, "each", None, None, None, None)
    spy = _Spy(one=row)
    anchor = spy.svc._get_udef_anchor(ROW_29)
    assert anchor is not None, "a priced description match must survive"
    assert anchor["unit_price_gbp"] == pytest.approx(0.045)
    # 0.82 for a non-exact UDEF match, less the 0.15 UDEF always carries because the table has
    # no effective_date column and an undated price is treated as an old one.
    assert anchor["confidence"] == 0.67, "matched on description, not on code — not 0.95"


# ── what historical RAG actually scores, computed not remembered ───────────────
#
# RAG is the source that answers these lines, and it is the only one in the chain that fetches
# candidates per significant token and then ranks them. UDEF and PMA both require the WHOLE
# description as one contiguous LIKE substring, which a BOM description almost never is.

def _score(part, candidate: str) -> float:
    return PricingService._token_overlap_score(
        PricingService._tokenize(part["description"]), candidate)


_MIN_OVERLAP = 0.45     # the constant inside _get_historical_rag


def test_the_line_is_tokenised_into_something_worth_searching_on():
    assert PricingService._tokenize(ROW_29["description"]) == {
        "M6X16", "0MM", "SOCKET", "CAP", "SCREW", "BZP"}


@pytest.mark.parametrize("part,candidate", [
    (ROW_29, "M6x16.0mm SOCKET CAP SCREW, BZP"),
    (ROW_29, "M6 x 16 SOCKET CAP SCREW BZP"),
    (ROW_30, "M6 SPRING WASHER"),
])
def test_the_right_historical_line_clears_the_threshold(part, candidate):
    """Yes, we find them — an identical or near-identical past line is matched and priced."""
    assert _score(part, candidate) >= _MIN_OVERLAP


@pytest.mark.parametrize("part,candidate", [
    (ROW_29, "4.0x10.0mm DOME RIVET, BLACK ANODIZED"),   # row 32, a different fixing entirely
    (ROW_30, "M6 FLAT WASHER BZP"),                      # a washer, but not this washer
])
def test_a_different_part_does_not_clear_it(part, candidate):
    """The threshold earns its keep here. Below it the line falls through to the market
    estimate flagged for review, which is the right answer for 'we do not know'."""
    assert _score(part, candidate) < _MIN_OVERLAP


# ── the hazard this exposed, recorded rather than papered over ─────────────────
#
# Jaccard counts tokens and has no idea which of them is the SIZE. "M6x16.0mm" is one token out
# of six, so a line that differs ONLY in size loses one token and keeps five — while the right
# screw written with different punctuation splits M6x16 into "M6" and "16" and loses two.
#
# _get_historical_rag takes max(score). So where the archive holds an M8 written the drawing's
# way and the M6 written another way, THE M8 WINS. For a socket cap screw that is pennies. The
# mechanism is not about pennies: it is that size is the most price-relevant word in a fixing
# description and the scorer treats it as one word among six.
#
# Left failing on purpose. Fixing it means teaching the scorer that a size token is not
# interchangeable — a real change to matching, with its own regression risk across every priced
# line, not something to slip in beside a guard.

@pytest.mark.xfail(strict=True, reason=(
    "size is one token among six, so a wrong-size line of the same family outscores the right "
    "part written with different punctuation. Needs size-aware matching, not a threshold tweak"))
def test_the_right_size_ought_to_beat_the_wrong_one():
    right = _score(ROW_29, "M6 x 16 SOCKET CAP SCREW BZP")      # correct screw, re-punctuated
    wrong = _score(ROW_29, "M8x20.0mm SOCKET CAP SCREW, BZP")   # wrong size, drawing's spelling
    assert right > wrong


def test_and_both_of_them_clear_the_threshold_today():
    """Which is what makes the above a live hazard rather than a curiosity: the wrong-size line
    is not merely close, it is accepted."""
    assert _score(ROW_29, "M8x20.0mm SOCKET CAP SCREW, BZP") >= _MIN_OVERLAP
    assert _score(ROW_30, "M8 SPRING WASHER") >= _MIN_OVERLAP


def test_a_different_head_on_the_same_shank_also_clears_it():
    """Row 31 is a BUTTON HEAD; row 29 is a SOCKET CAP. Same M6x16 BZP, different fastener.
    Recorded because it is the second way one of these lines can be priced from the wrong
    neighbour, and because it is the one an estimator would spot on a parity report."""
    assert _score(ROW_29, "M6x16.0mm BUTTON HEAD SCREW; BZP") >= _MIN_OVERLAP


# ── one predicate, not two ─────────────────────────────────────────────────────

def test_the_price_chain_and_the_key_builder_share_one_definition():
    """Two copies of "what counts as a category" would drift, and the drift would show up as
    a line refused in one arm and accepted in another — the hardest kind of thing to see."""
    src = (_ROOT / "src" / "pricing_service.py").read_text(encoding="utf-8")
    assert "from part_code_conventions import is_category_not_a_code" in src, (
        "pricing_service must import the predicate, not restate the vocabulary")
    assert "_CATEGORY_CODES" not in src, "the word list must live in exactly one module"
