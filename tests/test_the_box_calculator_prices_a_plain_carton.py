"""The box calculator (D-521): the estimators' stated three-pair arithmetic, corrected.

The AI BOX CALCULATOR sheet's own worked example (88 x 38 x 1955 on BC 150KT at 120 off)
is the fixture: the module must reproduce the sheet's nests and pair costs EXACTLY, and
then sum all three pairs where the sheet's total drops one (K10 = SUM(K7:K8) reads £1.82;
the complete box is £2.82)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import box_costing  # noqa: E402
from commercial_lines import _box_method_price  # noqa: E402


def test_the_sheets_own_example_reproduces_to_the_penny():
    r = box_costing.price_box(88, 38, 1955, 120)
    assert r["priced"]
    by_pair = {p["pair"]: p for p in r["panels"]}
    assert by_pair["Length/Breadth"]["per_sheet"] == 680
    assert by_pair["Height/Breadth"]["per_sheet"] == 40
    assert by_pair["Height/Length"]["per_sheet"] == 24
    assert abs(by_pair["Length/Breadth"]["pair_cost_gbp"] - 0.0353) < 1e-3
    assert abs(by_pair["Height/Breadth"]["pair_cost_gbp"] - 0.60) < 1e-3
    assert abs(by_pair["Height/Length"]["pair_cost_gbp"] - 1.00) < 1e-3
    assert abs(r["running_gbp"] - 0.7283) < 1e-3
    assert abs(r["setup_share_gbp"] - 0.4583) < 1e-3


def test_both_totals_are_returned_and_neither_is_declared_correct():
    """The sheet's K10 sums two pairs (£1.82 on its worked example); all three sum to
    £2.82. Which fits is judged against the Harley's history (the two-pair total reads
    median +0.4% there, the three-pair −22%), so price_box returns BOTH and the basis
    names them as an allowance, not a proven box price."""
    r = box_costing.price_box(88, 38, 1955, 120)
    assert abs(r["unit_gbp"] - 2.822) < 2e-3, r["unit_gbp"]
    assert abs(r["sheet_total_gbp"] - 1.822) < 2e-3, r["sheet_total_gbp"]
    assert "SUM(K7:K8)" in r["basis"] and "PROVISIONAL" in r["basis"]
    assert "one unit per carton" in r["basis"], "the assumptions are stated on the line"


def test_an_oversize_panel_declines_by_name_never_a_silent_zero():
    r = box_costing.price_box(2500, 2500, 2500, 10)
    assert not r["priced"]
    assert "does not fit" in r["reason"]
    bad = box_costing.price_box(0, 100, 100, 10)
    assert not bad["priced"]


def test_the_harleys_descriptions_parse_including_the_run_together_style():
    p = box_costing.parse_box_description("H324822 - 0304110 - 250x170x3200201 150KT DW")
    assert p["dims_mm"] == [250.0, 170.0, 320.0] and p["style"] == "0201"
    p = box_costing.parse_box_description("107868 - 555x235x160 0201 150KT B H")
    assert p["dims_mm"] == [555.0, 235.0, 160.0] and p["style"] == "0201"
    p = box_costing.parse_box_description("108800 - 610x430x1830 cap & sleeve")
    assert p["dims_mm"] == [610.0, 430.0, 1830.0] and p["style"] is None


def test_enabled_by_default_and_silent_when_switched_off(monkeypatch):
    """James, 14 Oct: 'our boxing calculation needs to be in the calculation of the
    estimate and written back to the s/sheet' — so the switch ships ON, with the
    two-formula comparison recorded beside it in config. Off, the rung is silent and
    the proven ladder prices the line exactly as before."""
    import config
    assert config.BOX_COSTING.get("enabled") is True
    order = {"order_quantity": 20,
             "counted_parts": [{"part_number": "12399-77J", "length_mm": 1198.0,
                                "width_mm": 398.0, "thickness_mm": 18.0,
                                "material": "MFC", "per_assembly": 1}],
             "left_out_parts": []}
    monkeypatch.setitem(config.BOX_COSTING, "enabled", False)
    assert _box_method_price(order) is None


def test_the_packaging_rung_prices_a_one_part_unit_from_its_envelope(monkeypatch):
    import config
    monkeypatch.setitem(config.BOX_COSTING, "enabled", True)
    order = {"order_quantity": 20,
             "counted_parts": [{"part_number": "12399-77J", "length_mm": 1198.0,
                                "width_mm": 398.0, "thickness_mm": 18.0,
                                "material": "MFC", "per_assembly": 1}],
             "left_out_parts": []}
    r = _box_method_price(order)
    assert r and not r.get("not_applicable"), r
    assert r["order_gbp"] > 0
    assert r["source_class"] == "box_calculator"
    assert "PROVISIONAL" in r["working"] and "panel pairs" in r["working"]
    assert "two-pair" in r["working"], "the configured formula is named on the line"
    # only the set-up share moves with quantity, so the per-unit falls as the order grows
    at = r["order_gbp_at_breaks"]
    assert at[100] / 100 < at[1] / 1


def test_the_configured_formula_decides_the_figure(monkeypatch):
    import config
    monkeypatch.setitem(config.BOX_COSTING, "enabled", True)
    order = {"order_quantity": 120,
             "counted_parts": [{"part_number": "X", "length_mm": 88, "width_mm": 38,
                                "thickness_mm": 1955, "per_assembly": 1}],
             "left_out_parts": []}
    monkeypatch.setitem(config.BOX_COSTING, "formula", "sheet")
    two = _box_method_price(order)
    monkeypatch.setitem(config.BOX_COSTING, "formula", "three_pair")
    three = _box_method_price(order)
    assert abs(two["order_gbp"] / 120 - 1.822) < 2e-3
    assert abs(three["order_gbp"] / 120 - 2.822) < 2e-3
    assert "three-pair" in three["working"]


def test_a_many_part_unit_prices_its_counted_cartons():
    """James, 14 Oct: the boxing cost is the NUMBER and SIZE of boxes. A multi-part unit
    takes the shipment plan's carton count (the measured blanks' volume and weight at the
    declared packing factor) and prices each standard carton with the same formula,
    set-up spread across the order's cartons."""
    order = {"order_quantity": 10,
             "counted_parts": [
                 {"part_number": "A", "length_mm": 500, "width_mm": 300,
                  "thickness_mm": 18, "per_assembly": 1},
                 {"part_number": "B", "length_mm": 400, "width_mm": 200,
                  "thickness_mm": 18, "per_assembly": 2}],
             "left_out_parts": [],
             "shipment": {"carton_count": 3, "carton_internal_mm": [1200, 800, 600],
                          "packing_factor": 0.8, "parts_without_a_blank": 0}}
    r = _box_method_price(order)
    assert r and not r.get("not_applicable"), r
    assert r["source_class"] == "box_calculator" and r["order_gbp"] > 0
    assert "3 x" in r["working"] and "1200 x 800 x 600" in r["working"]
    assert "PROVISIONAL" in r["working"]


def test_an_order_the_plan_flat_packs_has_no_cartons_to_price():
    """A blank larger than the carton flat-packs to pallets: carton_count is None and the
    rung declines by the plan's own words — the proven ladder prices it as before."""
    order = {"order_quantity": 10,
             "counted_parts": [
                 {"part_number": "A", "length_mm": 1800, "width_mm": 1200,
                  "thickness_mm": 1.5, "per_assembly": 1},
                 {"part_number": "B", "length_mm": 400, "width_mm": 200,
                  "thickness_mm": 18, "per_assembly": 2}],
             "left_out_parts": [],
             "shipment": {"carton_count": None, "carton_internal_mm": [1200, 800, 600],
                          "assumptions": ["1 part(s) are larger than the carton (1200 x "
                                          "800 mm), so the order is flat-packed onto "
                                          "pallets rather than boxed; carton count does "
                                          "not apply."]}}
    r = _box_method_price(order)
    assert r and r.get("not_applicable") and "flat-packed" in r["not_applicable"], r


def test_an_unmeasured_structural_part_routes_to_the_counted_cartons(monkeypatch):
    """A one-part unit with an unmeasured structural sibling no longer sizes a box around
    the one part (its envelope is unproven) — it goes to the counted-shipment path, and
    with nothing counted there it declines honestly."""
    order = {"order_quantity": 10,
             "counted_parts": [{"part_number": "A", "length_mm": 500, "width_mm": 300,
                                "thickness_mm": 18, "per_assembly": 1}],
             "left_out_parts": [{"part_number": "C", "reason": "no blank size recorded"}]}
    r = _box_method_price(order)
    assert r and r.get("not_applicable") and "no cartons to price" in r["not_applicable"]
