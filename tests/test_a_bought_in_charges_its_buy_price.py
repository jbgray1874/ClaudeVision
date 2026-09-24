"""A bought-in on an assembly's BOM charges its buy price, and the line names where it came from.

11650-06 (Rev B), 24 Sep 2026. The Yiree binding screw was researched at £1.25 each and the
workbook charged £2.29: two minutes of handling were added to the buy price of a screw that
sits in a spare set packed with the kit, whose packing time is already on the labour rows. And
the AI Provenance tab said the price came from "config_default_material_rates" — the material
block's fallback, written before the line was found to be bought in — not the AI market price
that set it. Review: "Reconcile bought-in fitting. Correct price provenance."
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import config                                                        # noqa: E402
import estimator                                                     # noqa: E402
from research_context import owning_assembly, stamp_research_context  # noqa: E402

_AI = {"selected": {"price": 1.25, "unit": "each", "source": "xAI Grok LLM - INDICATIVE",
                    "evidence": {"pricing_mode": "web_ai_llm_estimate"}}}


def _screw(**extra):
    p = {"part_number": "YIREE CODE - DWG491667", "description": "YIREE BINDING SCREW",
         "quantity": 20, "is_bought_in": True, "normalized_material": "BOUGHT_IN",
         "page_roles": ["bought_in"]}
    p.update(extra)
    return p


@pytest.fixture
def ai_priced(monkeypatch):
    monkeypatch.setattr(estimator, "_resolve_part_system_cost",
                        lambda part: {"applied_unit_cost": 1.25, "result": _AI,
                                      "matched_part_code": None})


def _unit(est):
    return est["cost_breakdown"]["unit_total_cost_gbp"]


def test_a_screw_on_an_assemblys_bom_charges_what_it_costs(ai_priced):
    est = estimator.estimate_part(_screw(owning_assembly="11650-06-SA02"), job_quantity=2)
    assert est["cost_breakdown"]["costing_basis"] == "system_cost_per_part"
    assert _unit(est) == pytest.approx(1.25)
    assert not est["cost_breakdown"]["system_cost"]["fitting_gbp_each"]


def test_a_loose_bought_in_still_takes_its_fitting(ai_priced):
    est = estimator.estimate_part(_screw(), job_quantity=2)
    rate = float(estimator.HOURLY_RATES_GBP.get("handling", 31.18))
    fit = config.BOUGHT_IN_FITTING_MIN_PER_PART / 60.0 * rate
    assert _unit(est) == pytest.approx(1.25 + fit, abs=0.01)
    assert est["cost_breakdown"]["system_cost"]["fitting_gbp_each"] == pytest.approx(fit, abs=1e-3)


def test_zero_minutes_in_config_means_no_fitting(ai_priced, monkeypatch):
    monkeypatch.setattr(config, "BOUGHT_IN_FITTING_MIN_PER_PART", 0)
    assert _unit(estimator.estimate_part(_screw(), job_quantity=2)) == pytest.approx(1.25)


def test_the_line_names_the_price_that_set_it(ai_priced):
    est = estimator.estimate_part(_screw(owning_assembly="11650-06-SA02"), job_quantity=2)
    ps = est["material_estimate"]["price_source"]
    assert ps["source_name"] == "xAI Grok LLM - INDICATIVE"
    assert "config_default_material_rates" not in str(ps)
    from estimation_report import _price_basis_label
    assert "config" not in _price_basis_label(ps).lower()


def test_the_owning_assembly_is_read_from_the_bom_not_a_file_name():
    rows = [{"part_number": "YIREE CODE - DWG491667", "bom_parent": "11650-06-SA02"}]
    assert owning_assembly({"part_number": "YIREE CODE - DWG491667"}, rows) == "11650-06-SA02"
    assert owning_assembly({"part_number": "X1", "bom_parent": "11650-06-GA KIT_REVB.PDF"}) == ""
    assert owning_assembly({"part_number": "X1", "bom_parents": [{"parent": "A-101"}]}) == "A-101"
    parts = [_screw()]
    stamp_research_context(parts, {"document_analysis": {"bom_rows": rows}})
    assert parts[0]["owning_assembly"] == "11650-06-SA02"
