r"""
test_the_sheet_and_the_engine_nest_the_same_way.py

THE ENGINE SAID SEVEN PARTS PER SHEET AND THE WORKBOOK SAID FOUR, FOR THE SAME PART.

11650-01-05A, a 1202 x 689 x 6mm polycarbonate door on a 3050 x 2050 sheet. The engine's
record priced it at GBP 18.69 and the Estimate sheet charged GBP 35.28 -- nearly a factor
of two, on the same run, from the same record, in the direction of under-charging.

Neither number was a mistake in isolation. estimator.select_sheet_size implements the
template's Sheet Steel nesting exactly:

    K38   INT(I/(F+20)) x INT((J-80)/(G+10))

and its own docstring says the Other Sheet Material section "uses a different rule (-5
margin, +20 both axes); that is handled separately for non-steel materials". It was handled
nowhere. The plastic path divided full sheet area by part area instead, which is not nesting
at all -- it ignores the gaps between parts and the unusable strip down the edge:

    _acr_pps = int(_full_sheet_area_m2 / _part_area_m2)          # 7.55 -> 7

The reasoning written beside it was that the sheet area cancels in the workbook's L/J, so
the cost comes out as exactly area x rate whatever J is. The algebra is right and the
premise is false: wb_populate writes L, the blank L/W and the sheet L/W into the row, and
the TEMPLATE recomputes J itself. The engine's J is never read by anything.

Which basis is commercially right -- pay for the area you use, or pay for the sheets you buy
-- is a real question and is not decided here. What is decided is that the two artefacts stop
charging different money: the engine predicts what the workbook will charge, and keeps the
area figure beside it so the assumption is visible.

SECOND DEFECT, FOUND ON THE WAY. "Is this part costed in the Other Sheet Material block" had
three answers: wb_populate's substring tokens, xlsx_output's exact-match set, and the engine's
silence. The first two disagree on every material anybody actually writes on a drawing.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import costed_facts as cf  # noqa: E402


# ── the workbook's own J51 rule ─────────────────────────────────────────────────────
def test_the_door_nests_four_to_a_sheet_like_the_workbook_says():
    """The number the Estimate sheet computed for 11650-01-05A. INT(3050/(1202+20)) = 2,
    INT((2050-5)/(689+20)) = 2, so 4 -- not the 7 the area divide produced."""
    assert cf.other_sheet_parts_per_sheet(1202, 689, 3050, 2050) == 4


def test_it_is_not_the_steel_rule():
    """K38 and J51 differ in both the margin and the gap. Using one for the other is how
    this started, and a part exists where they disagree -- so prove they are not the same
    function wearing two names."""
    from estimator import select_sheet_size
    steel = select_sheet_size("MILD_STEEL", 400, 300)["parts_per_sheet"]
    other = cf.other_sheet_parts_per_sheet(400, 300, 3050, 2050)
    assert steel != other, (
        f"both rules returned {steel}; the Other Sheet block is being nested by the steel "
        f"rule again, which is the defect this file is about")


def test_a_part_bigger_than_the_sheet_is_not_a_quantity():
    """None, not 0 and not 1. Zero divides into an infinite cost; one quietly claims a part
    fits on a sheet it is bigger than, and the row looks costed."""
    assert cf.other_sheet_parts_per_sheet(4000, 689, 3050, 2050) is None
    assert cf.other_sheet_parts_per_sheet(1202, 2500, 3050, 2050) is None


@pytest.mark.parametrize("args", [
    (None, 689, 3050, 2050), (1202, None, 3050, 2050), (1202, 689, None, 2050),
    (0, 689, 3050, 2050), ("wide", 689, 3050, 2050),
])
def test_a_missing_dimension_is_not_nested_into_a_number(args):
    assert cf.other_sheet_parts_per_sheet(*args) is None


def test_the_nest_does_not_rotate_the_part():
    """The template does not rotate, so an engine that did would produce a number the sheet
    disagrees with -- which is the whole defect, arrived at from the other side."""
    # 1000 x 500, NOT the door. The door's two orientations both happen to yield 4 -- an
    # accidental tie that made the first version of this test pass on a nester that DID
    # rotate. An accidental match is worse than a miss, because it hides the miss.
    wide = cf.other_sheet_parts_per_sheet(1000, 500, 3050, 2050)     # 3 x 2 = 6
    tall = cf.other_sheet_parts_per_sheet(500, 1000, 3050, 2050)     # 5 x 2 = 10
    assert (wide, tall) == (6, 10), "the J51 arithmetic itself has changed"
    assert wide != tall, "the nester is rotating parts; the workbook never does"


# ── the engine charges what the sheet charges ───────────────────────────────────────
def _door():
    return {"part_number": "11650-01-05A", "description": "DOOR",
            "normalized_material": "POLYCARBONATE", "materials": ["POLYCARBONATE"],
            "quantity": 1, "normalized_thickness_mm": 6,
            "normalized_geometry": {"blank_length_mm": 1202, "blank_width_mm": 689}}


def test_the_engine_and_the_workbook_agree_on_the_door():
    """M = (L/J) x (1+K), computed here from the same L, J and K the template uses. If this
    drifts, the JSON and the spreadsheet are charging different money again and only one of
    them is in front of the estimator."""
    from estimator import estimate_material
    me = estimate_material(_door())
    sheet_price, pps = me["sheet_price_gbp"], me["parts_per_sheet"]
    assert pps == 4
    assert me["unit_material_cost_gbp"] == pytest.approx(
        round(sheet_price / pps * 1.04, 2), abs=0.02), (
        "the engine's per-part figure is no longer the workbook's (L/J)x(1+K)")


def test_the_area_basis_is_kept_where_it_can_be_argued_with():
    """The other answer is a commercial position, not a bug. Charging one and hiding the
    other is how a decision like this stops being reviewable."""
    from estimator import estimate_material
    me = estimate_material(_door())
    assert me["area_only_cost_per_part_gbp"] == pytest.approx(18.69, abs=0.02)
    assert me["nesting_uplift_x"] == pytest.approx(1.89, abs=0.02)
    assert me["nesting_rule"] == "workbook_other_sheet_J51"


# ── one answer to "is this an other-sheet part" ─────────────────────────────────────
@pytest.mark.parametrize("material", [
    "MR MDF", "6MM ABS", "CLEAR POLYCARB", "POLYCARBONATE", "ACRYLIC", "3MM HIPS",
    "MELAMINE FACED CHIPBOARD", "BIRCH PLYWOOD",
])
def test_materials_as_drawings_actually_write_them_are_other_sheet(material):
    """xlsx_output's exact-match set said no to every one of these while wb_populate said
    yes, so the workbook and the AI spreadsheet could stream the same part differently."""
    assert cf.is_other_sheet_material(material) is True


@pytest.mark.parametrize("material", [
    "MILD STEEL", "STAINLESS STEEL", "ALUMINIUM", "ZINTEC", "2MM MS", "COLD ROLLED STEEL",
])
def test_metal_is_not_other_sheet(material):
    assert cf.is_other_sheet_material(material) is False


def test_every_reader_asks_the_same_function():
    """THE CALLERS, NOT THE HELPER. A shared definition that two modules keep their own copy
    of alongside is not a shared definition, and this codebase has shipped that twice."""
    import ast
    offenders = []
    for name in ("wb_populate.py", "xlsx_output.py", "estimator.py"):
        tree = ast.parse((ROOT / "src" / name).read_text(encoding="utf-8-sig",
                                                         errors="replace"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_is_board":
                body = ast.unparse(node)
                if "is_other_sheet_material" not in body:
                    offenders.append(f"{name}:{node.lineno} keeps its own board vocabulary")
    assert not offenders, "\n  ".join(offenders)
