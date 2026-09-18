r"""One fact says what a line prints, and where the figure came from.

James Gray, 18 September 2026:

    "Use one `displayed_charge` fact per line. Where a workbook sheet owns the charge, every
     renderer gets the workbook amount or a dash — never an engine comparison."
    "Every published currency amount must have a source fact and workbook-cell reference.
     Narrative totals may not use independent engine aggregates."

THE £3.88 WAS FOUND FIVE TIMES, ONE PER RERUN — the HTML report's money cell, the AI
Provenance column, the AI Explanation table, the AI Explanation narrative, and section 11's
reassurance that a dashed row IS costed. Each fix was written, tested green and shipped, and
the next book carried the figure somewhere else. That is not five bugs. It is one missing
fact, asked for in five places, each renderer re-deriving the answer from the raw estimate.

Twice the gate was keyed on a value nobody checked: the engine's `cost_method` (which on that
part is not the sheet formula at all), then the block's display label (a line carries the
block KEY). Both shipped. A renderer that asks this function cannot make either mistake,
because it never sees an engine figure unless the fact says it may.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

from displayed_charge import (  # noqa: E402
    cell_reference, displayed_charge, publishable_total, RULED_BLOCKS,
)


def _line(**kw):
    """A costed line, carrying the cell the read-back recorded for it."""
    return dict({"block": "bom", "sheet_row": 14, "charged_cell": "Estimate!M14"}, **kw)


# ── what prints, and from where ──────────────────────────────────────────────────────

def test_the_sheets_figure_is_what_prints():
    got = displayed_charge(_line(charged_ext_gbp=0.94, engine_ext_gbp=0.90))
    assert got["amount"] == 0.94
    assert got["basis"] == "workbook"


def test_every_amount_carries_the_cell_it_came_from():
    """A row number alone — "Estimate!63" — sends somebody to fourteen columns to find the
    money. The cell is RECORDED by the read-back that located the column, never inferred."""
    assert cell_reference(_line(charged_cell="Estimate!M63")) == "Estimate!M63"
    assert displayed_charge(_line(charged_ext_gbp=1.0))["cell"] == "Estimate!M14"


def test_a_cell_is_never_inferred_from_the_row_number():
    """The first cut built "Estimate!M{row}" from a MONEY_COLUMN constant, on the grounds that
    every money column in today's template is M. True today, and the same bet that shipped
    wrong twice this afternoon on the comparator gate."""
    import displayed_charge as D
    assert not hasattr(D, "MONEY_COLUMN"), "the column is being assumed again"
    assert cell_reference({"sheet_row": 63}) is None
    assert cell_reference({"sheet_row": 63, "charged_cell": ""}) is None


# ── the ruled block: the amount or a dash, never a comparison ───────────────────────

def test_the_steel_block_never_publishes_the_engines_figure():
    got = displayed_charge({"block": "steel", "sheet_row": 63,
                            "charged_cell": "Estimate!M63",
                            "charged_ext_gbp": 3.07, "engine_ext_gbp": 3.88})
    assert got["amount"] == 3.07
    assert got["publish_diagnostic"] is False
    assert "ruled" in got["withheld_reason"]


def test_the_engines_figure_is_kept_even_when_it_may_not_be_shown():
    """Withheld is not discarded. A diagnostic nobody can reach is a diagnostic nobody has."""
    got = displayed_charge({"block": "steel", "sheet_row": 63,
                            "charged_ext_gbp": 3.07, "engine_ext_gbp": 3.88})
    assert got["diagnostic"] == 3.88


def test_the_block_key_and_its_label_are_both_understood():
    """A costed line carries `steel`; "Sheet Steel" is the display label. Keying on the label
    is one of the two mistakes that shipped."""
    for block in ("steel", "Sheet Steel", "SHEET STEEL"):
        got = displayed_charge({"block": block, "sheet_row": 63,
                                "charged_ext_gbp": 3.07, "engine_ext_gbp": 3.88})
        assert got["publish_diagnostic"] is False, block


def test_every_other_block_keeps_its_cross_check():
    """The comparison has caught real faults. It goes only where a ruling replaced it."""
    for block in ("other_sheet", "tube", "wire", "bom"):
        got = displayed_charge({"block": block, "sheet_row": 20,
                                "charged_cell": "Estimate!M20",
                                "charged_ext_gbp": 10.0, "engine_ext_gbp": 12.0})
        assert got["publish_diagnostic"] is True, block


def test_agreement_is_not_published_as_a_disagreement():
    got = displayed_charge(_line(charged_ext_gbp=5.0, engine_ext_gbp=5.0))
    assert got["publish_diagnostic"] is False
    assert "agree" in got["withheld_reason"]


# ── a line the sheet never charged ──────────────────────────────────────────────────

def test_an_engine_only_amount_is_not_publishable_currency():
    """James Gray: "Do not let an engine-only amount become a publishable currency amount
    without a workbook cell. Keep it as a diagnostic/pending input." The first cut returned it
    as `amount`, so a renderer printed it in pounds with a caption — which is exactly how
    £3.88 reached five pages and £321.88 reached a narrative."""
    got = displayed_charge(_line(charged_ext_gbp=None, engine_ext_gbp=7.5))
    assert got["amount"] is None
    assert got["basis"] == "pending"
    assert got["diagnostic"] == 7.5, "the figure is kept, for diagnosis"
    assert got["publish_diagnostic"] is False
    assert "pending" in got["withheld_reason"]


def test_a_line_with_no_money_at_all_prints_nothing():
    got = displayed_charge(_line())
    assert got["amount"] is None
    assert got["basis"] == "none"


def test_rubbish_in_does_not_crash_a_renderer():
    for junk in (None, [], "", 0):
        got = displayed_charge(junk)
        assert got["amount"] is None and got["publish_diagnostic"] is False


# ── the £321.88 rule ────────────────────────────────────────────────────────────────

def test_a_narrative_total_comes_from_the_sheet():
    got = publishable_total({"run": {"unit_cost_gbp": 149.87,
                                     "unit_cell": "Estimate!G6"}})
    assert got["amount"] == 149.87
    assert got["cell"] == "Estimate!G6"


def test_a_total_with_no_recorded_cell_is_refused():
    """Read, but untraceable. The read-back scans for the unit-cost label and records the cell
    it found; hard-coding G6 here would be the guess this module exists to refuse."""
    got = publishable_total({"run": {"unit_cost_gbp": 149.87}})
    assert got["amount"] is None
    assert "cannot be published" in got["why"]


def test_an_unreadable_total_is_refused_rather_than_substituted():
    """`AI Explanation!A111` printed "Of the £321.88 it assembled" — the engine's own sum
    before the sheet's blocks, its absorption divisor and its customer terms — against a
    workbook reading £150.32. A sentence with no total is better than one with an
    untraceable total."""
    got = publishable_total({})
    assert got["amount"] is None
    assert "not the job's cost" in got["why"]


def test_the_ruled_blocks_are_named_once():
    assert "steel" in RULED_BLOCKS


# ── and every renderer asks it ───────────────────────────────────────────────────────

@pytest.mark.parametrize("module", ["job_report_html", "estimation_report"])
def test_the_renderers_ask_the_fact_rather_than_deciding(module):
    text = open(__import__(module).__file__.replace(".pyc", ".py"), encoding="utf-8").read()
    assert "displayed_charge" in text, f"{module} still decides for itself"


# ── and the wiring, which the first cut of this module did not have ─────────────────
#
# James Gray, 18 Sep 2026: "It does not wire `publishable_total()` anywhere. It has zero
# callers outside its test, so the £321.88 protection is not live." A fact nothing asks is
# not a protection; it is a docstring.

def test_the_covering_note_asks_for_a_publishable_total():
    import estimate_explained as EE
    text = open(EE.__file__.replace(".pyc", ".py"), encoding="utf-8").read()
    assert "publishable_total" in text, "the note still publishes a total nothing vouched for"


def test_the_read_back_records_the_cell_it_read_the_money_from():
    """`charged_cell` is stamped where the value COLUMN was located by reading the block
    header — the only place the answer is known rather than guessed."""
    import wep_readback_from_xlsx as W
    text = open(W.__file__.replace(".pyc", ".py"), encoding="utf-8").read()
    assert 'row["charged_cell"]' in text
    assert 'out["unit_cell"]' in text


def test_the_unit_cell_travels_to_the_note():
    import estimate_explained as EE
    text = open(EE.__file__.replace(".pyc", ".py"), encoding="utf-8").read()
    assert 'out["unit_cell"]' in text, "the cell is recorded and then dropped on the way"
