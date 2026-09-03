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
                      unit_assembly_from_label as unit_from)

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


def test_without_the_rule_every_line_was_three_times_too_many(costed):
    """The measurement, kept: this is what the sheet you have in your hand says."""
    before = resolve(ROWS)["effective"]
    assert before["12349-02-69-03M"] == 3 and costed["12349-02-69-03M"] == 1
    assert before["FIXING"] == 12 and costed["FIXING"] == 4
    assert before["P/P"] == 18 and costed["P/P"] == 6


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
