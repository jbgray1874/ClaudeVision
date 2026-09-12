"""A sheet that cannot be matched back to its job is a sheet somebody has to re-derive.

"Could you add description/date/drawing number at top please (easier to trace back when
requoting same job in future)" — the estimator, 12 Sep. The template already carries the
labels (C4 'Description', C7 'Date'); every pack went out with nothing beside them, and the
drawing-number box read "12349" on a job whose number is 12349-02, because the header write
took \\d+ of the folder name and stopped at the first hyphen.

The rules are the Rev box's rules: found by exact label (top rows only — 'Date' appears in
blocks further down the sheet), written only into an empty cell, values from the one
resolver that answers "what is this unit". A description that can say nothing better than
the drawing number is not written at all.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wb_populate import full_drawing_number, write_job_identity_header   # noqa: E402


def _sheet():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["C4"] = "Description"
    ws["C7"] = "Date"
    ws["F7"] = "Prepared By"
    ws["C40"] = "Date"                     # a lower block's own label — must stay untouched
    return ws


def _summary(number="12349-02-69", title="RETAILER COUNTER UNIT"):
    return {"llm_full_extract": {"drawing_info": {"drawing_number": number, "title": title}}}


# ── the drawing number is the whole number ────────────────────────────────────────────────

def test_the_folder_name_keeps_its_number_groups():
    assert full_drawing_number({}, "12349-02 SolidWorks Pack") == "12349-02"


def test_the_title_block_beats_the_folder_name():
    assert full_drawing_number(_summary(), "12349-02 SolidWorks") == "12349-02-69"


def test_a_folder_with_no_number_is_not_mangled():
    assert full_drawing_number({}, "Boots Ladder Rack") == "Boots Ladder Rack"


# ── description and date land beside their own labels ────────────────────────────────────

def test_description_and_date_fill_their_labelled_cells():
    ws = _sheet()
    written = write_job_identity_header(ws, _summary(), "12349-02")
    assert sorted(written) == ["date", "description"]
    assert ws["D4"].value == "RETAILER COUNTER UNIT"
    assert re.fullmatch(r"\d{2}/\d{2}/\d{4}", str(ws["D7"].value))


def test_a_date_label_further_down_the_sheet_is_not_touched():
    ws = _sheet()
    write_job_identity_header(ws, _summary(), "12349-02")
    assert ws["D40"].value is None


def test_an_occupied_cell_is_never_displaced():
    ws = _sheet()
    ws["D4"] = "the estimator already wrote this"
    written = write_job_identity_header(ws, _summary(), "12349-02")
    assert "description" not in written
    assert ws["D4"].value == "the estimator already wrote this"


def test_a_description_that_is_only_the_number_is_not_written():
    """A number repeated under a Description label is noise wearing a label."""
    ws = _sheet()
    summary = {"llm_full_extract": {"drawing_info": {"drawing_number": "12349-02"}}}
    written = write_job_identity_header(ws, summary, "12349-02")
    assert "description" not in written
    assert ws["D4"].value is None


def test_a_sheet_with_no_labels_takes_no_writes():
    wb = openpyxl.Workbook()
    ws = wb.active
    assert write_job_identity_header(ws, _summary(), "12349-02") == []
