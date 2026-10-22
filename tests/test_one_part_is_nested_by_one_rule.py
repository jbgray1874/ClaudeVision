"""A part is nested by ONE rule, and it is the rule its material is charged under.

WHAT THIS IS ABOUT. The workbook nests two ways:

    Estimate sheet, Sheet Steel           K38   INT(I/(F+20)) x INT((J-80)/(G+10))
    Estimate sheet, Other Sheet Material  J51   INT(I/(F+20)) x INT((J-5)/(G+20))

Adding J51 fixed the money on plastic and board and left the record lying. select_sheet_size
ran K38 over every material and wrote its answer into stock_estimate, so 11650-04's PETG side
panels came back carrying

    nesting_formula='INT(3050/(1250.0+20)) x INT((2050-80)/(525.0+10)) [template K38, ...]'

on a part that had been priced by J51. A diagnostic run to explain why a handed pair split in
price reported the STEEL rule for a plastic panel -- the number a reader sees was not the
number that charged the job, and the next fix was nearly aimed at the wrong thing.

WHY IT SURVIVED. On 1250 x 525 the two rules agree: 6 either way. A wrong rule that happens to
agree on the part in front of you is invisible until the geometry moves -- 1202 x 689 is where
they part company, and that is the door on the same job.

AND THE RULE HAS TO FOLLOW THE MATERIAL. The plastic cost branch is entered whenever an LLM
returns a GBP/m2 rate for a material the engine holds no price for, including a steel. Pinning
J51 to that branch would nest a steel by the plastic rule.
"""
from __future__ import annotations

import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import costed_facts  # noqa: E402
import estimator  # noqa: E402

SRC = os.path.join(os.path.dirname(__file__), "..", "src")

# The door on 11650, and the sheet it is cut from. The two rules disagree here: J51 nests 4
# and K38 nests 4 as well on the WIDTH axis only by luck of the margin -- what matters is that
# the two produce different formulae, and the one recorded is the one that charged.
DOOR_L, DOOR_W = 1202.0, 689.0
SIDE_PANEL_L, SIDE_PANEL_W = 1250.0, 525.0
SHEET_L, SHEET_W = 3050.0, 2050.0


def _material_estimate(material, blank_l, blank_w, thickness=3.0):
    """Through estimate_material, not through the nester. The defect was that the record and
    the money came from different calls, so a test that asks the nester directly cannot see
    it."""
    return estimator.estimate_material({
        "part_number": "T-1",
        "normalized_material": material,
        "normalized_thickness_mm": thickness,
        "quantity": 1,
        "blank_length_mm": blank_l,
        "blank_width_mm": blank_w,
        "material_estimate": {},
        "manufacturing_interpretation": {},
    })


def test_the_two_rules_actually_differ_on_a_real_part():
    """The premise. If J51 and K38 gave the same answer everywhere, every other assertion
    here would pass with the rules swapped and this file would prove nothing."""
    j51 = costed_facts.nest_on_sheet("ACRYLIC", DOOR_L, DOOR_W, SHEET_L, SHEET_W)
    k38 = costed_facts.nest_on_sheet("MILD STEEL", DOOR_L, DOOR_W, SHEET_L, SHEET_W)
    assert j51["nesting_formula"] != k38["nesting_formula"]
    # 2050-5 over 689+20 is 2 rows; 2050-80 over 689+10 is 2 as well, so the door is the case
    # where the FORMULA differs and the count does not. Find a part where the count differs
    # too, so nobody can claim the distinction is cosmetic.
    # 650 wide on a 2050 sheet: J51 gets (2050-5)/(650+20) = 3 rows, K38 gets
    # (2050-80)/(650+10) = 2. Half again as many parts off one sheet, on the same geometry.
    tall = costed_facts.nest_on_sheet("ACRYLIC", 500.0, 650.0, SHEET_L, SHEET_W)
    tall_steel = costed_facts.nest_on_sheet("MILD STEEL", 500.0, 650.0, SHEET_L, SHEET_W)
    assert tall["parts_per_sheet"] != tall_steel["parts_per_sheet"], (
        "the two rules must differ in COUNT somewhere, or the fix charges nothing new")


def test_a_plastic_part_carries_the_plastic_rule_on_its_record():
    me = _material_estimate("ACRYLIC", DOOR_L, DOOR_W)
    stock = me["stock_estimate"]
    assert stock["nesting_rule"] == "workbook_other_sheet_J51"
    assert "J51" in stock["nesting_formula"]
    assert "K38" not in stock["nesting_formula"], (
        "the steel rule was recorded for a part charged by the plastic one -- "
        "this is the defect, spelled out")


def test_the_nest_on_the_record_is_the_nest_that_priced_the_line():
    """Two answers to one question on one record is the whole defect family. The count the
    cost divided by and the count a reader sees have to be the same number."""
    me = _material_estimate("ACRYLIC", DOOR_L, DOOR_W)
    assert me["parts_per_sheet"] == me["stock_estimate"]["parts_per_sheet"]
    assert me["nesting_rule"] == me["stock_estimate"]["nesting_rule"]


def test_the_plastic_nest_matches_the_workbook_on_the_door():
    """1202 x 689 out of 3050 x 2050 nests 4 in the sheet the estimator is holding. The engine
    used to divide sheet area by part area and say 7."""
    me = _material_estimate("ACRYLIC", DOOR_L, DOOR_W)
    assert me["stock_estimate"]["parts_per_sheet"] == 4


def test_steel_is_still_nested_by_the_steel_rule():
    """The fix must not hand every part to J51. A regression here under-nests every steel part
    on every job, which is a bigger error than the one being fixed."""
    me = _material_estimate("MILD STEEL", SIDE_PANEL_L, SIDE_PANEL_W, thickness=2.0)
    stock = me["stock_estimate"]
    assert stock["nesting_rule"] == "workbook_sheet_steel_K38"
    assert "K38" in stock["nesting_formula"]


@pytest.mark.parametrize("material,expected", [
    ("PETG", "workbook_other_sheet_J51"),          # 11650-04's side panels
    ("2MM PETG", "workbook_other_sheet_J51"),      # as a DXF filename spells it
    ("ABS", "workbook_other_sheet_J51"),
    ("CLEAR POLYCARB", "workbook_other_sheet_J51"),
    ("MR MDF", "workbook_other_sheet_J51"),        # the exact-match set failed on this one
    ("HIGH IMPACT ACRYLIC", "workbook_other_sheet_J51"),
    ("FSC PINE", "workbook_other_sheet_J51"),
    ("MILD STEEL", "workbook_sheet_steel_K38"),
    ("STAINLESS STEEL 304", "workbook_sheet_steel_K38"),
    ("ALUMINIUM", "workbook_sheet_steel_K38"),
    ("", "workbook_sheet_steel_K38"),              # unknown material falls to the sheet block
    (None, "workbook_sheet_steel_K38"),
])
def test_the_rule_follows_the_material_not_the_code_path(material, expected):
    assert costed_facts.nesting_rule_for(material) == expected


def test_the_nesting_rule_and_the_workbook_block_can_never_disagree():
    """ONE CLASSIFIER. is_other_sheet_material decides which workbook block a part is costed
    in; the nesting rule is that block's rule. If these were two lists they would drift, which
    is exactly how _is_board came to exist twice and disagree with itself."""
    for token in costed_facts._PLASTIC_SHEET_TOKENS + costed_facts._BOARD_TIMBER_TOKENS:
        material = f"6MM {token.strip()} SHEET"
        assert costed_facts.is_other_sheet_material(material) is True
        assert costed_facts.nesting_rule_for(material) == "workbook_other_sheet_J51", material


# Every constant in both rules, pinned by a geometry that moves when it moves. Counts worked
# by hand from the template formulae on a 3050 x 2050 sheet:
#
#   J51  nx = INT(3050/(L+20))   ny = INT((2050-5)/(W+20))
#   K38  nx = INT(3050/(L+20))   ny = INT((2050-80)/(W+10))
#
# A table of "these two differ" is not enough on its own: it passes with both rules wrong in
# the same direction. These are absolute counts.
_NEST_TABLE = [
    # (material,  L,     W,      expected parts per sheet,  what it pins)
    ("ACRYLIC",   1202.0, 689.0,  4,  "the door, against the workbook"),
    ("ACRYLIC",   1250.0, 525.0,  6,  "11650-04's side panel"),
    ("ACRYLIC",    500.0, 670.0, 10,  "J51 width GAP: +10 would nest 15"),
    ("ACRYLIC",    500.0, 980.0, 10,  "J51 width MARGIN: -80 would nest 5"),
    ("ACRYLIC",   1520.0, 500.0,  3,  "J51 length gap: no gap would nest 6"),
    ("MILD STEEL", 500.0, 650.0, 10,  "K38 width gap: +20 would nest 15"),
    ("MILD STEEL", 500.0, 990.0,  5,  "K38 width MARGIN: -5 would nest 10"),
    ("MILD STEEL",1520.0, 500.0,  3,  "K38 length gap: no gap would nest 6"),
]


@pytest.mark.parametrize("material,length,width,expected,pins", _NEST_TABLE)
def test_each_rule_nests_exactly_what_the_template_nests(material, length, width, expected, pins):
    nest = costed_facts.nest_on_sheet(material, length, width, SHEET_L, SHEET_W)
    assert nest is not None and nest["parts_per_sheet"] == expected, pins


def test_a_steel_priced_through_the_llm_market_branch_is_still_nested_as_steel(monkeypatch):
    """The plastic COST branch is entered by ANY material an LLM returns a GBP/m2 rate for --
    the gate is `material in PLASTIC_SHEET_PRICED_MATERIALS or _llm_rate_m2`. It used to apply
    J51 unconditionally, so an exotic steel the engine holds no price for would have been
    nested by the plastic rule and under-charged.

    Through estimate_material, because asking nest_on_sheet directly tests the helper and the
    defect was in the caller.
    """
    monkeypatch.setattr(estimator, "market_indication_for",
                        lambda part, material: {"gbp_per_m2": 42.0, "source": "test"})
    # 500 x 290 on the DEFAULT 2500 x 1250 sheet this material resolves to: K38 nests 12 and
    # J51 nests 16, so applying the plastic rule to a steel would under-charge it by a third.
    me = _material_estimate("HARDOX 450", 500.0, 290.0, thickness=3.0)
    assert me["stock_estimate"]["parts_per_sheet"] == 12
    assert me["cost_method"] == "llm_market_sheet_rate", (
        "this part did not reach the LLM branch, so the test proves nothing about it")
    assert me["nesting_rule"] == "workbook_sheet_steel_K38"
    assert me["stock_estimate"]["nesting_rule"] == "workbook_sheet_steel_K38"
    assert me["parts_per_sheet"] == me["stock_estimate"]["parts_per_sheet"]


def test_a_part_that_does_not_nest_is_a_fact_not_a_quantity():
    """None, never 0 and never 1. Zero divides a sheet price into infinity; one quietly claims
    a part fits on a sheet it is bigger than."""
    assert costed_facts.nest_on_sheet("ACRYLIC", 9000.0, 689.0, SHEET_L, SHEET_W) is None
    assert costed_facts.nest_on_sheet("MILD STEEL", 100.0, 9000.0, SHEET_L, SHEET_W) is None
    assert estimator.select_sheet_size("ACRYLIC", 9000.0, 689.0)["parts_per_sheet"] is None


def test_other_sheet_parts_per_sheet_still_answers_for_callers_that_know_their_block():
    """Its callers name no material -- they are already inside the Other Sheet block. It has to
    keep giving J51's number, or the helper and the record part company again."""
    assert costed_facts.other_sheet_parts_per_sheet(DOOR_L, DOOR_W, SHEET_L, SHEET_W) == 4
    # A geometry where the two rules disagree, so this cannot pass while quietly asking for
    # the steel one: J51 nests 15 here and K38 nests 10.
    assert costed_facts.other_sheet_parts_per_sheet(500.0, 650.0, SHEET_L, SHEET_W) == 15
    assert costed_facts.other_sheet_parts_per_sheet(0, 100, SHEET_L, SHEET_W) is None
    assert costed_facts.other_sheet_parts_per_sheet(None, 100, SHEET_L, SHEET_W) is None
    assert costed_facts.other_sheet_parts_per_sheet(9000, 100, SHEET_L, SHEET_W) is None


def test_nobody_reimplements_a_nesting_rule_somewhere_else():
    """THE STRUCTURAL GUARD. This defect was not a wrong number, it was a SECOND copy of the
    arithmetic in a different file, reached by a different code path, answering the same
    question differently. Catching the number is not enough -- the shape has to be refused.

    Live src only; _archive and the estimator_old/estimator1 snapshots are history, not code.
    """
    offenders = []
    for name in sorted(os.listdir(SRC)):
        if not name.endswith(".py") or name == "costed_facts.py":
            continue
        if re.match(r"^(estimator(_old|1|_v\d+)?|.*_backup.*)\.py$", name) and name != "estimator.py":
            continue
        path = os.path.join(SRC, name)
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        # The arithmetic, not the words: a division by (part + gap) with one of the two
        # margins subtracted from the sheet. Comments naming K38 or J51 are fine and
        # necessary -- it is a SECOND IMPLEMENTATION that is refused. (A guard that grepped
        # raw prose caught its own explanatory comment seven times before this one.)
        code = re.sub(r"#[^\n]*", "", text)
        code = re.sub(r'("""|\'\'\')(?:.|\n)*?\1', "", code)
        for match in re.finditer(r"-\s*(80|5)\s*\)\s*/\s*\(\s*\w+\s*\+\s*(10|20)\s*\)", code):
            offenders.append(f"{name}: {match.group(0)}")
    assert not offenders, (
        "a nesting rule is implemented outside costed_facts:\n  " + "\n  ".join(offenders))
