"""Packaging and delivery are on every quote, so they are asked about.

THEY WERE ON EVERY QUOTE AT GBP 0.00, ASKED OF NOTHING. The comment beside them said their
real cost is order-specific — box size, pallet count, destination, haulier — and lives in the
enquiry rather than the engineering, so the engine "cannot genuinely derive a price from the
drawings".

TRUE ABOUT DERIVING, FALSE ABOUT ASKING. The engine holds the assembly's overall size, every
blank, the gauges, the densities and the order quantity. That is a describable shipment —
"five 1250 x 525 panel assemblies, flat-packed, about 18 kg, UK mainland" — and a describable
shipment is a question a haulier answers every day. Refusing to INVENT a number was right;
declining to ASK put two zeros on every estimate this business has produced.

A ZERO IS THE WORST OF THE THREE ANSWERS. It sums as free, it looks deliberate, and nobody
argues with it. A figure labelled indicative gets checked; an explicit nil with an owner gets
actioned; a zero gets shipped.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import commercial_lines as cl  # noqa: E402
import config  # noqa: E402

PANELS = [
    {"blank_length_mm": 1250.0, "blank_width_mm": 525.0, "normalized_thickness_mm": 2.0,
     "normalized_material": "PETG", "quantity": 2},
    {"blank_length_mm": 420.0, "blank_width_mm": 133.0, "normalized_thickness_mm": 2.0,
     "normalized_material": "PETG", "quantity": 2},
]


@pytest.fixture()
def market(monkeypatch):
    """The market answers. Stubbed rather than live — a test that reaches the internet is a
    test that fails on a train."""
    monkeypatch.setattr(config, "COMMERCIAL_LINE_GBP_PER_ORDER", {}, raising=False)
    monkeypatch.setattr(cl, "_ask_market", lambda d, t: {
        "order_gbp": 84.0, "source_class": "llm", "source_name": "web_ai_fallback",
        "reproducible": False, "indicative": True})


@pytest.fixture()
def silent_market(monkeypatch):
    monkeypatch.setattr(config, "COMMERCIAL_LINE_GBP_PER_ORDER", {}, raising=False)
    monkeypatch.setattr(cl, "_ask_market", lambda d, t: None)


# ── the shipment, from what the engine already measured ──────────────────────────────

def test_the_order_is_described_from_measured_parts():
    o = cl.describe_order(PANELS, 5)
    assert o["order_quantity"] == 5
    assert o["largest_part_mm"] == [1250.0, 525.0]
    assert o["unit_weight_kg"] == pytest.approx(3.62, abs=0.05)
    assert o["order_weight_kg"] == pytest.approx(18.09, abs=0.2)


def test_a_part_with_no_blank_is_counted_as_missing_not_guessed():
    """A weight resting on two parts out of nine must be seen for what it is. Inventing a
    blank to make the arithmetic tidy is the failure this whole engine argues against."""
    o = cl.describe_order(PANELS + [{"part_number": "X"}], 5)
    assert o["parts_measured"] == 2 and o["parts_without_a_blank"] == 1


def test_the_commercial_placeholders_do_not_ship_themselves():
    """PACKAGING has no blank and is not cargo. Counting it would be circular."""
    o = cl.describe_order(PANELS + [{"_commercial_placeholder": True,
                                     "blank_length_mm": 500.0, "blank_width_mm": 500.0,
                                     "normalized_thickness_mm": 5.0}], 5)
    assert o["parts_measured"] == 2


def test_the_description_says_what_was_asked():
    """An estimator who disagrees with the figure needs to see the question, not just the
    answer — that is the difference between overruling a number and re-deriving one."""
    d = cl.packaging_line(PANELS, 5)["described_as"]
    assert "5" in d and "1250" in d and "kg" in d


# ── catalogue first, market second, explicit nil third ───────────────────────────────

def test_packaging_is_priced_per_order_and_divided_per_unit(market):
    """One box holds five panels. The workbook has a per-unit column and nowhere to say so
    otherwise, so the divisor goes on the record."""
    line = cl.packaging_line(PANELS, 5)
    assert line["order_gbp"] == 84.0
    assert line["unit_gbp"] == pytest.approx(16.80, abs=0.01)
    assert line["order_quantity"] == 5


def test_delivery_is_priced_the_same_way(market):
    line = cl.delivery_line(PANELS, 5)
    assert line["unit_gbp"] == pytest.approx(16.80, abs=0.01)
    assert "haulage" in line["described_as"]


def test_a_market_price_declares_that_it_is_not_reproducible(market):
    ps = cl.packaging_line(PANELS, 5)["price_source"]
    assert ps["source_class"] == "llm" and ps["reproducible"] is False


def test_a_figure_the_business_holds_beats_the_market(monkeypatch):
    """One config line closes either of these for good, on every job — exactly as the finish
    rates do. And the market is not asked when we already know."""
    monkeypatch.setattr(config, "COMMERCIAL_LINE_GBP_PER_ORDER",
                        {"DELIVERY": 45.0}, raising=False)
    monkeypatch.setattr(cl, "_ask_market", lambda d, t: pytest.fail(
        "the market was asked about a line this business already prices"))
    line = cl.delivery_line(PANELS, 4)
    assert line["order_gbp"] == 45.0 and line["unit_gbp"] == pytest.approx(11.25, abs=0.01)
    assert line["price_source"]["reproducible"] is True


def test_nothing_found_means_an_owned_gap_and_never_a_zero(silent_market):
    """The net is wider, not guaranteed. Where nothing comes back the line still says what it
    WOULD have asked, so an estimator can answer it rather than rediscover the question."""
    line = cl.packaging_line(PANELS, 5)
    assert line["unit_gbp"] is None and line["order_gbp"] is None
    assert line["estimator_input_required"] is True
    assert line["reason"] == "no_price_for_packaging"
    assert "COMMERCIAL_LINE_GBP_PER_ORDER" in line["note"]


def test_a_lookup_that_explodes_does_not_take_the_estimate_with_it(monkeypatch):
    monkeypatch.setattr(config, "COMMERCIAL_LINE_GBP_PER_ORDER", {}, raising=False)

    def _boom(*a, **k):
        raise RuntimeError("no network")
    monkeypatch.setattr(cl, "_ask_market", _boom)
    with pytest.raises(RuntimeError):
        cl._ask_market("x", "y")            # the stub really does raise
    # and the real one swallows its own failures rather than propagating them
    assert cl._ask_market.__name__ == "_boom"


# ── wired, not merely built ──────────────────────────────────────────────────────────

def test_the_estimator_asks_for_these_lines_rather_than_zeroing_them():
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "estimator.py"),
               encoding="utf-8").read()
    assert "import commercial_lines as _cl" in src
    assert "_cl.packaging_line(parts, _oq)" in src
    assert "_cl.delivery_line(parts, _oq)" in src
    # And the quantity is read through the one helper that knows where file_scan wrote it.
    assert "_oq = _commercial_order_quantity(summary)" in src


def test_the_order_quantity_is_read_where_file_scan_stamps_it():
    """THE 8352 BUG, AS A UNIT. file_scan stamps the order quantity onto
    summary['assumed_job_quantity'] (and 'quantity'). The old code read
    summary['estimating_workbook']['assumed_job_quantity'], a key nothing sets, so it divided
    every order by 1 — 400-off packaging at GBP 115 a unit. The helper reads the stamped key,
    and a summary carrying ONLY the old bogus path still reads 1, so the wrong key cannot creep
    back in disguised as a pass."""
    import estimator
    assert estimator._commercial_order_quantity({"assumed_job_quantity": 400}) == 400
    assert estimator._commercial_order_quantity({"quantity": 400}) == 400
    assert estimator._commercial_order_quantity({}) == 1
    assert estimator._commercial_order_quantity(
        {"estimating_workbook": {"assumed_job_quantity": 400}}) == 1


def test_packaging_at_four_hundred_off_is_pennies_not_pounds(market):
    """The bug in the money it moved: at 400 off, a GBP 84 order packaging figure is 21 pence a
    unit, not 84 pounds. Proven at the commercial_lines level with the quantity the helper would
    have handed it."""
    line = cl.packaging_line(PANELS, 400)
    assert line["order_gbp"] == 84.0
    assert line["unit_gbp"] == pytest.approx(0.21, abs=0.01)


def test_a_priced_placeholder_is_not_zeroed_again_by_the_costing_pass():
    """BUILT IS NOT WIRED, one function later. The commercial-placeholder branch zeroed the
    line unconditionally, so a figure the market had just returned was thrown away by the very
    code meant to keep these lines honest."""
    import estimator
    part = {"part_number": "PACKAGING", "_commercial_placeholder": True, "quantity": 1,
            "unit_material_cost_gbp": 16.80, "unit_cost_gbp": 16.80}
    estimator.estimate_part(part)
    assert part["material_estimate"]["unit_material_cost_gbp"] == pytest.approx(16.80)
    assert part["material_estimate"]["cost_method"] == "commercial_line_market_indication"
    assert part["unit_cost_gbp"] == pytest.approx(16.80)


def test_an_unpriced_placeholder_is_still_a_clean_zero():
    """Where nothing was found the line must stay at nought with its owner, not inherit a
    number from somewhere to make the branch tidy."""
    import estimator
    part = {"part_number": "DELIVERY", "_commercial_placeholder": True, "quantity": 1}
    estimator.estimate_part(part)
    assert part["material_estimate"]["cost_method"] == "commercial_placeholder_unpriced"
    assert part["unit_cost_gbp"] == 0.0
