"""One board has one buying basis: a per-piece guess is never its sheet price (D-665).

12203-66-GA, 3 Nov 2026 19:48. Three 13.8 mm faced-MDF panels (Swiss Krono Oak D4428OV), each
with its blank, gauge and faced family, lacked only the board's sheet price: SDI Live matched no
row at 13.8 mm and the researched board rate produced no evidenced figure. The last-resort rescue
then asked the market, per panel, for "the raw material for one side panel; its size is not
known", and every answer was a price for one piece:

  * 01J and 03J: £4.50 and £9.50 written as sheet prices with a nest of one, refused as
    CONFLICTING BUYING BASES against nests of 203 and 49 (SCRUM-182) — £0;
  * 02J: about £0.32 a piece, which the workbook multiplied by the sheet's 261 pieces into an
    "£80.98 sheet price" no supplier quoted — £0.65 charged.

One board, three answers. The gap is the board's price; the panels stay one consistent,
named gap until a real sheet price for the specified board is supplied or found.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import estimator as E  # noqa: E402
import wb_populate as W  # noqa: E402


def _faced_unpriced(pn, length, width):
    return {"part_number": pn, "description": "TABLE TOP TRAY - PANEL", "quantity": 1,
            "normalized_material": "MDF",
            "material_estimate": {
                "material": "MDF", "thickness_mm": 13.8,
                "blank_length_mm": length, "blank_width_mm": width,
                "unit_material_cost_gbp": None, "cost_per_part_gbp": None,
                "extended_material_cost_gbp": None, "unpriced_inputs": ["sheet_price"],
                "cost_method": "faced_board_unpriced", "costing_material_family": "MFMDF"}}


def test_a_sized_faced_board_waiting_on_its_sheet_price_is_not_rescued_per_piece():
    parts = [_faced_unpriced("12203-66-01J", 375, 49), _faced_unpriced("12203-66-02J", 270, 49),
             _faced_unpriced("12203-66-03J", 375, 270)]
    asked = []

    def _market(pe):
        asked.append(pe["part_number"])
        return 4.5

    assert E.apply_last_resort_prices(parts, _market) == 0
    assert asked == [], "no per-piece question is put for a board whose only gap is its price"
    for pe in parts:
        assert pe["material_estimate"]["cost_method"] == "faced_board_unpriced"
        assert not pe["material_estimate"].get("sheet_price_gbp")


def test_an_unsized_made_part_is_still_given_its_material_allowance():
    pe = {"part_number": "X-01M", "description": "BRACKET", "quantity": 1,
          "normalized_material": "MILD_STEEL",
          "material_estimate": {"material": "MILD_STEEL", "unpriced_inputs": ["thickness", "blank"],
                                "cost_per_part_gbp": None}}
    assert E._last_resort_price_is_needed(pe) is True


def test_the_front_panels_80_98_was_a_per_piece_allowance_multiplied_up():
    """The 19:48 arithmetic, and the refusal."""
    me = {"cost_per_part_gbp": 0.3227, "parts_per_sheet": 261, "scrap_pct": 0.04,
          "cost_method": "last_resort_market_indication", "material_allowance_only": True}
    old = round(0.3227 * 261 / 1.04, 2)
    assert abs(old - 80.98) < 0.01, "what the workbook wrote as the board's sheet price"
    assert W.per_piece_price_basis(me)
    assert W.sheet_price_rebuilt_from_part_cost(me) is None


def test_a_nest_costed_part_still_gives_back_its_sheet_price():
    me = {"cost_per_part_gbp": 2.08, "parts_per_sheet": 40, "scrap_pct": 0.04,
          "cost_method": "board_sheet_rate"}
    assert W.sheet_price_rebuilt_from_part_cost(me) == 80.0
