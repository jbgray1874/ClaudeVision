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
purchased items on the Bill of Materials, packaging and delivery, and the scrap uplift added to
every line. Both are correct, and saying so costs one sentence.
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


def test_the_gap_is_computed_and_not_left_to_the_reader():
    assert "_gap = float(_mat) - _col_mat" in CODE, (
        "the difference between the column and the sheet is never worked out, so the tab "
        "prints two numbers and no account of why they differ")


def test_the_gap_is_named_rather_than_just_stated():
    at = CODE.index("_gap = float(_mat) - _col_mat")
    window = CODE[at:at + 1200]
    for thing in ("Bill of", "packaging", "scrap"):
        assert thing.lower() in window.lower(), (
            f"the explanation does not say the difference includes {thing} — 'they differ' is "
            f"what the reader could already see")


def test_it_says_neither_figure_is_wrong():
    """The failure mode is not confusion, it is DISTRUST: two totals with no account reads as
    a tab that disagrees with the workbook."""
    at = CODE.index("_gap = float(_mat) - _col_mat")
    window = CODE[at:at + 1200]
    assert "Neither figure is wrong" in window
    assert "the sheet is the money" in window


def test_nothing_is_said_when_there_is_nothing_to_say():
    """A note explaining a difference of zero is noise, and noise on this tab is what makes
    the real notes invisible."""
    at = CODE.index("_gap = float(_mat) - _col_mat")
    window = CODE[at:at + 1200]
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
