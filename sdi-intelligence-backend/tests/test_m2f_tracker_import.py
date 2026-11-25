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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from m2f.tracker_import import (  # noqa: E402
    import_tracker, parse_month_label, resolve_periods,
)


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
