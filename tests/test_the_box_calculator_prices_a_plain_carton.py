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


def test_the_total_carries_all_three_pairs_and_says_so():
    """The sheet's K10 sums two pairs; a box has six panels. The correction is declared
    in the basis so a checker comparing against the sheet sees why the figures differ."""
    r = box_costing.price_box(88, 38, 1955, 120)
    assert abs(r["unit_gbp"] - 2.822) < 2e-3, r["unit_gbp"]
    assert "SUM(K7:K8)" in r["basis"]


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


def test_the_packaging_rung_prices_a_one_part_unit_from_its_envelope():
    order = {"order_quantity": 20,
             "counted_parts": [{"part_number": "12399-77J", "length_mm": 1198.0,
                                "width_mm": 398.0, "thickness_mm": 18.0,
                                "material": "MFC", "per_assembly": 1}],
             "left_out_parts": []}
    r = _box_method_price(order)
    assert r and not r.get("not_applicable"), r
    assert r["order_gbp"] > 0
    assert r["source_class"] == "box_calculator"
    assert "panel pairs" in r["working"]
    # only the set-up share moves with quantity, so the per-unit falls as the order grows
    at = r["order_gbp_at_breaks"]
    assert at[100] / 100 < at[1] / 1


def test_a_many_part_unit_is_the_packers_decision_not_a_formulas():
    order = {"order_quantity": 10,
             "counted_parts": [
                 {"part_number": "A", "length_mm": 500, "width_mm": 300,
                  "thickness_mm": 18, "per_assembly": 1},
                 {"part_number": "B", "length_mm": 400, "width_mm": 200,
                  "thickness_mm": 18, "per_assembly": 2}],
             "left_out_parts": []}
    r = _box_method_price(order)
    assert r and r.get("not_applicable"), r
    assert "packer" in r["not_applicable"]


def test_an_unmeasured_structural_part_leaves_the_envelope_unproven():
    order = {"order_quantity": 10,
             "counted_parts": [{"part_number": "A", "length_mm": 500, "width_mm": 300,
                                "thickness_mm": 18, "per_assembly": 1}],
             "left_out_parts": [{"part_number": "C", "reason": "no blank size recorded"}]}
    r = _box_method_price(order)
    assert r and r.get("not_applicable") and "unproven" in r["not_applicable"]
