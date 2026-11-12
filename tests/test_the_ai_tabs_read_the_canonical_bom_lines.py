"""The AI annotation rows are built from the SAME list the Estimate sheet is built from.

canonicalise_part_estimates_for_workbook merges recogniser duplicates AND MINTS explicit
bought-in BOM lines that never got a pricing record (11762-17's £1.20 clip, priced as a
class-word clip is one). The rows that annotate the Estimate sheet's lines were reading the
pre-canonical part_estimates, so a line that carried a price on the sheet had NO provenance
row, and the report read the missing provenance row as "source not named" on a line that has
a source.

THE ROWS NO LONGER LIVE ON TABS OF THEIR OWN. "AI Material Detail" and "AI Price Provenance"
were written before Excel calculated, carrying the engine's figures beside a sheet charging
different money; their content is on AI Provenance, written after the read-back. The row
builders are kept — the Explanation tab and the covering note read them from the run JSON.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import openpyxl  # noqa: E402
import wb_populate as wp  # noqa: E402


def _clip_pe():
    return {
        "part_number": "STD PART",
        "description": "PERFO PLASTIC LOCKING CLIP",
        "page_roles": ["bought_in"],
        "unit_cost_gbp": 1.20,
        "material_estimate": {"unit_material_cost_gbp": 1.20,
                              "cost_per_part_gbp": 1.20,
                              "cost_method": "standard_commodity_provisional"},
        "source": "standard_commodity_provisional",
        "review_flags": ["Provisional standard-commodity price — confirm against a supplier quote."],
    }


def test_a_canonical_only_boughtin_reaches_the_price_provenance_rows():
    summary = {"estimate_summary": {
        "part_estimates": [],                      # pre-canonical: clip absent
        "canonical_part_estimates": [_clip_pe()],  # canonical: clip present
    }}
    rows = wp._price_provenance_rows(summary)
    parts = [str(r[0]) for r in rows]
    assert "STD PART" in parts, f"clip missing from the provenance rows: {parts}"
    # and the row names its source, in the record's words
    clip = next(r for r in rows if str(r[0]) == "STD PART")
    assert "commodity" in str(clip[3]).lower()


def test_the_writer_falls_back_to_part_estimates_when_no_canonical_list():
    # the no-cutover / no-workbook path is unchanged: it still reads part_estimates
    summary = {"estimate_summary": {"part_estimates": [_clip_pe()]}}
    parts = [str(r[0]) for r in wp._price_provenance_rows(summary)]
    assert "STD PART" in parts


def test_the_two_engine_figure_tabs_are_no_longer_written():
    """Two tabs carrying the engine's per-part money beside a sheet charging different money
    were the last place in the workbook where one line had two figures."""
    wb = openpyxl.Workbook()
    wp._append_ai_sheets(wb, {"estimate_summary": {"canonical_part_estimates": [_clip_pe()]}}, [])
    assert "AI Material Detail" not in wb.sheetnames
    assert "AI Price Provenance" not in wb.sheetnames
