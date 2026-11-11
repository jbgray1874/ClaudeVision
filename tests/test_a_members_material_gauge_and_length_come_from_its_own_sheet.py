"""A member's material, gauge and length come from its own sheet, as printed (D-761).

0358141's 09:32 record: the detail sheets' MATERIALS field runs into its gauge in the PDF text,
"3mmSTAINLESSSTELL", "30x30x2mmM S", "3mmM S", and no material was read for M3 to M7. The
upright M4 prints "1383 O/A" on its own sheet ("1383 O A" in the text) and was cut at 111.85,
a slot's position. Both are read from the part's own sheet, the printed words kept.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from part_index import _title_block_gauge_and_material as read  # noqa: E402


def test_the_glued_materials_field_is_read():
    assert read("QTY BULKQTY M7 4 3mmM S SHEET")["material"] == "MILD STEEL"
    assert read("QTY BULKQTY M7 4 3mmM S SHEET")["thickness_mm"] == 3.0
    sec = read("M4 2 30x30x2mmM S SHEET DATE")
    assert sec["material"] == "MILD STEEL" and sec["section"] == [30.0, 30.0, 2.0]
    assert read("M3 2 3mmSTAINLESSSTELL SHEET")["material"] == "STAINLESS STEEL"
    assert read("2mm S/S")["material"] == "STAINLESS STEEL"
    assert read("2mm M/S")["material"] == "MILD STEEL"


def test_no_metal_two_readings_or_a_word_are_not_guessed():
    assert read("QTY 1 18mm MDF") is None
    assert read("3mmM SHEET") is None                      # "M" then "SHEET" is not M S
    assert read("3mmM S 2mmSTAINLESSSTEEL") is None        # two readings: no choice


def test_the_overall_length_on_the_parts_own_sheet_is_its_length():
    from document_builder import _apply_post_build_fixes, _empty_part_record
    rec = _empty_part_record(part_number="UPC0358141 M4")
    rec.update({"pages": [7], "page_roles": ["detail"], "materials": ["MILD STEEL"],
                "material_family": "metal", "description": "UPRIGHT"})
    text = ("UPRIGHT 30 x 30 x 2mm M/S UPRIGHTS 30x30x2mm SHS TUBE ISOMETRIC 1383 O A "
            "RIGHT VIEW 30 111.85 30.3 15")
    _apply_post_build_fixes([rec], {"pages": [{"page_number": 7, "page": 7, "text": text,
                                                "page_role": {"primary_role": "detail"}}],
                                     "document_analysis": {"bom_rows": []}})
    ss = rec.get("section_stock") or {}
    assert ss.get("length_mm") == 1383.0 and ss.get("length_source") == "detail_sheet_overall"
    assert ss.get("length_printed") == "1383 O/A"
