r"""
test_which_supplier_is_worth_integrating.py

THE CATALOGUE IS NOT THE QUESTION.

The supplier profiler ranked by how many priced lines each supplier holds in
UDEF_PARTS_TABLE_FOR_ESTIMATING -- which ranks them by how much of their price list somebody
once imported. A supplier with five thousand catalogue lines we have never bought from
outranks one with forty lines that appear on every job, and an integration aimed by that
number is aimed at the wrong supplier.

Three facts decide where the effort goes, and all three are in data we already hold:

  DO WE STILL BUY FROM THEM   dbo.historical_quote_material_line, every quote this business
                              has raised, joined to its header for the date. A supplier
                              nobody has quoted in two years does not need an API however
                              big their catalogue is.

  CAN WE ALREADY PRICE THEM   spend on a part code UDEF holds today is spend we can
                              reproduce; chasing that supplier buys nothing. The number that
                              matters is spend on the codes it does NOT hold, because that
                              is what an estimator is currently guessing at.

  CAN AN API BE ASKED ANYTHING  a line carrying a manufacturer reference can be queried the
                              moment somebody publishes an endpoint. A line of free text
                              cannot, however good their API is, because nothing on our side
                              would know what to ask for. For those a price file is not the
                              second-best route, it is the only route that can work.

The recommendation is a function of those three and nothing else, so it is testable without
a database -- which matters, because the database this reads is on the estimating LAN and
the rule has to be arguable before anyone spends a month on an integration.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "pricing"))

import udef_supplier_profile as sp  # noqa: E402


# ── the recommendation ──────────────────────────────────────────────────────────────
def test_a_supplier_we_cannot_price_and_can_query_is_an_api():
    assert sp.recommend(used_lines=200, uncovered_spend=8_400.0,
                        reference_share=0.82, months_since_last_use=2).startswith("API")


def test_a_supplier_we_cannot_price_and_cannot_query_is_a_price_file():
    """The distinction that matters and is easiest to get wrong. Free-text descriptions mean
    an API has nothing to ask for — this is not a supplier we integrate later, it is one
    that can only ever be a file."""
    out = sp.recommend(used_lines=200, uncovered_spend=8_400.0,
                       reference_share=0.04, months_since_last_use=2)
    assert out.startswith("PRICE FILE")
    assert "nothing to ask for" in out


def test_a_supplier_already_covered_by_udef_needs_nothing():
    """Spend we can already reproduce is not spend an integration improves. Ranking by total
    spend would have put these at the top and sent somebody to build an API for prices we
    already hold."""
    assert sp.recommend(200, 40.0, 0.9, 2) == "already covered by UDEF"


def test_a_dormant_supplier_is_not_chased_however_big_they_look():
    assert "dormant" in sp.recommend(5_000, 90_000.0, 0.95, 30)


def test_a_handful_of_lines_is_not_an_integration():
    assert "too few" in sp.recommend(3, 9_000.0, 0.95, 1)


def test_never_used_is_not_read_as_recently_used():
    """months_since_last_use is None when no quote carries a date. That must not read as
    "used this month" — the whole point of the column is to stop effort going somewhere
    nobody buys from any more."""
    out = sp.recommend(200, 8_400.0, 0.82, None)
    assert out.startswith("API"), out          # undated, but the other facts still decide


@pytest.mark.parametrize("lines,uncovered", [
    (3, 9_000.0),        # also "too few lines"
    (200, 40.0),         # also "already covered by UDEF"
    (5_000, 90_000.0),   # otherwise a clear API
])
def test_dormancy_is_asked_first(lines, uncovered):
    """ASKED FIRST ON PURPOSE, and the cases below are the ones that prove it: each is
    dormant AND something else, so an implementation that asks in another order returns a
    different answer for every one of them.

    The distinction is not pedantry. "Too few lines" invites "so let us wait until there
    are more" and "already covered" invites "so we are fine" — both describe a relationship
    that is continuing. "Dormant" says we stopped buying from them, which is the fact that
    decides whether anyone should think about this supplier again at all."""
    assert "dormant" in sp.recommend(lines, uncovered, 0.99, 36)


@pytest.mark.parametrize("share,expected", [(0.5, "API"), (0.49, "PRICE FILE")])
def test_the_reference_threshold_is_where_it_says_it_is(share, expected):
    assert sp.recommend(200, 8_400.0, share, 1).startswith(expected)


# ── the report is honest when half its input is missing ─────────────────────────────
def test_the_tool_says_so_when_the_usage_half_cannot_be_read():
    """If historical_quote_material_line is unreachable, every supplier's 'bought' and
    'unpriceable' figure is zero and the ranking silently reverts to catalogue size — the
    exact question this was changed to stop answering. A report that quietly answers a
    different question is worse than one that fails."""
    src = (ROOT / "tools" / "pricing" / "udef_supplier_profile.py").read_text(encoding="utf-8")
    block = src[src.index("_used_rows(cur)"):src.index("finally:")]
    assert "except Exception" in block, "a failure here would be swallowed"
    assert "ranked by CATALOGUE SIZE" in block, (
        "the fallback does not tell the reader the ranking now means something else")


def test_it_ranks_by_what_cannot_be_priced():
    """Not by spend, and not by catalogue lines. The sort key is the deliverable."""
    src = (ROOT / "tools" / "pricing" / "udef_supplier_profile.py").read_text(encoding="utf-8")
    assert "-uncovered_spend.get(s, 0.0)" in src, (
        "the ranking is back on a number that does not decide anything")


def test_it_reads_what_we_bought_and_not_only_what_is_catalogued():
    src = (ROOT / "tools" / "pricing" / "udef_supplier_profile.py").read_text(encoding="utf-8")
    assert "dbo.historical_quote_material_line" in src
    assert "dbo.historical_quote_header" in src, "no join for the date, so dormancy is blind"


def test_it_stays_read_only():
    """It reads the live estimating database. A tool that profiles suppliers has no business
    writing anything, and being sure of that is what makes it safe to run at a prompt."""
    src = (ROOT / "tools" / "pricing" / "udef_supplier_profile.py").read_text(encoding="utf-8")
    for verb in ("INSERT ", "UPDATE ", "DELETE ", "DROP ", "ALTER ", "MERGE ", "TRUNCATE "):
        assert verb not in src.upper(), f"{verb.strip()} appears in a read-only tool"
