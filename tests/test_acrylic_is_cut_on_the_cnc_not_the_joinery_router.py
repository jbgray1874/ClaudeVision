"""Acrylic routing belongs on CNC, not on the joinery router.

THE ESTIMATOR'S OWN WORDS, on 12349-02: "It is picking up acrylic as CNC Joinery when it should
be CNC (Labour Rates different)."

He is right, and the rate card carries both rows:

    CNC          GBP 43.36 /hr   set-up 10 min   dept CNC
    CNC Joinery  GBP 64.07 /hr   set-up 15 min   dept CNCJ

They are different machines for different stock. `OP_NAME_MAP_ACRYLIC` had no CNC entry, so
`cnc_routing` on an acrylic part fell through to the generic map and landed on CNCJ — the 5 mm
high-impact acrylic front cover charged at the same rate as the 6 mm MDF packer. About GBP 21
an hour of difference on every acrylic routing line, plus five minutes of set-up it never uses.

WHAT MUST NOT MOVE. Board still goes to the joinery router: _map_operation checks the joinery
map BEFORE the acrylic one, which is what that row is for.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wb_populate import _map_operation                                  # noqa: E402


def test_acrylic_routing_goes_to_the_cnc():
    for _op in ("cnc_routing", "cnc", "cnc_joinery"):
        assert _map_operation(_op, True, "", "HIGH IMPACT ACRYLIC") == "CNC", _op
        assert _map_operation(_op, True, "", "ACRYLIC") == "CNC", _op


def test_board_still_goes_to_the_joinery_router():
    """THE ROW THAT ROUTER RATE IS FOR. A 6 mm MDF packer is cut on the joinery router and the
    joinery map is consulted first, so this is untouched by the acrylic entry."""
    for _mat in ("MDF", "TIMBER", "PLYWOOD"):
        assert _map_operation("cnc_routing", True, "", _mat) == "CNC Joinery", _mat


def test_metal_is_unchanged():
    """Nothing here is about steel, and a metal part never reaches the acrylic map."""
    assert _map_operation("cnc_routing", False, "", "MILD STEEL") == "CNC Joinery"


def test_both_rows_are_real_and_differently_priced():
    """ASSERTED AGAINST THE RATE CARD, so this cannot quietly point at a row that does not exist
    or at one that costs the same — either of which would make the fix pointless while passing."""
    from sheet_steel_costing import RATE_CARD
    _cnc, _joinery = RATE_CARD["CNC"], RATE_CARD["CNC Joinery"]
    assert _cnc[2] == "CNC" and _joinery[2] == "CNCJ"
    assert _cnc[0] < _joinery[0], "the acrylic row must be the cheaper machine, or this is noise"
    assert round(_joinery[0] - _cnc[0], 2) > 15.0, "and the gap is what makes it worth fixing"


def test_an_unnamed_material_keeps_the_joinery_row():
    """THE CONTRACT THIS FUNCTION PUBLISHES: "without it a timber part behaves as it did
    before". A caller that names no material cannot be told board from acrylic — `is_acrylic` is
    really _is_board and is true of MDF — so the cheaper machine is not handed out on a guess.

    My first attempt put the CNC entry in OP_NAME_MAP_ACRYLIC, which moved every material-less
    call and the MDF packer with it. The decision is asked of the MATERIAL instead."""
    assert _map_operation("cnc_routing", True) == "CNC Joinery"
    assert _map_operation("cnc_routing", True, "", "") == "CNC Joinery"


def test_the_material_test_is_positive_not_merely_not_metal():
    """_is_board answers "not sheet metal" and is true of MDF. This one asks whether the stock
    IS acrylic, which is the question the machine choice actually turns on."""
    from wb_populate import _is_acrylic_material
    for _yes in ("ACRYLIC", "5mm HIGH IMPACT ACRYLIC", "Perspex", "PMMA"):
        assert _is_acrylic_material(_yes), _yes
    for _no in ("MDF", "TIMBER", "PLYWOOD", "MILD STEEL", "", None):
        assert not _is_acrylic_material(_no), _no
