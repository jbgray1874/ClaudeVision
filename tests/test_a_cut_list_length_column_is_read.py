"""A cut list's LENGTH column is read, and its pieces are the part's stock (D-429).

8188-29-001, the common frame's goalpost: its sheet prints "ITEM QTY DESCRIPTION LENGTH /
1 2 25.40 x 25.40 x 1.22mm TUBE 300 / 2 1 25.40 x 25.40 x 1.22mm TUBE 1272". With no column
family for LENGTH the lengths were dropped, the two rows only confirmed the profile, and the
part's length came from the first "TUBE 300" in the page text: the live 14:50 book priced the
goalpost as one 300 mm lasered tube at £1.58.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import bom_pipeline as bp                                             # noqa: E402
import bom_table_extractor as bte                                     # noqa: E402

_TABLE = [["ITEM", "QTY", "DESCRIPTION", "LENGTH"],
          ["1", "2", "25.40 x 25.40 x 1.22mm TUBE", "300"],
          ["2", "1", "25.40 x 25.40 x 1.22mm TUBE", "1272"]]


def test_the_grid_reader_keeps_the_length_column():
    rows = bte.bom_rows_from_tables([_TABLE])
    assert [(r["quantity"], r.get("length_mm")) for r in rows] == [(2, 300.0), (1, 1272.0)]


def test_a_length_cell_is_one_figure_or_nothing():
    assert bte.length_cell_mm("300") == 300.0
    assert bte.length_cell_mm("1272 mm") == 1272.0
    assert bte.length_cell_mm("") is None
    assert bte.length_cell_mm("SEE DWG") is None
    assert bte.length_cell_mm("0") is None


def test_a_table_without_a_length_column_is_unchanged():
    rows = bte.bom_rows_from_tables([[["ITEM", "DWG NO.", "DESCRIPTION", "QTY"],
                                      ["1", "8188-29-002", "COMMON HEADER BASE", "1"]]])
    assert rows and "length_mm" not in rows[0]


def _goalpost():
    return {"part_number": "8188-29-001", "description": "COMMON HEADER GOALPOST",
            "normalized_material": "MILD STEEL", "stated_weight_kg": 1.663,
            "section_stock": {"a": 25.4, "b": 25.4, "t": 1.22, "length_mm": 300.0,
                              "profile_form": "SHS", "detection_path": "canonical_profile"}}


def test_the_pieces_from_the_length_column_are_the_parts_cut_list():
    part = _goalpost()
    rows = [dict(r, part_number="", bom_parent="8188-29-001", bom_parent_known=True)
            for r in bte.bom_rows_from_tables([_TABLE])]
    assert bp.apply_stated_cut_list_to_parts([part], rows) == 1
    ss = part["section_stock"]
    assert sorted(ss["cut_lengths_mm"]) == [300.0, 300.0, 1272.0]
    assert ss["length_mm"] == 1272.0 and ss["source"] == "drawing_deterministic"
    # 1,872 mm of 25.4 x 25.4 x 1.22 against the sheet's 1.663 kg: inside the tolerance
    assert not ss.get("length_indicative"), ss.get("cut_list_mass_check")


def test_a_length_in_the_description_still_wins_over_the_column():
    """12173-03-04M prints the length inside the description cell; that reading stands."""
    part = _goalpost()
    rows = [{"part_number": "", "description": "25.40 x 25.40 x 1.22mm TUBE 500",
             "quantity": 1, "length_mm": 999.0, "bom_parent": "8188-29-001",
             "bom_parent_known": True}]
    bp.apply_stated_cut_list_to_parts([part], rows)
    assert part["section_stock"]["cut_lengths_mm"] == [500.0]
