"""A code printed at two item numbers of one table is two lines (D-335).

12173-07-2-GA (Wrapping Paper Trough) lists 12173-07-2-02M SIDE PANEL at item 1 and again at
item 3, qty 1 each: a handed pair, "TO BE PRODUCED IN RH/LH HANDED PAIRS", made under one code.
The graph and bom_tree keyed rows by code and the second overwrote the first — one side panel.
Checked from the drawings before the run, not after it.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import bom_tree  # noqa: E402
import route_compiler as rc  # noqa: E402

TROUGH = "12173-07-2-GA"


def _row(code, qty, item, parent=TROUGH):
    return {"part_number": code, "description": "x", "quantity": qty, "item_number": item,
            "bom_parent": parent, "source_pdf": parent}


def _edges(rows, known):
    return {(c, p): q for c, p, q in rc._bom_stated_edges(rows, {}, set(known))}


def test_the_handed_side_panel_at_items_1_and_3_is_two():
    rows = [_row("12173-07-2-02M", 1, "1"), _row("12173-07-2-01M", 1, "2"),
            _row("12173-07-2-02M", 1, "3"), _row("12173-07-2-03M", 2, "4")]
    known = {TROUGH, "12173-07-2-01M", "12173-07-2-02M", "12173-07-2-03M"}
    e = _edges(rows, known)
    assert e[("12173-07-2-02M", TROUGH)] == 2
    assert e[("12173-07-2-03M", TROUGH)] == 2
    assert e[("12173-07-2-01M", TROUGH)] == 1


def test_the_same_item_read_twice_is_one_line():
    rows = [_row("12173-07-2-03M", 2, "4"), _row("12173-07-2-03M", 2, "4")]
    assert _edges(rows, {TROUGH, "12173-07-2-03M"})[("12173-07-2-03M", TROUGH)] == 2


def test_rows_with_no_item_number_keep_the_old_rule():
    rows = [_row("12173-07-2-03M", 2, None), _row("12173-07-2-03M", 2, None)]
    assert _edges(rows, {TROUGH, "12173-07-2-03M"})[("12173-07-2-03M", TROUGH)] == 2


def test_one_tab_under_two_frames_stays_two_edges():
    """12173-03-06M BACK PANEL TAB x8 under -202 and x8 under -203: two parents, 16 tabs."""
    rows = [_row("12173-03-06M", 8, "2", "12173-03-202"),
            _row("12173-03-06M", 8, "2", "12173-03-203")]
    e = _edges(rows, {"12173-03-202", "12173-03-203", "12173-03-06M"})
    assert e[("12173-03-06M", "12173-03-202")] == 8
    assert e[("12173-03-06M", "12173-03-203")] == 8


def test_bom_tree_adds_the_pair_too():
    rows = bom_tree.combine_repeated_item_rows(
        [_row("12173-07-2-02M", 1, "1"), _row("12173-07-2-02M", 1, "3"),
         _row("12173-07-2-02M", 1, "3")])
    assert len(rows) == 1 and rows[0]["quantity"] == 2
    assert rows[0]["combined_items"] == ["1", "3"]


def test_the_tables_pair_corrects_the_extracts_single_edge():
    """THE 29 SEP RUN (D-338). The extract's assembly list is keyed by code, so it named the
    side panel once, x1; the table's summed 2 was then refused as a re-statement of a link the
    extract already held. The book costed one side panel."""
    parts = [{"part_number": p, "description": p, "quantity": 1}
             for p in (TROUGH, "12173-07-2-01M", "12173-07-2-02M")]
    extract = {"assemblies": [{"part_number": TROUGH, "children": [
        {"part_number": "12173-07-2-01M", "qty": 1},
        {"part_number": "12173-07-2-02M", "qty": 1}]}]}
    rows = [_row("12173-07-2-02M", 1, "1"), _row("12173-07-2-01M", 1, "2"),
            _row("12173-07-2-02M", 1, "3")]
    g = rc.build_part_graph(parts, extract, rows)
    assert g["quantities"]["12173-07-2-02M"] == 2, g["quantities"]
    assert g["quantities"]["12173-07-2-01M"] == 1


def test_one_row_per_code_leaves_the_extracts_edge_alone():
    parts = [{"part_number": p, "description": p, "quantity": 1}
             for p in (TROUGH, "12173-07-2-01M")]
    extract = {"assemblies": [{"part_number": TROUGH, "children": [
        {"part_number": "12173-07-2-01M", "qty": 3}]}]}
    g = rc.build_part_graph(parts, extract, [_row("12173-07-2-01M", 1, "2")])
    assert g["quantities"]["12173-07-2-01M"] == 3
