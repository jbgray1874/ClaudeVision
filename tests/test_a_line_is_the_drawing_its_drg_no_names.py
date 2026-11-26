"""A parts-list line is the drawing its DRG NO. column names (Hotel Chocolat, 26 Nov 2026).

ITEM NO | FINISHED PART NO. | DRG NO. | DESCRIPTION | QTY -- "1 | 10100530 | B.34109 | LOW
TABLE GA | 1". The bill reader glued the two code columns ("10100438B.33579"), no title
block read "B.33579" as a drawing number, and no DXF named "nc1-b33579" matched a part: the
cash desk's carcases, the Wall of Chocolate's 30 boxes and the plinth's panels were priced
as web-guessed purchases at x1 with no sheet, no size and no route.
"""
from pathlib import Path

from bom_pipeline import number_drawing_members
from drawing_job_merge import part_number_from_dxf_path
from drawing_reference import split_line_code
from extractor_patterns import _extract_drawing_number_candidates
from part_code_conventions import looks_like_a_drawing_number
from part_identity import normalize_part_code


def test_a_glued_stock_code_and_drawing_reference_are_split():
    assert split_line_code("10100438B.33579") == ("B.33579", "10100438", "B.33579")
    assert split_line_code("10100438 B.33579") == ("B.33579", "10100438", "B.33579")
    assert split_line_code("- A.34080") == ("A.34080", None, "A.34080")


def test_a_purchase_with_no_drawing_keeps_its_stock_code():
    assert split_line_code("30016217N/A") == ("30016217", "30016217", None)


def test_other_codes_are_left_exactly_as_they_were():
    for code in ("12517-01-01M", "BI-SCREW", "FIXING49", "10100530", "M6 WING NUT"):
        assert split_line_code(code) == (code, None, None)


def test_three_spellings_of_one_drawing_are_one_code_and_a_drawing():
    assert {normalize_part_code(c) for c in ("B.33579", "B-33579", "B33579")} == {"B33579"}
    assert looks_like_a_drawing_number("B.33579") and looks_like_a_drawing_number("A-33486")
    assert normalize_part_code("12517-01-01M") == "12517-01-01M"


def test_a_standard_or_a_size_is_not_a_drawing_reference():
    for token in ("M.12345", "M6", "A4", "R100", "B.3357", "BI-SCREW", "J13092", "RM06236"):
        assert not split_line_code(token)[2]
    assert not looks_like_a_drawing_number("J13092")    # an M&S catalogue item


def test_a_title_block_reads_the_dotted_drawing_number():
    assert "B.34082" in _extract_drawing_number_candidates("TITLE DRG No. DRAWN BY A1 1:12 GP B.34082 08-11")


def test_a_cut_file_named_by_its_drawing_reference_is_matched():
    assert part_number_from_dxf_path(Path("nc1-b34495.DXF")) == "B34495"
    assert part_number_from_dxf_path(Path("nc1-b33519_3 Person Cash Desk.DXF")) == "B33519"
    assert part_number_from_dxf_path(Path("nc1-a34065_Floor Planter 800mm.DXF")) == "A34065"
    assert normalize_part_code(part_number_from_dxf_path(Path("nc1-b33579.DXF"))) == \
        normalize_part_code("B.33579")
    assert part_number_from_dxf_path(Path("12517-05-01M MS T2.0mm RevB.DXF")) == "12517-05-01M"


def test_one_drawing_on_three_lines_is_three_members_not_one_part_of_six():
    rows = [{"part_number": "B.34495", "drawing_reference": "B.34495", "description": d,
             "bom_parent": "A.34494", "quantity": q}
            for d, q in (("TOP PANEL", 1), ("SIDE PANEL", 4), ("BASE PANEL", 1))]
    assert number_drawing_members(rows) == 3
    assert [(r["part_number"], r["quantity"]) for r in rows] == \
        [("B34495-1", 1), ("B34495-2", 4), ("B34495-3", 1)]
    assert all(r["drawing_member_of"] == "B.34495" for r in rows)
    assert all(looks_like_a_drawing_number(r["part_number"]) for r in rows)


def test_the_same_line_twice_is_left_to_add_up():
    rows = [{"part_number": "B.34495", "drawing_reference": "B.34495", "description": "SIDE PANEL",
             "bom_parent": "A.34494", "quantity": 2} for _ in range(2)]
    assert number_drawing_members(rows) == 0 and rows[0]["part_number"] == "B.34495"
