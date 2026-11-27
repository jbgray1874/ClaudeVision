r"""Rung 4 produces a price, or it says exactly which source would have answered.

James Gray, 18 September 2026:

    "implement the central rung-4 producer so it can return an evidenced LLM-indicative
     price for a required line. That resolver must work generically for: bought-in
     components such as the felt pads; packing and delivery; specialist bought-in
     processes such as plating and plater freight. For each it must retain:
     source/evidence, date, unit, quantity basis, calculation, and the 'LLM indicative -
     review required' status. It must not read Howard's £250 or £120/£20 figures, nor any
     config literal."

THE DIFFERENCE THIS FILE EXISTS TO PROVE.

The felt pad was priced at 20p by a figure typed into config.py, and that entry called
itself INDICATIVE in those exact words. So "it is labelled indicative" is not the
difference between what was deleted and what rung 4 returns. The difference is that a
rung-4 figure CAN BE CHECKED: it names its source, the date it was true, what it is per,
the quantity it was found at, and the arithmetic from that figure to the money on the line.

Miss any one of those and there is no price — not a smaller one, not a zero. The tests
below are mostly about the refusals, because the refusals are what stop this becoming the
config table again with a longer label.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

from indicative_price import (BOUGHT_IN_COMPONENT, COMMERCIAL,  # noqa: E402
                              LLM_INDICATIVE_STATUS, SUBCONTRACT_PROCESS, classify,
                              research_brief, resolve_indicative)
from release_gate import line_is_answered  # noqa: E402

_TODAY = "2026-09-18"

_FULL = {
    "price_gbp": 0.18,
    "source": "https://example-trade.co.uk/felt-pad-25mm",
    "as_of": _TODAY,
    "unit": "each",
    "quantity_basis": "pack of 100",
}


def _researcher(**overrides):
    """A stand-in for the web/LLM rung. Injected so this is testable without a network —
    and so the engine can put its own researcher behind the same seam."""
    def _ask(_brief):
        return dict(_FULL, **overrides)
    return _ask


# ── the three classes are told apart ─────────────────────────────────────────────────

def test_the_three_line_shapes_are_recognised():
    assert classify({"code": "P/P",
                     "description": "BLACK FELT PAD, SELF-ADHESIVE"}) == BOUGHT_IN_COMPONENT
    assert classify({"code": "DELIVERY", "description": "Delivery"}) == COMMERCIAL
    assert classify({"code": "PACKAGING", "description": "Boxes"}) == COMMERCIAL
    assert classify({"code": "7332-01-101-PLATE",
                     "description": "plating"}) == SUBCONTRACT_PROCESS
    assert classify({"code": "PLATERFREIGHT",
                     "description": "Delivery to and from the platers"}) == COMMERCIAL


def test_a_brief_asks_for_the_thing_that_class_needs():
    """A component wants a unit price; a commercial line wants the ORDER cost; a process
    wants a rate against a measured property."""
    assert "PER EACH" in research_brief(
        {"code": "P/P", "description": "FELT PAD"})["ask"]
    assert "FOR THE WHOLE ORDER" in research_brief(
        {"code": "DELIVERY", "description": "Delivery"}, order_qty=6)["ask"]
    assert "MEASURED property" in research_brief(
        {"code": "X-PLATE", "description": "plating"})["ask"]


def test_a_process_brief_refuses_a_lump_sum_in_words():
    """"A lump sum for 'a job like this' is not usable: it cannot be re-derived." Which is
    exactly what Howard's £250 is."""
    assert "lump sum" in research_brief({"code": "X-PLATE", "description": "plating"})["ask"]


# ── each class produces a price with its arithmetic shown ────────────────────────────

def test_a_felt_pad_prices_and_shows_its_working():
    out = resolve_indicative(
        {"code": "P/P", "description": "BLACK FELT PAD 25mm", "quantity": 4},
        order_qty=6, as_of=_TODAY, ask=_researcher())
    assert out["price_gbp"] == 0.72, out                  # 4 off x 0.18
    assert "4 off x GBP 0.1800 each" in out["calculation"]["working"]
    assert out["status"] == LLM_INDICATIVE_STATUS


def test_a_commercial_line_is_priced_for_the_order_and_divided_by_it():
    """Priced per unit and frozen there is the fault the break mechanism exists to
    prevent: change the order quantity and every unit still carries the whole order."""
    out = resolve_indicative(
        {"code": "DELIVERY", "description": "Delivery, one pallet"},
        order_qty=6, as_of=_TODAY,
        ask=_researcher(price_gbp=180.0, unit="order", quantity_basis="1 pallet"))
    assert out["price_gbp"] == 30.0
    assert "/ 6 off" in out["calculation"]["working"]


def test_the_same_delivery_at_a_different_order_quantity_moves():
    a = resolve_indicative({"code": "DELIVERY", "description": "Delivery"}, order_qty=6,
                           as_of=_TODAY, ask=_researcher(price_gbp=180.0, unit="order",
                                                         quantity_basis="1 pallet"))
    b = resolve_indicative({"code": "DELIVERY", "description": "Delivery"}, order_qty=60,
                           as_of=_TODAY, ask=_researcher(price_gbp=180.0, unit="order",
                                                         quantity_basis="1 pallet"))
    assert a["price_gbp"] == 30.0 and b["price_gbp"] == 3.0


def test_plating_prices_against_the_parts_own_measured_mass():
    """Not a lump sum for the stand — a rate against something the part actually is, so it
    can be re-derived when the part changes."""
    out = resolve_indicative(
        {"code": "7332-01-101-PLATE", "description": "plating, decorative brass",
         "mass_kg": 0.9},
        order_qty=6, as_of=_TODAY,
        ask=_researcher(price_gbp=3.20, unit="kg", quantity_basis="per kg, 1-10kg band"))
    assert "0.9 kg x GBP 3.2000/kg" in out["calculation"]["working"]
    assert out["price_gbp"] == 2.88


def test_a_batch_minimum_is_spread_over_the_order_not_charged_per_unit():
    """A plater's vat minimum is one charge for the batch. Charging it per unit is how a
    six-off job carries six minimums."""
    out = resolve_indicative(
        {"code": "X-PLATE", "description": "plating", "mass_kg": 0.9},
        order_qty=6, as_of=_TODAY,
        ask=_researcher(price_gbp=3.20, unit="kg", quantity_basis="per kg",
                        minimum_gbp=95.0))
    assert "batch minimum GBP 95.00 / 6 off" in out["calculation"]["working"]
    assert out["price_gbp"] == round(0.9 * 3.20 + 95.0 / 6, 4)


# ── and every one of them satisfies the release gate ─────────────────────────────────

def test_a_resolved_line_passes_the_gate_that_blocks_an_unpriced_one():
    """The two halves meet here: the producer's output is exactly what the gate accepts."""
    out = resolve_indicative({"code": "P/P", "description": "FELT PAD", "quantity": 4},
                             order_qty=6, as_of=_TODAY, ask=_researcher())
    assert line_is_answered({"code": "P/P", "price_gbp": out["price_gbp"],
                             "rung": out["rung"], "evidence": out["evidence"]})


# ── the refusals, which are the point ────────────────────────────────────────────────

def test_no_researcher_means_no_price_and_a_named_gap():
    out = resolve_indicative({"code": "P/P", "description": "FELT PAD"}, as_of=_TODAY)
    assert out["price_gbp"] is None
    assert "no researcher was available" in out["missing"]


def test_a_missing_date_refuses_the_price():
    """"A market price without a date is folklore"."""
    out = resolve_indicative({"code": "P/P", "description": "FELT PAD"},
                             ask=_researcher(as_of=""))
    assert out["price_gbp"] is None
    assert "the date the price was true" in out["missing"]


def test_a_missing_source_refuses_the_price():
    out = resolve_indicative({"code": "P/P", "description": "FELT PAD"}, as_of=_TODAY,
                             ask=_researcher(source=""))
    assert out["price_gbp"] is None
    assert "a source" in out["missing"]


def test_a_missing_quantity_basis_refuses_the_price():
    """Break pricing moves: a price found at 1 off is not the price at 1,000."""
    out = resolve_indicative({"code": "P/P", "description": "FELT PAD"}, as_of=_TODAY,
                             ask=_researcher(quantity_basis=""))
    assert out["price_gbp"] is None
    assert "the quantity it was found at" in out["missing"]


def test_a_zero_from_the_researcher_is_not_a_price():
    out = resolve_indicative({"code": "P/P", "description": "FELT PAD"}, as_of=_TODAY,
                             ask=_researcher(price_gbp=0))
    assert out["price_gbp"] is None
    assert "this line still costs something" in out["missing"]


def test_a_researcher_that_throws_does_not_pass_the_line():
    def _boom(_brief):
        raise RuntimeError("no network")
    out = resolve_indicative({"code": "P/P", "description": "FELT PAD"}, ask=_boom)
    assert out["price_gbp"] is None
    assert "no network" in out["missing"]


# ── and what it must never read ──────────────────────────────────────────────────────

def test_a_figure_off_an_estimators_sheet_cannot_be_laundered_through_the_researcher():
    """Howard's £250 does not become a price by being handed to a model and returned as
    its answer. That produces a figure that LOOKS researched and is not."""
    out = resolve_indicative(
        {"code": "X-PLATE", "description": "plating", "mass_kg": 0.9},
        as_of=_TODAY, ask=_researcher(price_gbp=250.0, origin="estimator_sheet"))
    assert out["price_gbp"] is None
    assert "estimator_sheet" in out["missing"]


def test_a_config_literal_is_barred_as_a_source_too():
    out = resolve_indicative({"code": "P/P", "description": "FELT PAD"}, as_of=_TODAY,
                             ask=_researcher(origin="config_literal"))
    assert out["price_gbp"] is None
    assert "config" in out["missing"]


def test_an_amount_from_another_job_is_barred():
    out = resolve_indicative({"code": "P/P", "description": "FELT PAD"}, as_of=_TODAY,
                             ask=_researcher(origin="other_job"))
    assert out["price_gbp"] is None


def test_a_poisoned_INPUT_never_even_reaches_the_researcher():
    """Barred as an INPUT, not only as an output — a brief that quoted a previous price
    would be asking the model to agree with it."""
    seen = []

    def _watch(brief):
        seen.append(brief)
        return dict(_FULL)

    out = resolve_indicative(
        {"code": "X-PLATE", "description": "plating", "mass_kg": 0.9,
         "input_origins": {"mass_kg": "manual_estimate"}},
        as_of=_TODAY, ask=_watch)
    assert out["price_gbp"] is None
    assert seen == [], "the researcher was called with a contaminated brief"
    assert "manual_estimate" in out["missing"]


def test_a_clean_input_is_not_barred():
    """The control. If every origin were barred the guard would prove nothing."""
    out = resolve_indicative(
        {"code": "X-PLATE", "description": "plating", "mass_kg": 0.9,
         "input_origins": {"mass_kg": "solidworks_model"}},
        as_of=_TODAY, ask=_researcher(price_gbp=3.20, unit="kg",
                                      quantity_basis="per kg"))
    assert out["price_gbp"] is not None


# ── the label is one spelling, everywhere ────────────────────────────────────────────

def test_the_status_matches_the_gate_and_the_brief_never_carries_a_price():
    assert LLM_INDICATIVE_STATUS == "LLM indicative - review required"
    brief = research_brief({"code": "X-PLATE", "description": "plating", "mass_kg": 0.9})
    assert "250" not in str(brief), "the brief must not quote a previous price back"
    assert "120" not in str(brief)


# ── and it is actually on the path ───────────────────────────────────────────────────

def test_the_engine_consults_rung_four_where_the_config_table_used_to_answer():
    """A producer nobody calls is not a rung. This is the seam the withdrawn commodity
    table used to sit in — consulted last, after the catalogue, UDEF and history."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "src" / "estimator.py"
           ).read_text(encoding="utf-8")
    assert "from indicative_price import resolve_indicative as _rung4" in src
    # After the commodity rung, not before it: a real rate still wins.
    assert src.index("standard_commodity_price as _std_commodity") < \
        src.index("from indicative_price import resolve_indicative as _rung4")


def test_the_engine_puts_its_own_researcher_behind_the_seam():
    """The producer does not know how to search; the engine does. Injected, so the rule
    about what counts as evidence is testable without a network."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "src" / "estimator.py"
           ).read_text(encoding="utf-8")
    assert "from web_ai_price_lookup import lookup_web_ai_price as _look" in src
    assert "ask=_researcher," in src


def test_an_unpriced_line_keeps_the_reason_for_the_estimator():
    """What the workbook shows instead of a number, and which source to go and get."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "src" / "estimator.py"
           ).read_text(encoding="utf-8")
    assert 'NOT PRICED — {_ind[\'missing\']}' in src


def test_the_evidence_and_the_working_travel_with_the_price():
    """A price on the sheet whose evidence stayed behind is a price nobody can check —
    which is the state this whole rung exists to avoid."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent / "src" / "estimator.py"
           ).read_text(encoding="utf-8")
    start = src.index('"pricing_mode": "llm_indicative"')
    block = src[start:start + 400]
    assert '"evidence": _ind.get("evidence")' in block
    assert '"calculation": _ind.get("calculation")' in block
