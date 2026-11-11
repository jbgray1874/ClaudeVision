"""The pack's stated weight drives packaging and delivery when the blanks fall short.

THE COURIER WAS ASKED TO PRICE A 2 KG PARCEL FOR A 33 KG PODIUM (SCRUM-178). On
12678-01-GA only two parts of thirteen carried a blank the engine could weigh — 1.84 kg —
while the GA's title block states WEIGHT: 33.07kg. Nothing on the shipping side read that
figure, so the box calculator and the delivery lookup were both asked about "about 2 kg",
and the covering note even printed "if the unit weight above is lighter than the title
block, these are the parts carrying the difference" while using the lighter figure anyway.

THE RULE: where the pack states a unit weight, parts went unweighed, and the stated figure
is heavier than the measured sum, the stated figure is the shipment's weight — on the
order, on the plan, and at every re-planned quantity break. Both figures are kept so the
covering note shows the gap. A stated weight never lightens a measured order, and a fully
weighed order keeps its measured sum: that gap belongs to the weigh, not to shipping.

A WEIGHT THE SHEET QUALIFIES AS SOMETHING ELSE'S IS NOT THE PRODUCT'S. "MAX LOADING",
"GROSS", "SHIPPING" and the rest already mark a rating or a consignment total for the
title-block reader (D-406), and the same vocabulary holds here.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import commercial_lines as cl  # noqa: E402
import config  # noqa: E402
import palletising  # noqa: E402

PANELS = [
    {"blank_length_mm": 520.0, "blank_width_mm": 370.0, "normalized_thickness_mm": 2.5,
     "normalized_material": "MDF", "quantity": 1, "part_number": "12093-24-06J"},
]
UNWEIGHED = [{"part_number": "12678-01-02J", "description": "SPINE"},
             {"part_number": "12678-01-03J", "description": "TOP"}]
STATED = {"kg": 33.07, "where": "page 1"}


# ── reading the stated weight off the pack ───────────────────────────────────────────

def test_the_heaviest_qualifier_free_weight_is_the_products():
    summary = {"pages": [
        {"page_number": 1, "pypdf_text": "MAX LOADING:\nWEIGHT: 33.07kg\nSPECIFICATION"},
        {"page_number": 2, "pypdf_text": "GROSS WEIGHT 120kg for the consignment"},
        {"page_number": 3, "pypdf_text": "WEIGHT: 2068g"},
    ]}
    sw = cl.product_stated_weight(summary)
    assert sw is not None
    assert sw["kg"] == pytest.approx(33.07)
    assert sw["where"] == "page 1"


def test_a_pack_stating_no_weight_states_none():
    assert cl.product_stated_weight({"pages": [{"pypdf_text": "MAX LOADING: 50KG"}]}) is None
    assert cl.product_stated_weight(None) is None


# ── the order's weight ───────────────────────────────────────────────────────────────

def test_a_stated_weight_fills_what_the_blanks_could_not_weigh():
    o = cl.describe_order(PANELS + UNWEIGHED, 1, stated_weight=STATED)
    assert o["unit_weight_kg"] == pytest.approx(33.07)
    assert o["order_weight_kg"] == pytest.approx(33.07)
    assert o["stated_unit_weight_kg"] == pytest.approx(33.07)
    assert o["measured_unit_weight_kg"] < 33.07
    assert "stated weight drives packaging and delivery" in o["weight_basis"]
    assert "2 part(s) unweighed" in o["weight_basis"]


def test_a_stated_weight_never_lightens_a_measured_order():
    heavy = [{"blank_length_mm": 2000.0, "blank_width_mm": 1000.0,
              "normalized_thickness_mm": 10.0, "normalized_material": "MILD STEEL",
              "quantity": 1, "part_number": "PLATE"}]
    o = cl.describe_order(heavy + UNWEIGHED, 1, stated_weight={"kg": 5.0, "where": "page 1"})
    assert o["unit_weight_kg"] > 5.0
    assert o["stated_unit_weight_kg"] is None
    assert o["weight_basis"] is None


def test_a_fully_weighed_order_keeps_its_measured_sum():
    """Every part weighed and the pack says more: the gap belongs to the weigh, not to
    shipping — quietly adopting the heavier figure would bury a measuring defect."""
    o = cl.describe_order(PANELS, 1, stated_weight=STATED)
    assert o["parts_without_a_blank"] == 0
    assert o["stated_unit_weight_kg"] is None
    assert o["unit_weight_kg"] < 33.07


# ── the plan, and the re-plan at every break ─────────────────────────────────────────

def test_the_floor_reaches_the_counts_at_every_break():
    plan = palletising.plan_shipment(PANELS, 10, unit_weight_floor_kg=33.07)
    assert plan["order_weight_kg"] == pytest.approx(330.7)
    assert "stated_weight_floor" in plan["flags"]
    assert any("The pack states 33.07 kg a unit" in a for a in plan["assumptions"])
    # 330.7 kg does not fit one 25 kg carton run: the count is by the stated weight.
    assert plan["cartons_by_weight"] >= 14


def test_without_a_floor_the_plan_is_what_it_measured():
    plan = palletising.plan_shipment(PANELS, 10)
    assert "stated_weight_floor" not in plan["flags"]
    assert plan["order_weight_kg"] < 330.7


# ── the questions the market is asked ────────────────────────────────────────────────

@pytest.fixture()
def silent_market(monkeypatch):
    monkeypatch.setattr(config, "COMMERCIAL_LINE_GBP_PER_ORDER", {}, raising=False)
    monkeypatch.setattr(cl, "_commercial_researcher", lambda brief: {})


def test_the_delivery_ask_carries_the_stated_weight(silent_market):
    line = cl.delivery_line(PANELS + UNWEIGHED, 1, stated_weight=STATED)
    d = line["described_as"]
    assert "about 33 kg" in d
    assert "the pack's stated weight" in d
    assert line["basis"]["weight_basis"]
    # 33 kg is no parcel: the 25 kg carton limit decides, not the partial sum.
    assert "Palletised haulage" in d


def test_the_packaging_ask_carries_the_stated_weight(silent_market):
    d = cl.packaging_line(PANELS + UNWEIGHED, 1, stated_weight=STATED)["described_as"]
    assert "about 33 kg total (the pack's stated weight)" in d
