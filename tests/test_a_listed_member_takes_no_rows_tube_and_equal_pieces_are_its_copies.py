"""A member listed on another part's parts list takes no section from that list, and N equal
pieces on a row of N are the row's N parts (D-751).

8 Nov 2026, 0358141 at 14:31: the end caps M5, M6 and M7 have no sheet of their own and were
bound to page 3, the rail's parts list, which prints the rail's "15x30x2mm MS TOP TUBE". Each
became 15 x 30 x 2 tube at 1,400 mm, where the drawing makes them 3 mm plate caps. And the
upright M4, listed 2 off, came back from the read as cut_lengths_mm [1383, 1383]: one piece for
each of the two. The length reader summed them to 2,766 mm and the quantity doubled that, so
four lengths were bought for two uprights.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import estimator as e                                                 # noqa: E402
from source_connectors import llm_full_job as lj                      # noqa: E402

_RAIL_LIST = ("ITEM PART NUMBER DESCRIPTION QTY 1 UPC0358141 M4 UPRIGHT 2 "
              "2 UPC0358141 M5 ENDCAP 2 3 UPC0358141 M6 O A RAIL END 2 "
              "15x30x2mm MS TOP TUBE 1400")


def _post_build(part, page_text=_RAIL_LIST, role="assembly", bound_to_list=3):
    from document_builder import _apply_post_build_fixes, _empty_part_record
    rec = _empty_part_record(part_number=part["part_number"])
    rec.update({"pages": [3], "page_roles": [role], "materials": ["MILD STEEL"],
                "material_family": "metal"})
    if bound_to_list:
        rec["bound_to_parts_list_page"] = bound_to_list
    rec.update(part)
    summary = {"pages": [{"page_number": 3, "page": 3, "text": page_text,
                          "page_role": {"primary_role": role}}],
               "document_analysis": {"bom_rows": []}}
    _apply_post_build_fixes([rec], summary)
    return rec


# ── a parts list speaks for the row that prints the profile ─────────────────────────────

def test_an_end_cap_only_listed_on_the_rails_list_takes_no_tube():
    got = _post_build({"part_number": "UPC0358141 M5", "description": "ENDCAP"})
    assert not got.get("section_stock")
    assert any("a parts list this part is only listed on" in str(f)
               for f in got.get("review_flags") or [])


def test_the_list_page_is_not_the_parts_own_sheet_even_when_it_is_a_detail_page():
    """D-755, 0358141 at 15:47: page 3 is the rail's own DETAIL sheet carrying its parts list.
    Read as each cap's single detail sheet it gave them the rail's tube at the rail's 1,400 mm,
    and D-751's guard (no detail page) never fired."""
    got = _post_build({"part_number": "UPC0358141 M5", "description": "ENDCAP"}, role="detail")
    assert not got.get("section_stock")
    assert any("a parts list this part is only listed on" in str(f)
               for f in got.get("review_flags") or [])
    m6 = _post_build({"part_number": "UPC0358141 M6", "description": "O A RAIL END"},
                     role="detail")
    ss = m6.get("section_stock") or {}
    assert ss.get("read_from") == "parts_list_page", "so the part's own read can withdraw it"
    assert ss.get("length_source") != "detail_sheet_figure", "never the rail's length"


def test_a_part_whose_name_says_section_still_takes_it_and_is_marked():
    got = _post_build({"part_number": "UPC0358141 M6", "description": "O A RAIL END"})
    ss = got.get("section_stock") or {}
    assert ss.get("a") and ss.get("read_from") == "parts_list_page"
    assert ss.get("read_from_page") == 3


def test_a_part_with_its_own_sheet_is_not_touched_by_the_rule():
    got = _post_build({"part_number": "UPC0358141 M5", "description": "ENDCAP"},
                      role="detail", bound_to_list=None)
    assert (got.get("section_stock") or {}).get("read_from") is None


def test_part_index_records_the_binding_as_a_fact():
    src = (ROOT / "src" / "part_index.py").read_text(encoding="utf-8")
    at = src.index("which is a parts ")
    assert 'part["bound_to_parts_list_page"] = chosen_page.get("page_number")' in src[at:at + 900]
    # The engine failed to bind a sheet; it cannot know there is none (8 Nov review).
    assert "no detail sheet in this pack was bound to it" in src[at:at + 400]
    assert "no page in this pack details it" not in src


# ── the part's own read outranks the list's profile ─────────────────────────────────────

def _job(rows, assemblies=()):
    return {"found": True, "parts": rows, "assemblies": list(assemblies), "routes": []}


def test_the_parts_own_read_of_a_plate_withdraws_the_lists_tube():
    part = {"part_number": "UPC0358141 M6", "description": "O A RAIL END", "quantity": 2,
            "section_stock": {"a": 15.0, "b": 30.0, "t": 2.0, "length_mm": 1400,
                              "detection_path": "canonical_profile",
                              "read_from": "parts_list_page", "read_from_page": 3}}
    row = {"part_number": "UPC0358141 M6", "description": "O A RAIL END", "row_qty": 2,
           "material": "MILD STEEL", "material_family": "metal", "thickness_mm": 3.0}
    lj.apply_full_job_to_pre_estimate([part], _job([row]))
    assert not part.get("section_stock")
    assert part.get("normalized_thickness_mm") == 3.0
    assert any("WITHDRAWN" in str(f) for f in part.get("review_flags") or [])


def test_a_tube_read_or_a_profile_from_its_own_sheet_is_kept():
    # The read says it is the same 2 mm wall: nothing contradicts the profile.
    same = {"part_number": "X1", "quantity": 1,
            "section_stock": {"a": 15.0, "b": 30.0, "t": 2.0, "length_mm": 1400,
                              "read_from": "parts_list_page", "read_from_page": 3}}
    lj.apply_full_job_to_pre_estimate([same], _job([{"part_number": "X1", "thickness_mm": 2.0,
                                                     "material_family": "metal"}]))
    assert same.get("section_stock")
    # A profile not read off a list (its own sheet, its own row) is never withdrawn here.
    own = {"part_number": "X2", "quantity": 1,
           "section_stock": {"a": 15.0, "b": 30.0, "t": 2.0, "length_mm": 1400}}
    lj.apply_full_job_to_pre_estimate([own], _job([{"part_number": "X2", "thickness_mm": 3.0,
                                                    "material_family": "metal"}]))
    assert own.get("section_stock")


# ── N equal pieces on a row of N are its N parts ────────────────────────────────────────

def test_two_equal_pieces_on_a_row_of_two_are_one_piece_each():
    part = {"part_number": "UPC0358141 M4", "description": "UPRIGHT", "quantity": 2}
    row = {"part_number": "UPC0358141 M4", "description": "UPRIGHT", "row_qty": 2,
           "material": "MILD STEEL", "material_family": "tube",
           "tube_section": "30x30x2", "cut_lengths_mm": [1383, 1383]}
    lj.apply_full_job_to_pre_estimate([part], _job([row]))
    ss = part["section_stock"]
    assert ss["length_mm"] == 1383 and not ss.get("cut_lengths_mm")
    assert e._infer_section_length_mm(part) == 1383
    assert any("one 1383 mm piece for each of the 2" in str(f)
               for f in part.get("review_flags") or [])


def test_a_part_the_read_joins_on_its_own_keeps_its_pieces_and_says_both():
    """Two equal cuts alone do not say per part or per copy (8 Nov review): a frame drawn as
    one part, 2 off, of two equal tubes it is welded from, keeps both pieces."""
    frame = {"part_number": "F-03", "description": "FRAME", "quantity": 2}
    job = _job([{"part_number": "F-03", "row_qty": 2, "material_family": "tube",
                 "tube_section": "30x30x2", "cut_lengths_mm": [500, 500]}])
    job["routes"] = [{"operation": "welding", "part_numbers": ["F-03"], "inferred": False}]
    lj.apply_full_job_to_pre_estimate([frame], job)
    assert e._infer_section_length_mm(frame) == 1000
    assert any("the read joins this part on its own" in str(f) and "500 mm a part" in str(f)
               for f in frame.get("review_flags") or [])


def test_a_stated_weight_decides_between_one_piece_and_all_of_them():
    # 30x30x2 steel is about 1.70 kg/m: one 1,383 mm piece ~2.35 kg, two ~4.70 kg.
    heavy = {"part_number": "W-1", "quantity": 2}
    lj.apply_full_job_to_pre_estimate([heavy], _job([{
        "part_number": "W-1", "row_qty": 2, "material_family": "tube", "weight_g": 4700,
        "tube_section": "30x30x2", "cut_lengths_mm": [1383, 1383]}]))
    assert e._infer_section_length_mm(heavy) == 2766
    assert any("is all 2 pieces'" in str(f) for f in heavy.get("review_flags") or [])
    light = {"part_number": "W-2", "quantity": 2}
    lj.apply_full_job_to_pre_estimate([light], _job([{
        "part_number": "W-2", "row_qty": 2, "material_family": "tube", "weight_g": 2350,
        "tube_section": "30x30x2", "cut_lengths_mm": [1383, 1383]}]))
    assert e._infer_section_length_mm(light) == 1383


def test_a_frames_pieces_and_an_assemblys_members_are_still_summed():
    frame = {"part_number": "12173-03-04M", "quantity": 1}
    lj.apply_full_job_to_pre_estimate([frame], _job([{
        "part_number": "12173-03-04M", "row_qty": 1, "material_family": "tube",
        "tube_section": "30x30x2", "cut_lengths_mm": [1532, 1532, 290, 350]}]))
    assert e._infer_section_length_mm(frame) == 3704
    # Two equal pieces on a row of two, but the row is an assembly: they are its members.
    asm = {"part_number": "F-01", "quantity": 2}
    lj.apply_full_job_to_pre_estimate([asm], _job(
        [{"part_number": "F-01", "row_qty": 2, "material_family": "tube",
          "tube_section": "30x30x2", "cut_lengths_mm": [500, 500]}],
        assemblies=[{"part_number": "F-01", "children": []}]))
    assert e._infer_section_length_mm(asm) == 1000
    # Unequal pieces on a row whose count matches are a cut list, not copies.
    mixed = {"part_number": "F-02", "quantity": 2}
    lj.apply_full_job_to_pre_estimate([mixed], _job([{
        "part_number": "F-02", "row_qty": 2, "material_family": "tube",
        "tube_section": "30x30x2", "cut_lengths_mm": [500, 300]}]))
    assert e._infer_section_length_mm(mixed) == 800


def test_the_row_count_travels_with_the_read():
    import llm_full_extract as lfe
    got = lfe.project_row({"part_number": "M4", "qty": 2, "material_family": "tube",
                           "thickness_or_section": "30x30x2", "cut_lengths_mm": [1383, 1383]})
    assert got["row_qty"] == 2 and got["cut_lengths_mm"] == [1383, 1383]


# ── a route lands on the part, whatever its spelling (D-752) ─────────────────────────────

def test_a_route_spelled_as_the_sheet_prints_lands_on_the_listed_record():
    """0358141's read keyed its drilling to "UPC0358141M4"; the record is "UPC0358141 M4". The
    route's spelling became a target of its own and M4's drilling was charged twice."""
    from route_compiler import compile_job_route
    parts = [{"part_number": "UPC0358141 M4", "description": "UPRIGHT", "quantity": 2,
              "textual_operations": ["hole_machining"]}]
    extract = {"assemblies": [], "parts": [], "routes": [
        {"operation": "hole_machining", "part_numbers": ["UPC0358141M4"], "inferred": False,
         "evidence": "4 x M4 TAP", "scope": "part"}]}
    graph = compile_job_route(parts, extract)
    targets = {d["target_id"] for d in graph["decisions"] if d["operation"] == "hole_machining"}
    assert "UPC0358141M4" not in targets, targets
    assert "UPC0358141 M4" in targets, targets


def test_two_records_one_spacing_apart_are_never_guessed_between():
    from route_compiler import _record_for_model_assembly_name as resolve
    raw = {"AB 1": {}, "A B1": {}}
    assert resolve("AB1", raw) == "AB1"            # two candidates: left as read, not guessed
    assert resolve("AB1", {"AB 1": {}}) == "AB 1"
