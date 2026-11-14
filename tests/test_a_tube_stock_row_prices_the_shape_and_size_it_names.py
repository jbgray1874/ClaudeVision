"""A tube stock row prices the shape and size it names (14 Nov 2026).

JG: "are the 2 new ai calculators in there too now?" ... "we need to instruct to put live".
The AI Tube calculator's stock rows were joined to the engine's section price rows, and the
engine's profile reader wanted three numbers, two sides and a wall. Estimating's sheet lists
89 priced stock rows and 55 of them are round or square tube written with two: "ERW ROUND
19.05 x 1.2mm (6.1m)", "ERW SQUARE 30 x 1.5mm (6.1m)", "28.58 O.D x 1.20 - ERW (6.1m)". None
of those priced anything. And one size in two shapes ("ERW RECT. 40 x 20 x 1.5mm" at £25.92,
"ERW FSO 40 x 20 x 1.5mm" at £10.00) was read as one profile and priced at the middle.

The rows below are in the sheet's own words, with figures of this test's own.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import estimator as E  # noqa: E402

SRC = "AI Tube calculator"
ROWS = [
    ("T1", "ERW ROUND 19.05 x 1.2mm (6.1m)", 6.10, SRC, "EA"),
    ("T2", "ERW SQUARE 30 x 1.5mm (6.1m)", 12.20, SRC, "EA"),
    ("T3", "28.58 O.D x 1.20 - ERW (6.1m)", 30.50, SRC, "EA"),
    ("T4", "ERW ROUND 34.93 DIA x 2mm (6.1m)", 36.60, SRC, "EA"),
    ("T5", "ERW RECT. 40 x 20 x 1.5mm (6.1m)", 24.40, SRC, "EA"),
    ("T6", "ERW FSO 40 x 20 x 1.5mm (6.1m)", 9.15, SRC, "EA"),
    ("T7", "ERW SQUARE 25 X 25MM (6.1M)", 8.54, SRC, "EA"),
    ("T8", "ERW Round 50.0 x 2.0mm Wall (6.1m)", 18.30, SRC, "EA"),
    ("T9", "ERW SQUARE 19 x 1.2mm (6.1m)", 3.05, SRC, "EA"),
]


def _rate(a, b, t, shape=""):
    got = E._select_catalogue_section_stock_rate(ROWS, a, b, t, shape=shape)
    return (got["rate_gbp_per_m"], [r["part_code"] for r in got["rows"]]) if got else None


@pytest.mark.parametrize("a, b, t, shape, code, per_m", [
    (19.05, 19.05, 1.2, "round", "T1", 1.0),
    (30.0, 30.0, 1.5, "box", "T2", 2.0),
    (28.58, 28.58, 1.2, "round", "T3", 5.0),
    (34.93, 34.93, 2.0, "round", "T4", 6.0),
    (50.0, 50.0, 2.0, "round", "T8", 3.0),
])
def test_a_round_or_square_row_written_with_two_numbers_prices_its_tube(a, b, t, shape, code,
                                                                        per_m):
    assert _rate(a, b, t, shape) == (per_m, [code])


def test_a_rectangle_and_a_flat_sided_oval_of_one_size_are_two_items():
    assert _rate(40, 20, 1.5, "box") == (4.0, ["T5"])
    assert _rate(40, 20, 1.5, "oval") == (1.5, ["T6"])


def test_a_round_row_does_not_price_a_square_of_its_size_nor_a_square_a_round():
    assert _rate(19.05, 19.05, 1.2, "round") == (1.0, ["T1"])
    assert _rate(19.0, 19.0, 1.2, "box") == (0.5, ["T9"])


def test_a_part_that_names_no_shape_gets_no_average_of_a_rectangle_and_an_oval():
    got = E._select_catalogue_section_stock_rate(ROWS, 40, 20, 1.5)
    assert got["conflict"] is True and got["rate_gbp_per_m"] is None
    assert sorted(r["part_code"] for r in got["rows"]) == ["T5", "T6"]


def test_a_row_with_no_wall_prices_nothing():
    assert E._section_row_profile("ERW SQUARE 25 X 25MM (6.1M)") is None
    assert _rate(25, 25, 2.0, "box") is None


def test_a_wall_of_another_gauge_is_another_tube():
    assert _rate(19.05, 19.05, 2.0, "round") is None


@pytest.mark.parametrize("words, shape", [
    ("ERW ROUND 19.05 x 1.2mm (6.1m)", "round"), ("28.58 O.D x 1.20 - ERW (6.1m)", "round"),
    ("ERW ROUND 34.93 DIA x 2mm (6.1m)", "round"), ("CHS 48.3 x 3.2", "round"),
    ("ERW FSO 40 x 20 x 1.5mm (6.1m)", "oval"), ("ERW RECT. 40 x 20 x 1.5mm (6.1m)", "box"),
    ("ERW SQUARE 30 x 1.5mm (6.1m)", "box"), ("SHS 30x30x2", "box"), ("30 x 30 x 2 @ 7500MM", ""),
])
def test_the_shape_a_row_names(words, shape):
    assert E._section_row_shape(words) == shape


@pytest.mark.parametrize("form, shape", [("CHS", "round"), ("SHS", "box"), ("RHS", "box"),
                                         ("OVAL", "oval"), ("FSO", "oval"), ("", ""),
                                         ("FLAT", "")])
def test_the_shape_a_parts_own_section_form_is(form, shape):
    assert E._section_form_shape(form) == shape


def test_three_number_rows_read_exactly_as_they_did():
    assert E._section_row_profile("ERW RECT. 50.8 x 25.4 x 1.2mm (6.1m)") == (25, 51, 1.2)
    assert E._section_row_profile("SHS 30x30x2 FRAME TUBE") == (30, 30, 2.0)


# ── THROUGH TO THE PART'S OWN MATERIAL COST ────────────────────────────────────────────────
def _part(form, a, b, t, length=1000.0):
    return {"part_number": "T-01-04M", "description": "TUBE", "quantity": 1,
            "normalized_material": "MILD STEEL",
            "section_stock": {"a": a, "b": b, "t": t, "length_mm": length, "profile_form": form}}


def test_a_round_tube_part_is_priced_from_its_round_stock_row(monkeypatch):
    monkeypatch.setattr(E, "_fetch_catalogue_section_rows", lambda: list(ROWS))
    me = E.estimate_part(_part("CHS", 19.05, 19.05, 1.2), job_quantity=1)["material_estimate"]
    assert me["cost_method"] == "catalogue_section_stock_length_rate", me.get("cost_method")
    assert me["rate_gbp_per_m"] == 1.0
    assert [r["part_code"] for r in me["stock_estimate"]["catalogue_rows"]] == ["T1"]
    assert abs(me["unit_material_cost_gbp"] - round(1.0 * 1.0 * me["waste_factor_applied"], 2)) < 0.011


def test_a_rectangular_tube_part_takes_the_rectangle_row_not_the_oval_of_its_size(monkeypatch):
    monkeypatch.setattr(E, "_fetch_catalogue_section_rows", lambda: list(ROWS))
    me = E.estimate_part(_part("RHS", 40, 20, 1.5), job_quantity=1)["material_estimate"]
    assert [r["part_code"] for r in me["stock_estimate"]["catalogue_rows"]] == ["T5"]
    assert me["rate_gbp_per_m"] == 4.0


# ── THE NEAREST SIZE, AND NO AVERAGE OF TWO PRICES (reviewer, 14 Nov 2026) ─────────────────
NEAR = [
    ("N1", "ERW ROUND 15.88 x 1.2mm (6.1m)", 6.10, SRC, "EA"),
    ("N2", "ERW ROUND 16 x 1.2mm (6.1m)", 12.20, SRC, "EA"),
    ("N3", "ERW SQUARE 25.4 X 2.0MM (6.1M)", 6.10, SRC, "EA"),
    ("N4", "ERW SQUARE 25 X 2.0MM (6.1M)", 18.30, SRC, "EA"),
]
TWICE = [
    ("D1", "ERW SQUARE 30 x 1.5mm (6.1m)", 6.10, SRC, "EA"),
    ("D2", "ERW SQUARE 30 x 1.5mm (6.1m)", 12.20, SRC, "EA"),
    ("L1", "SHS 30 x 30 x 1.5 @ 6000MM", 18.00, "Steel Co", "EA"),
]


def _pick(rows, a, b, t, shape=""):
    return E._select_catalogue_section_stock_rate(rows, a, b, t, shape=shape)


def test_a_part_takes_the_row_nearest_its_own_size_not_the_middle_of_two_tubes():
    assert [r["part_code"] for r in _pick(NEAR, 15.88, 15.88, 1.2, "round")["rows"]] == ["N1"]
    assert [r["part_code"] for r in _pick(NEAR, 16.0, 16.0, 1.2, "round")["rows"]] == ["N2"]
    assert [r["part_code"] for r in _pick(NEAR, 25.4, 25.4, 2.0, "box")["rows"]] == ["N3"]
    assert _pick(NEAR, 25.0, 25.0, 2.0, "box")["rate_gbp_per_m"] == 3.0


def test_two_sheet_rows_for_one_tube_at_different_prices_give_no_rate_and_are_named():
    got = _pick(TWICE, 30, 30, 1.5, "box")
    assert got["conflict"] is True and got["rate_gbp_per_m"] is None
    assert [r["part_code"] for r in got["rows"]] == ["D1", "D2"], "the catalogue row is not part of the conflict"


def test_two_sheet_rows_that_agree_are_the_rate():
    rows = [TWICE[0], ("D3", "ERW SQUARE 30 x 1.5mm (6.1m)", 6.10, SRC, "EA"), TWICE[2]]
    got = _pick(rows, 30, 30, 1.5, "box")
    assert got["rate_gbp_per_m"] == 1.0 and not got.get("conflict")
    assert sorted(r["part_code"] for r in got["rows"]) == ["D1", "D3"], \
        "the sheet's price stands over the catalogue's for the same tube"


def test_with_no_sheet_row_the_catalogue_rows_are_used_as_before():
    got = _pick([TWICE[2]], 30, 30, 1.5, "box")
    assert got["rate_gbp_per_m"] == 3.0 and [r["part_code"] for r in got["rows"]] == ["L1"]


def test_a_part_whose_sheet_rows_disagree_is_not_priced_from_them_and_asks(monkeypatch):
    monkeypatch.setattr(E, "_fetch_catalogue_section_rows", lambda: list(TWICE[:2]))
    part = _part("SHS", 30, 30, 1.5)
    me = E.estimate_part(part, job_quantity=1)["material_estimate"]
    assert me["cost_method"] != "catalogue_section_stock_length_rate", me["cost_method"]
    flag = next(f for f in part["review_flags"] if "AI TUBE CALCULATOR ROWS DISAGREE" in f)
    assert "D1" in flag and "D2" in flag and "nothing is averaged" in flag
    assert any(q.get("source") == "estimator.tube_calculator_rows_disagree"
               for q in part.get("manufacturing_questions") or [])


def test_two_walls_within_a_third_of_a_millimetre_are_still_two_tubes():
    rows = [("W1", "ERW SQUARE 20 x 1.22mm (6.1m)", 12.20, SRC, "EA"),
            ("W2", "ERW SQUARE 20 x 1.5mm (6.1m)", 6.10, SRC, "EA")]
    assert [r["part_code"] for r in _pick(rows, 20, 20, 1.5, "box")["rows"]] == ["W2"]
    assert [r["part_code"] for r in _pick(rows, 20, 20, 1.2, "box")["rows"]] == ["W1"]
