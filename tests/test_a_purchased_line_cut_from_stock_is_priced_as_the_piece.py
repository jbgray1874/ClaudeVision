"""A purchased line that states a cut length is a piece cut from stock, priced as one (D-441).

8188-08 STRENGTHENER, "EXTRUSION 92: LENGTH =100mm" x 24. D-436 made it a purchased line;
the bought-in chain priced it as quantity x the figure found for EXTRUSION 92 — a figure for
whatever the seller sells (a metre, a stock length). Twenty-four 100 mm pieces are 2.4 m of
extrusion, not twenty-four stock lengths and not twenty-four metres. James Gray, 9 Oct: "x24 at
100 mm means 2.4 m of cut pieces, with an appropriate stock-buying allowance … must not charge
24 full stock lengths."
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import pytest                                                         # noqa: E402

import config                                                         # noqa: E402
import cut_piece_pricing as cpp                                       # noqa: E402

_WASTE = 1.0 + float(config.SECTION_STOCK_POLICY["waste_factor_pct"]) / 100.0
_STD = float(config.SECTION_STOCK_LENGTH_MIN_MM)


# ── reading the line ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text, mm", [
    ("EXTRUSION 92: LENGTH =100mm", 100.0),
    ("EXTRUSION 92 LENGTH: 100", 100.0),
    ("ALUMINIUM ANGLE 25x25x3 L=1200", 1200.0),
    ("PIANO HINGE 1.8M LONG", 1800.0),
    ("TRIM x 450 LG", 450.0),
    ("M6 X 12 THREADED INSERT", None),            # a 12 is a thread length, not a cut
    ("EXTRUSION 92", None),
    ("TUBE LENGTH =100mm LENGTH =200mm", None),   # two lengths name none
])
def test_the_stated_cut_length_is_read_or_refused(text, mm):
    assert cpp.stated_cut_length_mm(text) == mm


def test_a_thing_bought_by_the_length_is_known_by_its_words():
    assert cpp.names_a_thing_bought_by_the_length("EXTRUSION 92: LENGTH =100mm")
    assert cpp.names_a_thing_bought_by_the_length("25X25MM WIRE MESH PANEL") is False
    assert cpp.names_a_thing_bought_by_the_length("KINGDOM: 50mm x 10mm x 2m MAGNET") is False


@pytest.mark.parametrize("selected, kind, stock", [
    ({"uom": "M"}, "per_metre", None),
    ({"uom": "each"}, "each", None),
    ({"uom": "3M"}, "per_length", 3000.0),
    ({"uom": "LGTH", "provenance": "UDEF: X — EXTRUSION 92 6000MM | uom=LGTH"}, "per_length", None),
    ({"provenance": "UDEF: ABC — EXTRUSION 92 | supplier=Y | uom=M"}, "per_metre", None),
    ({}, "unknown", None),
])
def test_the_unit_of_sale_is_read_off_the_candidate(selected, kind, stock):
    got = cpp.unit_of_sale(selected)
    assert got["kind"] == kind and got["stock_length_mm"] == stock, got


# ── pricing the piece ───────────────────────────────────────────────────────────────────

_DESC = "EXTRUSION 92: LENGTH =100mm"


def test_sold_by_the_metre_the_piece_is_its_metres_plus_cut_loss():
    got = cpp.price_as_cut_piece(_DESC, {"uom": "M"}, 10.0, 24, 1)
    assert got["unit_of_sale"] == "per_metre" and got["question"] is None
    assert got["unit_gbp"] == pytest.approx(10.0 * 0.1 * _WASTE, abs=1e-4)
    assert "2.40 m" in got["basis"]


def test_sold_by_a_stated_length_the_piece_is_its_share_and_the_lengths_bought_are_said():
    got = cpp.price_as_cut_piece(_DESC, {"uom": "3M"}, 30.0, 24, 1)
    assert got["unit_of_sale"] == "per_length" and got["stock_length_mm"] == 3000.0
    assert got["unit_gbp"] == pytest.approx(30.0 * 100 / 3000 * _WASTE, abs=1e-4)
    assert got["lengths_bought"] == 1 and got["question"] is None
    # 24 x 100 mm x 1.04 = 2.496 m: one 3 m length; ten units of the product need nine
    assert cpp.price_as_cut_piece(_DESC, {"uom": "3M"}, 30.0, 24, 10)["lengths_bought"] == 9


def test_sold_each_is_read_as_a_stock_length_as_a_working_figure_and_asked():
    got = cpp.price_as_cut_piece(_DESC, {"uom": "each"}, 30.0, 24, 1)
    assert got["unit_of_sale"] == "each" and got["stock_length_mm"] == _STD
    assert got["unit_gbp"] == pytest.approx(30.0 * 100 / _STD * _WASTE, abs=1e-4)
    assert got["unit_gbp"] < 30.0, "never silently 24 stock lengths"
    q = got["question"]
    assert q and "per piece, per metre or per stock length" in q["issue"]
    assert "WORKING FIGURE" in got["basis"]
    assert f"GBP {30.0 * 24:.2f} a unit" in q["assumption"], q["assumption"]


def test_a_row_whose_words_state_the_stock_length_uses_it():
    got = cpp.price_as_cut_piece(_DESC, {"uom": "each", "item_priced": "EXTRUSION 92 6000MM"},
                                 30.0, 24, 1)
    assert got["stock_length_mm"] == 6000.0
    assert got["unit_gbp"] == pytest.approx(30.0 * 100 / 6000 * _WASTE, abs=1e-4)
    assert got["question"] is not None, "the unit of sale was still 'each' — still asked"


def test_a_line_that_states_no_cut_length_or_names_no_stock_is_left_alone():
    assert cpp.price_as_cut_piece("EXTRUSION 92", {"uom": "M"}, 10.0, 24) is None
    assert cpp.price_as_cut_piece("KINGDOM: 50mm x 10mm x 2m MAGNET", {"uom": "each"}, 48.5, 14) is None
    assert cpp.price_as_cut_piece("M6 X 12 THREADED INSERT", {"uom": "each"}, 0.2, 4) is None


# ── through the estimator ───────────────────────────────────────────────────────────────

def _strengthener():
    return {"part_number": "STRENGTHENER", "description": "EXTRUSION 92: LENGTH =100mm",
            "quantity": 24, "pages": [2], "page_roles": ["detail", "bought_in"],
            "is_bought_in": True, "normalized_material": "BOUGHT_IN"}


def _stub(price, uom):
    def _resolve(part):
        return {"result": {"selected": {"source": "UDEF_PARTS_TABLE_FOR_ESTIMATING",
                                        "price": price, "uom": uom,
                                        "provenance": f"UDEF: EXT92 — EXTRUSION 92 | uom={uom}"}},
                "applied_unit_cost": price, "matched_part_code": "EXTRUSION 92"}
    return _resolve


def test_the_estimator_prices_the_piece_not_the_stock(monkeypatch):
    import estimator
    monkeypatch.setattr(estimator, "_resolve_part_system_cost", _stub(30.0, "each"))
    part = _strengthener()
    pe = estimator.estimate_part(part, 1)
    me = pe["material_estimate"]
    assert me["cost_method"] == "bought_in_unit_price"
    expect = round(30.0 * 100 / _STD * _WASTE, 4)
    assert me["unit_material_cost_gbp"] == pytest.approx(expect, abs=1e-3), me
    assert me["extended_material_cost_gbp"] == pytest.approx(expect * 24, abs=0.05)
    assert part["cut_piece_pricing"]["stock_unit_price_gbp"] == 30.0
    assert part["estimator_input_required"] is True
    qs = part.get("manufacturing_questions") or []
    assert any("per piece, per metre or per stock length" in q["issue"] for q in qs), qs
    assert any("purchased line cut from stock" in str(f) for f in part["review_flags"])


def test_sold_by_the_metre_the_estimator_asks_nothing(monkeypatch):
    import estimator
    monkeypatch.setattr(estimator, "_resolve_part_system_cost", _stub(10.0, "M"))
    part = _strengthener()
    pe = estimator.estimate_part(part, 1)
    assert pe["material_estimate"]["unit_material_cost_gbp"] == pytest.approx(10.0 * 0.1 * _WASTE, abs=1e-3)
    assert not part.get("manufacturing_questions")
    assert not part.get("estimator_input_required")


def test_a_purchased_line_with_no_cut_length_prices_as_before(monkeypatch):
    import estimator
    monkeypatch.setattr(estimator, "_resolve_part_system_cost", _stub(0.2, "each"))
    part = dict(_strengthener(), part_number="FIXING M6x12mm",
                description="THREADED INSERT, HEADED HEX DRIVE", quantity=4)
    pe = estimator.estimate_part(part, 1)
    assert pe["material_estimate"]["unit_material_cost_gbp"] == pytest.approx(0.2, abs=1e-4)
    assert "cut_piece_pricing" not in part
