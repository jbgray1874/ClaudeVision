"""Thirteen operations promised, twelve on the sheet, and nothing anywhere said why.

Reading the 11 September 7332-01 pack the covering note offered "Every operation, and who
decided it — 13 lines" while the Estimate sheet carried 12 labour rows. Nothing was lost and
nothing disagreed: a workbook row is a tooling SETUP and can hold several parts, so the 2.5 mm
laser decisions for -003 and -004 share one nest row. But no artefact said that, so the only way
to reconcile 13 with 12 was to already know it — and the reasonable conclusion from outside was
that items were missing.

Two tabs with these names were removed from this workbook once, on the instruction "we do have
too many tabs in that overall spreadsheet", and that was right: they were bare text restating
facts held elsewhere. They are back because the Routes tab now carries something no other
artefact does — the decision AND the sheet row it landed on, side by side. Without that column
this would be a third place to read the same numbers.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import openpyxl                                                          # noqa: E402
import wb_populate as wbp                                                # noqa: E402


def _summary(*, with_rows: bool = True) -> dict:
    """Two laser decisions that share one nest row, plus a tubebend that has its own.

    COSTED, because this whole tab is a costed run's artefact: it reconciles route decisions to
    the WORKBOOK ROWS THAT CHARGED THEM, and those rows only exist once Excel has calculated.
    An uncosted fixture here was testing a state the tab is never written in — and it was the
    reason the yes/no column read as absent when bom_and_route_extract began naming that column
    after the source that produced it.
    """
    labour = {"rows": [
        {"workbook_row": 98, "part_numbers": ["7332-01-003", "7332-01-004"],
         "wb_operation": "Laser (Metal)", "decision_ids": ["dA", "dB"]},
        {"workbook_row": 103, "part_numbers": ["7332-01-002"],
         "wb_operation": "Tubebend", "decision_ids": ["dC"]},
    ]} if with_rows else {"rows": []}
    return {
        "job_number": "7332-01",
        "document_analysis": {"bom_rows": [
            {"part_number": "7332-01-003", "description": "STRAP", "quantity": 2,
             "material_text": "MS 2.5", "source": "bom_table", "source_page": 3},
            {"part_number": "7332-01-004", "description": "CAP", "quantity": 2,
             "material_text": "MS 2.5", "source": "bom_table", "source_page": 3}]},
        "workbook_labour": labour,
        "estimate_summary": {"canonical_route_shadow": {"decisions": [
            {"decision_id": "dA", "target_id": "7332-01-003", "operation": "laser_cutting",
             "status": "required", "scope": "part", "participants": ["7332-01-003"],
             "reason": "2.5mm MS flat"},
            {"decision_id": "dB", "target_id": "7332-01-004", "operation": "laser_cutting",
             "status": "required", "scope": "part", "participants": ["7332-01-004"],
             "reason": "2.5mm MS flat"},
            {"decision_id": "dC", "target_id": "7332-01-002", "operation": "tubebend",
             "status": "required", "scope": "part", "participants": ["7332-01-002"],
             "reason": "bent from tube"}]},
            "final_estimate": {"totals": {"unit_gbp": 80.34, "material_gbp": 40.89,
                                          "labour_gbp": 33.83}}},
    }


def _book(summary: dict):
    book = openpyxl.Workbook()
    wbp._append_ai_sheets(book, summary, [])
    return book


def _block_rows(sheet, block_title_starts: str) -> list:
    """The rows of ONE block on the shared sheet, as dicts keyed by that block's own header.

    The sheet holds three blocks, so there are three header rows and a reader that assumes row 1
    — or even "the first header" — reads the wrong table. The block is found by its title, the
    header is the next row whose first cell is filled, and the rows run until the first blank.
    """
    head = None
    for r in range(1, sheet.max_row + 1):
        first = str(sheet.cell(row=r, column=1).value or "")
        if first.startswith(block_title_starts):
            for probe in range(r + 1, min(r + 6, sheet.max_row + 1)):
                if str(sheet.cell(row=probe, column=1).value or "").strip() and \
                        not str(sheet.cell(row=probe, column=1).value).startswith(("With ",
                                                                                   "The ", "An ",
                                                                                   "THE ",
                                                                                   "Column ")):
                    head = probe
                    break
            break
    assert head, f"block {block_title_starts!r} not found on {sheet.title}"
    headers = [c.value for c in sheet[head]]
    out = []
    for r in range(head + 1, sheet.max_row + 1):
        if not str(sheet.cell(row=r, column=1).value or "").strip():
            break
        out.append(dict(zip(headers, [c.value for c in sheet[r]])))
    return out


def _routes(summary: dict) -> list:
    return _block_rows(_book(summary)["BOMs & Routes"], "2 · Routes")


def _boms(summary: dict) -> list:
    return _block_rows(_book(summary)["BOMs & Routes"], "1 · BOMs")


def test_the_workbook_gains_ONE_tab_carrying_both_subjects():
    """The request, plainly: ONE new tab, professional grade, holding only the BOMs and the
    routes and where they came from. Three tabs would be the same bloat with better fonts —
    "we do have too many tabs in that overall spreadsheet" still stands."""
    names = _book(_summary()).sheetnames
    assert "BOMs & Routes" in names
    assert "BOMs" not in names and "Routes" not in names, \
        "one sheet with blocks, not a tab per subject"


def test_the_one_tab_holds_all_three_blocks():
    ws = _book(_summary())["BOMs & Routes"]
    text = "\n".join(str(c.value) for r in ws.iter_rows() for c in r if c.value)
    assert "1 · BOMs" in text
    assert "2 · Routes" in text
    assert "3 · Where every column came from" in text
    assert "NO FIGURE ON THIS SHEET IS A COST" in text


def test_two_decisions_sharing_one_sheet_row_say_so_and_name_each_other():
    """THE RECONCILIATION THAT WAS MISSING. This is the whole reason the tabs are back."""
    rows = {r["part or assembly"]: r for r in _routes(_summary())}
    assert rows["7332-01-003"]["sheet row"] == 98
    assert rows["7332-01-004"]["sheet row"] == 98
    assert rows["7332-01-003"]["shares that row with"] == "7332-01-004"
    assert rows["7332-01-004"]["shares that row with"] == "7332-01-003"
    for code in ("7332-01-003", "7332-01-004"):
        assert "tooling SETUP" in rows[code]["why the counts differ"]
        assert "charged once between them" in rows[code]["why the counts differ"]


def test_a_decision_with_its_own_row_shares_with_nobody():
    """The guard on the guard: a column that says "shared" on every line explains nothing."""
    rows = {r["part or assembly"]: r for r in _routes(_summary())}
    assert rows["7332-01-002"]["sheet row"] == 103
    assert rows["7332-01-002"]["shares that row with"] == ""


def test_a_charged_decision_with_no_sheet_row_is_reported_as_a_broken_join():
    """Not silently blank. A decision that is charged and reaches no row means the route-to-sheet
    join failed for that line, which is exactly the class of defect that made the Operations
    sheet read as empty on every job."""
    rows = {r["part or assembly"]: r for r in _routes(_summary(with_rows=False))}
    for code in ("7332-01-002", "7332-01-003", "7332-01-004"):
        assert rows[code]["sheet row"] is None
        assert "the join from the route to the sheet is missing" in \
            rows[code]["why the counts differ"]


def test_an_uncharged_decision_is_not_reported_as_a_broken_join():
    """`not_applicable` has no sheet row by design, and flagging that as a failure would fill
    the column with noise and bury the real ones."""
    summary = _summary()
    summary["estimate_summary"]["canonical_route_shadow"]["decisions"].append(
        {"decision_id": "dD", "target_id": "7332-01-002", "operation": "folding",
         "status": "not_applicable", "scope": "part", "participants": ["7332-01-002"],
         "reason": "not possible on stock form 'tube'"})
    row = [r for r in _routes(summary) if r["operation"] == "folding"][0]
    assert row["charged"] == "no"
    assert row["sheet row"] is None
    assert "no sheet row is expected" in row["why the counts differ"]
    assert "missing" not in row["why the counts differ"]


def test_the_boms_tab_carries_the_reader_and_the_duplicate_flag():
    rows = _boms(_summary())
    assert len(rows) == 2
    assert rows[0]["read by"] == "bom_table"
    assert rows[0]["what that reader is"]


def test_a_decision_id_recorded_singly_rather_than_in_a_list_still_joins():
    """Rows carry decision_ids, and older rows carry a single decision_id. Reading one and not
    the other is how a present join reads as absent."""
    summary = _summary()
    summary["workbook_labour"]["rows"] = [
        {"workbook_row": 103, "part_numbers": ["7332-01-002"], "decision_id": "dC"}]
    row = [r for r in _routes(summary) if r["part or assembly"] == "7332-01-002"][0]
    assert row["sheet row"] == 103


def test_a_failure_building_the_tabs_never_stops_the_workbook_saving():
    """A diagnostic tab must not be the reason an estimate cannot be issued."""
    book = openpyxl.Workbook()
    try:
        wbp._append_ai_sheets(book, {"estimate_summary": "not a mapping"}, [])
    except Exception as err:                                             # noqa: BLE001
        pytest.fail(f"raised into populate_workbook: {type(err).__name__}: {err}")


def test_an_empty_record_adds_no_empty_tabs():
    """Three blank tabs on a thin job is the "too many tabs" complaint all over again."""
    names = _book({"job_number": "empty"}).sheetnames
    assert "BOMs" not in names
    assert "Routes" not in names


def test_the_reconciler_finds_the_yes_no_column_by_role_not_by_name():
    """bom_and_route_extract names that column after the source that produced it: "charged" on
    a costed run, "required by the route" on a pack nobody priced. This reconciler looked it up
    by the literal string, so on an uncosted record every decision came back None and was
    reported as "not charged, so no sheet row is expected" — a statement about money, made by a
    sheet with no money in it, about a route that had genuinely required the work.

    Unreachable today, because this tab is only written by a costed run. Pinned because "it
    cannot happen yet" is not a property anybody maintains.
    """
    import bom_and_route_extract as bre
    # A GENUINELY UNCOSTED RECORD NEEDS BOTH GONE, and that is the point rather than an
    # inconvenience: a workbook labour row carries the sheet row that CHARGED the decision, so
    # its presence is itself proof the pack was costed. Removing only final_estimate leaves a
    # record that is still, correctly, a costed one.
    summary = _summary(with_rows=False)
    summary["estimate_summary"].pop("final_estimate")
    summary.pop("workbook_labour", None)
    assert bre.source_declaration(summary)["operation_column"] == "required by the route"
    rows = _routes(summary)
    folding = [r for r in rows if r["operation"] == "tubebend"][0]
    # the decision IS required, and the reconciler must not report it as uncharged noise
    assert folding["required by the route"] == "yes"
    assert "no sheet row is expected" not in (folding["why the counts differ"] or "")
