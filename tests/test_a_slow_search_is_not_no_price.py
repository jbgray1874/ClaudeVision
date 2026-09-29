"""A slow web search is not "no price" (D-333).

12645, 29 Sep 2026: the two roller shutters went to £0, "no catalogue, price file or quote we
can query holds this item", while every fastener on the same book carried a market figure. A
roller shutter is a new, harder search than a screw. The lookup runs under a hard wall-clock
budget, and a miss is never stored, so a search that ran past it left the line at £0 on every
run. James Gray: "Neither should remain at £0 in a working estimate."

When the full search runs out of time, the model's own market estimate is asked the same
brief without the web round-trips. It prices the line tagged indicative, like any other market
figure, for the estimator to replace. Only if that also fails does the line stay unpriced.
"""
from __future__ import annotations

import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import config  # noqa: E402
import generated_price_cache as gpc  # noqa: E402
import pricing_service  # noqa: E402
import web_ai_price_lookup  # noqa: E402


def _shutter():
    return {"part_number": "Roller Shutter", "description": "Roller Shutter Door",
            "quantity": 2, "normalized_material": None, "page_roles": ["bought_in"],
            "is_bought_in": True}


@pytest.fixture()
def fast_budget(monkeypatch, tmp_path):
    policy = dict(getattr(config, "FALLBACK_PRICING_POLICY", {}) or {})
    policy["web_ai_call_timeout_s"] = 0.3
    monkeypatch.setattr(config, "FALLBACK_PRICING_POLICY", policy)
    monkeypatch.setattr(gpc, "default_cache_dir", lambda: str(tmp_path / "gp"))


def test_a_search_past_its_budget_falls_to_the_market_estimate(monkeypatch, fast_budget, capsys):
    asked = []

    def _lookup(spec, *, enable_web_search=True, enable_llm_estimate=True, **_kw):
        asked.append(enable_web_search)
        if enable_web_search:
            time.sleep(1.0)                               # the web search runs past the budget
            return {}
        return {"found": True, "price_gbp": 2500.0, "source_type": "llm_market_estimate",
                "confidence": 0.5, "review_reason": "indicative", "price_is_reproducible": True,
                "item_priced": "industrial steel roller shutter door, supply only"}

    monkeypatch.setattr(web_ai_price_lookup, "lookup_web_ai_price", _lookup)
    out = pricing_service.PricingService(conn=object())._get_web_ai_fallback(_shutter())
    assert asked == [True, False], asked
    assert out and out["unit_price_gbp"] == 2500.0
    assert out["review_flag"] is True                     # indicative, for the estimator to replace
    assert "asking the model's market estimate" in capsys.readouterr().out


def test_when_both_run_out_of_time_the_line_stays_unpriced_and_says_so(monkeypatch, fast_budget,
                                                                       capsys):
    def _slow(spec, **_kw):
        time.sleep(1.0)
        return {}

    monkeypatch.setattr(web_ai_price_lookup, "lookup_web_ai_price", _slow)
    svc = pricing_service.PricingService(conn=object())
    assert svc._get_web_ai_fallback(_shutter()) is None
    assert "market estimate also timed out" in capsys.readouterr().out
    assert svc._web_ai_consec_timeouts == 1               # the breaker still counts it
