"""A market sheet price is a market figure, wherever the line is nested (D-598q).

9287-10-GA's 19:05 live run, 24 Oct 2026: the solid-surface base was nested 22 to a 3680 x 760
slab at £523.11 a sheet, and that sheet price was an AI market lookup. The record called the
line firm because it sat on a nested block, so the headline asked only for the bumpons' £1.16
to be replaced; the market-lookup advisory read the raw part, which carries no price record,
and stayed silent. A catalogue median for a material class is named by its rows, and asked
where the drawing states a grade the rows do not.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import costed_facts                                                   # noqa: E402
import estimator                                                      # noqa: E402
from invariants import check_a_material_we_cannot_price_is_declared   # noqa: E402


def _origin(method, flags=(), sheet=523.11):
    part = {"part_number": "7777-10-005", "material_estimate": {
        "cost_method": method, "reliability_flags": list(flags), "sheet_price_gbp": sheet}}
    return costed_facts._price_origin(part, "leaf", "other_sheet", 24.73, 24.73, 139, False)


def test_a_market_sheet_price_on_a_nested_block_is_to_be_replaced():
    o = _origin("llm_market_sheet_rate", ["llm_market_rate_not_a_supplier_price"])
    assert o["firmness"] == costed_facts.INDICATIVE_MARKET
    assert "£523.11" in o["label"] and "Estimate!139" in o["label"]
    assert _origin("board_rate_researched", ["llm_indicative"])["firmness"] == \
        costed_facts.INDICATIVE_MARKET


def test_a_catalogue_or_config_sheet_price_stays_firm():
    assert _origin("sheet_rate_live_udef")["firmness"] == costed_facts.FIRM
    assert _origin("acrylic_area_per_m2_provisional")["firmness"] == costed_facts.FIRM


def test_the_market_advisory_reads_the_costed_row():
    raw = {"part_number": "7777-10-005", "normalized_material": "SOLID SURFACE"}
    costed = {"part_number": "7777-10-005", "normalized_material": "SOLID SURFACE",
              "material_market_indication": {"gbp_per_m2": 187.04, "material": "SOLID SURFACE",
                                             "source": "llm"},
              "material_estimate": {"cost_method": "llm_market_sheet_rate",
                                    "cost_per_part_gbp": 24.73}}
    found = check_a_material_we_cannot_price_is_declared(
        {"parts": [raw], "manufacturing_writeup": {"parts": [raw]},
         "estimate_summary": {"part_estimates": [costed]}})
    assert any("MARKET LOOKUP" in v["message"] and "7777-10-005" in v["message"]
               for v in found)


ROWS = [("EG-H3303-18", "EGGER MFC H3303 NATURAL OAK 2800 x 2070 x 18mm", 150.0),
        ("EG-W980-18", "EGGER MFC W980 PLATINUM WHITE 2800 x 2070 x 18mm", 120.0),
        ("FILM-1", "MFC EDGE FILM 22 x 100000 x 1mm", 9.0)]


def test_the_catalogue_rows_behind_a_median_are_kept():
    kept = estimator._plain_stock_rows(ROWS, "MFC", 18.0)
    assert [k["part_code"] for k in kept] == ["EG-H3303-18", "EG-W980-18"]
    assert estimator._plain_stock_rates_gbp_per_m2(ROWS, "MFC", 18.0) == \
        [k["gbp_per_m2"] for k in kept]


@pytest.fixture
def _catalogue(monkeypatch):
    estimator._SHEET_RATE_CACHE.clear()
    estimator._SHEET_RATE_ROWS.clear()
    kept = estimator._plain_stock_rows(ROWS, "PETG", 2.0) or [
        {"part_code": "PG-2", "description": "PETG CLEAR 2440 x 1220 x 2mm", "gbp_per_m2": 9.63}]
    estimator._SHEET_RATE_CACHE[("PETG", 2.0)] = 9.63
    estimator._SHEET_RATE_ROWS[("PETG", 2.0)] = kept
    monkeypatch.setattr(estimator, "market_indication_for", lambda part, material: None)
    yield
    estimator._SHEET_RATE_CACHE.clear()
    estimator._SHEET_RATE_ROWS.clear()


def _panel(stated=None):
    part = {"part_number": "7777-20-001", "normalized_material": "PETG",
            "normalized_thickness_mm": 2.0, "quantity": 1,
            "blank_length_mm": 1250.0, "blank_width_mm": 525.0,
            "material_estimate": {}, "manufacturing_interpretation": {}}
    if stated:
        part["material_stated"] = stated
    me = estimator.estimate_material(part)
    return part, me


def test_a_stated_grade_priced_from_its_class_is_asked(_catalogue):
    part, me = _panel("VIVAK UV CLEAR 2MM")
    assert me["cost_method"] == "sheet_rate_live_udef"
    assert me["catalogue_rows"][0]["part_code"] == "PG-2" and "PG-2" in me["note"]
    q = [x for x in part.get("manufacturing_questions") or []
         if x.get("subject") == "catalogue_class_rate"]
    assert q and "not from VIVAK UV CLEAR 2MM itself" in q[0]["assumption"]
    estimator.estimate_material(part)
    assert len([x for x in part["manufacturing_questions"]
                if x.get("subject") == "catalogue_class_rate"]) == 1, "asked once"


def test_no_stated_grade_or_the_class_itself_is_not_asked(_catalogue):
    for stated in (None, "PETG 2MM"):
        part, _ = _panel(stated)
        assert not any(x.get("subject") == "catalogue_class_rate"
                       for x in part.get("manufacturing_questions") or [])
