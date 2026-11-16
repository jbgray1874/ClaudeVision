r"""
test_hardware_never_reads_as_free.py

A BLANK IN THE MONEY COLUMN READS AS A PART THAT IS FREE TO BUY.

`apply_last_resort_prices` exists to make sure that never happens: where the engine could
find no catalogue, UDEF or derived price for a real bought-in, it puts a non-firm market
indication on the line so the estimator strikes a number they can see rather than missing a
zero they cannot.

On 12349 it rescued nothing. Every screw, insert, glide, and both the acrylic and MDF panels
came through the BOM at £0.

The gate asked `extended_total_cost_gbp > 0` -- "does this line already carry money?" -- but
that field is material PLUS labour (estimate_part's computed branch:
`extended_total_raw = (extended_material_cost + total_labour_cost) * qty_multiplier`). Every
fixing carries a couple of minutes of handling. So every fixing had a line total, so every
fixing failed the test, so no fixing was ever rescued -- and the column an estimator actually
reads a price out of stayed blank. The rescue built to prevent exactly this sat behind a
condition that hardware could not fail.

Two things have to hold, and the second only became reachable once the first was fixed:

  1. the question is asked of the MATERIAL column, not of the line total; and
  2. the rescued price is ADDED to the line, not assigned over it -- otherwise a fixing with
     £1.04 of handling on it becomes £0.40 all-in, and a rescue meant to add a missing price
     quietly subtracts a real one. Both numbers were zero before, which is why the plain
     assignment read as harmless for as long as the gate kept labour-bearing lines out.

A line that is £0 on purpose -- a commercial placeholder, a customer-supplied part, an
assembly parent carrying its material on its children, a firm catalogue price already applied
through the bought-in path -- must still be left alone.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

estimator = pytest.importorskip("estimator", reason="the engine module under test")


def _fixing(**over):
    """A hardware line as 12349 produced it: real, described, priced at nothing, and
    carrying the handling labour that made it look like it had already been costed."""
    pe = {
        "part_number": "SCR-M4-12",
        "description": "M4 x 12 POZI PAN SCREW",
        "quantity": 24,
        "material_estimate": {"cost_per_part_gbp": 0.0, "extended_material_cost_gbp": 0.0},
        "labour_estimate": {"total_labour_cost_gbp": 1.04},
        "unit_total_cost_gbp": 1.04,
        "extended_total_cost_gbp": 1.04,
        "costing_basis": "computed_material_plus_labour_qty_break_x1.000",
    }
    pe.update(over)
    return pe


# ── the case that was broken ────────────────────────────────────────────────────

def test_a_fixing_with_handling_on_it_is_still_offered_a_price():
    """The whole of 12349's hardware failed here and nowhere else."""
    assert estimator._last_resort_price_is_needed(_fixing()) is True


def test_the_line_total_alone_does_not_disqualify_a_line():
    """Whatever the line total is, if the material column is blank the part reads as free."""
    assert estimator._last_resort_price_is_needed(_fixing(extended_total_cost_gbp=812.60)) is True


@pytest.mark.parametrize("material", [
    {"cost_per_part_gbp": 0.40, "extended_material_cost_gbp": 9.60},
    {"unit_material_cost_gbp": 0.40},
    {"extended_material_cost_gbp": 9.60},
])
def test_a_line_that_already_has_material_is_left_alone(material):
    """Any of the three fields carrying money means the column is not blank."""
    assert estimator._last_resort_price_is_needed(_fixing(material_estimate=material)) is False


# ── the labour that must survive the rescue ─────────────────────────────────────

def test_the_rescued_price_is_added_to_the_labour_and_does_not_replace_it():
    rescued = estimator.apply_last_resort_prices([_fixing()], lambda pe: 0.40)
    assert rescued == 1


def test_a_rescue_never_makes_a_line_cheaper_than_it_was():
    pe = _fixing()
    before = pe["extended_total_cost_gbp"]
    estimator.apply_last_resort_prices([pe], lambda pe_: 0.40)
    assert pe["extended_total_cost_gbp"] >= before, (
        "a rescue that lowers a line total has thrown away costed labour")
    assert pe["extended_total_cost_gbp"] == pytest.approx(1.04 + 0.40 * 24, abs=0.01)
    assert pe["unit_total_cost_gbp"] == pytest.approx(1.04 + 0.40, abs=0.01)


def test_the_material_column_carries_the_material_and_only_the_material():
    """The £ the estimator reads must be the price of the part, not the part plus its
    handling -- that column is compared against a supplier quote."""
    pe = _fixing()
    estimator.apply_last_resort_prices([pe], lambda pe_: 0.40)
    me = pe["material_estimate"]
    assert me["cost_per_part_gbp"] == pytest.approx(0.40)
    assert me["extended_material_cost_gbp"] == pytest.approx(9.60)
    assert me["cost_method"] == "last_resort_market_indication"


def test_a_line_that_had_no_labour_is_costed_exactly_as_before():
    """The change must be invisible to the lines the rescue already worked on."""
    pe = _fixing(labour_estimate={"total_labour_cost_gbp": 0.0},
                 unit_total_cost_gbp=0.0, extended_total_cost_gbp=0.0)
    estimator.apply_last_resort_prices([pe], lambda pe_: 0.40)
    assert pe["unit_total_cost_gbp"] == pytest.approx(0.40)
    assert pe["extended_total_cost_gbp"] == pytest.approx(9.60)
    assert pe["costing_basis"] == "last_resort_market_indication"


def test_the_basis_says_when_labour_was_already_on_the_line():
    """Whoever reads the basis has to be able to tell the two shapes apart."""
    pe = _fixing()
    estimator.apply_last_resort_prices([pe], lambda pe_: 0.40)
    assert pe["costing_basis"] == "last_resort_market_indication_plus_labour"


def test_no_price_found_leaves_an_honest_gap():
    """A market figure is not invented where none exists."""
    pe = _fixing()
    assert estimator.apply_last_resort_prices([pe], lambda pe_: None) == 0
    assert pe["extended_total_cost_gbp"] == pytest.approx(1.04)
    assert "cost_method" not in pe["material_estimate"]


# ── the lines that are £0 on purpose, still refused ─────────────────────────────

@pytest.mark.parametrize("marker", [
    {"_commercial_placeholder": True},
    {"source": "commercial_placeholder"},
    {"risk_flags": ["customer_supplied_zero_cost"]},
    {"is_assembly_parent": True},
    {"route_context": {"is_assembly_parent": True}},
    {"costing_basis": "system_cost_per_part"},
    {"cost_breakdown": {"system_cost": {"applied_to_total": True}}},
])
def test_a_line_that_is_free_for_a_reason_is_never_given_a_market_price(marker):
    assert estimator._last_resort_price_is_needed(_fixing(**marker)) is False


def test_a_line_with_nothing_to_look_up_is_refused():
    assert estimator._last_resort_price_is_needed(
        _fixing(part_number="", description="")) is False


def test_a_priced_line_with_no_material_record_at_all_is_still_left_alone():
    """Nothing says what such a line's total is made of, so re-pricing it could only
    double-apply. The question can only be asked of a material record that exists."""
    pe = _fixing()
    pe.pop("material_estimate")
    assert estimator._last_resort_price_is_needed(pe) is False
