"""A line named by its stock code is the drawing whose title block prints that code
(Hotel Chocolat, Wall of Chocolate, 26 Nov 2026).

The GA lists "00026207 WOC BOX ASSEMBLY x30" with no drawing column. Sheet A-33488 prints
"FINISHED PART NO.00026207" in its title block and holds the box's own parts list; sheet
E-33488 prints "FINISHED PART NO. : - 10100277", the ticket surround the box takes four of.
The line and the sheet were two parts, so A-33488 was a second top level and every part of
the box was costed once, not thirty times: screws at 10 instead of 300, the ticket surround
at 1 instead of 120.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import route_compiler as rc  # noqa: E402
from bom_pipeline import name_lines_by_title_blocks  # noqa: E402
from drawing_reference import (drawings_named_by_title_blocks,  # noqa: E402
                               finished_parts_on_sheet, sheet_drawing_reference)


def _row(pn, desc, qty, parent, sheet, **kw):
    return dict({"part_number": pn, "description": desc, "quantity": qty, "bom_parent": parent,
                 "bom_parent_known": True, "bom_sheet": sheet, "source_pdf": parent}, **kw)


def _pack():
    rows = [
        _row("00026207", "WOC BOX ASSEMBLY", 30, "A-33486", "Midfloor.pdf#0"),
        _row("10100273", "WOC BOTTOM SUPPORT FRAMES", 2, "A-33486", "Midfloor.pdf#0"),
        _row("10100275", "WOC BOX WELDED ASSEMBLY", 1, "A-33488", "Sub.pdf#0"),
        _row("10100277", "WOC BOX TICKET SURROUND", 4, "A-33488", "Sub.pdf#0"),
        _row("30002236", "M6X20 CSK POZI MACHINE SCREW", 10, "A-33488", "Sub.pdf#0"),
        _row("D-33494", "WOC BOX LHS", 1, "A-33493", "Sub.pdf#1",
             finished_part_no="20126039", drawing_reference="D-33494"),
        _row("D-33498", "WOC BOX SHELF", 4, "A-33493", "Sub.pdf#1",
             finished_part_no="20126035", drawing_reference="D-33498"),
    ]
    sheets = [("Midfloor.pdf#0", "FINISHED PART NO.10100272 DRG No. A-33486"),
              # the parts-list header names the column too, and runs into no code
              ("Sub.pdf#0", "FINISHED PART NO.00026207 ITEM NO. FINISHED PART NO. DRG NO"),
              ("Sub.pdf#1", "FINISHED PART NO.10100275 DRG No. A-33493"),
              # a detail sheet with no parts list: its own DRG No. says which drawing it is
              ("Sub.pdf#70", "FINISHED PART NO. : - 10100277 DRG No. E-33488")]
    return rows, sheets


def _graph(rows, model_names_the_box_by_stock_code=True):
    parts = [{"part_number": r["part_number"], "description": r["description"],
              "quantity": r["quantity"]} for r in rows]
    parts += [{"part_number": p, "description": d, "quantity": 1} for p, d in (
        ("A-33486", "WOC MIDFLOOR"), ("A-33488", "WOC BOX"), ("A-33493", "WOC BOX WELDED"),
        ("E-33488", "TICKET SURROUND"))]
    ext = {"assemblies": [{"part_number": "00026207", "children": [
        {"part_number": "10100275", "qty": 1}, {"part_number": "10100277", "qty": 4}]}]} \
        if model_names_the_box_by_stock_code else {}
    g = rc.build_part_graph(parts, llm_extract=ext, bom_rows=rows)
    return {n.part_number: n.qty_per_unit for n in g["nodes"]}


def test_a_title_block_names_the_finished_part_it_draws():
    assert finished_parts_on_sheet("FINISHED PART NO.00026207") == {"00026207"}
    assert finished_parts_on_sheet("FINISHED PART NO. : - 10100277") == {"10100277"}
    assert finished_parts_on_sheet("ITEM NO. FINISHED PART NO. DRG NO. DESCRIPTION") == set()
    assert sheet_drawing_reference("TITLE DRG No. E-33488 SCALE") == "E-33488"
    assert sheet_drawing_reference("DRG No. B.34109 DRG No. B.34082") is None


def test_a_code_the_sheets_own_list_prints_or_two_drawings_claim_names_nothing():
    assert drawings_named_by_title_blocks(
        [("FINISHED PART NO. 10100530 B.34109", "B.34082", {"10100530"})]) == {}
    assert drawings_named_by_title_blocks(
        [("FINISHED PART NO.10100277 DRG No. E-33488", None, ()),
         ("FINISHED PART NO.10100277 DRG No. C-33460", None, ())]) == {}


def test_the_ga_line_and_the_box_lines_become_the_drawings():
    rows, sheets = _pack()
    found = name_lines_by_title_blocks(rows, sheets)
    by_desc = {r["description"]: r for r in rows}
    assert by_desc["WOC BOX ASSEMBLY"]["part_number"] == "A-33488"
    assert by_desc["WOC BOX ASSEMBLY"]["finished_part_no"] == "00026207"
    assert by_desc["WOC BOX WELDED ASSEMBLY"]["part_number"] == "A-33493"
    assert by_desc["WOC BOX TICKET SURROUND"]["part_number"] == "E-33488"
    # the GA's own title-block code is on no line; a purchase keeps its stock code
    assert by_desc["M6X20 CSK POZI MACHINE SCREW"]["part_number"] == "30002236"
    assert by_desc["WOC BOTTOM SUPPORT FRAMES"]["part_number"] == "10100273"
    assert len(found) == 3 and all(f["severity"] == "info" for f in found)


def test_thirty_boxes_take_thirty_of_everything_in_a_box():
    rows, sheets = _pack()
    name_lines_by_title_blocks(rows, sheets)
    q = _graph(rows)
    assert q["A-33488"] == 30 and q["A-33493"] == 30
    assert q["30002236"] == 300            # ten screws a box
    assert q["D-33498"] == 120             # four shelves a box
    assert q["E-33488"] == 120             # four ticket surrounds a box
    assert q["10100273"] == 2              # outside the box: untouched
    assert "00026207" not in q and "10100275" not in q and "10100277" not in q


def test_without_the_title_blocks_the_box_was_counted_once():
    rows, _ = _pack()
    q = _graph(rows)
    assert q["30002236"] == 10 and q["D-33498"] == 4 and q["E-33488"] == 1


def test_one_drawing_spelled_two_ways_is_one_part():
    rows = [_row("B.34495", "PLINTH PANEL", 2, "A.34494", "P.pdf#0",
                 finished_part_no="10100600", drawing_reference="B.34495"),
            _row("30000711", "M6 INSERT NUT", 4, "B-34495", "P.pdf#1")]
    parts = [{"part_number": p, "description": d, "quantity": 1}
             for p, d in (("A.34494", "PLINTH"), ("B-34495", "PLINTH PANEL"),
                          ("B.34495", "PLINTH PANEL"), ("30000711", "M6 INSERT NUT"))]
    q = {n.part_number: n.qty_per_unit
         for n in rc.build_part_graph(parts, bom_rows=rows)["nodes"]}
    assert "B.34495" not in q                # the sheet's own title block spells it B-34495
    assert q["B-34495"] == 2 and q["30000711"] == 8
