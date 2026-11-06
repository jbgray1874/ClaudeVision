"""A thing sold off a roll is priced by the metre, each piece paying for its own length (D-728).

12677-01-GA, 31 Oct 2026: four 233 x 20 mm strips of VHB gel tape were researched "per each",
came back at GBP 9.50 (the price of a roll) and were charged four times, GBP 39.52 for 0.93 m of
tape. JG, 5 Nov: "price the gel tape by length at a per-metre rate." The strip's own printed size
gives its length; the market is asked the price per metre; a roll price is refused by the
producer's unit check; and a line with no metre rate is asked, never charged a roll per strip.

Synthetic lines and a stand-in researcher; no network and no job's files.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import estimator                                                         # noqa: E402


def _gel_tape():
    return {"part_number": "GEL TAPE", "description": "VHB GEL TAPE  233 × 20",
            "quantity": 4, "page_roles": ["bought_in"], "is_bought_in": True,
            "normalized_material": "BOUGHT_IN"}


def _answers(**found):
    seen = {}

    def ask(brief):
        seen["brief"] = brief
        return dict(found)
    return ask, seen


PER_METRE = {"price_gbp": 2.40, "unit": "m", "source": "Example supplier listing",
             "as_of": "2026-11-05", "quantity_basis": "1 m off a 33 m roll"}
PER_ROLL = {"price_gbp": 9.50, "unit": "roll", "source": "Example supplier listing",
            "as_of": "2026-11-05", "quantity_basis": "1 roll"}


@pytest.mark.parametrize("desc, length", [("VHB GEL TAPE  233 × 20", 233.0),
                                          ("Foam Tape 890x10x1.5mm", 890.0),
                                          ("EPDM TAPE LENGTH: 200.00", 200.0)])
def test_the_piece_length_is_read_off_the_strip(desc, length):
    assert estimator.roll_piece_length_mm({"description": desc})[0] == length


def test_a_line_without_a_size_has_no_piece_length():
    assert estimator.roll_piece_length_mm({"description": "VHB GEL TAPE"}) == (None, "")


def test_the_market_is_asked_per_metre_for_one_pieces_length(monkeypatch):
    ask, seen = _answers(**PER_METRE)
    monkeypatch.setattr(estimator, "_rung4_researcher", ask)
    part = _gel_tape()
    r = estimator._resolve_part_system_cost(part)
    assert seen["brief"]["wanted_unit"] == "metre"
    assert seen["brief"]["quantity_needed"] == pytest.approx(0.233)
    assert r["applied_unit_cost"] == pytest.approx(0.233 * 2.40, abs=1e-4)   # one strip
    assert part["roll_goods_by_length"]["metres_per_unit"] == pytest.approx(0.932)
    assert any(f.startswith("ROLL GOODS priced by length") for f in part["review_flags"])


def test_the_line_charges_four_strips_not_four_rolls(monkeypatch):
    ask, _ = _answers(**PER_METRE)
    monkeypatch.setattr(estimator, "_rung4_researcher", ask)
    pe = estimator.estimate_part(_gel_tape())
    me = pe["material_estimate"]
    assert me["unit_material_cost_gbp"] == pytest.approx(0.5592, abs=1e-4)
    assert me["extended_material_cost_gbp"] == pytest.approx(4 * 0.5592, abs=1e-3)
    assert not any(str(f).startswith("ROLL GOODS: NOT PRICED")
                   for f in pe.get("review_flags") or [])


def test_a_roll_price_is_refused_and_the_line_is_asked_not_rescued(monkeypatch):
    """With no SDI row, no roll length stated and no dated market rate held (D-733), the line
    is asked, never charged a roll per strip."""
    ask, _ = _answers(**PER_ROLL)
    monkeypatch.setattr(estimator, "_rung4_researcher", ask)
    monkeypatch.setattr(estimator.config, "ROLL_GOODS_RESEARCHED_METRE_RATES", ())
    part = _gel_tape()
    r = estimator._resolve_part_system_cost(part)
    assert r["applied_unit_cost"] is None
    assert "roll_goods_per_metre_unpriced" in part["risk_flags"]
    assert any("no price per metre" in q["issue"] for q in part["manufacturing_questions"])
    assert estimator._last_resort_price_is_needed(
        {"part_number": "GEL TAPE", "risk_flags": part["risk_flags"]}) is False


def test_a_catalogued_roll_keeps_its_own_roll_arithmetic(monkeypatch):
    """TAPE113C's roll length is held; the market is not asked per metre for it."""
    ask, seen = _answers(**PER_METRE)
    monkeypatch.setattr(estimator, "_rung4_researcher", ask)
    part = {"part_number": "TAPE113C", "description": "EPDM TAPE 25 x 1 LENGTH: 200",
            "quantity": 3, "page_roles": ["bought_in"], "is_bought_in": True}
    estimator._resolve_part_system_cost(part)
    assert (seen.get("brief") or {}).get("wanted_unit") != "metre"
    assert "roll_goods_by_length" not in part


def test_a_counted_item_that_is_not_a_roll_is_still_asked_per_each(monkeypatch):
    ask, seen = _answers(price_gbp=0.35, unit="each", source="Example", as_of="2026-11-05",
                         quantity_basis="1 off")
    monkeypatch.setattr(estimator, "_rung4_researcher", ask)
    part = {"part_number": "BUMPER", "description": "ROUND BUMPER 19 x 1.9",
            "quantity": 4, "page_roles": ["bought_in"], "is_bought_in": True}
    r = estimator._resolve_part_system_cost(part)
    assert seen["brief"]["wanted_unit"] == "each"
    assert r["applied_unit_cost"] == pytest.approx(0.35)


@pytest.mark.parametrize("extra, said", [
    ({"normalized_geometry": {"bbox_mm": [233.0, 20.0, 1.0]}}, "the model's extents"),
    ({"blank_length_mm": 233.0, "blank_width_mm": 20.0}, "the part's own blank"),
    ({"normalized_geometry": {"blank_length_mm": 20.0, "blank_width_mm": 233.0}},
     "the part's measured blank")])
def test_a_modelled_strip_gives_its_length_from_its_own_extents(extra, said):
    """12677-01, 6 Nov 10:38: the description said only "VHB GEL TAPE"; the 233 x 20 the BOM
    line printed came from the record's own extents, which this reader did not look at."""
    part = dict({"part_number": "GEL TAPE", "description": "VHB GEL TAPE"}, **extra)
    length, where = estimator.roll_piece_length_mm(part)
    assert length == 233.0 and where.startswith(said)


def test_a_modelled_strip_is_asked_by_the_metre(monkeypatch):
    ask, seen = _answers(**PER_METRE)
    monkeypatch.setattr(estimator, "_rung4_researcher", ask)
    part = {"part_number": "GEL TAPE", "description": "VHB GEL TAPE", "quantity": 4,
            "page_roles": ["bought_in"], "is_bought_in": True,
            "normalized_geometry": {"bbox_mm": [233.0, 20.0, 1.0]}}
    r = estimator._resolve_part_system_cost(part)
    assert seen["brief"]["wanted_unit"] == "metre"
    assert r["applied_unit_cost"] == pytest.approx(0.233 * 2.40, abs=1e-4)


class _Service:
    """A stand-in pricing service: its anchor answer is the one given."""
    def __init__(self, anchor):
        self._anchor = anchor

    def _select_anchor_price_source(self, part):
        return dict(self._anchor)


def test_the_pricing_services_per_piece_market_answer_is_passed_over_for_a_roll(monkeypatch):
    """12677-01, 6 Nov 10:38: the service's own market fallback answered GBP 9.50 "each"
    before the per-metre rung was reached. A roll line with a piece length now passes it over
    and is asked by the metre."""
    monkeypatch.setattr(estimator, "_get_pricing_service", lambda: _Service(
        {"unit_price_gbp": 9.50, "source": "llm_estimate", "source_type": "web_ai_fallback"}))
    ask, seen = _answers(**PER_METRE)
    monkeypatch.setattr(estimator, "_rung4_researcher", ask)
    part = _gel_tape()
    r = estimator._resolve_part_system_cost(part)
    assert r["applied_unit_cost"] == pytest.approx(0.233 * 2.40, abs=1e-4)
    assert any("per-piece figure £9.50 is not used" in f for f in part["review_flags"])


def test_an_sdi_catalogue_answer_for_a_roll_line_still_stands(monkeypatch):
    monkeypatch.setattr(estimator, "_get_pricing_service", lambda: _Service(
        {"unit_price_gbp": 0.40, "source": "udef_parts_table_for_estimating",
         "source_type": "catalogue"}))
    monkeypatch.setattr(estimator, "_rung4_researcher",
                        lambda b: pytest.fail("SDI's own price answered; no research"))
    r = estimator._resolve_part_system_cost(_gel_tape())
    assert r["applied_unit_cost"] == pytest.approx(0.40)
