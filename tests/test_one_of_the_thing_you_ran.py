r"""
test_one_of_the_thing_you_ran.py

Tim costed one 12349-02-69-100. The engine costed three of them, and said 7 off on top.

_family() is the leading number, so a whole job is usually ONE family — 12349-02-69-03M,
-04M, -01A and -08J are all "12349". The GA row "12349-02-69-100 x3" therefore set the
multiplier for every part on the job: steel at 3 x GBP 5.74, screws at 12 where Tim has 4,
bumpons at 18 where Tim has 6. £220.91 against Tim's £158.46 is not a 40% miss on the same
unit; they were not costing the same article.

The GA is not wrong. Three modules DO hang on that wall. It is the wrong question — the
estimate is for one module, which is what the estimator pointed at and what Tim sold, and
three-per-wall is where they go rather than what is being made.

WHAT IS NOT TOUCHED: a sub-assembly used several times INSIDE the module. The packer is 3 per
module and the bumpons 6, on Tim's sheet as on ours. Only the assembly the job is FOR stops
multiplying.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bom_tree import (resolve_effective_quantities as resolve,               # noqa: E402
                      unit_assembly_from_label as unit_from,
                      unit_assembly_from_the_tree as unit_from_tree)

# 12349-02 as the pack actually is: a GA showing three modules on a wall, and a drawing per
# part underneath it, with a bought-in on two of them.
ROWS = [
    {"part_number": "12349-02-69-100", "quantity": 3, "source_pdf": "GA.pdf"},
    {"part_number": "12349-02-69-03M", "quantity": 1, "source_pdf": "03M.pdf"},
    {"part_number": "12349-02-69-04M", "quantity": 1, "source_pdf": "04M.pdf"},
    {"part_number": "12349-02-69-01A", "quantity": 1, "source_pdf": "01A.pdf"},
    {"part_number": "12349-02-69-08J", "quantity": 3, "source_pdf": "08J.pdf"},
    {"part_number": "FIXING", "quantity": 4, "source_pdf": "03M.pdf"},
    {"part_number": "P/P", "quantity": 6, "source_pdf": "01A.pdf"},
]
FOLDER = r"K:\Estimating\Live Enquiry\12349-02-69-100 GRAVITY FEEDER MODULES"

# What Tim's sheet carries, per module.
TIM = {"12349-02-69-03M": 1, "12349-02-69-04M": 1, "12349-02-69-01A": 1,
       "12349-02-69-08J": 3, "FIXING": 4, "P/P": 6}


@pytest.fixture(scope="module")
def costed():
    return resolve(ROWS, unit_assembly=unit_from(FOLDER, ROWS))["effective"]


@pytest.mark.parametrize("code,qty", sorted(TIM.items()))
def test_every_line_matches_the_estimator(costed, code, qty):
    assert costed.get(code) == qty


def test_the_size_of_what_was_wrong_is_on_the_record(costed):
    """The measurement, kept — but no longer by re-running the old behaviour, because there is
    no way left to ask for it: the GA's own shape now settles this even when nothing names the
    assembly. So it is asserted from the data instead.

    The GA says 3. Every fabricated line was multiplied by it. The sheet in your hand reads
    03M at 3, FIXING at 12 and P/P at 18 against Tim's 1, 4 and 6."""
    out = resolve(ROWS, unit_assembly=unit_from(FOLDER, ROWS))
    assert out["install_context"] == {"12349-02-69-100": 3}, "the multiplier is not recorded"
    multiplier = out["install_context"]["12349-02-69-100"]
    for code, tim in (("12349-02-69-03M", 1), ("FIXING", 4), ("P/P", 6)):
        assert costed[code] == tim
        assert costed[code] * multiplier == tim * 3, (
            f"{code} used to be costed at {tim * multiplier}, not {tim}")


def test_a_part_used_several_times_inside_the_module_still_is(costed):
    """The packer is 3 per module on Tim's sheet too. Only the assembly the job is FOR stops
    multiplying — everything below it multiplies exactly as before."""
    assert costed["12349-02-69-08J"] == 3


# ── identifying the unit ───────────────────────────────────────────────────────

def test_the_folder_the_estimator_pointed_at_names_the_unit():
    assert unit_from(FOLDER, ROWS) == "12349-02-69-100"


def test_the_longest_match_wins():
    """"12349" and "12349-02-69-100" can both appear in one folder name and only one of them
    is an assembly somebody builds."""
    rows = ROWS + [{"part_number": "12349", "quantity": 1, "source_pdf": "GA.pdf"}]
    assert unit_from(FOLDER, rows) == "12349-02-69-100"


def test_a_folder_that_names_nothing_changes_nothing():
    """The rule must be inert on every job whose folder is called something else — which is
    most of them, and all the ones already estimated."""
    assert unit_from(r"K:\jobs\misc pack", ROWS) is None
    assert resolve(ROWS, unit_assembly=None)["effective"] == resolve(ROWS)["effective"]


def test_a_unit_that_is_already_one_is_not_reported_as_context():
    """A GA showing one of the assembly is the ordinary case and has nothing to say."""
    rows = [dict(r, quantity=1) if r["part_number"] == "12349-02-69-100" else r for r in ROWS]
    assert resolve(rows, unit_assembly="12349-02-69-100")["install_context"] == {}


def test_the_change_is_reported_not_made_quietly():
    """A quantity that silently became a third of what it was is exactly as hard to trust as
    one that silently tripled."""
    out = resolve(ROWS, unit_assembly=unit_from(FOLDER, ROWS))
    assert out["install_context"] == {"12349-02-69-100": 3}
    said = " ".join(f["detail"] for f in out["flags"])
    assert "install context" in said and "12349-02-69-100" in said


# ── and the drawing the tree hangs off ─────────────────────────────────────────

def test_a_bought_in_row_cannot_make_a_sub_drawing_look_like_the_ga():
    """_family() returns "" for FIXING/PLAS/POWDER, and counting that empty string made a
    sub-assembly carrying one screw look like it referenced two families — beating the real
    GA, which references one family and every part in it. The whole tree then hangs off the
    wrong drawing, and the GA's own row lands in `effective` as if it were a part."""
    assert resolve(ROWS)["main_ga"] == "GA.pdf"
    assert "12349-02-69-100" not in resolve(ROWS, unit_assembly="12349-02-69-100")["effective"]


def test_the_caller_passes_the_job_name():
    src = (ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")
    i = src.index("from bom_tree import unit_assembly_from_label")
    assert "unit_assembly=_unit_asm" in src[i:i + 1200], "the rule is never given a label"
    assert "review_flags" in src[i:i + 1600], "the change is not surfaced to the estimator"


# ── and the folder has to be recognised however it is spelled ──────────────────

@pytest.mark.parametrize("folder", [
    "12349-02-69-100 GRAVITY FEEDER MODULES",       # the share, as the estimator files it
    "123490269100__GRAVITY_FEEDER_MODULES_REV_A",   # Tim's own file, no separators at all
    "12349-02-69-100-GravityFeeder",
    "12349_02_69_100 Gravity Feeder",               # underscores instead of hyphens
])
def test_the_assembly_is_found_however_the_folder_spells_it(folder):
    """A folder is not spelled the way a part number is. Comparing with the hyphens intact
    meant the rule fired on one spelling and silently did nothing on the others — and doing
    nothing here leaves every part at three times its quantity, which is the failure it exists
    to stop."""
    assert unit_from(rf"K:\Estimating\Live Enquiry\{folder}", ROWS) == "12349-02-69-100"


def test_flattening_does_not_let_a_shorter_code_win():
    """Still matched whole, longest still wins — so the family number cannot beat the
    assembly for a folder that names the assembly."""
    rows = ROWS + [{"part_number": "12349", "quantity": 1, "source_pdf": "GA.pdf"}]
    assert unit_from(r"K:\jobs\123490269100 GRAVITY FEEDER", rows) == "12349-02-69-100"


# ── when nobody named the folder helpfully ────────────────────────────────────
#
# 12349-02's pack actually lives in "...\\fanatics\\12349-02", which does not contain
# 12349-02-69-100. The folder rule finds nothing there and every part stays at three times
# its quantity. A fix that only works when somebody named a folder helpfully is not a fix.
#
# The GA's own shape says it. A BAY lists several assemblies and the unit is all of them
# together. An INSTALL ARRANGEMENT lists ONE assembly several times: that drawing is a picture
# of where the articles go, and the article is the unit.

REAL_FOLDER = r"\\sdi-dc01\Shared\...\SDIIntelligenceAISheet\fanatics\12349-02"

# A genuine bay: several different assemblies on one GA, each used twice.
BAY = [
    {"part_number": "1448-GA", "quantity": 2, "source_pdf": "BAY.pdf"},
    {"part_number": "3886-GA", "quantity": 2, "source_pdf": "BAY.pdf"},
    {"part_number": "1448-01", "quantity": 1, "source_pdf": "1448.pdf"},
    {"part_number": "3886-01", "quantity": 1, "source_pdf": "3886.pdf"},
]


def test_the_folder_this_pack_is_really_in_names_nothing():
    """Stated, because it is the premise of everything below."""
    assert unit_from(REAL_FOLDER, ROWS) is None


@pytest.mark.parametrize("code,qty", sorted(TIM.items()))
def test_the_ga_shape_settles_it_without_the_folder(code, qty):
    out = resolve(ROWS, unit_assembly=unit_from(REAL_FOLDER, ROWS))
    assert out["effective"].get(code) == qty


def test_it_still_says_which_assembly_it_decided_on():
    out = resolve(ROWS, unit_assembly=None)
    assert out["install_context"] == {"12349-02-69-100": 3}


def test_a_bay_of_several_assemblies_is_untouched():
    """THE THING THIS MUST NOT BREAK. A bay IS a composite article and its children genuinely
    multiply. Two or more structural codes on the GA and the rule says nothing at all."""
    out = resolve(BAY)
    assert out["install_context"] == {}
    assert out["effective"]["1448-01"] == 2 and out["effective"]["3886-01"] == 2


def test_one_assembly_shown_once_is_not_install_context():
    """A GA showing one of the assembly is the ordinary case and has nothing to say."""
    rows = [dict(r, quantity=1) if r["part_number"] == "12349-02-69-100" else r for r in ROWS]
    assert unit_from_tree(rows, "GA.pdf") is None


def test_a_bag_of_screws_does_not_make_a_ga_composite():
    """Bought-in rows carry no number family. A GA listing one assembly and some fixings is
    still a GA listing one assembly."""
    rows = ROWS + [{"part_number": "FIXING99", "quantity": 8, "source_pdf": "GA.pdf"}]
    assert unit_from_tree(rows, "GA.pdf") == "12349-02-69-100"


def test_the_folder_wins_when_it_has_something_to_say():
    """A folder that spells the assembly out is a person saying which article this is, and
    that beats reading it off a drawing.

    ASSERTED ON BEHAVIOUR, not on the spelling of one line. This used to search bom_tree.py for
    the literal "_unit = _norm(unit_assembly)" and broke the moment that line was renamed — while
    the rule it cares about was intact. A test that fails on a rename and passes on a behaviour
    change is pointed the wrong way round.
    """
    GA = "GA.pdf"
    rows = [
        # the GA's own shape would say -100 and -101 are both install context
        {"part_number": "12349-02-69-100", "quantity": 3, "source_pdf": GA},
        {"part_number": "12349-02-69-101", "quantity": 3, "source_pdf": GA},
        {"part_number": "12349-02-69-04M", "quantity": 1, "source_pdf": "sub.pdf"},
    ]
    # a person naming -101 must override that, and ONLY -101 becomes the unit
    out = resolve(rows, main_ga=GA, unit_assembly="12349-02-69-101")
    assert set(out.get("install_context") or {}) == {"12349-02-69-101"}, \
        "the named assembly wins; the tree's own reading does not get a say as well"


# ── several variants of one module, all at the same quantity ──────────────────────────


def test_an_install_arrangement_of_several_variants_is_still_an_arrangement():
    """TIM WILKES ON 12349-02, 4 SEPTEMBER: "Why is it picking up x 3 of part 12349-02-69-04M",
    "12349-02-69-06A Front Cover - Only 1 per unit (AI picking up 3)", "Why is it showing 6 x
    powder coat operation when only 2 x parts to powder coat", "Where did 3 per unit come from
    for 6mm MDF(Packer)". Four complaints, one cause.

    That pack's GA lists 12349-02-69-100, -101 AND -08J, all at three. "Exactly one structural
    code" returned nothing, no unit assembly was found, and every part came out at three times
    its quantity. The comment above resolve_effective_quantities had already predicted the
    numbers: "the screws at 12 where Tim has 4, the bumpons at 18 where Tim has 6".
    """
    GA = "12349-02-69-GA_Gravity Feeders_RevA.PDF"
    rows = [
        {"part_number": "12349-02-69-100", "quantity": 3, "source_pdf": GA},
        {"part_number": "12349-02-69-101", "quantity": 3, "source_pdf": GA},
        {"part_number": "12349-02-69-08J", "quantity": 3, "source_pdf": GA},
        {"part_number": "12349-02-69-04M", "quantity": 1, "source_pdf": "sub100.PDF"},
        {"part_number": "12349-02-69-06A", "quantity": 1, "source_pdf": "sub100.PDF"},
        {"part_number": "12349-02-69-08J", "quantity": 1, "source_pdf": "sub08J.PDF"},
        {"part_number": "P/P", "description": "BUMPON", "quantity": 6,
         "source_pdf": "sub100.PDF"},
    ]
    out = resolve(rows, main_ga=GA)
    effective = out["effective"]
    assert effective["12349-02-69-04M"] == 1, "the Lid"
    assert effective["12349-02-69-06A"] == 1, "Tim: only 1 per unit"
    assert effective["12349-02-69-08J"] == 1, "the MDF packer"
    assert effective["P/P"] == 6, "Tim has 6 bumpons, not 18"
    assert set(out["install_context"]) == {"12349-02-69-100", "12349-02-69-101",
                                           "12349-02-69-08J"}


def test_a_bay_of_different_articles_still_multiplies():
    """THE CASE THIS MUST NOT TOUCH, and the discriminator is the family. A bay is several
    DIFFERENT articles bolted into one composite thing — 2 x 1448-GA, 2 x 3886-GA, 1 x 1455-GA —
    and the unit is all of them together. Dividing that by two would understate a real job."""
    BAY = "bay.PDF"
    rows = [
        {"part_number": "1448-GA", "quantity": 2, "source_pdf": BAY},
        {"part_number": "3886-GA", "quantity": 2, "source_pdf": BAY},
        {"part_number": "1455-GA", "quantity": 1, "source_pdf": BAY},
        {"part_number": "1448-01", "quantity": 1, "source_pdf": "s1.PDF"},
    ]
    out = resolve(rows, main_ga=BAY)
    assert out["effective"]["1448-01"] == 2, "still multiplied by its parent"
    assert not out.get("install_context"), "nothing here is install context"


def test_mixed_quantities_on_one_family_are_a_bill_not_an_arrangement():
    """All three conditions are required. 2 x A and 1 x B of the same family is a bill for a
    composite article, not a picture of where one article goes."""
    from bom_tree import install_context_codes
    GA = "ga.PDF"
    rows = [{"part_number": "1234-01-100", "quantity": 2, "source_pdf": GA},
            {"part_number": "1234-01-101", "quantity": 1, "source_pdf": GA}]
    assert install_context_codes(rows, GA) == set()


def test_a_single_article_shown_once_is_not_reinterpreted():
    from bom_tree import install_context_codes
    GA = "ga.PDF"
    rows = [{"part_number": "1234-01-100", "quantity": 1, "source_pdf": GA}]
    assert install_context_codes(rows, GA) == set()


def test_the_reinterpretation_is_flagged_rather_than_silent():
    """"a quantity that silently became a third of what it was is exactly as hard to trust as
    one that silently tripled" — this file's own words."""
    GA = "ga.PDF"
    rows = [{"part_number": "1234-01-100", "quantity": 3, "source_pdf": GA},
            {"part_number": "1234-01-101", "quantity": 3, "source_pdf": GA},
            {"part_number": "1234-01-04M", "quantity": 1, "source_pdf": "sub.PDF"}]
    flags = resolve(rows, main_ga=GA).get("flags") or []
    said = " ".join(str(f.get("detail") or "") for f in flags)
    assert "where they go, not what is being made" in said


# ── the shape the RECORD actually has, not the shape the fixtures had ─────────────────
#
# The fixtures above use filenames as source_pdf. The dual-path reader — which is what every
# real run uses — sets source_pdf to the PARENT LABEL, so the tree groups by parent. The
# 12349-02 workbook shows it: 12349-02-69-100 grouped under 12349-02-69-GA, 04M under -100.
# Everything here is taken from that workbook.


REAL = [
    {"part_number": "12349-02-69-100", "quantity": 3, "source_pdf": "12349-02-69-GA"},
    {"part_number": "STD PART", "quantity": 18, "source_pdf": "12349-02-69-GA"},
    {"part_number": "12349-02-69-08J", "quantity": 3, "source_pdf": "12349-02-69-GA"},
    {"part_number": "12349-02-69-101", "quantity": 1, "source_pdf": "12349-02-69-100"},
    {"part_number": "12349-02-69-03M", "quantity": 1, "source_pdf": "12349-02-69-100"},
    {"part_number": "12349-02-69-04M", "quantity": 1, "source_pdf": "12349-02-69-100"},
    {"part_number": "12349-02-69-06A", "quantity": 1, "source_pdf": "12349-02-69-100"},
    {"part_number": "FIXING", "quantity": 4, "source_pdf": "12349-02-69-100"},
    {"part_number": "12349-02-69-01A", "quantity": 1, "source_pdf": "12349-02-69-101"},
    {"part_number": "P/P", "quantity": 6, "source_pdf": "12349-02-69-101"},
]


def test_every_quantity_tim_gave_comes_out_right():
    """Tim Wilkes, 4 September, on the 3 September estimate. Six figures, one cause."""
    eff = resolve(REAL)["effective"]
    assert eff["12349-02-69-04M"] == 1, "Lid — he asked why it was picking up 3"
    assert eff["12349-02-69-06A"] == 1, "Front Cover — 'Only 1 per unit (AI picking up 3)'"
    assert eff["12349-02-69-08J"] == 1, "MDF Packer — 'Where did 3 per unit come from'"
    assert eff["P/P"] == 6, "bumpons"
    assert eff["FIXING"] == 4, "M4 screws"
    assert eff["STDPART"] == 6, "wood screws — 18 on a GA of three arrangements"


def test_a_leaf_listed_only_on_the_ga_still_gets_a_quantity():
    """THE BUG THIS FOUND IN MY OWN FIX. The main-GA loop skipped a code when its FAMILY had a
    sub-drawing. On a single-family job that is every leaf: 12349-02-69-08J is an MDF packer
    listed only on the GA, and it was skipped as though its children lived elsewhere. Nothing
    gave it an effective quantity at all, so it kept the GA's 3."""
    eff = resolve(REAL)["effective"]
    assert "12349-02-69-08J" in eff, "it must not vanish"
    assert eff["12349-02-69-08J"] == 1


def test_an_assembly_node_is_still_kept_out_of_the_parts(
):
    """The GA's own row must not land in `effective` as if it were a part. A node is an
    assembly when it has children grouped under it, when its own row lives on a sub-drawing
    too, or when somebody named it as the unit."""
    eff = resolve(REAL)["effective"]
    assert "12349-02-69-100" not in eff, "it has children grouped under it"
    assert "12349-02-69-101" in eff, "a sub-assembly IS a part of its parent"


def test_a_quantity_that_does_not_divide_is_left_alone_and_flagged():
    """5 across 3 arrangements is not a per-arrangement quantity, and guessing one would be
    worse than leaving it."""
    rows = list(REAL) + [{"part_number": "PLAS", "quantity": 5,
                          "source_pdf": "12349-02-69-GA"}]
    out = resolve(rows)
    assert out["effective"]["PLAS"] == 5
    said = " ".join(str(f.get("detail") or "") for f in (out.get("flags") or []))
    assert "does not divide evenly" in said
