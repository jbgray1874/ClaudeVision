"""A per-piece LLM price is asked once per spec and stored, so it prices the line.

8352's stand carries castors, clips, a graphic and three trays — everyday bought-ins with no
catalogue rate. The web/LLM fallback priced them, but the figure changed every run (a cable line
moved GBP 4.54 -> 8.54), so the workbook WITHHELD it: an unrepeatable number is kept off the
total as a hint beside a zero, and on a pack that is mostly hardware that reads as free.

The sheet rates solved this with a content-addressed cache — ask once per specification, store
it, and the same part returns the same number next run. The per-piece bought-in path never used
it. Now it does: routed through generated_price_cache, the figure holds still, is reported
reproducible from the first run, and so PRICES the line (tagged indicative) instead of being
withheld. That is the 'always a number' policy, applied to the bought-ins it kept missing.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pricing_service  # noqa: E402
import generated_price_cache as gpc  # noqa: E402
import web_ai_price_lookup  # noqa: E402


def _part():
    return {"part_number": "3086", "description": "42x76mm ticket clips (Artisan)",
            "quantity": 3, "normalized_material": None}


@pytest.fixture()
def stubbed_market(monkeypatch, tmp_path):
    """The market answers a fixed number, and the cache lives in a temp dir. A test that reached
    the internet is a test that fails on a train."""
    calls = {"n": 0}

    def _fake_lookup(spec, **kwargs):
        calls["n"] += 1
        return {"found": True, "price_gbp": 5.0, "source_type": "llm_market_estimate",
                "confidence": 0.5, "review_reason": "indicative"}

    monkeypatch.setattr(web_ai_price_lookup, "lookup_web_ai_price", _fake_lookup)
    monkeypatch.setattr(gpc, "default_cache_dir", lambda: str(tmp_path / "gp"))
    return calls


def test_the_price_comes_back_reproducible_so_the_column_can_use_it(stubbed_market):
    svc = pricing_service.PricingService(conn=object())
    out = svc._get_web_ai_fallback(_part())
    assert out is not None and out["unit_price_gbp"] == 5.0
    assert out["price_is_reproducible"] is True, (
        "an uncached LLM price is withheld from the total; it must be reproducible to be priced")


def test_the_market_is_asked_once_per_spec_not_once_per_run(stubbed_market):
    """The whole reason it holds still: the second run reads the store, it does not ask again and
    get a different number."""
    svc = pricing_service.PricingService(conn=object())
    first = svc._get_web_ai_fallback(_part())
    second = svc._get_web_ai_fallback(_part())
    assert stubbed_market["n"] == 1, "the market was asked twice for one specification"
    assert first["unit_price_gbp"] == second["unit_price_gbp"] == 5.0
    assert second["price_is_reproducible"] is True


def test_a_different_part_is_a_different_question(stubbed_market):
    """The cache keys on the specification, so it does not hand a clip's price to a castor."""
    svc = pricing_service.PricingService(conn=object())
    svc._get_web_ai_fallback(_part())
    other = dict(_part(), part_number="CASTOR", description="Tente Linea castor 5925UAP050L51")
    svc._get_web_ai_fallback(other)
    assert stubbed_market["n"] == 2, "two different parts shared one cached price"


def test_a_miss_is_not_stored_as_a_price(monkeypatch, tmp_path):
    """A lookup that finds nothing is not remembered as an answer — tomorrow asks again rather
    than inheriting today's network problem as a fact about the part."""
    monkeypatch.setattr(web_ai_price_lookup, "lookup_web_ai_price",
                        lambda spec, **k: {"found": False, "price_gbp": None})
    monkeypatch.setattr(gpc, "default_cache_dir", lambda: str(tmp_path / "gp"))
    svc = pricing_service.PricingService(conn=object())
    assert svc._get_web_ai_fallback(_part()) is None
