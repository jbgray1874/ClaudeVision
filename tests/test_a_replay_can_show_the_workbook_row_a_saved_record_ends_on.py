"""A SAVED RECORD CAN BE TAKEN TO THE WORKBOOK ROW IT ENDS ON, WITHOUT A RUN (14 Nov 2026).

12674-01-GA's base was charged £6.24 on a build that held the safeguard against exactly that.
The reviewer: "Please reproduce this exact record through to Estimate!M11, not just the
intermediate part calculation." tools/replay_saved_job.py stopped at the engine's figure and
said so. With --workbook it writes the replayed record into the template with the run's own
writer and prints the material rows as the writer left them.

The contrast is the point of the tool: a line with a price shows a price cell on its row, and
a line the engine refused to price shows its row with no price cell.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))


def _line(code, name, price):
    me = {"material": "TIMBER", "thickness_mm": None}
    pe = {"part_number": code, "description": name, "quantity": 1,
          "normalized_material": "TIMBER", "material_estimate": me,
          "process_estimate": {}, "labour_estimate": {}, "review_flags": [],
          "unit_total_cost_gbp": price or 0.0, "extended_total_cost_gbp": price or 0.0}
    if price:
        me.update({"unit_material_cost_gbp": price, "cost_per_part_gbp": price,
                   "extended_material_cost_gbp": price,
                   "cost_method": "last_resort_market_indication",
                   "material_allowance_only": True})
        pe["costing_basis"] = "last_resort_market_indication"
    else:
        pe["costing_basis"] = "computed"
        pe["construction_not_established"] = {"missing": ["its thickness"]}
        pe["review_flags"].append(f"{code}: NOT PRICED — construction not established")
    return pe


def _book(tmp_path, monkeypatch, lines):
    import replay_saved_job as R
    from test_a_wire_is_sized_by_its_own_weight import _template
    monkeypatch.setenv("SDI_WB_TEMPLATE", str(_template(tmp_path / "template.xlsx")))
    # These hand-made lines carry no compiled route; the sheet is built from them as they stand.
    import wb_populate
    monkeypatch.setattr(wb_populate.config, "CANONICAL_ROUTE_WORKBOOK_CUTOVER", False)
    summary = {"estimate_summary": {"part_estimates": lines}, "quantity": 1}
    book = R.write_workbook(summary, "T-01-GA", tmp_path / "replay")
    assert book, "the workbook stage wrote no book"
    assert Path(book).parent == tmp_path / "replay" / "books", "written outside the replay folder"
    return R, book


def _price(row):
    """What the writer put in the row's Price cell on the Bill of Materials block."""
    import wb_populate
    from openpyxl.utils import get_column_letter
    col = get_column_letter(wb_populate.CELL_MAP["bom"]["col_price"])
    return row["cells"].get(f"{col}{row['row']}")


def test_a_charged_line_shows_its_price_on_its_row(tmp_path, monkeypatch):
    R, book = _book(tmp_path, monkeypatch, [_line("T-01-01J", "BASE", 6.0)])
    rows = R.workbook_rows(book, "T-01-01J")
    assert len(rows) == 1, rows
    assert _price(rows[0]) == 6.0, f"the £6.00 the record charges is not on the row: {rows[0]}"


def test_a_line_the_engine_refused_to_price_shows_its_row_with_no_price(tmp_path, monkeypatch):
    R, book = _book(tmp_path, monkeypatch, [_line("T-01-01J", "BASE", None)])
    rows = R.workbook_rows(book, "T-01-01J")
    assert len(rows) == 1, "the unpriced line is still a row on the sheet"
    assert _price(rows[0]) is None, f"a price was written on a line nobody priced: {rows[0]}"


def test_only_the_rows_that_name_what_was_asked_for_are_shown(tmp_path, monkeypatch):
    R, book = _book(tmp_path, monkeypatch, [_line("T-01-01J", "BASE", 6.0),
                                            _line("T-01-02J", "TOP", 9.0)])
    assert [r["cells"] for r in R.workbook_rows(book, "T-01-02J")
            if any("T-01-01J" in str(v) for v in r["cells"].values())] == []
    assert len(R.workbook_rows(book)) == 2


def test_an_unreachable_template_writes_no_book_and_claims_nothing(tmp_path, monkeypatch, capsys):
    import replay_saved_job as R
    monkeypatch.setenv("SDI_WB_TEMPLATE", str(tmp_path / "absent.xlsx"))
    summary = {"estimate_summary": {"part_estimates": [_line("T-01-01J", "BASE", 6.0)]}}
    assert R.write_workbook(summary, "T-01-GA", tmp_path / "replay") is None
    import wb_populate
    assert wb_populate.CELL_MAP["output_dir"] != str(tmp_path / "replay" / "books"), \
        "the writer's own output folder was left pointing at the replay's"
