"""A sheet metal priced at its own rate is not costed as mild steel (D-559).

401918-01-GA, 21 Oct 2026 11:14 book: 401918-01-01M, a 3 mm STAINLESS STEEL rub strip, sat in
the Sheet Steel block at Estimate!M93 and the sheet costed it from L5, the mild-steel £/tonne —
£1.38 where a stainless sheet gives about £4.75. The engine's own record had the stainless rate
(config £3.10/kg); the block it was written to has one rate for every row.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import config  # noqa: E402
import wb_populate as wbp  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("mat", ["STAINLESS STEEL", "STAINLESS_STEEL", "ALUMINIUM", "ALUMINUM"])
def test_a_metal_far_from_the_sheet_steel_rate_is_priced_at_its_own(mat):
    rate = wbp._own_sheet_rate(mat)
    assert rate == config.MATERIAL_PRICE_GBP_PER_KG[mat]
    l5 = config.WORKBOOK_INPUT_DEFAULTS["sheet_steel_cost_per_tonne_gbp"] / 1000.0
    assert abs(rate - l5) / l5 > config.SHEET_STEEL_RATE_FAMILY_TOLERANCE


@pytest.mark.parametrize("mat", ["MILD STEEL", "MILD_STEEL", "ZINTEC", "GALVANISED STEEL", "CR4 MILD STEEL"])
def test_l5s_own_steels_stay_in_the_sheet_steel_block(mat):
    assert wbp._own_sheet_rate(mat) is None


def test_a_board_or_an_unrated_material_is_not_this_question():
    assert wbp._own_sheet_rate("MDF") is None                 # a board: the board path's
    assert wbp._own_sheet_rate("ACRYLIC") is None
    assert wbp._own_sheet_rate("UNOBTAINIUM") is None         # no rate: nothing to compare
    assert wbp._own_sheet_rate("") is None


def test_the_tolerance_is_configs(monkeypatch):
    monkeypatch.setattr(config, "SHEET_STEEL_RATE_FAMILY_TOLERANCE", 5.0, raising=False)
    assert wbp._own_sheet_rate("STAINLESS STEEL") is None     # within a very wide family


def test_the_router_sends_it_to_other_sheet_material_before_the_steel_branch():
    src = (ROOT / "src" / "wb_populate.py").read_text(encoding="utf-8")
    own = src.index("# 2c. A SHEET METAL PRICED AT ITS OWN RATE IS NOT L5's STEEL (D-559)")
    steel = src.index("# 3. steel (sheet or stated-weight, with real geometry)")
    assert own < steel, "the own-rate branch must be tested before the Sheet Steel branch takes it"
    seg = src[own:steel]
    assert "_own_sheet_rate(mat)" in seg and "board_parts.append(pe)" in seg
    assert "blank_dimensions(pe)" in seg                     # only with a blank it can nest
    assert 'pe["_other_sheet_at_own_rate_gbp_per_kg"]' in seg


def test_the_row_nests_into_the_metals_own_standard_sheet():
    """2500 x 1250 for stainless, not a board's 2440 x 1220 — so the cost per sheet it writes
    (£/kg x sheet volume x density) is the sheet the shop buys."""
    src = (ROOT / "src" / "wb_populate.py").read_text(encoding="utf-8")
    body = src.split("def _write_board_row(")[1].split("\n    row = o[\"first_row\"]")[0]
    assert '_other_sheet_at_own_rate_gbp_per_kg' in body and 'STANDARD_SHEET_SIZES_MM' in body
    price = wbp._board_sheet_price_from_kg_rate("STAINLESS STEEL", 3.0, 2500, 1250)
    assert price == round(2.5 * 1.25 * 0.003 * 8000 * 3.10, 2)         # £232.50 a sheet
