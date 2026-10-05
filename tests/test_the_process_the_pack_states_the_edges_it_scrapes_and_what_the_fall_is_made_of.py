"""12696-01 Bag Pricing Hook, 5 Oct book on 3e2ae7a, James Gray's verdict (D-393):

    "As an estimate to hand to Dave, it is below the bar ... the weld row says CO2 despite
     the TIG note, PETG scraped edges have no cost ... The 250-off figure also depends heavily
     on spreading packaging across the batch; that basis needs checking."

Three readings, none of which added or removed money on its own:

* the pack says "ALL WELDS TO BE TIG UNLESS STATED"; the rate card has one arc-weld row,
  "Weld (CO2)", so the weld is charged there — but nothing said the process was TIG, and the
  row title read as a decision that it was not;
* 01A's title block reads FINISH: SCRAPED EDGES. The coat gates read it as bare — right — and
  the hand work it names was charged by nobody;
* the Quantity Breaks sheet showed each column's unit cost and the saving against one off,
  and nothing of what the saving was: the order's packaging and delivery divided by more
  units, and every department's set-up divided by more units.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import config                                                         # noqa: E402
import extractor_patterns as ep                                       # noqa: E402
import finish_rules as fr                                             # noqa: E402
import quantity_sweep as qs                                           # noqa: E402
import wb_populate as wp                                              # noqa: E402
import weld_symbols as ws                                             # noqa: E402

LEGEND = "WELD SPECIFICATION: ALL WELDS TO BE TIG UNLESS STATED RESISTANCE WELDING WIRE TO WIRE"


# ── the process the pack states ───────────────────────────────────────────────────────────

def test_the_packs_weld_specification_names_its_process():
    read = ep.weld_process_stated(LEGEND)
    assert read["process"] == "TIG" and read["default"] is True
    # squashed, as weld_symbols keeps a sheet's text, and letter-spaced, as a border reads
    assert ep.weld_process_stated("ALLWELDSTOBETIGUNLESSSTATED")["process"] == "TIG"
    assert ep.weld_process_stated("A L L W E L D S T O B E M I G")["process"] == "MIG"
    # the vocabulary is config's, and a word inside another is not a process
    assert "TIG" in config.WELD_PROCESS_VOCAB
    assert ep.weld_process_stated("FATIGUE TESTED") is None
    assert ep.weld_process_stated("") is None


def test_the_specification_alone_still_puts_no_weld_on_a_part():
    """The reading is for a part whose own sheet states the weld; the legend never is one."""
    assert ep.legend_cues_set_aside(LEGEND) == ["welding"]
    part = {"part_number": "X-01M", "textual_operations": []}
    ws.apply_to_parts([part], {"X-01M": {"counts": {}, "pages": [3],
                                         "text": "ALLWELDSTOBETIGUNLESSSTATED"}})
    assert "welding" not in part["textual_operations"]
    assert "weld_process_stated" not in part


def test_a_welded_part_records_the_process_and_where_it_is_charged():
    weldment = {"part_number": "X-101", "textual_operations": []}
    ws.apply_to_parts([weldment], {"X-101": {"counts": {"fillet": 2}, "pages": [2],
                                             "text": "ALLWELDSTOBETIGUNLESSSTATED"}})
    assert "welding" in weldment["textual_operations"]
    assert weldment["weld_process_stated"]["process"] == "TIG"
    assert weldment["weld_process_stated"]["charged_on"] == "Weld (CO2)"
    flags = " ".join(weldment["review_flags"])
    assert "WELDED per the drawing" in flags
    assert "WELD PROCESS TIG" in flags and "Weld (CO2)" in flags


def test_a_weld_stated_by_the_finish_field_records_the_process_too():
    member = {"part_number": "X-202", "textual_operations": []}
    ws.apply_finish_welds([member], {"X-202": {"finish": "WELDED", "pages": [4],
                                               "text": "ALLWELDSTOBETIGUNLESSSTATED"}})
    assert member["weld_process_stated"]["process"] == "TIG"


def test_the_weld_row_says_the_process_beside_the_rate_it_is_charged_at():
    recs = {"X-101": {"weld_process_stated": {"process": "TIG", "default": True}}}
    note = wp.weld_process_note("Weld (CO2)", ["X-101"], recs)
    assert "TIG per the pack's weld specification" in note
    assert "Weld (CO2) rate" in note
    # no other row, and no row whose parts state nothing
    assert wp.weld_process_note("Fold", ["X-101"], recs) == ""
    assert wp.weld_process_note("Weld (CO2)", ["X-01M"], recs) == ""
    assert wp.weld_process_note("Weld (CO2)", ["X-101"], {}) == ""


# ── the edges the sheet says are scraped ──────────────────────────────────────────────────

def test_scraped_edges_is_a_statement_of_hand_work_and_still_no_coat():
    hits, rest = fr.process_statements("SCRAPED EDGES")
    assert "deburring" in hits["SCRAPED EDGES"] and rest == ""
    assert fr.minted_operation("SCRAPED EDGES") == "deburring"
    assert fr.minted_operation("POWDER COATED") == ""
    assert "bare" in fr.finish_families("SCRAPED EDGES")        # nothing is coated


def test_a_petg_strip_whose_finish_is_scraped_edges_gets_a_costed_deburr():
    strip = {"part_number": "X-01A", "normalized_material": "PETG",
             "textual_operations": ["laser_cutting"]}
    stamped = ws.apply_finish_processes([strip], {"X-01A": {"finish": "SCRAPED EDGES"}})
    assert stamped == ["X-01A"]
    assert "deburring" in strip["textual_operations"]
    assert strip["operation_sources"]["deburring"] == "drawing_deterministic"
    assert any("SCRAPED EDGES" in f and "names no coat" in f for f in strip["review_flags"])
    # and the acrylic side charges it on its own manual row, with the work named
    assert wp.OP_NAME_MAP_ACRYLIC["deburring"] == "Manual labour (Acrylic)"
    desc = wp.labour_row_description("Manual labour (Acrylic)", "PETG", 1.0, ["X-01A"],
                                     work_ops=["deburring"])
    assert "edge scraping / deburr" in desc


def test_hand_work_already_on_the_part_is_not_doubled_and_a_coat_is_not_a_process():
    strip = {"part_number": "X-01A", "textual_operations": ["manual_labour_acrylic"],
             "operation_sources": {"manual_labour_acrylic": "inference"}}
    assert ws.apply_finish_processes([strip], {"X-01A": {"finish": "SCRAPED EDGES"}}) == []
    assert "deburring" not in strip["textual_operations"]
    assert strip["operation_sources"]["manual_labour_acrylic"] == "drawing_deterministic"
    coated = {"part_number": "X-101", "textual_operations": []}
    assert ws.apply_finish_processes([coated], {"X-101": {"finish": "POWDER COATED"}}) == []
    welded = {"part_number": "X-202", "textual_operations": []}
    assert ws.apply_finish_processes([welded], {"X-202": {"finish": "WELDED"}}) == []
    assert welded["textual_operations"] == []                     # the weld readers' statement
    ruled = {"part_number": "X-03J", "textual_operations": [],
             "operations_ruled_out": {"deburring": "board is not deburred"}}
    assert ws.apply_finish_processes([ruled], {"X-03J": {"finish": "SCRAPED EDGES"}}) == []


# ── what the fall from one off is made of ─────────────────────────────────────────────────

FINAL = {
    "material_rows": [
        {"part_code": "PACKAGING", "total_value_gbp": 8.00},
        {"part_code": "DELIVERY", "total_value_gbp": 9.00},
        {"part_code": "FIXING297", "total_value_gbp": 0.11},
    ],
    "labour_rows": [
        {"operation": "Weld (CO2)", "setup_minutes": 30, "dept_rate_gbp_per_hour": 42.0},
        {"operation": "Fold", "setup_minutes": 15, "dept_rate_gbp_per_hour": 40.0},
        {"operation": "P.Coat", "setup_minutes": None, "dept_rate_gbp_per_hour": 35.0},
    ],
}


def test_the_basis_is_read_off_the_rows_and_divided_by_the_quantity():
    one = qs.basis_from_rows(FINAL, 1)
    assert one == {"order_charges_per_unit": 17.00, "setup_per_unit": 31.00}
    assert qs.basis_from_rows(FINAL, 250) == {"order_charges_per_unit": 17.00,
                                               "setup_per_unit": 0.12}
    # not read is not zero
    assert qs.basis_from_rows({"labour_rows": [{"operation": "Fold"}]}, 10) == {}
    assert qs.basis_from_rows(None, 10) == {} and qs.basis_from_rows(FINAL, 0) == {}


def _book(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    wb.active.title = "Estimate"
    p = tmp_path / "12696-01_estimate.xlsx"
    wb.save(p)
    return openpyxl, p


SWEPT = {"rows": [
    {"quantity": 1, "material": 19.31, "labour": 202.94, "unit": 246.25,
     "order_charges_per_unit": 17.00, "setup_per_unit": 193.77},
    {"quantity": 250, "material": 2.38, "labour": 9.95, "unit": 13.89,
     "order_charges_per_unit": 0.07, "setup_per_unit": 0.78},
]}


def test_the_breaks_sheet_lays_out_what_each_column_is_made_of(tmp_path):
    from quantity_breaks_tab import SHEET_NAME, write_quantity_breaks_tab
    openpyxl, p = _book(tmp_path)
    assert write_quantity_breaks_tab(p, SWEPT, requested=[1, 250]) == SHEET_NAME
    sh = openpyxl.load_workbook(p)[SHEET_NAME]
    labels = {str(sh.cell(row=r, column=1).value or ""): r for r in range(1, 30)}
    assert "What the fall from 1 off is made of" in labels
    r = labels["Packaging & delivery £/unit"]
    assert [sh.cell(row=r, column=c).value for c in (2, 3)] == [17.00, 0.07]
    r = labels["Labour set-up £/unit"]
    assert [sh.cell(row=r, column=c).value for c in (2, 3)] == [193.77, 0.78]
    r = labels["Labour run £/unit"]
    assert [sh.cell(row=r, column=c).value for c in (2, 3)] == [9.17, 9.17]
    r = labels["Unit cost less the spread money £"]
    assert [sh.cell(row=r, column=c).value for c in (2, 3)] == [35.48, 13.04]
    note = " ".join(str(sh.cell(row=r, column=1).value or "") for r in range(1, 30))
    assert "check that figure before quoting a break" in note
    # the rows above it are where they always were
    assert sh.cell(row=5, column=1).value == "Quantity"
    assert sh.cell(row=8, column=3).value == 13.89


def test_a_sweep_that_read_no_basis_writes_no_basis_rows(tmp_path):
    from quantity_breaks_tab import SHEET_NAME, write_quantity_breaks_tab
    openpyxl, p = _book(tmp_path)
    bare = {"rows": [{k: v for k, v in r.items()
                      if k not in ("order_charges_per_unit", "setup_per_unit")}
                     for r in SWEPT["rows"]]}
    write_quantity_breaks_tab(p, bare)
    sh = openpyxl.load_workbook(p)[SHEET_NAME]
    text = " ".join(str(sh.cell(row=r, column=1).value or "") for r in range(1, 30))
    assert "made of" not in text and "set-up" not in text
