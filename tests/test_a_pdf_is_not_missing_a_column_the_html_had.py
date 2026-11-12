"""The PDF rendered cleanly, reported its byte count, and was sent out with a column missing.

WHAT HAPPENED. The August landscape report was rendered, checked for size, and delivered. On
page 12 the action list's **Why now** column ran off the right edge. Auditing the whole
document found the same fault in all three tables:

    Verdict          3 cells
    Worth a look?    4 cells
    Why now          7 cells   ← the justification for every action on the page

Fourteen cells. Nothing failed, nothing warned, and the byte count looked healthy.

WHY, AND WHY IT IS WORSE THAN TRUNCATION. The tables sit in `.table-wrap{overflow-x:auto}`.
On a screen that scrolls, so nothing is lost — measured at 1440, 1280, 1100 and 900px, no
table overflowed at all. A4 less 12mm margins is about 703px of content, and there the tables
are wider than the page. Chromium then CLIPS, and it does not paint what it clips: the words
are not shortened, they are ABSENT FROM THE FILE. `pdftotext` cannot find them because they
were never written. A document that looks finished gets forwarded.

`white-space:nowrap` on the header cells and the name column is what forced the width, so the
fix is an @media print block that releases it and pins the table layout.

THE REAL FIX IS THE CHECK, NOT THE STYLESHEET. This document is fixed; the next one will have
its own layout. So the renderer now compares its output against its own input and refuses to
report success when text has gone missing.

TWO WAYS THAT COMPARISON WAS WRONG BEFORE IT WAS RIGHT, both pinned below:

  interleaving   A PDF's text layer is in LAYOUT order. Once a cell wraps to two lines, its
                 second line is emitted after the neighbouring column's first, so searching
                 for a passage as a contiguous string fails on text that is present. The
                 first version reported five such passages missing; all five were on the page.
  letter-spacing The eyebrow is set at .18em, so Chromium places each glyph separately and
                 the text extracts as "S D I D I S P L AY S LT D" — present, correct, and not
                 a word.

A check that cries wolf is one people learn to skip past, which is how it comes to be
disabled in the month it would have mattered.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_TOOL_PATH = _ROOT / "tools" / "reports" / "render_report_pdf.py"
_TOOL = _TOOL_PATH.read_text(encoding="utf-8")
_REPORT = _ROOT / "reports" / "SDI-AI-Technology-Landscape-2026-08.html"

pymupdf = pytest.importorskip("pymupdf", reason="the checker needs a PDF text layer to read")
sys.path.insert(0, str(_TOOL_PATH.parent))
from render_report_pdf import verify                            # noqa: E402


def _pdf(tmp_path: Path, *lines: str) -> Path:
    """A one-page PDF whose text layer is exactly these lines."""
    doc = pymupdf.open()
    page = doc.new_page()
    y = 72
    for line in lines:
        page.insert_text((60, y), line, fontsize=10)
        y += 16
    out = tmp_path / "out.pdf"
    doc.save(str(out))
    doc.close()
    return out


def _html(tmp_path: Path, body: str) -> Path:
    out = tmp_path / "in.html"
    out.write_text(f"<html><body>{body}</body></html>", encoding="utf-8")
    return out


# ── it notices a passage that did not make it ─────────────────────────────────

def test_a_dropped_cell_is_reported(tmp_path):
    """THE ASSERTION, and the failure that prompted all of this."""
    html = _html(tmp_path, "<table><tr>"
                           "<td>Open SOLIDWORKS Labs and try LEO on a legacy drawing</td>"
                           "<td>Cheapest possible test of the most expensive roadmap item</td>"
                           "</tr></table>")
    pdf = _pdf(tmp_path, "Open SOLIDWORKS Labs and try LEO on a legacy drawing")
    lost = verify(html, pdf)
    assert lost, "a cell present in the HTML and absent from the PDF was not reported"
    assert "expensive" in " ".join(lost), "the report does not name the words that went missing"


def test_a_complete_render_reports_nothing(tmp_path):
    """The other half. A check that fires on a good document is a check that gets ignored."""
    html = _html(tmp_path, "<p>Deterministic readers hold ranks seventy to ninety, and "
                           "vision sits at rank forty filling gaps.</p>")
    pdf = _pdf(tmp_path, "Deterministic readers hold ranks seventy to ninety, and",
                         "vision sits at rank forty filling gaps.")
    assert verify(html, pdf) == [], "a faithful render was reported as missing text"


# ── the two ways it was wrong before it was right ────────────────────────────

def test_a_wrapped_table_cell_is_not_mistaken_for_a_missing_one(tmp_path):
    """INTERLEAVING. The PDF text layer is in layout order, so a wrapped cell's second line
    comes after the neighbouring column's first. The passage is on the page; as a contiguous
    string it is not findable. The first version of this check reported five such passages
    missing, every one of them present."""
    html = _html(tmp_path, "<td>Read how Anchorpoint handles SolidWorks binary churn</td>"
                           "<td>Storage architecture decision, cheap now</td>")
    # As the columns actually emit: line one of each cell, then line two of each.
    pdf = _pdf(tmp_path, "Read how Anchorpoint handles", "Storage architecture",
                         "SolidWorks binary churn", "decision, cheap now")
    assert verify(html, pdf) == [], (
        "wrapped text was reported missing — this is the false alarm that makes a checker "
        "worthless, because the next person turns it off")


def test_letter_spaced_headings_are_not_reported_missing(tmp_path):
    """LETTER-SPACING. At .18em Chromium places each glyph separately and the text extracts
    as 'S D I D I S P L AY S LT D'. Present, correct, and not a word."""
    html = _html(tmp_path, "<span>SDI Displays Ltd — SDI Intelligence</span>")
    pdf = _pdf(tmp_path, "S D I D I S P L AY S LT D — S D I I N T E L L I G E N C E")
    assert verify(html, pdf) == [], "a letter-spaced heading was reported as missing text"


def test_the_gap_closing_fallback_does_not_excuse_a_real_absence(tmp_path):
    """The fallback above compares against the text with every gap removed, which is a weaker
    test. It must not become a way for genuinely absent words to pass: a word that is in
    neither form is still missing."""
    html = _html(tmp_path, "<td>Price a twenty-four gigabyte card and benchmark it</td>")
    pdf = _pdf(tmp_path, "P R I C E A C A R D")
    assert verify(html, pdf), "the gap-closing fallback let a genuinely missing passage pass"


# ── the renderer refuses to call it a success ────────────────────────────────

def test_the_renderer_checks_its_own_output():
    assert "def verify(" in _TOOL, "the renderer does not check what it produced"
    main = _TOOL[_TOOL.index("def main("):]
    assert "verify(" in main, "verify is defined but never called — the recurring failure here"
    assert "return 1" in main[main.index("verify("):], (
        "a PDF with missing text still exits zero, so nothing downstream can tell")


def test_it_says_what_to_do_about_it():
    """"Some text is missing" sends somebody to compare two documents by eye. The cause is
    nearly always the same one, and naming it turns that into a two-line stylesheet edit."""
    main = _TOOL[_TOOL.index("def main("):]
    assert "overflow-x:auto" in main and "@media print" in main, (
        "the warning does not name the cause, so it cannot be acted on without rediscovering it")


# ── and the document that was broken is fixed ────────────────────────────────

@pytest.mark.skipif(not _REPORT.exists(), reason="the report is not in this checkout")
def test_the_landscape_report_releases_its_tables_for_print():
    css = _REPORT.read_text(encoding="utf-8")
    block = re.search(r"@media print\s*\{(.*?)\n  \}", css, re.S)
    assert block, "the report has no @media print block, so its tables clip again on paper"
    # THE RULES, NOT THE PROSE ABOUT THEM. The block carries a comment saying "normal, NOT
    # break-word", and matching on the raw text failed the very edit that was correct. That
    # is the fifth time in this suite a search has been fooled by an explanation of the thing
    # it was searching for, so the comments come out before anything is asserted.
    body = re.sub(r"/\*.*?\*/", " ", block.group(1), flags=re.S)
    assert "overflow: visible" in body, (
        "overflow-x:auto is still in force when printing — it scrolls on screen and CLIPS on "
        "paper, and Chromium does not paint what it clips")
    assert "white-space: normal" in body, (
        "the nowrap rules still force the tables wider than the page")
    assert "break-word" not in body, (
        "break-word splits a noun across two lines and into two tokens in the text layer, "
        "which is how a searchable document stops being searchable")
