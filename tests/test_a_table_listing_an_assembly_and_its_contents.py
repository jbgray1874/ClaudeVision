"""A parts table that lists a sub-assembly AND its contents counts the contents once.

12312-01-GA: the GA table lists the LIGHTING ASM and, beside it, the LED driver, LED tape,
power cord and Y-splitter that the lighting assembly holds through 08X. The roll-up summed both
routes and costed two of each — £43.39 a unit the drawing never asked for.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import route_compiler as rc                                       # noqa: E402

GA, LA, DIFF = "12312-01-GA", "12312-01-LIGHTING", "12312-01-08X"


def _graph(ga_driver_qty=1):
    parts = [{"part_number": GA, "is_assembly_parent": True},
             {"part_number": LA, "is_assembly_parent": True},
             {"part_number": DIFF, "description": "SILICONE LED DIFFUSER"},
             {"part_number": "BI-DRIVER", "description": "LED POWER DRIVER", "page_roles": ["bought_in"]},
             {"part_number": "BI-GROMMET", "description": "RUBBER GROMMET", "page_roles": ["bought_in"]}]
    rows = [{"part_number": LA, "quantity": 1, "bom_parent": GA, "bom_sheet": "p1"},
            {"part_number": "BI-DRIVER", "quantity": ga_driver_qty, "bom_parent": GA, "bom_sheet": "p1"},
            {"part_number": "BI-GROMMET", "quantity": 3, "bom_parent": GA, "bom_sheet": "p1"},
            {"part_number": DIFF, "quantity": 1, "bom_parent": LA, "bom_sheet": "p3"},
            {"part_number": "BI-DRIVER", "quantity": 1, "bom_parent": DIFF, "bom_sheet": "p14"}]
    g = rc.build_part_graph(parts, {}, bom_rows=rows)
    return {n.part_number: n for n in g["nodes"]}


def test_the_contents_of_a_listed_assembly_are_counted_once():
    nodes = _graph()
    assert nodes["BI-DRIVER"].qty_per_unit == 1, nodes["BI-DRIVER"].qty_trail
    assert "counted once" in nodes["BI-DRIVER"].qty_note
    assert nodes["BI-GROMMET"].qty_per_unit == 3, "a part only the table lists is untouched"


def test_a_different_count_is_a_genuine_extra_and_stays():
    nodes = _graph(ga_driver_qty=2)
    assert nodes["BI-DRIVER"].qty_per_unit == 3


def test_edges_from_different_reads_are_still_counted_once():
    """14:57 rerun: the GA's edge to the lighting assembly and its edge to the driver came
    from different reads, so no single table held both, and the driver stayed at 2."""
    parts = [{"part_number": GA, "is_assembly_parent": True},
             {"part_number": LA, "is_assembly_parent": True},
             {"part_number": DIFF, "description": "SILICONE LED DIFFUSER"},
             {"part_number": "BI-DRIVER", "description": "LED POWER DRIVER", "page_roles": ["bought_in"]}]
    ext = {"assemblies": [{"part_number": GA, "children": [{"part_number": LA, "qty": 1}]}]}
    rows = [{"part_number": "BI-DRIVER", "quantity": 1, "bom_parent": GA},
            {"part_number": DIFF, "quantity": 1, "bom_parent": LA, "bom_sheet": "p3"},
            {"part_number": "BI-DRIVER", "quantity": 1, "bom_parent": DIFF, "bom_sheet": "p14"}]
    g = rc.build_part_graph(parts, ext, bom_rows=rows)
    nodes = {n.part_number: n for n in g["nodes"]}
    assert nodes["BI-DRIVER"].qty_per_unit == 1, nodes["BI-DRIVER"].qty_trail


# ── A TABLE'S TOTAL IS NOT A PER-PARENT COUNT (12773-01-GA, 14 Nov 2026) ───────────────────
# Each sheet lists its parts flat, with totals. The shelf's sheet says 8 plates in four
# shelves, each body's sheet says 4 in its two shelves, and the model counts 2 in each shelf.
# The plates were reached by four paths, 16 + 4 + 16 + 4, and 40 were charged against the 8
# in the product. The codes here are this test's own.
TOP, LOWER, UPPER, SHELF, PLATE = "T-01-GA", "T-02-GA", "T-03-101", "T-02-101", "T-02-103"


def _flat_tables(plate_counts_per_parent=True, body_row=4, model_total=8):
    plate = {"part_number": PLATE, "description": "LOCK PLATE"}
    if plate_counts_per_parent:
        plate.update(quantity=2, quantity_source="solidworks_api",
                     quantity_total_per_unit=model_total,
                     quantity_total_per_unit_source="solidworks_api")
    parts = [{"part_number": TOP, "is_assembly_parent": True},
             {"part_number": LOWER, "is_assembly_parent": True},
             {"part_number": UPPER, "is_assembly_parent": True},
             {"part_number": SHELF, "is_assembly_parent": True}, plate]
    rows = [{"part_number": LOWER, "quantity": 1, "bom_parent": TOP, "bom_sheet": "p1"},
            {"part_number": UPPER, "quantity": 1, "bom_parent": TOP, "bom_sheet": "p1"},
            {"part_number": SHELF, "quantity": 2, "bom_parent": LOWER, "bom_sheet": "p3"},
            {"part_number": PLATE, "quantity": body_row, "bom_parent": LOWER, "bom_sheet": "p3"},
            {"part_number": SHELF, "quantity": 2, "bom_parent": UPPER, "bom_sheet": "p5"},
            {"part_number": PLATE, "quantity": body_row, "bom_parent": UPPER, "bom_sheet": "p5"},
            {"part_number": PLATE, "quantity": 8, "bom_parent": SHELF, "bom_sheet": "p6"}]
    g = rc.build_part_graph(parts, {}, bom_rows=rows)
    return {n.part_number: n for n in g["nodes"]}


def test_a_part_listed_flat_on_every_sheet_is_counted_through_its_own_assembly_once():
    nodes = _flat_tables()
    assert nodes[PLATE].qty_per_unit == 8, nodes[PLATE].qty_trail
    assert nodes[SHELF].qty_per_unit == 4
    assert "counted once" in nodes[PLATE].qty_note


def test_a_body_row_that_is_more_than_its_shelves_bring_is_a_genuine_extra_and_stays():
    """Contrast: each body's table says 6 where its two shelves bring 4. That is not the
    shelves' contents listed again, so the row is kept and the count rises."""
    nodes = _flat_tables(body_row=6)
    assert nodes[PLATE].qty_per_unit > 8, nodes[PLATE].qty_trail


def test_with_no_reader_that_counts_per_parent_the_tables_are_costed_as_before():
    """Contrast: nothing counts the plate per shelf, so the table's figures stand and the
    line is left for a person, as it was."""
    nodes = _flat_tables(plate_counts_per_parent=False)
    assert nodes[PLATE].qty_per_unit == 40, nodes[PLATE].qty_trail
