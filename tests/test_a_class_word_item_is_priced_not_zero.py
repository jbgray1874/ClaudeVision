"""A class-word bought-in with no commodity rate is priced by the chain, not shipped at £0.

7332-01's "P/P — BLACK FELT PAD" is a canonical bought-in minted straight onto the BOM. It has
no catalogue code and no fixed commodity row, so it read £0 — and an item at £0 bounces straight
back. It now asks the same price chain every other line uses (which names the supplier it points
at) and prices INDICATIVE with that source. Only when even that finds nothing does it fall to the
explicit "estimator to price" row — never a silent free line.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import estimator  # noqa: E402
import wb_populate  # noqa: E402


def _summary_with_felt_pad():
    return {"canonical_route_shadow": {"nodes": [
        {"part_number": "P/P", "kind": "bought_in",
         "description": "BLACK FELT PAD, SELF-ADHESIVE, 25mm DIA", "qty_per_unit": 4},
    ]}}


def test_a_class_word_item_is_priced_from_the_chain_with_a_supplier(monkeypatch):
    # the price chain returns an indicative unit + a named supplier (as it does on a live box)
    def _fake_rpsc(part):
        return {"applied_unit_cost": 0.12,
                "result": {"selected": {"source": "llm_market_estimate",
                                        "metadata": {"supplier_name":
                                                     "RS Components (AI-indicative — verify)"}}}}
    monkeypatch.setattr(estimator, "_resolve_part_system_cost", _fake_rpsc)

    out = wb_populate.canonicalise_part_estimates_for_workbook(_summary_with_felt_pad(), [])
    pad = next(p for p in out if str(p.get("part_number")) == "P/P")
    assert wb_populate._bom_line_price(pad) == 0.12         # priced, not £0
    assert pad.get("extended_total_cost_gbp") == 0.48       # x4
    assert not pad.get("_price_explicitly_withheld")
    assert "RS Components" in (pad.get("supplier") or "")   # the source is named
    assert pad.get("costing_basis") == "market_ai_indicative"


def test_it_falls_to_estimator_to_price_only_when_the_chain_is_dry(monkeypatch):
    monkeypatch.setattr(estimator, "_resolve_part_system_cost",
                        lambda part: {"applied_unit_cost": None, "result": {}})
    out = wb_populate.canonicalise_part_estimates_for_workbook(_summary_with_felt_pad(), [])
    pad = next(p for p in out if str(p.get("part_number")) == "P/P")
    assert pad.get("_price_explicitly_withheld") is True    # honest named gap, not a silent £0
    assert wb_populate._bom_line_price(pad) is None


def test_a_commodity_match_still_wins_over_the_chain(monkeypatch):
    # a PALLET has a fixed config figure — that must be used, the chain not even asked
    called = {"n": 0}
    def _spy(part):
        called["n"] += 1
        return {"applied_unit_cost": 99.0, "result": {}}
    monkeypatch.setattr(estimator, "_resolve_part_system_cost", _spy)
    summary = {"canonical_route_shadow": {"nodes": [
        {"part_number": "STD PART", "kind": "bought_in",
         "description": "PALLET 1200x1000", "qty_per_unit": 1}]}}
    out = wb_populate.canonicalise_part_estimates_for_workbook(summary, [])
    pallet = next(p for p in out if str(p.get("part_number")) == "STD PART")
    assert wb_populate._bom_line_price(pallet) == 12.0      # commodity, not the chain's 99
    assert called["n"] == 0                                 # chain never consulted
