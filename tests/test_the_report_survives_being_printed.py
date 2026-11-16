"""The document that gets walked through with estimators had no print rules at all.

James is taking this report into a room next week and reading it off paper. It carried no
`@media print` block of any kind, and a browser's defaults lose content from a page like this
one in three ways that all read to a reader as "the bottom is missing".

  THE COLOUR IS THE WARNING, AND COLOUR IS WHAT PRINTING DROPS. Browsers omit background
  colours on paper unless a page says otherwise, so every callout came out white on white.
  The red PRESENT, NOT READ rows, the missing-drawings notice, the whole what-to-check
  apparatus printed as ordinary prose. The rows designed to be alarming are exactly the ones
  that disappear, which is the wrong way round.

  A TABLE'S HEADINGS STOP AT PAGE ONE. Section 12 runs to forty-odd rows across three sheets.
  Without display:table-header-group, pages two and three are unlabelled columns of part
  numbers and status words — the data is on the paper and unreadable, which is worse than
  absent because nobody knows to ask for it.

  AND ROWS SPLIT DOWN THE MIDDLE. Every finding row now carries two lines — a label and its
  explanation — so a row that breaks across the fold puts half a finding at the foot of one
  page and half at the head of the next, where they read as two separate findings.

WHY THIS IS A TEST AND NOT A TWEAK. None of it is visible on screen. A print stylesheet is
only ever exercised in a print preview nobody opens, so it will be silently deleted by the next
person reformatting this block unless something objects. And the whole style block is a PLAIN
string, not an f-string — the first version of these rules was written with the braces doubled
for f-string escaping and would have shipped as invalid CSS, passing every existing test,
because nothing in the suite had ever looked at the rendered CSS.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import job_report_html as jr                                            # noqa: E402


def _rendered() -> str:
    return jr.build_report_html({
        "part_estimates": [{"part_number": "10575-01-001"}],
        "estimate_summary": {"part_estimates": [
            {"part_number": "10575-01-001", "extended_total_cost_gbp": 40.0}]},
        "invariants": {"violations": [], "checks_run": ["a"], "may_quote_firm": True},
    })


def test_the_page_has_print_rules_at_all():
    assert "@media print" in _rendered(), (
        "the report a person prints and reads in a meeting has no print stylesheet")


def test_the_css_is_valid_css_and_not_f_string_escaping():
    """THE FAILURE THAT WOULD HAVE SHIPPED SILENTLY. This style block is a plain string. Braces
    written doubled — the habit from every f-string in this file — produce `@media print {{`,
    which no browser applies, and every other test in this suite passes regardless because none
    of them reads the CSS."""
    html = _rendered()
    style = re.search(r"<style>(.*?)</style>", html, re.S)
    assert style, "no style block"
    css = style.group(1)
    assert "{{" not in css, "the print rules are f-string-escaped and no browser will apply them"
    assert "@media print {" in css


def test_the_warning_colours_reach_the_paper():
    """A callout printed white on white is a warning that has been deleted, and the reader has
    no way to know it was ever there."""
    css = re.search(r"<style>(.*?)</style>", _rendered(), re.S).group(1)
    block = css[css.index("@media print"):]
    assert "print-color-adjust:exact" in block.replace(" ", "")


def test_a_long_table_keeps_its_column_headings_on_every_page():
    """Section 12 is forty-odd rows over three sheets of paper. Pages two and three without
    headings are columns of part numbers and status words nobody can read."""
    css = re.search(r"<style>(.*?)</style>", _rendered(), re.S).group(1)
    block = css[css.index("@media print"):]
    assert "table-header-group" in block


def test_a_finding_is_not_split_across_the_fold():
    """Each row carries a label and its explanation on two lines now. Half a finding at the
    foot of one page and half at the head of the next reads as two findings."""
    css = re.search(r"<style>(.*?)</style>", _rendered(), re.S).group(1)
    block = css[css.index("@media print"):]
    assert "page-break-inside:avoid" in block.replace(" ", "")
    assert "page-break-after:avoid" in block.replace(" ", ""), (
        "a heading can still be orphaned at the bottom of a page")


def test_the_side_by_side_grid_becomes_one_column_on_paper():
    """A CSS grid container is the classic way for a printed page to swallow its second
    column."""
    css = re.search(r"<style>(.*?)</style>", _rendered(), re.S).group(1)
    block = css[css.index("@media print"):]
    assert ".split" in block and "display:block" in block.replace(" ", "")


def test_the_document_still_closes_itself():
    """A truncated file is the other thing "the bottom is missing" can mean, and it is the one
    worth ruling out from the engine's side rather than from a file somebody sends back."""
    html = _rendered()
    assert html.rstrip().endswith("</html>")
    assert html.count("<body") == html.count("</body>") == 1
