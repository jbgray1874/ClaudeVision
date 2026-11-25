"""One number on two detail sheets, and a listed twin with no sheet: price it, say why.

A drawing office copies a sheet and does not renumber it. Estimating prices on judgement
every day; the engine takes the same call, prices the twin, and states it on the line.
Ordinary repeats of a part number across a pack are untouched.
"""
from invariants import check_part_evidence_safety
from part_evidence_safety import prepare


def _page(n, number, body):
    return {"page_number": n, "pdfplumber_text": body,
            "page_analysis": {"title_block": {"drawing_numbers": [number]}}}


def _pack():
    pages = [_page(5, "100-05-GA", "ITEM NO PART NUMBER 100-05-07A 3"),
             _page(7, "100-05-07A", "343 150 R5 FLAT"),
             _page(9, "100-09-GA", "ITEM NO PART NUMBER 100-09-07A 5"),
             _page(11, "100-05-07A", "270 50 R5 FLAT")]
    parts = [{"part_number": "100-05-07A", "description": "Acrylic bracket", "quantity": 3,
              "pages": [7, 11], "normalized_material": "ACRYLIC", "normalized_thickness_mm": 3.0},
             {"part_number": "100-09-07A", "description": "Acrylic bracket", "quantity": 5,
              "pages": [9], "normalized_geometry": {"bbox_mm": [270.0, 50.0, 40.0]}}]
    return {"pages": pages, "manufacturing_writeup": {"parts": parts}}


def test_the_twin_takes_the_sheet_after_its_listing_and_is_priced_on_it():
    s = _pack(); prepare(s)
    a, b = s["manufacturing_writeup"]["parts"]
    assert b["bound_detail_sheet"] == {"page": 11, "twin_of": "100-05-07A"}
    assert (b["normalized_material"], b["normalized_thickness_mm"]) == ("ACRYLIC", 3.0)
    assert (b["blank_length_mm"], b["blank_width_mm"]) == (270.0, 50.0)
    assert (a["part_number"], a["quantity"], b["part_number"], b["quantity"]) == \
        ("100-05-07A", 3, "100-09-07A", 5)
    assert "Page 11" in b["evidence_safety_issues"]["twin_detail_sheet"]["message"]


def test_the_judgement_is_a_stated_warning_not_a_block():
    s = _pack(); prepare(s)
    found = check_part_evidence_safety(s)
    assert found and {f["severity"] for f in found} == {"warning"}


def test_one_part_on_two_sheets_with_no_unbound_twin_is_left_alone():
    s = _pack()
    s["manufacturing_writeup"]["parts"].pop()          # no listed part lacks a sheet
    prepare(s)
    assert not s["manufacturing_writeup"]["parts"][0].get("evidence_safety_issues")
