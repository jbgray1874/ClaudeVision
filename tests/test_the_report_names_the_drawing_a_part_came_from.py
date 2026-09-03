r"""
test_the_report_names_the_drawing_a_part_came_from.py

"On the html report are we now showing the drawing that the part is associated with, that we
were able to extract the data from to make the decision?"

Section 9 said "the drawing" and pointed at section 14 for the page. In a pack of eleven
sheets "the drawing" names none of them, so an estimator checking a gauge had to go and find
which one to open — in the section whose entire job is saying where a number came from.

ONE READER, NOT A SECOND OPINION. It uses the same _sources_of the covering note uses, so the
two documents cannot name different files for one part. Two records of one fact is the defect
this whole set of documents exists to avoid.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

SRC = (ROOT / "src" / "job_report_html.py").read_text(encoding="utf-8")


def _section_nine() -> str:
    i = SRC.index("# WHICH DRAWING, NOT WHICH KIND OF DRAWING.")
    return SRC[i:SRC.index("def _source_legend", i)]


def test_the_column_exists():
    assert "<th>Which drawing files and pages</th>" in _section_nine()


def test_the_column_has_a_cell_on_every_row():
    """A header with nothing under it makes every row's columns line up wrong."""
    body = _section_nine()
    assert '<td class="mini">{_where_from(p)}</td>' in body


def test_it_uses_the_same_reader_as_the_covering_note():
    """Not a second implementation. Two documents naming different files for one part is
    exactly the failure mode this is meant to close."""
    body = _section_nine()
    assert "from estimate_explained import _sources_of as _srcof" in body
    assert "_srcof(part, _pack, _pages)" in body


def test_a_bought_in_says_it_has_no_drawing_rather_than_not_recorded():
    """The same mistake this section already fixed for blank sizes: a bolt has no drawing of
    its own and nobody will ever record one, so "not recorded" reads as a gap that isn't."""
    body = _section_nine()
    assert "bought in &mdash; no drawing" in body
    assert "_bi(part)" in body


def test_the_intro_no_longer_sends_the_reader_to_section_14_for_it():
    """BOTH copies. That paragraph is written out twice — once for the ordinary table and once
    for the early return when no part reached the costed pool — and the first pass at this
    updated one of them. Two records of one sentence, which is the same defect in prose."""
    import re as _re
    intros = [SRC[m.start():m.start() + 400] for m in
              _re.finditer(r"<h2>9 &nbsp;Where the bill of materials came from</h2>", SRC)]
    assert len(intros) == 2, "the section heading is written a different number of times now"
    for intro in intros:
        assert "which drawing file it" in intro
        assert "which drawing page owns it, is in section 14" not in intro


def test_a_reader_that_cannot_answer_does_not_break_the_report():
    """Every other section of this report survives a missing helper; so must this. A report
    that fails to build teaches nobody anything."""
    body = _section_nine()
    assert "except Exception" in body
    assert "_srcof, _pack, _pages = None, [], {}" in body
    assert "if _srcof is None:" in body


def test_the_helpers_it_reaches_for_are_really_there():
    """Asserted against the module rather than trusted — these are private names, and a rename
    would leave the column silently empty on every job."""
    import estimate_explained as ee
    for name in ("_sources_of", "_pack_files", "_page_index"):
        assert hasattr(ee, name), f"estimate_explained has no {name}"


def test_the_report_still_builds():
    import job_report_html
    assert hasattr(job_report_html, "generate_report")
