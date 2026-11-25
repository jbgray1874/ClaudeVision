"""Tests for the Monday2Friday tracker importer.

The fixture workbook is synthetic: it copies the tracker's layout (legend row,
month headers, total rows, the 'Forcasting Total' sheet) with invented values,
so no client data lives in the repository. Set M2F_TRACKER to a real tracker
to also run the reconciliation test against it.
"""
import os
import sys
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest
from openpyxl.styles import PatternFill
from openpyxl.styles.colors import Color

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from m2f.tracker_import import (  # noqa: E402
    import_tracker, parse_month_label, resolve_periods, theme_palette,
)


def _solid(rgb=None, theme=None):
    colour = Color(rgb="FF" + rgb) if rgb else Color(theme=theme)
    return PatternFill(fill_type="solid", fgColor=colour)


@pytest.fixture
def tracker(tmp_path):
    # Learn the default theme colours openpyxl writes, so the legend can use the
    # RGB of theme colour 9 while a forecast cell uses the theme reference.
    probe = tmp_path / "probe.xlsx"
    openpyxl.Workbook().save(probe)
    accent = theme_palette(openpyxl.load_workbook(probe))[9]

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Current -Boots"
    for cell, word, fill in (("K1", "Risk", _solid("FF0000")), ("L1", "TBC ", _solid("FFFF00")),
                             ("M1", "Confirmed", _solid(accent)), ("N1", "Invoiced", _solid("5B9BD5"))):
        ws[cell] = word
        ws[cell].fill = fill
    for col, header in zip("ABCDEFGH", ["Project", "PM", "PO", "OCT", "NOV", "DEC", "JAN FY27", "FEB FY27"]):
        ws[f"{col}2"] = header

    ws["A3"], ws["B3"], ws["C3"] = "Alpha display", "Conor", 4100000001
    ws["D3"], ws["D3"].fill = 100, _solid("FF0000")
    ws["G3"], ws["G3"].fill = 50, _solid(theme=9)               # theme green = Confirmed

    ws["A4"], ws["B4"] = "Beta fixtures", "conor / Chloe M"
    ws["E4"], ws["E4"].fill = "£1,200.50", _solid("FFFF00")   # text amount, TBC
    ws.row_dimensions[4].hidden = True

    ws["A5"] = 12345                                           # named only by a number
    ws["F5"], ws["F5"].fill = 300, _solid("00B0F0")            # colour not on the legend

    ws["A6"], ws["H6"] = "Gamma order", "loade"                # unreadable amount
    ws["D7"] = 999                                             # value on an unnamed row

    ws["D10"], ws["E10"], ws["F10"] = "=SUM(D3:D9)", "=SUM(E3:E9)", "=SUM(F3:F4)"  # F5 outside
    ws["J20"] = "=SUM(D3:H5)"      # BUK rows 3-5
    ws["J21"] = "=SUM(D6:H9)"      # Sigma rows 6-9
    ws["J22"] = "=SUM(D10:H10)"    # across a total row whose G10, H10 are empty

    ft = wb.create_sheet("Forcasting Total")
    ft["A1"], ft["B1"], ft["C1"] = "FY26", "Budgeted", "Tracker"
    ft["A2"], ft["C2"] = "Oct FY26", "=SUM('Current -Boots'!D10)"
    ft["A3"], ft["C3"] = "Nov FY26", "=SUM('Current -Boots'!E10)"
    ft["A4"], ft["C4"] = "Dec FY26", "=SUM('Current -Boots'!F10)"
    ft["A5"], ft["C5"] = "Jan FY27", "=SUM('Current -Boots'!D20)"  # empty cell, Oct column
    ft["A6"], ft["C6"] = "Feb FY27", 777                            # typed total
    ft["A7"] = "Totals"
    ft["M8"], ft["O8"] = "BUK", "='Current -Boots'!J20"
    ft["M9"], ft["O9"] = "Sigma ", "='Current -Boots'!J21"
    ft["M10"], ft["O10"] = "BOPS", "='Current -Boots'!J22"

    wb.create_sheet("Complete")
    path = tmp_path / "tracker.xlsx"
    wb.save(path)
    return path


def codes(result):
    return {i.code for i in result.issues}


def test_month_labels():
    assert parse_month_label("JAN FY27") == (1, 2027)
    assert parse_month_label("JUN FY27 ") == (6, 2027)
    assert parse_month_label("Oct FY 25") == (10, 2025)
    assert parse_month_label("August FY26") == (8, 2026)
    assert parse_month_label("OCT") == (10, None)
    assert parse_month_label("Upcoming/ potential sales") is None
    assert parse_month_label("Margin %") is None


def test_years_walk_out_from_the_fy_header():
    cols = [(1, 10, None), (2, 11, None), (3, 12, None), (4, 1, 2027), (5, 2, 2027)]
    periods, problems = resolve_periods(cols)
    assert periods == {1: (2026, 10), 2: (2026, 11), 3: (2026, 12), 4: (2027, 1), 5: (2027, 2)}
    assert problems == []


def test_years_handle_repeated_months_and_gaps():
    # OCT NOV DEC JULY AUG SEP OCT NOV DEC JAN FY27 (the Luxury tab's layout)
    months = [10, 11, 12, 7, 8, 9, 10, 11, 12, 1]
    cols = [(i + 1, m, 2027 if i == 9 else None) for i, m in enumerate(months)]
    periods, _ = resolve_periods(cols)
    assert [periods[i + 1] for i in range(10)] == [
        (2025, 10), (2025, 11), (2025, 12), (2026, 7), (2026, 8),
        (2026, 9), (2026, 10), (2026, 11), (2026, 12), (2027, 1)]


def test_undated_months_are_reported_not_guessed():
    periods, problems = resolve_periods([(1, 10, None), (2, 11, None)])
    assert periods == {} and problems


def test_forecast_lines_get_dates_and_legend_status(tracker):
    result = import_tracker(tracker)
    lines = {x.cell: x for x in result.forecast_lines}
    assert (lines["D3"].period, lines["D3"].amount, lines["D3"].status) == ("2026-10", "100.00", "Risk")
    assert (lines["G3"].period, lines["G3"].status) == ("2027-01", "Confirmed")
    assert (lines["E4"].amount, lines["E4"].status) == ("1200.50", "TBC")
    assert lines["F5"].status is None
    assert lines["H6"].amount is None and lines["H6"].raw == "loade"


def test_projects_keep_source_keys_and_sub_accounts(tracker):
    result = import_tracker(tracker)
    projects = {p.review_key: p for p in result.projects}
    assert set(projects) == {"BUK-003", "BUK-004", "BUK-005", "BUK-006"}
    assert projects["BUK-004"].hidden is True
    assert projects["BUK-003"].account == "Boots UK"
    assert projects["BUK-006"].account == "Sigma"
    assert projects["BUK-003"].fields["po_ref"] == 4100000001
    assert {a["name"]: a["parent"] for a in result.accounts} == {
        "Boots": None, "Boots UK": "Boots", "Sigma": "Boots"}
    assert result.skipped_tabs == {"Complete": "completed work, kept in the source workbook"}


def test_people_are_grouped_case_insensitively_but_not_merged(tracker):
    people = {p["key"]: p for p in import_tracker(tracker).people}
    assert people["conor"]["spellings"] == {"Conor": 1, "conor": 1}
    assert "chloe m" in people and "chloe" not in people


def test_problems_become_issues(tracker):
    result = import_tracker(tracker)
    assert {
        "amount_typed_as_text", "amount_unreadable", "status_unclassified", "name_is_number",
        "values_on_unnamed_rows", "value_outside_total", "total_reads_empty_cell",
        "total_reads_wrong_month", "total_typed", "account_total_misses_months",
    } <= codes(result)
    outside = next(i for i in result.issues if i.code == "value_outside_total")
    assert outside.cell == "F5"
    misses = next(i for i in result.issues if i.code == "account_total_misses_months")
    assert "G10, H10" in misses.message


def test_reconciliation_adds_our_lines_per_month(tracker):
    result = import_tracker(tracker)
    by_label = {e["label"]: e for e in result.reconciliation}
    assert by_label["Oct FY26"]["ours"] == "100.00"
    assert by_label["Nov FY26"]["ours"] == "1200.50"
    assert by_label["Dec FY26"]["ours"] == "300.00"
    assert any(p.get("problem") == "points at an empty cell" for p in by_label["Jan FY27"]["parts"])


def test_credit_limits_are_left_out_unless_asked(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = " Brands - Accounts"
    ws.append(["Brand", "Sector", "Brand Contact", "Credit Limit"])
    ws.append(["Example Brand", "Luxury", "Jo <jo@example.com>", "£100,000"])
    path = tmp_path / "brands.xlsx"
    wb.save(path)
    plain = import_tracker(path).brands[0]
    assert plain["has_credit_limit"] is True and "credit_limit_raw" not in plain
    assert plain["emails"] == ["jo@example.com"]
    assert import_tracker(path, include_sensitive=True).brands[0]["credit_limit_raw"] == "£100,000"


@pytest.mark.skipif(not os.getenv("M2F_TRACKER"), reason="set M2F_TRACKER to a real tracker workbook")
def test_real_tracker_reconciles_to_the_penny_or_explains_why():
    result = import_tracker(os.environ["M2F_TRACKER"])
    text_amounts = {i.cell: i for i in result.issues if i.code == "amount_typed_as_text"}
    for entry in result.reconciliation:
        diff = Decimal(entry.get("difference", "0"))
        if diff:
            explained = sum(Decimal(x.amount) for x in result.forecast_lines
                            if x.cell in text_amounts and x.period == entry["period"])
            assert diff == explained, entry
