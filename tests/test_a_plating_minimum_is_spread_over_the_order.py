"""A plating minimum is spread over the order, so it falls away at volume (D-689).

12693-01-GA, 4 Nov 2026: the worktop weldment's plating line was priced off the trade card,
18.3 kg at £2.50/kg with the plater's £95 minimum. At 1 off the minimum governs and £95 is
right. The Estimate cell held £95 as a literal and the break table repeated it in every
column, so the 50-off unit carried the whole minimum again: about £49 a unit too much, £2,450
on the order. The card's unit is max(mass x rate, minimum / order); the line now carries
both halves, the break table works the sum at each quantity, and the Estimate cell reads the
break row like every other line that moves.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import material_price_break as mpb  # noqa: E402

_LINE = {"unit_gbp": 45.75, "order_minimum_gbp": 95.0}


def test_the_minimum_governs_one_off():
    assert mpb._price_at(_LINE, 1) == pytest.approx(95.0)


def test_the_rate_governs_once_the_minimum_is_spread_thin():
    assert mpb._price_at(_LINE, 50) == pytest.approx(45.75)


def test_between_the_two_the_minimum_is_shared():
    assert mpb._price_at({"unit_gbp": 10.0, "order_minimum_gbp": 95.0}, 5) == pytest.approx(19.0)


def test_a_flat_line_is_unchanged():
    assert mpb._price_at({"unit_gbp": 1.5}, 50) == pytest.approx(1.5)


def test_the_break_table_takes_both_halves_from_the_estimate(monkeypatch):
    import costed_facts
    monkeypatch.setattr(costed_facts, "costed_job", lambda _s: {"lines": [
        {"sheet_row": 21, "part_number": "12999-01-104-PLATE", "charged_unit_gbp": 95.0},
        {"sheet_row": 22, "part_number": "FIX1", "charged_unit_gbp": 0.22}]})
    summary = {"estimate_summary": {"part_estimates": [
        {"part_number": "12999-01-104-PLATE",
         "unit_with_order_minimum": {"unit_gbp": 45.75, "order_minimum_gbp": 95.0}},
        {"part_number": "FIX1"}]}}
    lines = {ln["code"]: ln for ln in mpb.lines_from_record(summary)}
    plate = lines["12999-01-104-PLATE"]
    assert plate["unit_gbp"] == 45.75 and plate["order_minimum_gbp"] == 95.0
    assert mpb._price_at(plate, 1) == pytest.approx(95.0)
    assert mpb._price_at(plate, 50) == pytest.approx(45.75)
    assert "order_minimum_gbp" not in lines["FIX1"]


def test_the_estimate_cell_reads_the_break_row_for_such_a_line():
    src = (ROOT / "src" / "wb_populate.py").read_text(encoding="utf-8")
    i = src.index("AND A UNIT RATE WITH AN ORDER MINIMUM (D-689)")
    block = src[i:i + 700]
    assert 'pe.get("unit_with_order_minimum")' in block
    assert "if (_at_breaks or _with_minimum)" in block


def _plated(finish, kg=18.3, order=1):
    from estimator import apply_subcontract_plating
    parts = [{"part_number": "12999-01-104", "description": "WORKTOP WELDMENT",
              "normalized_finish": finish, "is_assembly_parent": True, "quantity": 1,
              "material_estimate": {"unit_material_mass_kg": kg}},
             {"part_number": "12999-01-104-PLATE", "_plating_placeholder": True,
              "_plating_weldment": "12999-01-104",
              "_plating_members": ["12999-01-104"], "quantity": 1,
              "description": "plating"}]
    apply_subcontract_plating(parts, {"customer": "Test"}, order, parts)
    return parts[1]


def test_the_plating_line_records_its_rate_and_minimum():
    line = _plated("ZINC PLATED")
    assert line["material_estimate"]["cost_method"] == "subcontract_plating_indicative"
    assert line["unit_material_cost_gbp"] == pytest.approx(95.0)
    halves = line["unit_with_order_minimum"]
    assert halves["unit_gbp"] == pytest.approx(18.3 * 2.5)
    assert halves["order_minimum_gbp"] == pytest.approx(95.0)


def test_a_line_not_priced_off_the_card_carries_no_halves():
    """A decorative finish is asked of the finisher (D-683): nothing to spread."""
    line = _plated("LIGHT AGED ZINC PLATED WITH WAXED")
    assert line["material_estimate"]["cost_method"] == "subcontract_plating_quote_needed"
    assert "unit_with_order_minimum" not in line
