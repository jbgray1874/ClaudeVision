"""A real line that reads as free gets a non-firm market price — but a sealed query never does.

Policy the estimator asked for: a real part must never show a blank in the money column, because
a blank reads as free and is the one error nobody catches. Where the engine found no
catalogue/UDEF/derived price for a real bought-in, the honest answer is an indicative market
figure (non-firm), not a zero. So after every part is costed, a last-resort pass gives each
'reads as free' line a per-each market/LLM price that ENTERS the non-firm total.

The hard constraint — and the reason this is safe to add after two FOOTPLATE regressions: the
last-resort MUST refuse a sealed recogniser query. FOOTPLATE was un-priced by the recogniser and
then re-priced £14-£26 by the very market lookup this pass uses; if the last-resort touched it,
the phantom walks straight back in. So the pass skips the seal markers explicitly (belt-and-
braces with the seal's early return), and a line that is £0 for any legitimate reason
(placeholder, customer-supplied, assembly parent, already priced) is left alone. Where the lookup
genuinely finds nothing, the line stays an honest gap — a market figure is never invented.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import estimator as E  # noqa: E402


# ── the seal skip — the guardrail that stops the FOOTPLATE regression ────────────────────
def test_a_sealed_query_is_never_eligible_by_cost_source():
    assert E._last_resort_price_is_needed(
        {"description": "Foot Plate", "cost_source": "layer2_possible_fabricated_query",
         "extended_total_cost_gbp": 0}) is False


def test_a_sealed_query_is_never_eligible_by_costing_basis():
    assert E._last_resort_price_is_needed(
        {"description": "Foot Plate", "costing_basis": "recogniser_query_not_priced",
         "extended_total_cost_gbp": 0}) is False


def test_the_application_never_touches_a_sealed_line_even_if_passed():
    """THE REGRESSION GUARD. Hand the pass a sealed footplate AND a real free line together;
    only the real one is rescued, the phantom stays at nothing."""
    sealed = {"part_number": "BI-FOOTPLATE", "description": "Foot Plate",
              "cost_source": "layer2_possible_fabricated_query",
              "extended_total_cost_gbp": 0, "quantity": 1}
    real = {"part_number": "3086", "description": "Ticket Clips",
            "extended_total_cost_gbp": 0, "quantity": 3}
    n = E.apply_last_resort_prices([sealed, real], lambda pe: 0.40)
    assert n == 1
    assert sealed.get("extended_total_cost_gbp") == 0            # phantom untouched
    assert real.get("extended_total_cost_gbp") == 1.20          # 0.40 x 3, entered the total


# ── fires on a genuine 'reads as free' line ──────────────────────────────────────────────
def test_a_real_free_bought_in_is_eligible():
    assert E._last_resort_price_is_needed(
        {"part_number": "3086", "description": "Ticket Clips",
         "extended_total_cost_gbp": 0}) is True


def test_the_rescued_line_enters_the_total_marked_non_firm():
    real = {"part_number": "3086", "description": "Ticket Clips",
            "extended_total_cost_gbp": 0, "quantity": 3}
    E.apply_last_resort_prices([real], lambda pe: 0.40)
    assert real["material_estimate"]["extended_material_cost_gbp"] == 1.20
    assert real["costing_basis"] == "last_resort_market_indication"
    assert any("LAST-RESORT" in str(f) and "NON-FIRM" in str(f)
               for f in real.get("review_flags", []))


# ── refuses every line that is £0 for a reason ───────────────────────────────────────────
def test_a_placeholder_is_left_free():
    assert E._last_resort_price_is_needed(
        {"description": "Packaging", "_commercial_placeholder": True,
         "extended_total_cost_gbp": 0}) is False


def test_a_customer_supplied_line_is_left_free():
    assert E._last_resort_price_is_needed(
        {"description": "Graphic", "risk_flags": ["customer_supplied_zero_cost"],
         "extended_total_cost_gbp": 0}) is False


def test_an_assembly_parent_is_left_free():
    assert E._last_resort_price_is_needed(
        {"description": "STAND ASSY", "is_assembly_parent": True,
         "extended_total_cost_gbp": 0}) is False
    assert E._last_resort_price_is_needed(
        {"description": "STAND ASSY", "route_context": {"is_assembly_parent": True},
         "extended_total_cost_gbp": 0}) is False


def test_a_line_that_already_has_money_is_not_touched():
    assert E._last_resort_price_is_needed(
        {"description": "Castor", "extended_total_cost_gbp": 4.5}) is False


def test_a_line_with_nothing_to_look_up_is_left_alone():
    assert E._last_resort_price_is_needed(
        {"part_number": "", "description": "", "extended_total_cost_gbp": 0}) is False


# ── an honest gap is never filled with an invented number ────────────────────────────────
def test_a_lookup_miss_leaves_the_line_an_honest_gap():
    line = {"part_number": "X", "description": "Obscure Widget",
            "extended_total_cost_gbp": 0, "quantity": 1}
    n = E.apply_last_resort_prices([line], lambda pe: None)
    assert n == 0
    assert (line.get("extended_total_cost_gbp") or 0) == 0
    assert line.get("costing_basis") != "last_resort_market_indication"


def test_it_is_wired_after_the_costing_loop():
    """Wired where the seal's early return has already fired, so a sealed line cannot reach it."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "estimator.py"),
               encoding="utf-8").read()
    loop = src.index("part_estimate = estimate_part(part, job_quantity=_order_qty)")
    call = src.index("apply_last_resort_prices(part_estimates, _last_resort_lookup)")
    totals = src.index("material_total_raw = sum(")
    assert loop < call < totals
