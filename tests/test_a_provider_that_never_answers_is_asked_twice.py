r"""
test_a_provider_that_never_answers_is_asked_twice.py

TWENTY-FIVE SECONDS A PART, TO LEARN NOTHING, ON EVERY PART.

web_search_providers already latches an ACCOUNT-level refusal — 429, 401, 403 — because
asking again with a different material cannot change the answer. A timeout was deliberately
excluded from that: a blip is transient and must not turn web pricing off for a whole job.

The failure actually seen is not a blip. On 12552 every SerpAPI call timed out, and
FALLBACK_PRICING_POLICY["web_ai_call_timeout_s"] is 25 — so each unpriced part waited the
full timeout for a provider that was never going to reply, inside a run that already takes
twenty to forty minutes.

So: two CONSECUTIVE failures latch, and any success resets the count. A merely slow network
keeps its lookups; an unreachable one pays for that discovery once instead of once per part.

THE KEY IS THE BUG THIS TEST EXISTS TO CATCH. search_serpapi opens with
`if "serpapi" in _PROVIDER_REFUSED` — lowercase. A latch written under "SerpAPI" would be
set, announced on the console, and never consulted: the run would say lookups were off and
carry on making them, which is worse than not latching at all because the log would lie.
The last assertion here is on the key, not the count.
"""
from __future__ import annotations

import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import web_search_providers as wsp  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_latch():
    wsp.forget_provider_refusals()
    yield
    wsp.forget_provider_refusals()


def _timeout(*_a, **_kw):
    raise TimeoutError("The read operation timed out")


def test_one_timeout_does_not_turn_pricing_off(monkeypatch):
    """A blip must not cost the job its web lookups."""
    monkeypatch.setenv("SERPAPI_API_KEY", "test-key")
    monkeypatch.setattr(wsp, "_http_get_json", _timeout)

    hits, err = wsp.search_serpapi("2mm mild steel sheet price uk")
    assert hits == [] and "timed out" in str(err)
    assert "serpapi" not in wsp._PROVIDER_REFUSED, (
        "One timeout latched. A single slow response is not evidence the provider is "
        "unreachable, and turning pricing off on it costs the job every web-derived figure."
    )


def test_the_second_consecutive_timeout_latches(monkeypatch, capsys):
    """The observed failure mode: it never answers, so stop paying the timeout per part."""
    monkeypatch.setenv("SERPAPI_API_KEY", "test-key")
    monkeypatch.setattr(wsp, "_http_get_json", _timeout)

    wsp.search_serpapi("first")
    wsp.search_serpapi("second")

    assert "serpapi" in wsp._PROVIDER_REFUSED, (
        "Two consecutive timeouts and the provider is still being asked. Every further part "
        "waits the full 25s timeout to be told the same nothing."
    )
    said = capsys.readouterr().out
    assert "web price lookup is off" in said and "estimator" in said, (
        f"The latch must say what it did and what happens to the affected lines: {said!r}"
    )


def test_the_latch_is_keyed_where_the_guard_looks(monkeypatch):
    """Written under the key search_serpapi actually checks — lowercase 'serpapi'.

    A latch under 'SerpAPI' would announce itself and then be ignored on the very next call,
    so the run's log would claim lookups were off while it kept making them.
    """
    monkeypatch.setenv("SERPAPI_API_KEY", "test-key")
    monkeypatch.setattr(wsp, "_http_get_json", _timeout)
    wsp.search_serpapi("first")
    wsp.search_serpapi("second")

    assert "serpapi" in wsp._PROVIDER_REFUSED

    # The proof it is honoured: a third call must not reach the network at all.
    def _explode(*_a, **_kw):
        raise AssertionError("the provider was called again after the latch was set")

    monkeypatch.setattr(wsp, "_http_get_json", _explode)
    hits, err = wsp.search_serpapi("third")
    assert hits == [] and "unreachable" in str(err)


def test_a_success_between_failures_resets_the_count(monkeypatch):
    """Intermittent is not unreachable. Only CONSECUTIVE failures count."""
    monkeypatch.setenv("SERPAPI_API_KEY", "test-key")

    monkeypatch.setattr(wsp, "_http_get_json", _timeout)
    wsp.search_serpapi("first — fails")

    monkeypatch.setattr(wsp, "_http_get_json",
                        lambda *_a, **_kw: {"organic_results": [{"link": "https://x.co/p"}]})
    hits, _ = wsp.search_serpapi("second — works")
    assert hits, "the successful call should have returned a hit"

    monkeypatch.setattr(wsp, "_http_get_json", _timeout)
    wsp.search_serpapi("third — fails again")

    assert "serpapi" not in wsp._PROVIDER_REFUSED, (
        "A flaky provider was latched off. The success in the middle proves it is reachable; "
        "only two failures in a row mean it is not."
    )


def test_an_account_refusal_still_latches_on_the_first(monkeypatch, capsys):
    """The existing rule is untouched: 429 is an answer, and one is enough."""
    monkeypatch.setenv("SERPAPI_API_KEY", "test-key")

    def _429(*_a, **_kw):
        raise urllib.error.HTTPError("u", 429, "Too Many Requests", None, None)

    monkeypatch.setattr(wsp, "_http_get_json", _429)
    wsp.search_serpapi("only once")
    assert "serpapi" in wsp._PROVIDER_REFUSED
    assert "ACCOUNT" in capsys.readouterr().out
