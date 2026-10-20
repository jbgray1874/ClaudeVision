"""Four quantities, four workbooks, and the comparison nobody could make.

    "Brief requests quantity break for 10, 50, 250 and 1000 - can't see break for 10 Number
     but a break for 100 Number is included but not required ... For ease of process / check
     can all quantity breaks be on one sheet / show formulas selected."
                                      — Howard Thurley, SDI estimating, 0355255, 9 Sep 2026

The sweep prices every break and saves A WORKBOOK PER QUANTITY, each opening on a page that
says which quantity it is. That is right for sending one out, and wrong for the job Howard was
doing: comparing four breaks meant four files open, four tabs, and reading the unit cost out of
each by eye. The deliverable would not let him make the one comparison it exists to support.

So the breaks also land as columns on one sheet, with the saving against the smallest break
subtracted — because "what does the volume buy me" is what a break table is for, and it is not
a subtraction anybody should do in their head.

AND IT SAYS WHAT IT WAS ASKED FOR. He asked for 10, 50, 250 and 1000 and got 50, 100, 250 and
1000: a break he did not want, and — the part that matters — one missing that he did. A table
that prints only what it produced cannot show that, so this one names the difference at the top
of the sheet he is already looking at, rather than in a log.

IT REPORTS, IT DOES NOT PRICE. Every figure is read off the recalculated sheet by the sweep.
Nothing here computes money, and the variant workbooks remain the ones to send.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

openpyxl = pytest.importorskip("openpyxl")

from quantity_breaks_tab import (SHEET_NAME, select_show_formulas,    # noqa: E402
                                 write_quantity_breaks_tab)
import config                                                          # noqa: E402


def _book(tmp_path):
    wb = openpyxl.Workbook()
    wb.active.title = "Estimate"
    wb["Estimate"]["C6"] = "Quantity"
    p = tmp_path / "0355255_estimate.xlsx"
    wb.save(p)
    return p


SWEPT = {"rows": [
    {"quantity": 10, "material": 3.10, "labour": 4.53, "unit": 7.63,
     "workbook": r"K:\out\0355255_qty10.xlsx"},
    {"quantity": 50, "material": 2.40, "labour": 2.73, "unit": 5.13,
     "workbook": r"K:\out\0355255_qty50.xlsx"},
    {"quantity": 250, "material": 2.20, "labour": 2.45, "unit": 4.65},
    {"quantity": 1000, "material": 2.15, "labour": 2.40, "unit": 4.55},
]}


def _sheet(tmp_path, swept=SWEPT, requested=None):
    p = _book(tmp_path)
    assert write_quantity_breaks_tab(p, swept, requested=requested) == SHEET_NAME
    return openpyxl.load_workbook(p)[SHEET_NAME]


# ── one sheet, one comparison ────────────────────────────────────────────────────────────

def test_every_break_is_a_column_on_one_sheet(tmp_path):
    ws = _sheet(tmp_path)
    head = [ws.cell(row=5, column=c).value for c in range(2, 6)]
    assert head == [10, 50, 250, 1000]


def test_the_unit_cost_of_each_is_on_it(tmp_path):
    ws = _sheet(tmp_path)
    assert [ws.cell(row=8, column=c).value for c in range(2, 6)] == [7.63, 5.13, 4.65, 4.55]


def test_the_saving_is_subtracted_rather_than_left_to_the_reader(tmp_path):
    """The question a break table answers. 4.55 against 7.63 is the number he is after."""
    ws = _sheet(tmp_path)
    assert ws.cell(row=11, column=2).value == "—"
    thousand = str(ws.cell(row=11, column=5).value)
    assert thousand.startswith("-3.08")
    assert "-40.4%" in thousand


def test_the_order_value_is_shown_too(tmp_path):
    ws = _sheet(tmp_path)
    assert ws.cell(row=9, column=2).value == round(7.63 * 10, 2)
    assert ws.cell(row=9, column=5).value == round(4.55 * 1000, 2)


def test_it_names_the_workbook_each_column_came_from(tmp_path):
    """A figure here and a variant on disk must be matchable, or the comparison is a claim."""
    ws = _sheet(tmp_path)
    assert ws.cell(row=12, column=2).value == "0355255_qty10.xlsx"


# ── and says what it was asked for ───────────────────────────────────────────────────────

def test_a_break_that_was_asked_for_and_not_priced_is_named(tmp_path):
    """HOWARD'S ACTUAL COMPLAINT. 10 was in the brief and not on the sheet."""
    swept = {"rows": [r for r in SWEPT["rows"] if r["quantity"] != 10]}
    ws = _sheet(tmp_path, swept, requested=[10, 50, 250, 1000])
    note = str(ws["A3"].value or "")
    assert "asked for and NOT priced: 10" in note


def test_a_break_nobody_asked_for_is_named_too(tmp_path):
    swept = {"rows": SWEPT["rows"] + [{"quantity": 100, "material": 2.3,
                                       "labour": 2.6, "unit": 4.9}]}
    ws = _sheet(tmp_path, swept, requested=[10, 50, 250, 1000])
    assert "priced but not asked for: 100" in str(ws["A3"].value or "")


def test_nothing_is_flagged_when_the_breaks_match(tmp_path):
    ws = _sheet(tmp_path, requested=[10, 50, 250, 1000])
    assert not str(ws["A3"].value or "").strip()


# ── it may not damage the estimate ───────────────────────────────────────────────────────

def test_a_sweep_that_produced_nothing_writes_no_tab(tmp_path):
    p = _book(tmp_path)
    assert write_quantity_breaks_tab(p, {"rows": []}) is None
    assert SHEET_NAME not in openpyxl.load_workbook(p).sheetnames


def test_rubbish_in_does_not_raise_into_a_run(tmp_path):
    p = _book(tmp_path)
    for junk in (None, {}, {"rows": "not a list"}, {"rows": [{"quantity": "x"}]}):
        assert write_quantity_breaks_tab(p, junk) is None


def test_running_it_twice_replaces_rather_than_stacks(tmp_path):
    p = _book(tmp_path)
    write_quantity_breaks_tab(p, SWEPT)
    write_quantity_breaks_tab(p, SWEPT)
    names = openpyxl.load_workbook(p).sheetnames
    assert names.count(SHEET_NAME) == 1


def test_the_estimate_sheet_is_untouched(tmp_path):
    p = _book(tmp_path)
    write_quantity_breaks_tab(p, SWEPT)
    assert openpyxl.load_workbook(p)["Estimate"]["C6"].value == "Quantity"


# ── show formulas: a view, and off by default ────────────────────────────────────────────

def test_show_formulas_sets_the_view_and_nothing_else(tmp_path):
    p = _book(tmp_path)
    assert select_show_formulas(p, ("Estimate",)) == ["Estimate"]
    wb = openpyxl.load_workbook(p)
    assert wb["Estimate"].sheet_view.showFormulas is True
    assert wb["Estimate"]["C6"].value == "Quantity"          # not a cell changed


def test_a_sheet_that_is_not_there_is_skipped_quietly(tmp_path):
    assert select_show_formulas(_book(tmp_path), ("Nope",)) == []


def test_it_ships_off_because_it_hides_the_money(tmp_path):
    """With it selected the sheet opens showing =IF(H96=0,... instead of the price. Right
    for checking the working, useless for reading the number — so it is a switch an
    estimator asks for, not the default everyone gets."""
    assert config.SHOW_FORMULAS_ON_ESTIMATE is False
    assert "Estimate" in config.SHOW_FORMULAS_SHEETS


def test_both_estimators_are_recorded_as_having_asked(tmp_path):
    src = (ROOT / "src" / "config.py").read_text(encoding="utf-8")
    assert "Howard Thurley" in src and "Tim Wilkes" in src
    assert "Ctrl+`" in src
