"""One board has one buying basis: a per-piece guess is never its sheet price (D-665).

12203-66-GA, 3 Nov 2026 19:48. Three 13.8 mm faced-MDF panels (Swiss Krono Oak D4428OV), each
with its blank, gauge and faced family, lacked only the board's sheet price: SDI Live matched no
row at 13.8 mm and the researched board rate produced no evidenced figure. The last-resort rescue
then asked the market, per panel, for "the raw material for one side panel; its size is not
known", and every answer was a price for one piece:

  * 01J and 03J: £4.50 and £9.50 written as sheet prices with a nest of one, refused as
    CONFLICTING BUYING BASES against nests of 203 and 49 (SCRUM-182) — £0;
  * 02J: no allowance could be researched, so the workbook's last gap-filler priced its sheet
    from the plain-MDF core: 2800 x 2070 x 13.8 mm at 750 kg/m3 and £1.35/kg = £80.98 a sheet,
    raw-core money on a laminated panel (D-666) — £0.65 charged.

(D-665 first credited the £80.98 to a per-piece allowance multiplied up; the 20:10 run's own
line for 02J, "no material allowance could be researched", disproved that. The per-piece
guard stays, because that path exists; the £80.98 was the £/kg gap-filler.)

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


def test_a_per_piece_allowance_is_never_multiplied_up_into_a_sheet_price():
    me = {"cost_per_part_gbp": 0.32, "parts_per_sheet": 261, "scrap_pct": 0.04,
          "cost_method": "last_resort_market_indication", "material_allowance_only": True}
    assert W.per_piece_price_basis(me)
    assert W.sheet_price_rebuilt_from_part_cost(me) is None


# ── D-666: a faced board is not its core by weight ──────────────────────────────────────

def test_the_80_98_is_the_plain_mdf_core_by_weight():
    """Where 02J's sheet price came from, to the penny."""
    assert W._board_sheet_price_from_kg_rate("MDF", 13.8, 2800, 2070) == 80.98


def test_a_faced_board_line_is_recognised_from_any_of_its_records():
    unpriced = _faced_unpriced("12203-66-02J", 270, 49)
    assert W.faced_board_line({}, unpriced)
    rescued = {"part_number": "12203-66-02J", "normalized_material": "MDF",
               "material_estimate": {"material": "MDF", "cost_method": "x"}}
    own = {"part_number": "12203-66-02J",
           "material_estimate": {"costing_material_family": "MFMDF"}}
    assert W.faced_board_line({"manufacturing_writeup": {"parts": [own]}}, rescued)
    plain = {"part_number": "P-01", "normalized_material": "MDF",
             "material_estimate": {"material": "MDF"}}
    assert not W.faced_board_line({}, plain)


def test_the_core_rate_gap_filler_is_not_reached_by_a_faced_board():
    import inspect
    src = inspect.getsource(W.populate_workbook)
    guard = src.index("if not _sheet_price and faced_board_line(summary, pe):")
    filler = src.index("_sheet_price = _board_sheet_price_from_kg_rate(", guard)
    assert "elif not _sheet_price:" in src[guard:filler], \
        "the £/kg gap-filler sits behind the faced-board refusal"


def test_a_nest_costed_part_still_gives_back_its_sheet_price():
    me = {"cost_per_part_gbp": 2.08, "parts_per_sheet": 40, "scrap_pct": 0.04,
          "cost_method": "board_sheet_rate"}
    assert W.sheet_price_rebuilt_from_part_cost(me) == 80.0
