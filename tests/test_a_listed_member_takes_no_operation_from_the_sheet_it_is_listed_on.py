"""A weld legend never welds a part, and a member takes no joint from a sheet it is only listed on
(D-756, corrected and narrowed by D-757).

0358141 at 15:47 charged Weld (CO2) and Dress Welds on the rub strips M2 and M3, Estimate rows 157
and 158. They had no sheet of their own bound, so part_index bound them to page 2, the frame M1's
sheet with its parts list. Page 2's saved text carries the pack's specification legend with its
spaces stripped: "WELDSPECIFICATION" and "ALL WELDS TO BE MIG UNLESS STATED". The legend stripper
needed the spaces, so the keyword recogniser read "WELD" off it.

D-756 first quoted "WELD AND DRESS, TAP M4, FOLD" as page 2's note. It is not on page 2: it was
the fixed example wording plain_english printed beside every note-sourced operation (reviewer,
9 Nov). The example is gone from the report, and the fixtures below use the legend's real form.

Reviewer: "A general weld-process note specifies how an established weld is made; it does not
establish a weld on every member. Preserve genuine explicit or reasonably inferred frame, ballast
and member joints, charged once." And D-756 as first written was too broad: an assembly-level
instruction on the list page still applies to the members it lists.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# The specification border as 0358141's PDF text carries it: spaces stripped, no heading colon.
_LEGEND = ("MATERIALSSPECIFICATIONIS400GRITFINALPOLISH WELDSPECIFICATION "
           "ALLWELDSTOBEMIGUNLESSSTATED BRIGHTZINC ALWAYSREMOVEBURRSANDSHARPCORNERS")
_FRAME_LIST = ("ITEM PART NUMBER DESCRIPTION QTY 1 UPC0358141 M2 LONG RUB STRIP 1 "
               "2 UPC0358141 M3 SHORT RUB STRIP 2 " + _LEGEND)


def _post_build(part, pages, bound_to_list=None, roles=None):
    from document_builder import _apply_post_build_fixes, _empty_part_record
    rec = _empty_part_record(part_number=part["part_number"])
    rec.update({"pages": [p for p, _t in pages],
                "page_roles": list(roles or ["detail"] * len(pages)),
                "materials": ["STAINLESS STEEL"], "material_family": "metal"})
    if bound_to_list:
        rec["bound_to_parts_list_page"] = bound_to_list
    rec.update(part)
    summary = {"pages": [{"page_number": p, "page": p, "text": t,
                          "page_role": {"primary_role": (roles or ["detail"] * len(pages))[i]}}
                         for i, (p, t) in enumerate(pages)],
               "document_analysis": {"bom_rows": []}}
    _apply_post_build_fixes([rec], summary)
    return rec


def _joints(rec):
    return {o for o in (rec.get("textual_operations") or []) if "weld" in o}


# ── the legend, spaced or not, establishes no weld ───────────────────────────────────────

def test_the_space_stripped_legend_is_not_a_weld_note():
    from extractor_patterns import infer_operations_from_text as infer
    from extractor_patterns import strip_specification_legend as strip
    for text in (_LEGEND,
                 "WELD SPECIFICATION ALL WELDS TO BE MIG UNLESS STATED",
                 "SPECIFICATIONWELDSPECIFICATIONALLWELDSTOBETIGUNLESSSTATED"):
        assert not {o for o in infer(strip(text)) if "weld" in o}, text


def test_a_real_weld_callout_is_still_read_spaced_or_not():
    from extractor_patterns import infer_operations_from_text as infer
    from extractor_patterns import strip_specification_legend as strip
    for text in ("WELD ALL ROUND 4 PLACES", "WELDALLROUND4PLACES", "CORNERS TO BE WELDED",
                 _LEGEND + " CORNERS TO BE WELDED AND DRESSED"):
        assert "welding" in infer(strip(text)), text


def test_a_strip_listed_on_the_frame_sheet_takes_no_weld_from_its_legend():
    got = _post_build({"part_number": "UPC0358141 M2", "description": "LONG RUB STRIP"},
                      [(2, _FRAME_LIST)], bound_to_list=2)
    assert not _joints(got), got.get("textual_operations")


# ── a joint stays with the sheet's own part; other instructions still reach members ───────

def test_a_listed_member_takes_no_joint_from_the_list_but_keeps_its_general_instructions():
    sheet = _FRAME_LIST + " CORNERS TO BE WELDED AND DRESSED POWDER COAT BLACK RAL 9005"
    got = _post_build({"part_number": "UPC0358141 M2", "description": "LONG RUB STRIP"},
                      [(2, sheet)], bound_to_list=2)
    assert not _joints(got), got.get("textual_operations")
    assert any("no weld or dressing taken from page 2" in str(f)
               for f in got.get("review_flags") or [])
    # An assembly-level instruction on the list page still applies to the parts it lists.
    assert "powder_coating" in set(got.get("textual_operations") or []), \
        got.get("textual_operations")


def test_the_sheets_own_part_and_an_assembly_keep_the_joint():
    sheet = _FRAME_LIST + " CORNERS TO BE WELDED AND DRESSED"
    own = _post_build({"part_number": "UPC0358141 M1", "description": "FRAME"}, [(2, sheet)])
    assert "welding" in _joints(own)
    asm = _post_build({"part_number": "UPC0358141 M1", "description": "FRAME",
                       "is_assembly_parent": True}, [(2, sheet)], bound_to_list=2)
    assert "welding" in _joints(asm), "an assembly keeps its own page's joint"


def test_a_listed_part_with_its_own_sheet_takes_its_joint_from_that_sheet():
    sheet = _FRAME_LIST + " CORNERS TO BE WELDED AND DRESSED"
    plain = _post_build({"part_number": "UPC0358141 M2", "description": "LONG RUB STRIP"},
                        [(2, sheet), (5, "UPC 0358141 M2 LONG RUB STRIP 3MM STAINLESS " + _LEGEND)],
                        bound_to_list=2)
    assert not _joints(plain), "its own sheet draws no weld"
    welded = _post_build({"part_number": "UPC0358141 M2", "description": "LONG RUB STRIP"},
                         [(2, sheet), (5, "UPC 0358141 M2 TAB WELD ALL ROUND " + _LEGEND)],
                         bound_to_list=2)
    assert "welding" in _joints(welded), "its own sheet's weld is its own"


def test_the_report_no_longer_prints_an_example_as_if_quoted():
    import plain_english
    src = Path(plain_english.__file__).read_text(encoding="utf-8")
    at = src.index('"a note on the drawing":')
    assert "TAP M4" not in src[at:at + 300]


# ── D-760: every legend sentence, also with its spaces lost ──────────────────────────────

def test_every_legend_line_is_set_aside_with_its_spaces_stripped():
    """0358141's 09:32 record: every detail sheet carries "RESISTANCEWELDINGWIRETOWIRE
    THESETDOWNSHOULD..." from the legend, which put a weld on all seven members once D-757 had
    taken the MIG line away. The joined form of each configured legend sentence is derived."""
    from extractor_patterns import infer_operations_from_text as infer
    from extractor_patterns import strip_specification_legend as strip
    for text in ("M2 1 RESISTANCEWELDINGWIRETOWIRETHESETDOWNSHOULD CHINAMATERIALSPECIFICATIONS",
                 "RESISTANCE WELDING WIRE TO WIRE THE SET DOWN SHOULD BE"):
        assert not {o for o in infer(strip(text)) if "weld" in o}, text
    for text in ("RESISTANCE WELD THE MESH TO THE FRAME", "SPOTWELD 4 PLACES", "PUDDLEWELDED"):
        assert "welding" in infer(strip(text)), text
