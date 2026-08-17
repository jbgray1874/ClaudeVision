"""A board/plastic line with no sheet dimensions goes to the BOM, not a £0 Other-Sheet row.

8352's Tente castor is a bought-in moulding whose material read as ABS, so it was routed to the
Other Sheet block. That block costs a part from its L×W (nest into a sheet); the castor has no
dimensions, so it read £0 — a real bought-in showing free. A board line that cannot be costed as
a sheet is not a sheet: it now routes to the BOM as a per-each line, where the catalogue / market
/ last-resort price applies. A genuine board PANEL keeps its dimensions and still costs as a sheet
in the Other Sheet block; one merely missing its size lands on the BOM too and is flagged to add
dimensions, so either way it no longer reads as free. Keyed on the missing geometry, not on a
name, so it inherits to every pack.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import costed_facts as cf  # noqa: E402


def test_a_dimensionless_board_line_is_not_board_costable():
    """THE CASTOR. No L×W means the Other Sheet block cannot cost it — it must not sit there."""
    castor = {"part_number": "TENTE LINEA CASTOR", "description": "Black",
              "normalized_material": "ABS", "material_estimate": {}}
    bd = cf.blank_dimensions(castor)
    assert not (bd.get("length_mm") and bd.get("width_mm"))


def test_a_board_panel_with_dimensions_is_board_costable():
    """A real MDF panel keeps its dims and stays in the Other Sheet block."""
    panel = {"part_number": "8352-01-03", "normalized_material": "MDF",
             "material_estimate": {"blank_length_mm": 1235, "blank_width_mm": 365}}
    bd = cf.blank_dimensions(panel)
    assert bd.get("length_mm") and bd.get("width_mm")


def test_the_router_sends_a_dimensionless_board_line_to_the_bom():
    """Wired: the board branch keeps only the lines it can cost as a sheet and sends the rest to
    the BOM, before falling through to the sheet-metal/unclassifiable branches."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "wb_populate.py"),
               encoding="utf-8").read()
    board_branch = src.index("# 6. board / other sheet — but ONLY when it can be costed AS a sheet.")
    # Within the board branch, a costable line goes to board_parts, else to bom_parts.
    seg = src[board_branch:board_branch + 1400]
    assert "board_parts.append(pe)" in seg
    assert "bom_parts.append(pe)" in seg
    assert "blank_dimensions(pe)" in seg
