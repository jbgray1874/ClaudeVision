r"""A replacement box never reaches an estimator, whichever module put it there.

James, reviewing the 7332-01 six-off book: "Remove the visible replacement characters
from workbook/report text."

test_a_workbook_uses_glyphs_excel_has.py holds FIVE NAMED MODULES to the rule by reading
their source. That catches a developer pasting an emoji into a heading, and it cannot catch
anything else: a U+FFFD does not exist in this source tree at all, it is manufactured at
run time when some byte fails to decode — a drawing note in cp1252, a supplier description
through a non-UTF-8 console, a string read back out of the estimators' own .xls template.

So this file holds the rule on the VALUE, at the boundary, where the origin does not
matter. The two tests are deliberately different in kind:

    the unit tests      say what `repair` does to each class of character, including the
                        ones it must leave alone
    the boundary test   builds a real openpyxl workbook with damage in it, runs the scrub
                        the populate path runs, and reads the cells back

The second is the one that would have caught this. A rule proven only against its own
source is proven against the place it was already obeyed.
"""
from __future__ import annotations

import os
import pathlib
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

from workbook_hygiene import (is_broken_formula, needs_repair, repair,  # noqa: E402
                              scrub_report_text, scrub_workbook)

_SRC = pathlib.Path(__file__).resolve().parent.parent / "src"

# Named by codepoint, never pasted, so this test file is itself clean under the glyph rule.
_FFFD = "�"
_FACTORY = "\U0001F3ED"
_ROBOT = "\U0001F916"
_VS16 = "️"
_WARN_BMP = "⚠"        # BMP. Draws in Calibri. Must survive.
_POUND = "£"
_DIAMETER = "Ø"
_EMDASH = "—"


# ── what it removes ──────────────────────────────────────────────────────────────────

def test_the_replacement_box_is_dropped_not_printed():
    """The original character is already lost upstream; the box tells the estimator
    nothing except that we mishandled it."""
    assert repair(f"Mild Steel 1.0mm{_FFFD}") == "Mild Steel 1.0mm"
    assert _FFFD not in repair(f"{_FFFD}{_FFFD}Ticket Strip{_FFFD}")


def test_an_emoji_is_dropped_because_calibri_has_no_glyph_for_it():
    assert repair(f"{_FACTORY} SDI Live UDEF") == "SDI Live UDEF"
    assert repair(f"{_ROBOT}{_VS16} AI indicative") == "AI indicative"


def test_the_variation_selector_goes_with_the_pictograph_it_qualified():
    """Left on its own it is a zero-width character some fonts draw as a box of its own."""
    assert repair(f"{_ROBOT}{_VS16}") == ""
    assert _VS16 not in repair(f"check{_VS16} this")


# ── what it must NOT touch ───────────────────────────────────────────────────────────

def test_the_symbols_the_workbook_actually_uses_all_survive():
    """The rule is about the plane, not about punctuation. Stripping these would damage
    real content to fix a problem they do not have."""
    line = f"{_WARN_BMP} 2 x {_DIAMETER}8mm {_EMDASH} {_POUND}12.40/unit"
    assert repair(line) == line
    assert not needs_repair(line)


def test_plain_text_is_returned_unchanged_and_identically():
    text = "MANM insert labour, 108 inserts at 15s"
    assert repair(text) is text


def test_a_non_string_passes_straight_through():
    """Asked of every cell, so it must not care what type the cell holds."""
    for value in (None, 0, 12.5, True):
        assert repair(value) is value
        assert needs_repair(value) is False


def test_a_newline_is_never_eaten_when_the_gaps_are_closed():
    """Estimator-input blocks and provenance notes are multi-line; collapsing the space a
    dropped icon left must not run two lines together."""
    out = repair(f"{_FACTORY} first line\n{_ROBOT} second line")
    assert out == "first line\nsecond line"


def test_the_words_around_a_dropped_icon_keep_their_single_spaces():
    assert repair(f"Pricing: {_FACTORY} 3 priced") == "Pricing: 3 priced"


# ── the boundary itself ──────────────────────────────────────────────────────────────

def test_a_real_workbook_comes_out_clean_and_says_what_it_changed():
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Estimate"
    ws["A1"] = f"Material{_FFFD} spec"
    ws["A2"] = f"{_FACTORY} SDI Live UDEF"
    ws["A3"] = f"{_POUND}12.40 {_EMDASH} per unit"      # clean, must not be rewritten
    ws["A4"] = 12.40                                     # not a string
    other = wb.create_sheet("AI Price Provenance")
    other["B2"] = f"{_ROBOT}{_VS16} AI indicative"

    changed, per_sheet, broken = scrub_workbook(wb)

    assert broken == []
    assert ws["A1"].value == "Material spec"
    assert ws["A2"].value == "SDI Live UDEF"
    assert ws["A3"].value == f"{_POUND}12.40 {_EMDASH} per unit"
    assert ws["A4"].value == 12.40
    assert other["B2"].value == "AI indicative"

    assert changed == 3, "three string cells were damaged, and only those three"
    assert per_sheet == {"Estimate": 2, "AI Price Provenance": 1}, (
        "the log has to name WHICH sheet, or the estimator cannot go and look")


def test_a_clean_workbook_is_left_completely_alone():
    """Nothing is marked dirty for free: a book with no damage reports no changes."""
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    wb.active["A1"] = f"{_POUND}4.00/kg standard powder"
    changed, per_sheet, broken = scrub_workbook(wb)
    assert (changed, per_sheet, broken) == (0, {}, [])


def test_a_merged_continuation_cell_does_not_kill_the_save():
    """openpyxl exposes merged continuations and refuses the assignment. The value lives on
    the anchor, which this walk reaches in its own right."""
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["A1"] = f"{_FACTORY} merged heading"
    ws.merge_cells("A1:C1")
    changed, _, _broken = scrub_workbook(wb)
    assert ws["A1"].value == "merged heading"
    assert changed == 1


# ── the wiring, so the boundary is actually on the path ──────────────────────────────

def test_the_populate_path_runs_the_scrub_before_it_saves():
    """A guard nobody calls is not a guard. The scrub has to happen on the way to
    wb.save(), not merely exist."""
    src = (_SRC / "wb_populate.py").read_text(encoding="utf-8")
    assert "from workbook_hygiene import scrub_workbook" in src
    scrub_at = src.index("scrub_workbook(wb)")
    save_at = src.index("wb.save(out_path)")
    assert scrub_at < save_at, "the book is saved before it is checked"


def test_the_module_that_enforces_the_rule_is_pure_ascii():
    """An earlier version of this module's docstring CLAIMED its source named every
    character by escape, while the file carried literal copies of U+FFFD and the variation
    selector. Both are in the BMP, so a guard that only looks above U+FFFF waved them
    through — the claim was false and the test could not tell.

    The check is now the whole byte range: a module whose job is to remove characters other
    files should not contain has no business containing them itself, and the documentation
    is verified rather than asserted."""
    raw = (_SRC / "workbook_hygiene.py").read_bytes()
    offenders = sorted({b for b in raw if b > 0x7F})
    assert not offenders, (
        f"non-ASCII bytes in the hygiene module: {[hex(b) for b in offenders]}. Name the "
        f"character by escape instead of pasting it.")


# ── the broken reference ─────────────────────────────────────────────────────────────

def test_a_formula_carrying_a_ref_error_is_recognised():
    assert is_broken_formula("=LOOKUP($D$6,'Material Price Break'!$D$4:$N$4,"
                             "'Material Price Break'!#REF!)")
    assert not is_broken_formula("=LOOKUP($D$6,'Material Price Break'!$D$4:$N$4,"
                                 "'Material Price Break'!D14:N14)")
    assert not is_broken_formula("#REF! mentioned in a note, not a formula")
    assert not is_broken_formula(None) and not is_broken_formula(12.4)


def test_the_broken_price_cell_is_blanked_and_named():
    """J20 on the 7332-01 book: the template's own broken LOOKUP survived on a line the
    engine believed it had left blank, and M20 inherited the error into the block total.
    An unpriced line shows a blank."""
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Estimate"
    ws["J20"] = ("=LOOKUP($D$6,'Material Price Break'!$D$4:$N$4,"
                 "'Material Price Break'!#REF!)")
    ws["J21"] = "=LOOKUP($D$6,'Material Price Break'!$D$4:$N$4,'Material Price Break'!D15:N15)"

    changed, _per_sheet, broken = scrub_workbook(wb)

    assert ws["J20"].value is None, "the broken formula is still in the delivered book"
    assert ws["J21"].value.startswith("=LOOKUP"), "a working formula must not be touched"
    assert broken == ["Estimate!J20"], (
        "the address has to be named on the log — the #REF! is the TEMPLATE's fault and "
        "wants fixing at source, not silently cleaning every run")
    assert changed == 1


def test_the_run_says_the_template_still_carries_it():
    """Blanking is right for the book in hand and wrong as a habit."""
    src = (_SRC / "wb_populate.py").read_text(encoding="utf-8")
    assert "BROKEN TEMPLATE FORMULA blanked" in src
    assert "wants fixing at source" in src


# ── the report, which is the other half of "workbook/report text" ────────────────────

def test_a_replacement_character_is_dropped_from_a_rendered_report():
    """A browser draws U+FFFD as a black diamond, which is no better than Excel's box."""
    html = f"<td>Mild Steel{_FFFD} 1.0mm</td>"
    assert scrub_report_text(html) == "<td>Mild Steel 1.0mm</td>"


def test_the_report_pass_does_not_reflow_the_markup():
    """The whole document is one string here, so collapsing runs of spaces would rewrite
    the layout the builder produced. Only the damaged characters go."""
    html = "<div>\n    <span>  spaced  </span>\n</div>"
    assert scrub_report_text(html) == html


def test_the_report_writer_runs_the_pass_before_it_writes():
    src = (_SRC / "job_report_html.py").read_text(encoding="utf-8")
    scrub_at = src.index("scrub_report_text(htmlout)")
    write_at = src.index("Path(out_path).write_text(htmlout")
    assert scrub_at < write_at, "the report is written before it is cleaned"
