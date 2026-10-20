"""An AI/market price names a supplier, not just "an AI".

A web/AI fallback price used to reach the sheet as supplier "web/AI estimate" / "xai llm". The
web-SEARCH path already carries the real scraped supplier; the LLM-ESTIMATE path returns the
suppliers it says to verify against (verify_against) — name the first, tagged indicative, so an
estimator reading "where did this come from" gets a company, not just the model.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pricing_service as ps  # noqa: E402


def test_it_names_the_supplier_the_estimate_points_at():
    out = ps._ai_indicative_supplier({"verify_against": ["RS Components", "Metals4U"],
                                      "llm_provider": "xai"})
    assert out.startswith("RS Components")
    assert "AI-indicative" in out            # honest that it is not a firm quote


def test_it_counts_the_other_suppliers():
    out = ps._ai_indicative_supplier({"verify_against": ["RS Components", "Metals4U", "Cromwell"]})
    assert "RS Components" in out and "+2 more" in out


def test_it_falls_back_to_the_provider_when_none_named():
    assert ps._ai_indicative_supplier({"verify_against": [], "llm_provider": "grok-4.3"}) \
        == "AI market estimate (grok-4.3)"
    assert ps._ai_indicative_supplier({}) == "AI market estimate"
