"""The report, the workbook tab and the markdown document are one answer, rendered three ways.

The failure this guards against is the one the explanation exists to expose: two places in the
same pack answering "where did that figure come from" and not agreeing. So the report does not
go and read the workbook itself — it renders what estimate_explained produced, the same call
the tab makes.

The other half is honesty about reach. The report can be generated on a machine that cannot see
the workbook, and a section that renders half of itself in that case is worse than one that says
what it needs.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

import job_report_html                                                   # noqa: E402


def test_a_report_that_cannot_reach_the_workbook_says_so(tmp_path):
    html = job_report_html._explanation_section(
        {"saved_output_paths": {"json": str(tmp_path / "x.json")}})
    assert "Not produced" in html
    assert "AI Explanation" in html, (
        "the reader is told where the same content is, rather than left with a gap")
    assert "<table" not in html, "half a table is worse than none"


def test_a_workbook_that_will_not_open_costs_the_report_nothing(tmp_path):
    book = tmp_path / "12552-00.xlsx"
    book.write_bytes(b"not really a workbook")
    html = job_report_html._explanation_section(
        {"saved_output_paths": {"estimate_xlsx": str(book)}})
    assert "Not produced" in html
    assert "Nothing else in this report is affected" in html


def test_the_run_records_which_workbook_it_produced():
    """It recorded the json, text, log, csv and sql it wrote — and not the estimate itself,
    so nothing reading the run back could find the spreadsheet the run exists to make."""
    source = (SRC / "main.py").read_text(encoding="utf-8")
    assert '["estimate_xlsx"]) = str(xlsx_path)' in source
    assert source.count('["estimate_xlsx"]) = str(xlsx_path)') == 2, (
        "stamped on the in-memory summary AND the canonical JSON — a report regenerated a "
        "week later reads the file, not this process")


def test_the_report_renders_the_document_rather_than_re_reading_the_workbook():
    source = (SRC / "job_report_html.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(source))
              if isinstance(n, ast.FunctionDef) and n.name == "_explanation_section")
    body = ast.get_source_segment(source, fn)
    assert "estimate_explained.sections" in body and "estimate_explained.build" in body
    assert "openpyxl" not in body, (
        "a second pass over the workbook is a second answer, and two answers to one question "
        "is the failure this section exists to expose")


def test_the_section_is_wired_into_the_report():
    source = (SRC / "job_report_html.py").read_text(encoding="utf-8")
    assert "{_explanation_section(summary)}" in source
    assert source.index("{_invariants_section(summary)}") < \
        source.index("{_explanation_section(summary)}"), (
        "it follows the consistency checks, so the reader has been told how far to trust the "
        "number before being shown every row of it")


def test_markup_in_a_part_description_cannot_reach_the_page():
    assert job_report_html._explained_inline("<script>x</script>") == \
        "&lt;script&gt;x&lt;/script&gt;"


def test_the_documents_own_emphasis_survives():
    """The bold marks the figure that is actually charged. Losing it loses the point."""
    assert job_report_html._explained_inline("**£11.48**") == "<b>£11.48</b>"
    assert job_report_html._explained_inline("see `Estimate!63`") == \
        "see <code>Estimate!63</code>"


def test_wide_tables_scroll_inside_themselves():
    """Ten columns. Without this the page scrolls sideways and one row costs the whole
    report's width."""
    css = (SRC / "job_report_html.py").read_text(encoding="utf-8")
    assert ".scroll{overflow-x:auto" in css
    assert 'class="scroll"' in css
    assert ".t-muted{" in css, (
        "used since the report was written and never defined — every t-muted span has been "
        "rendering as ordinary text")


def test_a_job_estimated_before_the_path_was_recorded_can_still_be_regenerated(tmp_path):
    """Every job on the share predates the stamp. A fix that only applies to future runs
    leaves the two jobs anybody actually wants to look at without section 14."""
    import ast
    source = (SRC / "job_report_html.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(source))
              if isinstance(n, ast.FunctionDef) and n.name == "generate_report")
    body = ast.get_source_segment(source, fn)
    assert "workbook" in [a.arg for a in fn.args.args], "nameable on the call"
    assert '["estimate_xlsx"] = str(workbook)' in body
    assert "--workbook" in source, "and from the command line"
