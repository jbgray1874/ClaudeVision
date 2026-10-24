"""A box is its panels, and a material its own sheet prints is kept (D-598j).

9287-10-GA, a clear acrylic cube on a solid-surface base, 24 Oct 2026, offline dry run:

1. The box's SIDE and TOP flats share the part number 9287-10-002 and the same 300 x 300 blank,
   so they were read as two issues of one panel and one was dropped. The box was costed as a
   single panel. Role words in the names make them pieces; a name says what a piece is, not
   how many, so each is costed once and the count is asked.
2. The base's own sheet prints "HANEX GAD-001", which the material book cannot name; the GA's
   "HANEX, ACRYLIC" resolved to acrylic and the base inherited it. The printed words are kept
   and asked about instead.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import drawing_job_merge as d                                         # noqa: E402
import extractor_patterns as ep                                       # noqa: E402
import file_scan                                                      # noqa: E402


def _flats(tmp_path, names, size=300):
    import ezdxf
    for n in names:
        doc = ezdxf.new()
        doc.modelspace().add_lwpolyline([(0, 0), (size, 0), (size, size), (0, size)], close=True)
        doc.saveas(tmp_path / n)
    return sorted(tmp_path.glob("*.DXF"))


def _merge(tmp_path, names, extra_parts=()):
    parts = [{"part_number": "7777-10-002", "description": "BOX", "quantity": 1,
              "normalized_finish": "POLISHED EDGES", "surface_finishes": ["POLISHED EDGES"]},
             *extra_parts]
    out = d.augment_summary_with_dxf({"manufacturing_writeup": {"parts": parts}, "pages": []},
                                     _flats(tmp_path, names), reestimate=False)
    return {p["part_number"]: p for p in out["manufacturing_writeup"]["parts"]}, \
        out.get("dxf_augmentation") or {}


def test_a_side_and_a_top_of_one_size_are_two_pieces_not_two_revisions(tmp_path):
    parts, report = _merge(tmp_path, ["7777-10-002 SIDE_5mm ACR_REV[A].DXF",
                                      "7777-10-002 TOP_5mm ACR_REV[A].DXF"])
    box = parts["7777-10-002"]
    assert box["is_assembly_parent"] is True
    assert set(box["assembly_children"]) == {"7777-10-002-SIDE-01", "7777-10-002-TOP-01"}
    for code in box["assembly_children"]:
        assert parts[code]["dxf_minted_piece_of"] == "7777-10-002"
        assert parts[code]["normalized_finish"] == "POLISHED EDGES", "the box's sheet states it"
    q = [x for x in box["manufacturing_questions"] if x["subject"] == "dxf_piece_count"]
    assert q and "how many" in q[0]["issue"].lower(), "a name is not a count: it is asked"
    assert any(a["reason"] == "role_pieces_promoted" for a in report["ambiguous_dxf"])


def test_two_issues_of_one_panel_are_still_one_panel(tmp_path):
    parts, report = _merge(tmp_path, ["7777-10-002 TOP_5mm ACR_REV[A].DXF",
                                      "7777-10-002 TOP_5mm ACR_REV[B].DXF"])
    assert not parts["7777-10-002"].get("assembly_children")
    assert any(a["reason"] == "multiple_flats_one_part_same_blank_deduped"
               for a in report["ambiguous_dxf"])


def test_children_in_scope_keep_their_own_binding(tmp_path):
    kid = {"part_number": "7777-10-002-01", "description": "SIDE PANEL", "quantity": 4}
    parts, report = _merge(tmp_path, ["7777-10-002 SIDE_5mm ACR_REV[A].DXF",
                                      "7777-10-002 TOP_5mm ACR_REV[A].DXF"], [kid])
    assert not any(a["reason"] == "role_pieces_promoted" for a in report["ambiguous_dxf"])


def test_a_material_the_book_cannot_name_is_kept_as_printed():
    tb = ep.extract_title_block_fields(
        "MATERIAL: HANEX GAD-001 DO NOT SCALE - IF IN DOUBT ASK!\nDWG NO. 7777-10-005")
    assert tb["materials"] == []
    assert tb["material_stated_unresolved"] == "HANEX GAD-001"
    merged = ep.merge_title_block_fields(tb, {"materials": []})
    assert merged["material_stated_unresolved"] == "HANEX GAD-001"
    resolved = ep.extract_title_block_fields("MATERIAL: ACRYLIC\nDWG NO. 7777-10-002")
    assert resolved["material_stated_unresolved"] is None


def _own_sheet(printed):
    pages = [{"page_number": 2, "page_analysis": {"title_block": {
        "drawing_numbers": ["7777-10-005"], "materials": [],
        "material_stated_unresolved": printed}}}]
    doc = {"primary_fields": {"normalized_material": "ACRYLIC"},
           "title_block": {"materials": ["ACRYLIC"],
                           "normalized": {"primary_material": "ACRYLIC"}}}
    base = {"part_number": "7777-10-005", "description": "BASE"}
    other = {"part_number": "7777-10-009", "description": "SPACER"}
    file_scan._inherit_document_material_to_parts([base, other], doc, pages)
    return base, other


def test_a_part_whose_own_sheet_prints_a_material_does_not_inherit_another():
    # D-598m: the printed words go through the same vocabulary as a DXF name, so a brand
    # the vocabulary knows names its family; the exact grade and its page are kept.
    base, other = _own_sheet("HANEX GAD-001")
    assert base["normalized_material"] == "SOLID SURFACE"
    assert base["material_stated"] == "HANEX GAD-001"
    assert base["owned_material_evidence"]["page"] == 2
    assert file_scan._source_of(base, "normalized_material") == "drawing_deterministic"
    assert other["normalized_material"] == "ACRYLIC", "a part with no sheet still inherits"


def test_a_material_no_vocabulary_names_is_carried_as_printed_and_asked():
    base, other = _own_sheet("RESIN-X9 GRADE 4")
    assert base["normalized_material"] == "RESIN-X9 GRADE 4", "never another sheet's acrylic"
    assert any(f.startswith("MATERIAL AS PRINTED") for f in base["review_flags"])
    assert other["normalized_material"] == "ACRYLIC"
