"""A board the engine holds a £/kg rate for is not costed at £0.

8352-01-03 is a 1235x365x12 timber panel. The engine holds MATERIAL_PRICE_GBP_PER_KG['MDF'] =
1.35 and MATERIAL_DENSITY_KG_PER_M3['MDF'] = 750, so material_has_a_rate is true — which is why
it is not on the no-rate list and gets no market fallback. Yet the Other Sheet block read a
ready-made £/sheet, found none, and shipped the panel at £0 with the rate in plain sight. The
block never turned the £/kg into a £/sheet the way the steel block turns £/tonne into a sheet
cost.

Now it does: £/kg x sheet volume x density gives the cost of the sheet the part nests into, and
the workbook divides that by parts-per-sheet exactly as it does for steel. A rate that lives in
config is reproducible, so this is an SDI material rate, not an unrepeatable AI figure.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import wb_populate as wb  # noqa: E402
import config  # noqa: E402


def test_1235x365x12_mdf_is_not_free():
    """THE GUARD. The exact panel that shipped at £0 now has a sheet price from its config rate."""
    price = wb._board_sheet_price_from_kg_rate("MDF", 12, 2440, 1220)
    assert price is not None and price > 0
    # 2.44 x 1.22 x 0.012 m3 x 750 kg/m3 x 1.35 £/kg = ~36.18 per 2440x1220 sheet
    assert price == pytest.approx(36.18, abs=0.5)


def test_it_matches_the_hand_calculation():
    vol = (2.44) * (1.22) * (0.012)                       # m3
    expected = round(vol * config.MATERIAL_DENSITY_KG_PER_M3["MDF"]
                     * config.MATERIAL_PRICE_GBP_PER_KG["MDF"], 2)
    assert wb._board_sheet_price_from_kg_rate("MDF", 12, 2440, 1220) == expected


def test_birch_ply_prices_higher_than_mdf():
    """Once the material identity is right, birch ply (1.65) costs more than MDF (1.35) — so the
    ply-vs-MDF conflict is a real money difference, not cosmetic."""
    mdf = wb._board_sheet_price_from_kg_rate("MDF", 12, 2440, 1220)
    ply = wb._board_sheet_price_from_kg_rate("BIRCH_PLYWOOD", 12, 2440, 1220)
    assert ply > mdf


def test_a_material_with_no_rate_returns_none_not_zero():
    """An honest gap, never a guessed number: no rate/density in config -> None, so the caller
    still flags the true £0, rather than inventing a price."""
    assert wb._board_sheet_price_from_kg_rate("UNOBTANIUM", 12, 2440, 1220) is None


def test_a_missing_dimension_returns_none():
    assert wb._board_sheet_price_from_kg_rate("MDF", None, 2440, 1220) is None
    assert wb._board_sheet_price_from_kg_rate("MDF", 12, 0, 1220) is None


def test_underscore_and_space_spellings_both_resolve():
    assert wb._board_sheet_price_from_kg_rate("MDF BOARD", 12, 2440, 1220) == \
        wb._board_sheet_price_from_kg_rate("MDF_BOARD", 12, 2440, 1220)


def test_the_block_uses_the_derivation():
    """Wired into the Other Sheet block before the £0 flag."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "wb_populate.py"),
               encoding="utf-8").read()
    assert "_board_sheet_price_from_kg_rate(" in src
    assert src.index("_board_sheet_price_from_kg_rate(\n                pe.get") \
        < src.index("has no sheet price")
