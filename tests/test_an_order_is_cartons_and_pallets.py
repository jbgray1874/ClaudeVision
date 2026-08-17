"""An order is a countable number of cartons and pallets, from what the engine already measured.

The measured figures (weight, solid volume) are arithmetic on the blanks and densities. The one
assumption — how much void a protective pack carries — is a named lever declared on every
result, kept apart from the arithmetic. Everything downstream is floor/ceil counting against
config limits, and anything that will not fit a carton or a pallet is FLAGGED, not crushed into
a tidy count. It keys on geometry, density and config — no customer, no filename — so a new
order counts by the same rules.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import palletising as p  # noqa: E402
import config  # noqa: E402


def _part(L, W, T, material="ABS", qty=1):
    return {"blank_length_mm": L, "blank_width_mm": W, "normalized_thickness_mm": T,
            "normalized_material": material, "quantity": qty}


# A steel part heavy enough that WEIGHT sets the carton count, not volume — the realistic case.
STEEL = [_part(1000.0, 800.0, 3.0, "MILD STEEL", qty=1)]


# ── the measured figures ─────────────────────────────────────────────────────────────

def test_weight_is_arithmetic_on_the_blanks():
    plan = p.plan_shipment(STEEL, 10)
    # 1.0 x 0.8 x 0.003 m3 x 7850 kg/m3 x 10 = 188.4 kg
    assert plan["order_weight_kg"] == pytest.approx(188.4, abs=0.5)
    assert plan["parts_measured"] == 1


def test_a_part_with_no_blank_is_skipped_not_guessed():
    plan = p.plan_shipment(STEEL + [{"part_number": "X"}], 10)
    assert plan["parts_measured"] == 1 and plan["parts_without_a_blank"] == 1


def test_a_commercial_placeholder_does_not_ship_itself():
    plan = p.plan_shipment(STEEL + [{"_commercial_placeholder": True,
                                     "blank_length_mm": 500, "blank_width_mm": 500,
                                     "normalized_thickness_mm": 5}], 10)
    assert plan["parts_measured"] == 1


# ── the one assumption, declared and leverable ───────────────────────────────────────

def test_the_packing_factor_is_on_every_result_and_named():
    plan = p.plan_shipment(STEEL, 10)
    assert plan["packing_factor"] == 0.8
    assert any("packing factor" in a.lower() for a in plan["assumptions"])


def test_packed_volume_is_solid_volume_over_the_packing_factor():
    plan = p.plan_shipment(STEEL, 10)
    assert plan["packed_volume_m3"] == pytest.approx(plan["solid_volume_m3"] / 0.8, rel=1e-3)


def test_the_packing_factor_is_a_config_lever(monkeypatch):
    monkeypatch.setattr(config, "PALLETISING_CONFIG", {"packing_factor": 0.5}, raising=False)
    plan = p.plan_shipment(STEEL, 10)
    assert plan["packing_factor"] == 0.5
    assert plan["packed_volume_m3"] == pytest.approx(plan["solid_volume_m3"] / 0.5, rel=1e-3)


# ── the counts ───────────────────────────────────────────────────────────────────────

def test_cartons_are_counted_by_weight_when_weight_binds():
    """188 kg at 25 kg a carton is 8 cartons; the volume would fit in one. The count is the
    binding limit, not the convenient one."""
    plan = p.plan_shipment(STEEL, 10)
    assert plan["cartons_by_weight"] == 8
    assert plan["carton_count"] == 8


def test_pallets_are_counted_from_cartons_and_weight():
    """Eight cartons at three per pallet is three pallets; the weight alone would be one. Again
    the binding limit wins."""
    plan = p.plan_shipment(STEEL, 10)
    assert plan["pallet_count"] == 3


def test_a_heavier_pallet_limit_changes_the_pallet_count(monkeypatch):
    """The pallet weight limit is a config lever: drop it and more pallets are needed for the
    same order, deterministically."""
    monkeypatch.setattr(config, "PALLETISING_CONFIG", {"pallet_max_weight_kg": 50.0},
                        raising=False)
    plan = p.plan_shipment(STEEL, 10)
    # 188.4 kg / 50 = 4 pallets by weight, which now binds over the 3 by cartons.
    assert plan["pallet_count"] == 4


# ── what it will not pretend to pack ─────────────────────────────────────────────────

def test_a_blank_bigger_than_the_carton_is_flat_packed_not_boxed():
    """A 900 x 850 blank does not lie flat in an 1200 x 800 carton. Cartons stop being the unit;
    the order flat-packs onto pallets and the carton count is withheld with a reason."""
    plan = p.plan_shipment([_part(900.0, 850.0, 3.0, "ALUMINIUM", qty=1)], 5)
    assert plan["carton_count"] is None
    assert "blank_exceeds_carton" in plan["flags"]
    assert plan["pallet_count"] >= 1
    assert "blank_exceeds_pallet" not in plan["flags"]


def test_a_blank_bigger_than_the_pallet_is_flagged_as_a_crate_decision():
    """A 1250 x 1100 blank overhangs a 1200 x 1000 pallet. That is a crate / oversize-haulage
    call the engine will not guess; the pallet count becomes a weight-only lower bound and the
    flag is loud."""
    plan = p.plan_shipment([_part(1250.0, 1100.0, 3.0, "MILD STEEL", qty=1)], 4)
    assert "blank_exceeds_pallet" in plan["flags"]
    assert plan["pallet_count"] >= 1


def test_nothing_measurable_is_not_a_confident_one_carton():
    """No blank anywhere means the shipment cannot be counted. It says so rather than return a
    tidy '1 carton, 1 pallet' that a reviewer would trust."""
    plan = p.plan_shipment([{"part_number": "X"}, {"part_number": "Y"}], 10)
    assert plan["carton_count"] is None and plan["pallet_count"] is None
    assert "shipment_not_countable" in plan["flags"]


# ── the phrase that goes on the shipment description ──────────────────────────────────

def test_summary_phrase_boxed():
    assert "carton" in p.summary_phrase(p.plan_shipment(STEEL, 10))


def test_summary_phrase_flat_packed():
    phrase = p.summary_phrase(p.plan_shipment([_part(900.0, 850.0, 3.0, qty=1)], 5))
    assert "flat-packed" in phrase


def test_summary_phrase_empty_when_not_countable():
    assert p.summary_phrase(p.plan_shipment([{"part_number": "X"}], 10)) == ""


# ── wired into the quote, not merely built ───────────────────────────────────────────

def test_describe_order_carries_the_shipment_plan():
    """BUILT IS NOT WIRED. The count is useless if it never reaches the quote — describe_order
    must attach the plan the packaging and delivery lines read."""
    import commercial_lines as cl
    order = cl.describe_order(STEEL, 10)
    assert order.get("shipment") is not None
    assert order["shipment"]["pallet_count"] == 3


def test_the_packaging_description_states_the_count(monkeypatch):
    """An estimator overruling the packaging figure sees how many cartons and pallets it was
    built on, not just a weight."""
    import commercial_lines as cl
    monkeypatch.setattr(config, "COMMERCIAL_LINE_GBP_PER_ORDER", {}, raising=False)
    monkeypatch.setattr(cl, "_ask_market", lambda d, t: None)
    desc = cl.packaging_line(STEEL, 10)["described_as"]
    assert "carton" in desc and "pallet" in desc


def test_the_delivery_description_states_the_pallet_count(monkeypatch):
    import commercial_lines as cl
    monkeypatch.setattr(config, "COMMERCIAL_LINE_GBP_PER_ORDER", {}, raising=False)
    monkeypatch.setattr(cl, "_ask_market", lambda d, t: None)
    desc = cl.delivery_line(STEEL, 10)["described_as"]
    assert "pallet(s)" in desc
