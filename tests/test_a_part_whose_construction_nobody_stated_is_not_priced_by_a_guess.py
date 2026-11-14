"""A PART WHOSE CONSTRUCTION NOBODY STATED IS NOT PRICED BY A MARKET GUESS (14 Nov 2026).

12674-02-GA's base was charged £8.32 with no material and no thickness; 12674-01-GA's £6.24 as
"timber" with no thickness. Both were measured. Both reached the made-part allowance (D-485),
which asked the market for "sheet stock ... its size is not known", and the answers were
charged. Reviewer: "Base still uses £8.32 with unknown material"; "labelled timber without a
thickness, not an evidenced construction cost". JG: no hard-coded or guessed prices; flag what
needs a decision rather than silently choosing it.

The line now stays an honest gap that says what is missing and asks for it, and the market is
not asked. A part whose material and gauge are stated still takes an allowance where it needs
one, and a part with its material known and no size still takes D-485's.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import estimator as E  # noqa: E402


def _answer(price=8.0, item="18 mm MFC board"):
    return {"price_gbp": price, "unit": "each", "source": "https://example.test/board",
            "as_of": "2026-11-13", "quantity_basis": "1 off", "item_priced": item,
            "price_is_reproducible": True}


@pytest.fixture()
def asked(monkeypatch):
    calls = []
    monkeypatch.setattr(E, "_rung4_researcher", lambda brief: (calls.append(brief), _answer())[1])
    return calls


def _base(material=None, thickness=None, length=350.0, width=250.0):
    """The 12674-02-GA base as it reached the allowance: a made part, measured, routed."""
    me = {"material": material, "thickness_mm": thickness, "unpriced_inputs": []}
    if length and width:
        me.update(blank_length_mm=length, blank_width_mm=width)
    pe = {"part_number": "T-01J", "description": "BASE", "quantity": 1, "review_flags": [],
          "material_estimate": me,
          "route_context": {"textual_operations": ["cnc_routing", "hole_machining"]}}
    if material:
        pe["normalized_material"] = material
    return pe


def test_a_measured_base_with_no_material_and_no_thickness_is_not_priced(asked):
    pe = _base()
    assert E._made_part_material_allowance(pe) is None
    assert asked == [], "the market was asked to guess what the part is made of"
    assert pe["construction_not_established"]["missing"] == ["its material", "its thickness"]
    flag = next(f for f in pe["review_flags"] if "construction not established" in f)
    assert "NOT PRICED" in flag and "350 x 250 mm" in flag
    q = pe["manufacturing_questions"][0]
    assert "its material and its thickness not stated" in q["issue"]
    assert q["source"] == "estimator.construction_not_established"


def test_timber_with_no_thickness_is_not_priced_either(asked):
    pe = _base(material="TIMBER", length=2369.6, width=295.2)
    assert E._made_part_material_allowance(pe) is None and asked == []
    assert pe["construction_not_established"]["missing"] == ["its thickness"]
    assert any("2369.6 x 295.2 mm, timber" in f for f in pe["review_flags"])


def test_the_same_base_with_its_material_and_gauge_stated_is_priced(asked):
    pe = _base(material="MFC", thickness=18.0)
    assert E._made_part_material_allowance(pe) == 8.0
    assert len(asked) == 1 and "construction_not_established" not in pe


def test_a_part_with_its_material_known_and_no_size_keeps_its_allowance(asked):
    """D-485 stands: the market prices the raw stock for one part of a stated material."""
    pe = _base(material="MILD_STEEL", length=None, width=None)
    assert E._made_part_material_allowance(pe) == 8.0 and len(asked) == 1


def test_a_bracket_with_no_material_is_not_priced_by_a_guess(asked):
    pe = {"part_number": "J-CPT09", "description": "BRACKET", "quantity": 30,
          "assumed_job_quantity": 200, "review_flags": []}
    assert E._made_part_material_allowance(pe) is None and asked == []
    assert pe["construction_not_established"]["missing"] == ["its material"]


def test_through_the_last_resort_pass_the_base_stays_a_gap_and_says_so(asked):
    base, known = _base(), _base(material="MFC", thickness=18.0)
    known["part_number"] = "T-02J"
    rescued = E.apply_last_resort_prices([base, known], E._last_resort_lookup)
    assert rescued == 1
    assert not (base["material_estimate"].get("extended_material_cost_gbp") or 0)
    assert "last_resort" not in str(base.get("costing_basis") or "")
    assert any("construction not established" in f for f in base["review_flags"])
    assert known["costing_basis"] == "last_resort_market_indication"
    assert known["material_estimate"]["extended_material_cost_gbp"] == 8.0


def test_an_uncoded_line_keeps_todays_allowance(asked):
    """6364's cam locks: no drawing number, read as made because they carry their parent's
    hole and polish. Their misclassification is its own fault; this change does not turn
    their market figure into a question about their construction."""
    pe = {"part_number": None, "description": "CAM LOCK - 90deg. 19 x 16mm", "quantity": 4,
          "review_flags": [], "material_estimate": {"blank_length_mm": 659.0, "blank_width_mm": 444.0},
          "route_context": {"textual_operations": ["hole_machining", "diamond_polish"]}}
    assert E._made_part_material_allowance(pe) == 8.0 and len(asked) == 1
    assert "construction_not_established" not in pe
