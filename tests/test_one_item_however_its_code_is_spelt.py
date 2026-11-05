"""One item is one item in the AI-price check, however its code is spelt (D-696).

12693-01-GA's 22:06 book carries the ticket holder as one line, 16 off. Its records hold the
code as "0327590-A-LINE 78X78MM TICKET HOLDER_2274" and as
"0327590-A-LINE78X78MMTICKETHOLDER_2274", and price_not_reproducible said "2 item(s)",
naming both. Spellings that differ only in spaces and punctuation are now one item, shown in
the fuller spelling. Two different codes stay two.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import invariants  # noqa: E402
import price_provenance as pp  # noqa: E402


def _stamp():
    return {"schema": pp.PRICE_SOURCE_SCHEMA, "source_class": "ai_estimate",
            "source_name": "llm_market", "applied": True,
            "selected": {"price": 1.5, "source": "llm_market"}}


def _job(*codes):
    return {"estimate_summary": {"part_estimates": [
        {"matched_part_code": c,
         "cost_breakdown": {"system_cost": {"applied_to_total": True, "source": _stamp()}}}
        for c in codes]}}


def test_two_spellings_of_one_code_are_one_item():
    out = invariants.check_prices_are_reproducible(_job(
        "0327590-A-LINE 78X78MM TICKET HOLDER_2274", "0327590-A-LINE78X78MMTICKETHOLDER_2274"))
    assert len(out) == 1
    assert out[0]["message"].startswith("1 item(s)")
    assert out[0]["detail"]["parts"] == ["0327590-A-LINE 78X78MM TICKET HOLDER_2274"]


def test_two_codes_are_still_two_items():
    out = invariants.check_prices_are_reproducible(_job("FIX12", "FIX125"))
    assert len(out) == 1 and out[0]["message"].startswith("2 item(s)")
