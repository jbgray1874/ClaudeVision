"""A standard commodity with a CLASS WORD for a code still reaches its config price.

11762-17 lists "STD PART / PERFO PLASTIC LOCKING CLIP". The code column is the class word
STD PART, not a SKU, and the only route to the reproducible config provisional (£1.20) ran
INSIDE PricingService's web/AI fallback — reachable only with a live DB connection and only
after a gate let the part through. So on a box whose DB rung was unavailable, or whose gate
refused the line, the clip was handed £0 despite a fixed figure sitting in config, and the
sheet showed a bought-in as free to make.

The engine now consults the commodity table DIRECTLY, DB-free, as the last resort in
_resolve_part_system_cost — keyed on the description, so a class-word code is no obstacle. A
standard commodity is a material buy placed during the assembly labour the parent already
carries, so it takes no bench-fitting uplift: the BOM shows the buy price itself, and the
total carries exactly that figure.

These run OFFLINE (SDI_OFFLINE=1) so _get_pricing_service() returns None — proving the price
comes from config alone, not a database.
"""
from __future__ import annotations

import os
import sys

os.environ["SDI_OFFLINE"] = "1"        # before importing the engine: no live PricingService
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import estimator  # noqa: E402
import wb_populate  # noqa: E402


_CLIP_DESC = "PERFO PLASTIC LOCKING CLIP - BOTTLTD.CO.UK"


def _clip(qty: int = 1) -> dict:
    return {"part_number": "STD PART", "description": _CLIP_DESC,
            "normalized_material": "MILD STEEL", "quantity": qty}


def test_the_chokepoint_prices_the_clip_without_a_pricing_service():
    """No DB, no PricingService: the config commodity is still reached in _resolve_part_system_cost."""
    assert estimator._get_pricing_service() is None      # genuinely offline
    sc = estimator._resolve_part_system_cost(_clip())
    assert sc["applied_unit_cost"] == 1.2
    assert (sc["result"]["selected"]["source"]) == "standard_commodity_provisional"


def test_a_class_word_code_is_no_obstacle_because_the_match_is_on_description():
    """STD PART carries no code to look up; the description does the matching."""
    sc = estimator._resolve_part_system_cost(_clip())
    assert sc["applied_unit_cost"] == 1.2
    # matched on the description, not a code — the stamp must not claim a code hit
    assert sc["matched_part_code"] is None


def test_the_clip_lands_at_the_buy_price_on_the_bom_and_the_total():
    """£1.20 on the BOM price column and in the unit total — not £0, and not buy+fitting."""
    pe = estimator.estimate_part(_clip(), job_quantity=20)
    assert pe["unit_total_cost_gbp"] == 1.2
    assert wb_populate._bom_line_price(pe) == 1.2
    me = pe.get("material_estimate") or {}
    assert me.get("unit_material_cost_gbp") == 1.2


def test_a_commodity_provisional_takes_no_bench_fitting_uplift():
    """A general bought-in gets a fitting uplift; a standard commodity does not — it is placed
    during the assembly labour the parent already carries. So the unit total is the bare buy."""
    pe = estimator.estimate_part(_clip(), job_quantity=20)
    # buy price only: no £1.04 fitting, no labour bled into the material column
    assert pe["unit_total_cost_gbp"] == 1.2
    assert pe.get("cost_breakdown", {}).get("costing_basis") == "system_cost_per_part"


def _clip_stub(qty: int = 1) -> dict:
    """The RECOGNISED-BUT-UNPRICED bought-in stub extract_bought_in_from_pages produces — a
    code the catalogue could not match. This is the shape the real clip arrives as, and it
    short-circuits estimate_part before _resolve_part_system_cost."""
    return {"part_number": "STD PART", "description": _CLIP_DESC,
            "source": "sdi_bom_code_unpriced", "unit_cost_gbp": None,
            "quantity": qty, "page_roles": ["bought_in"]}


def test_a_recognised_but_unpriced_commodity_stub_is_priced_at_source():
    """The stub path returned £0 before ever reaching the pricing chokepoint. A known commodity
    is priced right there instead of shipping as a bought-in that reads as free."""
    pe = estimator.estimate_part(_clip_stub(), job_quantity=20)
    assert pe["unit_total_cost_gbp"] == 1.2
    assert wb_populate._bom_line_price(pe) == 1.2
    assert pe.get("cost_breakdown", {}).get("costing_basis") == "standard_commodity_provisional" \
        or pe.get("costing_basis") == "standard_commodity_provisional"


def test_a_recognised_but_unpriceable_stub_still_passes_through_unpriced():
    """A genuine no-price bought-in (a fixing with no catalogue match) must stay estimator-to-price,
    not be captured by the commodity table."""
    fixing = {"part_number": "FIXING", "description": "M6x20 SOCKET CAP SCREW",
              "source": "sdi_bom_code_unpriced", "unit_cost_gbp": None, "quantity": 1}
    pe = estimator.estimate_part(fixing, job_quantity=20)
    assert pe.get("unit_total_cost_gbp") is None
    assert pe.get("costing_basis") == "sdi_bom_code_estimator_to_price"


def test_a_fabricated_part_is_not_captured_as_a_commodity():
    """The commodity table must not touch a real fabricated leaf."""
    bp = {"part_number": "11762-17-02M", "description": "BACK PLATE",
          "normalized_material": "MILD STEEL", "quantity": 1}
    sc = estimator._resolve_part_system_cost(bp)
    assert sc["applied_unit_cost"] is None
