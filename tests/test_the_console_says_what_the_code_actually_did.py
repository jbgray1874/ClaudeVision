r"""
test_the_console_says_what_the_code_actually_did.py

TWO FAULTS OFF ONE 11650 RUN, BOTH ABOUT A CONSOLE THAT WAS NOT TELLING THE TRUTH.

FIRST -- an announcement asserting a decision the code did not take. These two lines came out
one after the other, about the same part:

    [material] 11650-01-05A: no rate for ABS; market indication GBP 39.18/m2 (GBP 245.00/sheet,
       llm_market_estimate) - PRICED FROM IT, marked as an LLM estimate.
    [material] 11650-01-05A: ABS is not priceable by this engine ... Priced from POLYCARBONATE.

Both cannot be so. The market indication is computed for the ARBITRATED material whether or
not a substitution rescued the price, deliberately, so an estimator can judge whether the
substitution matters. But the pricing block asks `material_has_a_rate(material)` about the
PRICING material -- POLYCARBONATE, which has a rate -- so the LLM figure never entered the
arithmetic. The line was costed from POLYCARBONATE and the console said otherwise.

A console that asserts a decision the code did not take is worse than a silent one, because
it is believed. Whoever read that would have gone looking for an ABS rate to correct, and the
number they needed to argue with was the polycarbonate one.

SECOND -- a provider being asked seven times to repeat itself. The same run printed

    SerpAPI search failed: HTTP Error 429: Too Many Requests

seven times. 429 is the provider talking about the SUBSCRIPTION, not about the query; asking
about a different material cannot change it. Seven network round trips, six of which could
only produce information already in the first, and a wall of noise over the estimate.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import estimator  # noqa: E402
import web_search_providers as wsp  # noqa: E402


# ── an account-level refusal is remembered, and said once ───────────────────────────
@pytest.fixture(autouse=True)
def _clean_latch():
    wsp.forget_provider_refusals()
    yield
    wsp.forget_provider_refusals()


class _Boom(Exception):
    pass


def _make_it_fail(monkeypatch, message):
    calls = []

    def _fail(url, *a, **k):
        calls.append(url)
        raise TimeoutError(message)

    monkeypatch.setattr(wsp, "_http_get_json", _fail)
    monkeypatch.setenv("SERPAPI_API_KEY", "test-key")
    return calls


def test_a_quota_refusal_stops_the_next_seven_requests(monkeypatch, capsys):
    calls = _make_it_fail(monkeypatch, "HTTP Error 429: Too Many Requests")
    for i in range(8):
        hits, err = wsp.search_serpapi(f"6mm ABS sheet {i}")
        assert hits == [] and err
    assert len(calls) == 1, (
        f"the provider was asked {len(calls)} times to repeat the same answer about the "
        f"account; one round trip is all that answer can be worth")


def test_the_refusal_is_said_once_and_says_what_it_means_for_the_estimate(monkeypatch, capsys):
    _make_it_fail(monkeypatch, "HTTP Error 429: Too Many Requests")
    for _ in range(4):
        wsp.search_serpapi("6mm ABS sheet")
    said = capsys.readouterr().out
    assert said.count("[web-price]") == 1, "one refusal, one message"
    assert "left for the estimator" in said, (
        "the consequence for the ESTIMATE is the part that matters — a lookup that silently "
        "stops is how a line comes out at nothing")


def test_the_latch_is_not_the_only_thing_keeping_it_quiet():
    """DELIBERATELY THE HELPER, and said so. The count test above passes even with the
    once-guard deleted, because the early return in search_serpapi means nothing reaches
    here twice today. That makes the guard a survivor no caller-level test can kill -- and
    the moment a third provider is added without its own early return, the guard is the only
    thing between a spent key and a wall of identical messages. Held here so it cannot be
    tidied away as dead code."""
    import io
    import contextlib
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        wsp._remember_refusal("serpapi", "HTTP Error 429: Too Many Requests")
        wsp._remember_refusal("serpapi", "HTTP Error 429: Too Many Requests")
    assert out.getvalue().count("[web-price]") == 1


@pytest.mark.parametrize("message", [
    "HTTP Error 429: Too Many Requests",
    "HTTP Error 401: Unauthorized",
    "HTTP Error 403: Forbidden",
])
def test_every_account_level_answer_latches(monkeypatch, message):
    calls = _make_it_fail(monkeypatch, message)
    wsp.search_serpapi("q1")
    wsp.search_serpapi("q2")
    assert len(calls) == 1, f"{message} is about the account, not the query"


def test_an_ordinary_failure_does_not_latch(monkeypatch):
    """A timeout or a dropped connection says nothing about the subscription, and the next
    material might well succeed. Latching on those would silently stop pricing a whole job
    because one request was unlucky."""
    calls = _make_it_fail(monkeypatch, "The read operation timed out")
    wsp.search_serpapi("q1")
    wsp.search_serpapi("q2")
    assert len(calls) == 2


def test_one_dead_provider_does_not_silence_the_other(monkeypatch):
    """Keyed by provider. A spent SerpAPI key says nothing about Google CSE."""
    calls = _make_it_fail(monkeypatch, "HTTP Error 429: Too Many Requests")
    wsp.search_serpapi("q")
    assert len(calls) == 1
    monkeypatch.setenv("GOOGLE_CSE_API_KEY", "k")
    monkeypatch.setenv("GOOGLE_CSE_CX", "cx")
    wsp.search_google_cse("q")
    # ASKED, not assumed dead. Counting the round trips is the only way to tell "CSE was
    # tried and refused in its own right" from "CSE was never asked because SerpAPI was
    # spent" -- both return an error string, and only one of them is correct.
    assert len(calls) == 2, "Google CSE was refused on SerpAPI's behalf and never asked"


# ── the market indication says which of the two figures priced the line ─────────────
def test_the_engine_does_not_claim_the_llm_figure_priced_a_substituted_line():
    """THE REAL FUNCTION, not a re-implementation of its message. estimate_part is too large
    to drive from a test, so this asserts on the source: the claim must be CONDITIONAL on
    whether a substitution happened, and both wordings must exist."""
    import ast
    tree = ast.parse((ROOT / "src" / "estimator.py").read_text(encoding="utf-8-sig",
                                                               errors="replace"))
    body = ast.unparse(tree)
    assert "_priced_from_it = _material_conflict is None" in body, (
        "the 'PRICED FROM IT' claim is unconditional again. It is false whenever a "
        "substitution rescued the price, which is exactly when it gets printed.")
    assert "FOR COMPARISON ONLY" in body, (
        "there is no wording for the substituted case, so the message can only be the "
        "one that is wrong half the time")


def test_the_substituted_wording_names_the_material_that_actually_priced_it():
    """Naming it 'the substitute below' every time would leave the estimator to match two
    messages by eye. The conflict record carries the name; use it."""
    src = (ROOT / "src" / "estimator.py").read_text(encoding="utf-8-sig", errors="replace")
    assert "_material_conflict.get('priced_material')" in src, (
        "the comparison wording must read the key the conflict record actually uses — "
        "priced_material. A .get on a key that does not exist prints the fallback forever "
        "and nothing ever fails.")


def test_the_conflict_record_really_carries_that_key():
    """The other half of the pair above. Asserting the reader alone is how a message comes
    to quietly print its fallback for the life of the code."""
    conflict = estimator._material_we_can_actually_price(
        {"part_number": "X", "materials": ["POLYCARBONATE"]}, "ABS")[1]
    assert conflict is not None, "ABS with POLYCARBONATE alongside it must still be rescued"
    assert conflict.get("priced_material"), \
        "the conflict record no longer names the material that priced the line"
