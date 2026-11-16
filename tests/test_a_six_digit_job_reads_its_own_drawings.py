"""A six-digit job number reads its own drawings, its own table and its own finishes (D-547/D-548/D-549).

401918-01-GA, the 1200 rail, 20 Oct 2026 book: every flat DXF was refused as "another assembly's",
the base frames were retagged as purchases, every sheet's drawing number came back "6063 -
ALUMINIUM", the GA's material read "STEEL REV", the frame's tube cut list was a question costed at
nothing, the brushed stainless rub strip went through the powder booth, and the coat's colour code
became a phantom line. Each cause is general; each is pinned here on the shapes that sheet prints.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# The specification block of the GA as pdfplumber interleaves it with the revision table.
GA_SPEC = (
    "MAX LOADING:\nWEIGHT: 21.6kg\nREVISION TABLE\nSPECIFICATION:\n"
    "MATERIAL: STEEL REV DWG NO DESCRIPTION DATE BY\n"
    "COPY OF EXISING DESIGN + MINOR UPDATES -\n"
    "FINISH: POWDER COATED A ALL 09/01/2026 IB\nNEW COLOUR\n"
    "COLOUR: CHALKY WHITE POWDER 248\nB - FIXINGS CHANGED TO STAINLESS 05/02/2026 IB\n"
    "GENERAL TOLERANCES: FINISH SPECIFICATIONS: THIS DRAWING IS THE PROPERTY OF")

# An assembly sheet's title block: headings on one line, values on another, after its parts list.
ASSEMBLY_SHEET = (
    "ITEM DWG NO. DESCRIPTION QTY\n1 401918-01-03M FRAME - WELDMENT 1\n"
    "2 401918-01-02M FRAME - END CAP 2\n"
    "MATERIAL: MILD STEEL\nFINISH: POWDER COATED\nCOLOUR: CHALKY WHITE POWDER 248\n"
    "• 6063 - ALUMINIUM FOR EXTRUSION\n© ALL DIMENSIONS ARE IN mm. DRAWING No SCALE REV\n"
    "DO NOT SCALE FROM DRAWING. 401918-01-201 1:12 B\n")


# ── the job number is four to six digits ──────────────────────────────────────

def test_a_flat_dxf_named_for_a_six_digit_job_is_that_part():
    from drawing_job_merge import job_prefix_from_path, part_number_from_dxf_path
    assert part_number_from_dxf_path(Path("401918-01-01M_3mm SS_revB.DXF")) == "401918-01-01M"
    assert part_number_from_dxf_path(Path("401918-01-08M_3mm_MS_revB.dxf")) == "401918-01-08M"
    assert job_prefix_from_path(Path("401918-01-05M_2mm_MS_revB.dxf")) == "401918-01"


def test_the_shorter_numbers_still_read_as_they_did():
    from drawing_job_merge import part_number_from_dxf_path
    assert part_number_from_dxf_path(Path("12242-01-01M_MS_1_5mm_revD.DXF")) == "12242-01-01M"
    assert part_number_from_dxf_path(Path("9376-01-001_MS_1_5mm_revL.DXF")) == "9376-01-001"
    assert part_number_from_dxf_path(Path("10975-02-A01_2mm.DXF")) == "10975-02-A01"


def test_a_code_is_never_read_from_the_middle_of_a_longer_number():
    """The 4-5 digit pattern found '01918-01-01M' inside '401918-01-01M' — a code that matched no
    part, so the flat was refused as another assembly's."""
    from drawing_job_merge import part_number_from_dxf_path
    assert part_number_from_dxf_path(Path("1401918-01-01M_2mm.DXF")) in (None, "1401918-01-01M")


def test_a_six_digit_assembly_is_not_retagged_as_a_purchase():
    src = (Path(__file__).resolve().parents[1] / "src" / "document_builder.py").read_text(
        encoding="utf-8")
    assert '_re_bi.match(r"^\\d{3,6}-", _pn_bi)' in src


# ── the revision table is struck however its header is spelt ──────────────────

def test_a_dwg_no_revision_table_interleaved_with_the_fields_leaves_them_clean():
    from extractor_patterns import extract_title_block_fields
    tb = extract_title_block_fields(GA_SPEC)
    assert tb["materials"] == ["STEEL"]
    assert any("POWDER" in f for f in tb["surface_finishes"])
    assert not any("09/01" in f or "ALL" in f.split() for f in tb["surface_finishes"])
    assert tb["colours"] == ["CHALKY WHITE POWDER 248"]
    assert [r["rev"] for r in tb["revision_table"]] == ["A", "B"]


def test_a_row_that_names_no_number_supersedes_nothing():
    from extractor_patterns import parse_revision_table
    t = parse_revision_table(GA_SPEC)
    assert t["superseded"] == {}
    assert t["current_revision"] == "B"
    assert t["current_number"] == ""


def test_the_drawing_number_is_the_title_blocks_not_the_first_parts_list_code():
    from extractor_patterns import extract_title_block_fields
    assert extract_title_block_fields(ASSEMBLY_SHEET)["drawing_numbers"][0] == "401918-01-201"


# ── a cut list of several sections is several members ─────────────────────────

def _rows():
    return [
        {"part_number": "", "description": "15.00 x 30.00 x 2.00mm TUBE 1164", "quantity": 1,
         "bom_parent": "401918-01-03M"},
        {"part_number": "", "description": "30.00 x 15.00 x 2.00mm TUBE 1294", "quantity": 1,
         "bom_parent": "401918-01-03M"},
        {"part_number": "", "description": "30.00 x 30.00 x 2.00mm TUBE 1395", "quantity": 2,
         "bom_parent": "401918-01-03M"},
        {"part_number": "50.00", "description": "x 20.00 x 2.00mm TUBE 703", "quantity": 1,
         "bom_parent": "401918-01-07M"},
        {"part_number": "50.00", "description": "x 20.00 x 2.00mm TUBE 154", "quantity": 2,
         "bom_parent": "401918-01-07M"},
    ]


def test_a_size_read_as_a_code_is_rejoined():
    from part_identity import rejoin_dimension_split_rows
    rows = _rows()
    assert rejoin_dimension_split_rows(rows) == 2
    assert rows[3]["part_number"] == "" and rows[3]["description"].startswith("50.00 x 20.00")


def test_several_sections_become_members_and_one_section_stays_on_its_part():
    from part_identity import (mint_cut_list_member_identities, rejoin_dimension_split_rows)
    rows = _rows()
    rejoin_dimension_split_rows(rows)
    assert mint_cut_list_member_identities(rows) == 3
    assert [r["part_number"] for r in rows[:3]] == [
        "401918-01-03M-CL1", "401918-01-03M-CL2", "401918-01-03M-CL3"]
    assert all(r["identity_source"] == "cut_list_member" for r in rows[:3])
    # 07M's pieces are one section (50 x 20 x 2): D-383 reads them on 07M itself.
    assert rows[3]["part_number"] == "" and rows[4]["part_number"] == ""


def test_a_member_is_a_made_tube_part_cut_by_length_under_its_weldment():
    from document_builder import cut_list_member_records
    from part_identity import mint_cut_list_member_identities
    rows = _rows()[:3]
    mint_cut_list_member_identities(rows)
    parent = {"part_number": "401918-01-03M", "surface_finishes": ["WELDED"], "pages": [7],
              "normalized_material": "MILD STEEL"}
    recs = cut_list_member_records(rows, [parent])
    assert [r["part_number"] for r in recs] == [
        "401918-01-03M-CL1", "401918-01-03M-CL2", "401918-01-03M-CL3"]
    r3 = recs[2]
    assert r3["is_bought_in"] is False and r3["page_roles"] == ["section"]
    ss = r3["section_stock"]
    assert (ss["a"], ss["b"], ss["t"], ss["length_mm"]) == (30.0, 30.0, 2.0, 1395.0)
    assert r3["textual_operations"] == ["saw"] and r3["quantity"] == 2
    assert r3["cut_list_member_of"] == "401918-01-03M"
    # Its finish is its weldment's — WELDED, coated with the assembly — not the document's.
    assert r3["surface_finishes"] == ["WELDED"] and not r3.get("finish_inherited_from")


def test_the_bought_in_minter_never_takes_a_member():
    from document_builder import bought_in_rows_without_records
    from part_identity import mint_cut_list_member_identities
    rows = _rows()[:3]
    mint_cut_list_member_identities(rows)
    assert bought_in_rows_without_records(rows, []) == []


# ── a brushed finish is not coated; a colour is not a purchase ────────────────

def test_a_brushed_part_is_not_the_documents_to_coat():
    from finish_rules import finish_contradiction
    assert finish_contradiction("powder_coating", "BRUSHED")
    assert finish_contradiction("powder_coating", "POWDER COATED") is None


def test_a_coat_colour_code_in_the_colour_field_is_not_minted():
    src = (Path(__file__).resolve().parents[1] / "src" / "estimator.py").read_text(
        encoding="utf-8")
    at = src.index("A COLOUR IS NOT A PURCHASE (D-547)")
    assert 'prefix in ("POWDER", "PAINT") and code not in _qty_by_code' in src[at:at + 1200]


def test_an_assemblys_material_is_not_reported_as_unpriced():
    src = (Path(__file__).resolve().parents[1] / "src" / "invariants.py").read_text(
        encoding="utf-8")
    at = src.index("AN ASSEMBLY'S MATERIAL IS ITS MEMBERS' (D-547)")
    assert "weldment_parent_material_in_children" in src[at:at + 900]


def test_a_weldments_pieces_are_its_assemblys_coated_area():
    from estimator import stamp_members_coated_area
    asm = {"part_number": "401918-01-201", "quantity": 1, "inferred_operations": ["powder_coating"],
           "assembly_children": ["401918-01-03M"], "normalized_material": "MILD STEEL"}
    weldment = {"part_number": "401918-01-03M", "quantity": 1, "normalized_material": "MILD STEEL",
                "surface_finishes": ["WELDED"]}
    pieces = [
        {"part_number": f"401918-01-03M-CL{i}", "quantity": q, "cut_list_member_of": "401918-01-03M",
         "normalized_material": "MILD STEEL", "surface_finishes": ["WELDED"],
         "section_stock": {"a": a, "b": b, "t": 2.0, "length_mm": L, "cut_lengths_mm": [L],
                           "profile_form": "RHS"}}
        for i, (a, b, L, q) in enumerate([(15, 30, 1164, 1), (15, 30, 1294, 1), (30, 30, 1395, 2)], 1)]
    assert stamp_members_coated_area([asm, weldment, *pieces]) == 1
    # 0.09 x 1.164 + 0.09 x 1.294 + 2 x 0.12 x 1.395, about 0.56 m2 of tube
    assert 0.5 < asm["_powder_members_coated_m2"] < 0.62
