"""£70.27 on one tab, £144.40 on another, and nothing said which was wrong.

WHAT JAMES FOUND on 10575-02, reading the workbook as an estimator would:

    AI Provenance   "sheet calculated £607.47" · £70.27 in the material column
    Estimate sheet  Total Material Cost £144.40

His note: "The £144.40 is real on the Estimate sheet. Provenance's £70.27 is only the per-part
material column. The other £74 is 'Powder / scrap / other workbook material' (51%). Both can be
true; the sheet is the money."

He worked that out. The sheet did not tell him. It printed both numbers side by side, said "the
workbook is authoritative", and stopped — which reads as an admission that the tab disagrees
with the workbook and nobody has looked into it.

FIFTY-ONE PER CENT OF THE MATERIAL TOTAL IN AN UNEXPLAINED DIFFERENCE is not a rounding note.
It is the reader's first real test of whether this tab can be trusted, and it is on the tab
whose entire purpose is showing where numbers came from. A provenance sheet that cannot account
for its own total has answered the question it exists to answer with "close enough".

The column is per-part material and only that. The sheet's material total also carries the
powder consumable and the per-line scrap uplift — lines belonging to no single part, which the
Decision Report has always broken out as "Powder / scrap / other workbook material". Both are
correct, and saying so costs one sentence.

THE FIRST ATTEMPT AT THAT SENTENCE NAMED THE WRONG THINGS, and James caught it before it
shipped to an estimator: it said the gap was "purchased items on the Bill of Materials,
packaging and delivery", every one of which is already IN the per-part column — packaging at
£28, the pallet, FIXING2104, the screws, the TESA tape. His words: "Tim will look for packaging
in the gap, find it in the column, and distrust Provenance again." A wrong explanation is worse
than none, because it gets followed.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "src" / "estimation_report.py").read_text(encoding="utf-8")
DEC = (ROOT / "src" / "job_decision_report.py").read_text(encoding="utf-8")

# The comments quote the numbers and the wording they exist to explain.
CODE = re.sub(r"#[^\n]*", " ", re.sub(r'"""(?:.|\n)*?"""', " ", SRC))

# AND THE SEAMS CLOSED, because the sentence is built from adjacent f-string fragments and
# Python joins them at runtime. "Neither figure is " + "wrong" is one phrase to a reader and two
# to a substring search, so a guard reading the raw source reports a sentence missing that is
# on the page in front of the estimator. Joining the fragments the way the interpreter does is
# the only way to assert on what is actually written.
PROSE = re.sub(r'"\s*\n\s*f?"', "", CODE)


def test_the_gap_is_computed_and_not_left_to_the_reader():
    assert "_gap = float(_mat) - _col_mat" in CODE, (
        "the difference between the column and the sheet is never worked out, so the tab "
        "prints two numbers and no account of why they differ")


def test_the_gap_is_named_in_the_words_the_other_tab_uses():
    """AND THE FIRST ATTEMPT NAMED THE WRONG THINGS, which was worse than saying nothing.

    It read "purchased items on the Bill of Materials, packaging and delivery" — every one of
    which is already IN this column: packaging at £28, the pallet, FIXING2104, the screws, the
    TESA tape. A reader who went looking for packaging in the gap would have found it in the
    column and concluded the tab cannot account for itself, which is precisely the distrust the
    sentence exists to prevent.

    The Decision Report has computed this residual all along and labels it. Same arithmetic,
    same words, so the two tabs agree instead of offering two explanations."""
    window = PROSE[PROSE.index("_gap = float(_mat) - _col_mat"):][:2200]
    assert "POWDER / SCRAP / OTHER WORKBOOK MATERIAL" in window, (
        "the difference is not named as the residual the Decision Report already breaks out")
    for wrong in ("Bill of Materials", "packaging and delivery"):
        assert wrong not in window, (
            f"the explanation still says the gap contains {wrong!r} — it is in the per-part "
            f"column, so a reader will find it there and stop trusting this tab")


def test_the_label_matches_the_decision_reports_row_exactly():
    """Two tabs explaining one difference in two vocabularies is the original defect wearing a
    different hat. The reader must be able to match the sentence to the row."""
    row_label = "Powder / scrap / other workbook material"
    assert row_label in DEC, "the Decision Report no longer has that row"
    window = PROSE[PROSE.index("_gap = float(_mat) - _col_mat"):][:2200].upper()
    assert row_label.upper() in window


def test_it_sends_the_reader_to_where_the_figure_is_broken_out():
    at = CODE.index("_gap = float(_mat) - _col_mat")
    assert "Decision Report" in CODE[at:at + 1600], (
        "the sentence asks to be taken on trust instead of naming the tab that shows it")


def test_it_says_neither_figure_is_wrong():
    """The failure mode is not confusion, it is DISTRUST: two totals with no account reads as
    a tab that disagrees with the workbook."""
    at = CODE.index("_gap = float(_mat) - _col_mat")
    window = PROSE[PROSE.index("_gap = float(_mat) - _col_mat"):][:2200]
    assert "Neither figure is wrong" in window
    assert "the sheet is the money" in window


def test_nothing_is_said_when_there_is_nothing_to_say():
    """A note explaining a difference of zero is noise, and noise on this tab is what makes
    the real notes invisible."""
    at = CODE.index("_gap = float(_mat) - _col_mat")
    window = CODE[at:at + 1600]
    assert "abs(_gap) >= 0.01" in window, (
        "the explanation is printed unconditionally, including when the two agree")


def test_both_tabs_still_agree_on_which_is_authoritative():
    """The Decision Report reconciles the same way. Two tabs explaining the same difference
    differently would be the original defect wearing a different hat."""
    for name, src in (("provenance", SRC), ("decision report", DEC)):
        assert "The workbook is authoritative" in src or "the sheet is the money" in src, (
            f"the {name} no longer names which figure to trust")


def test_the_labour_line_still_explains_why_there_is_no_per_part_figure():
    """The other half of the same question. Labour is charged per department row across every
    part in a setup, so a reader looking for a per-part labour column has to be told there
    cannot be one rather than concluding it is missing."""
    at = CODE.index("_lab_txt")
    window = CODE[at:at + 600]
    assert "department row" in window
