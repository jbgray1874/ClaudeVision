"""A sheet whose title block prints the drawing reference and the member in separate fields is
that member's sheet (D-758).

Reviewer, 9 Nov, from 0358141's saved PDF text: page 5 prints "UPC 0358141" and "M2" with
quantity 1 (Long Rub Strip), page 7 "UPC 0358141" and "M4" with quantity 2 (Upright), page 10
"UPC 0358141" and "M7" with quantity 4 (Base End Cap), as separate title-block fields. No field
holds the parts list's "UPC0358141 M2", so no spelling matched; the reference alone named the top
assembly. The identity is rebuilt from the same title block, corroborated by description and
quantity, never from numbers anywhere on the page; the fields and the page are kept, and a
reference that differs from the parts list's (M7 is listed as UPC0358131 M7) is said.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _row(pn, desc, qty):
    return {"part_number": pn, "description": desc, "quantity": qty, "source": "BOTH",
            "bom_sheet": "pack.pdf#1"}


def _sheet(number, title_block_text, reference, page_text="", role="detail"):
    return {"page_number": number, "page_role": {"primary_role": role},
            "pattern_summary": {"part_numbers": []}, "geometry_summary": {},
            "normalized_text": page_text or title_block_text,
            "region_text": {"title_block": title_block_text},
            "page_analysis": {"title_block": {"drawing_numbers": [reference]}}}


def _index(pages, rows):
    from document_builder import build_part_index
    return {p["part_number"]: p for p in
            build_part_index({"pages": pages, "document_analysis": {"bom_rows": rows}})}


_ROWS = [_row("UPC0358141", "PANTHEON KIDS BASE", 1),
         _row("UPC0358141 M2", "LONG RUB STRIP", 1),
         _row("UPC0358141 M3", "SHORT RUB STRIP", 2),
         _row("UPC0358141 M4", "UPRIGHT", 2),
         _row("UPC0358131 M7", "BASE END CAP", 4)]


def test_the_strip_sheet_binds_to_the_strip_not_the_assembly():
    parts = _index([_sheet(5, "DRAWING No UPC 0358141 PART M2 QTY 1 TITLE LONG RUB STRIP",
                           "UPC 0358141")], _ROWS)
    m2 = parts["UPC0358141 M2"]
    assert 5 in m2["pages"]
    assert 5 not in (parts.get("UPC0358141") or {}).get("pages", []), "not the top assembly's"
    ev = m2["title_block_identity"][0]
    assert ev["page"] == 5 and ev["member_field_printed"] == "M2"
    assert ev["source"] == "title_block_region" and ev["corroborated_by"]
    assert any("separate fields" in str(f) for f in m2.get("review_flags") or [])
    assert "UPC0358141M2" not in parts and "UPC 0358141" not in parts, "no record minted"


def test_another_layout_binds_the_same_way():
    rows = [_row("AB1234", "STAND", 1), _row("AB1234-07", "BRACKET", 2)]
    parts = _index([_sheet(3, "DWG NO AB1234 ITEM 07 DESCRIPTION BRACKET QTY 2 SCALE 1:5",
                           "AB1234")], rows)
    assert 3 in parts["AB1234-07"]["pages"]


def test_a_title_block_that_prints_several_members_binds_none_of_them():
    """A parts list read into the title-block region prints M2 and M3 together: no guess."""
    parts = _index([_sheet(2, "UPC 0358141 M1 FRAME 1 M2 LONG RUB STRIP 1 M3 SHORT RUB STRIP 2",
                           "UPC 0358141")], _ROWS)
    assert 2 not in parts["UPC0358141 M2"].get("pages", [])
    assert 2 not in parts["UPC0358141 M3"].get("pages", [])


def test_no_corroboration_no_binding():
    parts = _index([_sheet(6, "DRAWING No UPC 0358141 PART M2 QTY 9 TITLE MOUNTING PLATE",
                           "UPC 0358141")], _ROWS)
    assert 6 not in parts["UPC0358141 M2"].get("pages", [])


def test_the_member_field_must_be_in_the_title_block_not_elsewhere_on_the_page():
    parts = _index([_sheet(5, "DRAWING No UPC 0358141 TITLE LONG RUB STRIP QTY 1",
                           "UPC 0358141", page_text="SECTION M2 DETAIL LONG RUB STRIP")], _ROWS)
    assert 5 not in parts["UPC0358141 M2"].get("pages", [])


def test_the_cap_binds_to_its_listed_record_and_the_discrepancy_is_said():
    parts = _index([_sheet(10, "DRAWING No UPC 0358141 PART M7 QTY 4 TITLE BASE END CAP",
                           "UPC 0358141")], _ROWS)
    m7 = parts["UPC0358131 M7"]
    assert 10 in m7["pages"]
    assert m7["title_block_identity"][0]["reference_differs_from_list"] is True
    assert any("one digit away" in str(f) for f in m7.get("review_flags") or [])


def test_the_assemblys_own_sheet_with_no_member_field_is_unchanged():
    parts = _index([_sheet(1, "DRAWING No UPC 0358141 TITLE PANTHEON KIDS BASE QTY 1",
                           "UPC0358141", role="assembly")], _ROWS)
    assert 1 in parts["UPC0358141"]["pages"]
    assert not parts["UPC0358141"].get("title_block_identity")
