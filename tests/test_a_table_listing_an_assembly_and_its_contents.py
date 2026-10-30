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
