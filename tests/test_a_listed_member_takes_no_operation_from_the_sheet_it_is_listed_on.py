"""A part only listed on another part's sheet takes no operation from that sheet's notes (D-756).

0358141 at 15:47: the rub strips M2 and M3 had no sheet of their own bound, so part_index bound
them to page 2, the frame M1's sheet, which prints its parts list. Page 2's notes say "WELD AND
DRESS, TAP M4, FOLD". Read as the strips' own, they charged Weld (CO2) and Dress Welds on two
screw-fixed strips, Estimate rows 157 and 158, beside the frame's own weld. Reviewer: "Remove
strip weld/dress charges where the construction only establishes screw fixing."
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

_FRAME_SHEET = ("UPC0358141 M1 FRAME ITEM PART NUMBER DESCRIPTION QTY 1 UPC0358141 M2 LONG RUB "
                "STRIP 1 2 UPC0358141 M3 SHORT RUB STRIP 2 NOTES: WELD AND DRESS, TAP M4, FOLD")
_STRIP_SHEET = "UPC0358141 M2 LONG RUB STRIP 3MM STAINLESS STEEL FOLD UP 90 DEG 4 X M4 TAP"


def _post_build(part, pages, bound_to_list=None):
    from document_builder import _apply_post_build_fixes, _empty_part_record
    rec = _empty_part_record(part_number=part["part_number"])
    rec.update({"pages": [p for p, _t in pages], "page_roles": ["detail"] * len(pages),
                "materials": ["STAINLESS STEEL"], "material_family": "metal"})
    if bound_to_list:
        rec["bound_to_parts_list_page"] = bound_to_list
    rec.update(part)
    summary = {"pages": [{"page_number": p, "page": p, "text": t,
                          "page_role": {"primary_role": "detail"}} for p, t in pages],
               "document_analysis": {"bom_rows": []}}
    _apply_post_build_fixes([rec], summary)
    return rec


def test_a_strip_bound_to_the_frames_list_takes_no_weld_from_its_notes():
    got = _post_build({"part_number": "UPC0358141 M2", "description": "LONG RUB STRIP"},
                      [(2, _FRAME_SHEET)], bound_to_list=2)
    ops = set(got.get("textual_operations") or [])
    assert not ops & {"welding", "dress_welds", "tapping", "folding"}, ops
    assert "welding" not in (got.get("operation_sources") or {})
    assert any("parts list this part is only listed on" in str(f)
               for f in got.get("review_flags") or [])


def test_the_same_notes_on_the_parts_own_sheet_still_give_it_the_work():
    """The rule is about whose sheet it is, not about the words: on its own sheet the same
    note is the part's, and a part never bound to a list is not touched."""
    own = _post_build({"part_number": "UPC0358141 M1", "description": "FRAME"},
                      [(2, _FRAME_SHEET)])
    assert "welding" in set(own.get("textual_operations") or [])


def test_a_listed_part_with_its_own_sheet_reads_that_sheet_and_not_the_list():
    got = _post_build({"part_number": "UPC0358141 M2", "description": "LONG RUB STRIP"},
                      [(2, _FRAME_SHEET), (6, _STRIP_SHEET)], bound_to_list=2)
    ops = set(got.get("textual_operations") or [])
    assert "welding" not in ops and "dress_welds" not in ops, ops
    assert not any("parts list this part is only listed on" in str(f)
                   for f in got.get("review_flags") or []), "its own sheet answered"
