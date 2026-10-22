"""Three faults the 8188-08 19:32 live book carried, each fixed as a rule (D-442, D-443, D-444).

D-442 — the price found WAS the piece. STRENGTHENER "EXTRUSION 92: LENGTH =100mm" x 24: the
researched figure said "100 mm length of EXTRUSION 92 profile, one piece" at £1.85, and D-441
read "no unit of sale" as a stock length and divided it by 3,000 — £0.06 a piece, £1.50 the
line. A candidate that names a piece, or the piece's own length, is per piece and stands.

D-443 — a wrapped cell is one row where records are minted. D-435 taught the route compiler
that an identity spelled as another's code and description joined is one row read as one
cell; the dual-path reconcile mints its own records first and never asked, so the table
reader's whole-cell "FIXING M6X12MM THREADED INSERT, HEADED HEX DRIVE" was appended beside
"FIXING M6x12mm" — four inserts charged as eight for the third book running.

D-444 — only a line carrying money blocks the quote. The check reported "2 line(s) …
KINGDOM; KINGDOM:" — the second a record of the same row with its separator, set aside with
the stopper and carrying nothing on the sheet.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import pytest                                                         # noqa: E402

import cut_piece_pricing as cpp                                       # noqa: E402
import invariants                                                     # noqa: E402
from part_identity import same_row_read_as_one_cell                   # noqa: E402

_DESC = "EXTRUSION 92: LENGTH =100mm"


# ── D-442 ───────────────────────────────────────────────────────────────────────────────

def test_a_researched_figure_that_names_one_piece_is_the_piece():
    sel = {"source": "web", "price": 1.85,
           "metadata": {"item_priced": "100 mm length of EXTRUSION 92 profile, one piece"}}
    got = cpp.price_as_cut_piece(_DESC, sel, 1.85, 24, 1)
    assert got["unit_of_sale"] == "per_piece"
    assert got["unit_gbp"] == 1.85 and got["question"] is None
    assert "piece itself" in got["basis"]


def test_a_figure_that_names_the_pieces_own_length_is_the_piece():
    sel = {"price": 1.85, "item_priced": "EXTRUSION 92 100MM"}
    assert cpp.price_as_cut_piece(_DESC, sel, 1.85, 24, 1)["unit_of_sale"] == "per_piece"


def test_a_figure_that_names_a_stock_length_is_still_the_stock():
    sel = {"uom": "each", "item_priced": "EXTRUSION 92 6000MM"}
    got = cpp.price_as_cut_piece(_DESC, sel, 30.0, 24, 1)
    assert got["unit_of_sale"] == "each" and got["stock_length_mm"] == 6000.0
    assert got["question"] is not None


def test_no_unit_and_no_item_named_is_still_read_as_a_stock_length_and_asked():
    got = cpp.price_as_cut_piece(_DESC, {"price": 1.85}, 1.85, 24, 1)
    assert got["unit_of_sale"] == "unknown" and got["question"] is not None
    assert got["unit_gbp"] < 1.85


# ── D-443 ───────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("a, da, b, db, same", [
    ("FIXING M6X12MM THREADED INSERT, HEADED HEX DRIVE", "", "FIXING M6x12mm", "THREADED INSERT, HEADED HEX DRIVE", True),
    ("FIXING M6x12mm", "THREADED INSERT, HEADED HEX DRIVE", "FIXING M6X12MM THREADED INSERT, HEADED HEX DRIVE", "THREADED INSERT, HEADED HEX DRIVE", True),
    ("KINGDOM:", "50mm x 10mm x 2m MAGNET", "KINGDOM", "50mm x 10mm x 2m MAGNET", True),
    ("FIXING49", "M6 THINSHEET THREADED INSERT", "FIXING M6x12mm", "THREADED INSERT, HEADED HEX DRIVE", False),
    ("8188-08-013", "WAVE LAYER 3", "8188-08-014", "WAVE LAYER 2", False),
    ("BI-TAPE", "", "BI-TAPE-2", "", False),
])
def test_one_row_read_two_ways_is_known_and_two_rows_are_not(a, da, b, db, same):
    assert same_row_read_as_one_cell(a, da, b, db) is same


def test_the_reconcile_holds_a_whole_cell_row_on_the_coded_record():
    import inspect
    import file_scan
    src = inspect.getsource(file_scan)
    assert "same_row_read_as_one_cell" in src, "the reconcile must use the shared predicate"
    assert src.count("_one_cell(") >= 2, "both the fastener loop and the other-row pass ask it"


# ── D-444 ───────────────────────────────────────────────────────────────────────────────

_MARK = {"reason": "the printed size 50mm x 10mm x 2m mixes m and mm", "units": ["m", "mm"]}


def test_only_a_line_carrying_money_blocks_the_quote():
    priced = {"part_number": "KINGDOM", "_price_unresolved": _MARK,
              "material_estimate": {"unit_material_cost_gbp": 48.5}}
    aside = {"part_number": "KINGDOM:", "_price_unresolved": _MARK,
             "material_estimate": {"unit_material_cost_gbp": 48.5}}
    unpriced = {"part_number": "KINGDOM: TBC", "_price_unresolved": _MARK}
    summary = {"estimate_summary": {"part_estimates": [priced, aside, unpriced]},
               "set_aside_outside_product": [{"part_number": "KINGDOM:"}]}
    v = invariants.check_an_unresolved_reading_blocks_the_quote(summary)
    assert len(v) == 1 and v[0]["severity"] == invariants.BLOCKING
    assert v[0]["detail"]["count"] == 1 and v[0]["detail"]["parts"] == ["KINGDOM"], v[0]


def test_a_priced_unresolved_line_still_blocks():
    summary = {"estimate_summary": {"part_estimates": [
        {"part_number": "KINGDOM", "_price_unresolved": _MARK,
         "cost_breakdown": {"total": 706.16}}]}}
    assert invariants.check_an_unresolved_reading_blocks_the_quote(summary)


def test_a_second_spelling_of_one_priced_line_is_counted_once():
    summary = {"estimate_summary": {"part_estimates": [
        {"part_number": "KINGDOM", "_price_unresolved": _MARK, "material_estimate": {"unit_material_cost_gbp": 48.5}},
        {"part_number": "KINGDOM:", "_price_unresolved": _MARK, "material_estimate": {"unit_material_cost_gbp": 48.5}}]}}
    v = invariants.check_an_unresolved_reading_blocks_the_quote(summary)
    assert v[0]["detail"]["count"] == 1


def test_the_writeups_minter_does_not_mint_a_whole_cell_reading_of_a_held_row():
    """The 10:12 book: the reconcile asked the rule, but the record was already born in the
    writeup's minter, keyed on the exact code. The minter asks it too."""
    import document_builder as db
    held = [{"part_number": "FIXING M6x12mm", "description": "THREADED INSERT, HEADED HEX DRIVE",
             "quantity": 4, "page_roles": ["bought_in"]}]
    rows = [{"part_number": "FIXING M6X12MM THREADED INSERT, HEADED HEX DRIVE",
             "description": "THREADED INSERT, HEADED HEX DRIVE", "quantity": 4, "bom_parent": "8188-08-SA03"},
            {"part_number": "KINGDOM:", "description": "50mm x 10mm x 2m MAGNET", "quantity": 14}]
    minted = db.bought_in_rows_without_records(rows, held)
    assert [m["part_number"] for m in minted] == ["KINGDOM:"], minted
