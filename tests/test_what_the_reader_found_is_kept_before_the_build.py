"""What the deterministic reader found is kept before the build can merge, filter or drop it,
and each finding is followed through the record, the costing and the workbook (SCRUM-194,
requirement 2; the reviewer, 9 Nov 2026).

A ledger made from the built parts can only hold what survived. 0358141's five flat parts
(1168 x 11, 80 x 11, 30 x 30, 60 x 19, 30 x 15) print their extents as "<n> O/A" on their own
sheets; the reader read the figures and the build kept no blank, so no ledger built from the
parts could say a size was lost. The findings are captured page by page at scan, with page,
value, units, words and the part the page names; a finding no part was given stays visible.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import document_builder as db  # noqa: E402
import findings_trace as ft  # noqa: E402
import reader_findings as rf  # noqa: E402

_TB5 = ("SHEETTITLE FINISHES LONG RUB STRIP BRUSHED240GRIT KIDS 1400 x MATERIALS BASE RAIL "
        "SPERLINGREF PREFIX REV QTY BULKQTY 1 M2 3mmSTAINLESSSTEEL SHEET DATE DRAWNBY CHECKED UPC 0358141 5 10 OF")
_P5 = ("SOFTENEDGES\n11O A\n5.5 5.5\nISOMETRIC\n3\n20 282CTS 282CTS 282CTS 282CTS 20\n11\nGRAIN\nPLANVIEW\n"
       "(5x)n3.4THRU\nwn6.3X90.00°\n1168O A\nM\n3\nM\nFRONTVIEW\n" + _TB5)
_P3 = ("W-W ( 1: 4) PARTSLIST ITEM QTY DESCRIPTION PARTNUMBER 1 2 UPRIGHT UPC0358141 M4\n1400 O A\n"
       "(9X) M3X0.5 TOP FACE\n15x30x2mm M S TOP TUBE 1394 TUBE\nBALLAST BAR PUDDLE WELDED INTO BASE RAIL\n"
       "SHEETTITLE RAIL KIDS 1400 x MATERIALS 1 M1 SHEET UPC 0358141 3 10 OF")


def _summary():
    return {"pages": [
        {"page_number": 1, "pdfplumber_text": "GENERAL ARRANGEMENT 1400 O A 480 O A 1400 O A",
         "region_text": {"title_block": "SHEETTITLE GA KIDS 1400 x UPC 0358141 1 10 OF"}},
        {"page_number": 3, "pdfplumber_text": _P3,
         "region_text": {"title_block": "SHEETTITLE RAIL KIDS 1400 x MATERIALS 1 M1 SHEET UPC 0358141 3 10 OF"}},
        {"page_number": 5, "pdfplumber_text": _P5, "region_text": {"title_block": _TB5}}],
        "document_analysis": {"bom_rows": [
            {"part_number": "UPC0358141 M1", "description": "RAIL", "quantity": 1, "bom_sheet": "x.pdf#1"},
            {"part_number": "UPC0358141 M2", "description": "LONG RUB STRIP", "quantity": 1, "bom_sheet": "x.pdf#1"},
            {"part_number": "HAFELE 651.09.302", "description": "M8 x 22 Base Leveller", "quantity": 4,
             "bom_sheet": "x.pdf#1"}]}}


def test_the_findings_are_read_off_the_pages_with_page_part_value_and_words():
    led = rf.capture(_summary())
    assert led["captured"] == "scan" and led["schema"] == "reader_findings.v1"
    by = {(i["page"], i["kind"], str(i.get("part"))): i for i in led["items"]}
    size = next(i for i in led["items"] if i["page"] == 5 and i["kind"] == "overall")
    assert size["part"] == "UPC0358141 M2" and sorted(size["value"]) == [11.0, 1168.0] and "1168" in size["words"]
    assert by[(5, "material", "UPC0358141 M2")]["value"] == "STAINLESS STEEL"
    assert by[(5, "thickness", "UPC0358141 M2")]["value"] == 3.0
    assert by[(5, "finish", "UPC0358141 M2")]["value"] == "brushed"
    hole = next(i for i in led["items"] if i["page"] == 5 and i["kind"] == "hole")
    assert hole["value"]["diameter_mm"] == 3.4 and hole["value"]["count"] == 5, "counts survive"
    csk = next(i for i in led["items"] if i["page"] == 5 and i["kind"] == "countersink")
    assert csk["value"] == {"diameter_mm": 6.3, "angle_deg": 90.0}
    thread = next(i for i in led["items"] if i["page"] == 3 and i["kind"] == "thread")
    assert thread["value"]["thread"] == "M3x0.5" and thread["value"]["count"] == 9 and thread["part"] == "UPC0358141 M1"
    assert not any(i["kind"] == "thread" and i["value"]["thread"].startswith("M30") for i in led["items"]), \
        "30x30x2mm is a section, not a thread"
    ga = next(i for i in led["items"] if i["page"] == 1 and i["kind"] == "overall")
    assert ga["part"] is None and led["unassigned"] >= 1, "a finding no part was given stays visible"
    lev = next(i for i in led["items"] if i["kind"] == "bom_row" and i["part"].startswith("HAFELE"))
    assert lev["value"]["quantity"] == 4 and lev["value"]["purchase"], "a bought-in row is a finding too"


def test_a_flat_parts_two_overall_figures_on_its_own_sheet_are_its_blank_and_three_are_not():
    part = {"part_number": "UPC0358141 M2", "pages": [5], "materials": ["STAINLESS STEEL"]}
    lookup = {5: {"text": _P5 + " " + _P5, "page": {"pdfplumber_text": _P5}}}
    assert db._own_sheet_overall_blank(part, lookup)
    assert (part["blank_length_mm"], part["blank_width_mm"]) == (1168.0, 11.0)
    assert part["blank_length_mm_source"] == "detail_sheet_overall" and part["blank_printed"] == "1168 O/A x 11 O/A"
    cap = {"part_number": "X M5", "pages": [8]}
    assert db._own_sheet_overall_blank(cap, {8: {"text": "", "page": {"pdfplumber_text": "30O A ISOMETRIC 30O A R2"}}})
    assert (cap["blank_length_mm"], cap["blank_width_mm"]) == (30.0, 30.0), "the same figure twice is a square"
    fold = {"part_number": "X", "pages": [3]}
    assert not db._own_sheet_overall_blank(fold, {3: {"text": "", "page": {"pdfplumber_text": "1400 O A 480 O A 1400 O A"}}})
    tube = {"part_number": "X M4", "pages": [7], "section_stock": {"a": 30, "b": 30, "t": 2}}
    assert not db._own_sheet_overall_blank(tube, {7: {"text": "", "page": {"pdfplumber_text": "1383 O A"}}})
    merged_only = {"part_number": "Y", "pages": [9]}
    assert db._own_sheet_overall_blank(merged_only, {9: {"text": "19O A 60O A 19O A 60O A", "page": {}}})
    assert (merged_only["blank_length_mm"], merged_only["blank_width_mm"]) == (60.0, 19.0), \
        "merged text repeats its regions: distinct figures only"


def _costed(blank=True):
    s = _summary()
    s["reader_findings"] = rf.capture(s)
    m2 = {"part_number": "UPC0358141 M2", "pages": [5], "materials": ["STAINLESS STEEL"], "quantity": 1,
          "normalized_thickness_mm": 3.0, "textual_operations": ["countersinking"], "normalized_finish": "BRUSHED 240 GRIT",
          "page_roles": ["detail"]}
    if blank:
        m2.update(blank_length_mm=1168.0, blank_width_mm=11.0, blank_length_mm_source="detail_sheet_overall")
    m1 = {"part_number": "UPC0358141 M1", "pages": [3], "materials": ["MILD STEEL"], "quantity": 1,
          "section_stock": {"a": 15, "b": 30, "t": 2, "cut_lengths_mm": [1394, 1170], "length_mm": 2564},
          "textual_operations": ["welding", "tapping"], "page_roles": ["detail"]}
    s["manufacturing_writeup"] = {"parts": [m1, m2]}
    s["estimate_summary"] = {"part_estimates": [
        {"part_number": "UPC0358141 M2", "quantity": 1, "normalized_material": "STAINLESS_STEEL",
         "normalized_thickness_mm": 3.0, **({"blank_length_mm": 1168.0, "blank_width_mm": 11.0} if blank else {})},
        {"part_number": "UPC0358141 M1", "quantity": 1, "normalized_material": "MILD_STEEL",
         "section_stock": {"a": 15, "b": 30, "t": 2, "cut_lengths_mm": [1394, 1170]}}]}
    s["final_estimate"] = {"source": "excel_calculated"}
    s["drawing_charge_result"] = {"items": [
        {"id": "D2.material", "kind": "material", "record": "UPC0358141 M2", "state": "carried", "cells": []},
        {"id": "D2.size", "kind": "size", "record": "UPC0358141 M2", "state": "carried", "cells": []},
        {"id": "D2.quantity", "kind": "quantity", "record": "UPC0358141 M2", "state": "carried", "cells": []},
        {"id": "D2.op.countersinking", "kind": "operation", "record": "UPC0358141 M2", "state": "charged",
         "cells": ["Estimate!M160"]},
        {"id": "D2.finish", "kind": "stated", "record": "UPC0358141 M2", "state": "unresolved", "cells": []},
        {"id": "D1.op.tapping", "kind": "operation", "record": "UPC0358141 M1", "state": "charged",
         "cells": ["Estimate!M158"]},
        {"id": "D1.section", "kind": "section", "record": "UPC0358141 M1", "state": "carried", "cells": []}]}
    return s


def test_each_finding_is_followed_through_record_costing_and_workbook_and_a_lost_one_fails():
    t = ft.audit(_costed())
    assert t["applicable"] and t["captured"] == "scan" and t["read_back"]
    by = {(r["page"], r["kind"], str(r["part"])): r for r in t["items"]}
    size = by[(5, "overall", "UPC0358141 M2")]
    assert size["record"]["state"] == "in_record" and size["costing"]["state"] == "costed"
    assert size["workbook"]["state"] == "carried" and size["verdict"] == "PASS"
    csk = by[(5, "countersink", "UPC0358141 M2")]
    assert csk["record"]["state"] == "held_as_operation" and csk["workbook"]["cells"] == ["Estimate!M160"]
    assert csk["verdict"] == "PASS"
    fin = by[(5, "finish", "UPC0358141 M2")]
    assert fin["workbook"]["state"] == "unresolved" and fin["verdict"] == "FAIL", "stated work unresolved fails"
    thread = by[(3, "thread", "UPC0358141 M1")]
    assert thread["record"]["state"] == "held_as_operation" and thread["verdict"] == "PASS"
    ga = by[(1, "overall", "None")]
    assert ga["verdict"] == "REFERENCE" and "envelope" in ga["disposition"] and ga in t["unassigned"], \
        "a finding no part was given is listed with its disposition"
    lost = ft.audit(_costed(blank=False))
    size2 = {(r["page"], r["kind"], str(r["part"])): r for r in lost["items"]}[(5, "overall", "UPC0358141 M2")]
    assert size2["record"]["state"] == "dropped" and size2["verdict"] == "FAIL", size2


def test_a_record_without_captured_findings_is_not_applicable_never_reconstructed():
    s = _costed()
    s.pop("reader_findings")
    t = ft.audit(s)
    assert t["applicable"] is False and t["status"] == "NOT TESTED" and "predates" in t["why"] and t["items"] == []


# ── M1's transfer defects (reviewer, 9 Nov 2026) ─────────────────────────────────────────

_P4 = ("AF FRONTVIEW 3\n3 3\n12\n60\nM8x1.25THRUBOTTOMFACE\n(4TOTAL)\n222 n10THRUBOTTOMFACE\n102CTS\n"
       "TUBE FORPUDDLEWELD\n(11TOTAL)\n60\n80 505CTS 505CTS 80\n1170TUBE")


def test_a_count_printed_after_the_callout_survives_and_each_thread_keeps_its_own_spec():
    s = {"pages": [{"page_number": 4, "pdfplumber_text": _P4, "region_text": {"title_block": "BULKQTY M1 A SHEET"}},
                   {"page_number": 3, "pdfplumber_text": "(9x)M3x0.5 AA 30x30x2mm MSUPRIGHTS",
                    "region_text": {"title_block": "REV QTY BULKQTY M1 A 1 MILDSTEEL SHEET DATE"}}],
         "document_analysis": {"bom_rows": [{"part_number": "UPC0358141 M1", "description": "RAIL", "quantity": 1}]}}
    led = rf.capture(s)
    holes = [i for i in led["items"] if i["kind"] == "hole"]
    threads = sorted((i["page"], i["value"]["thread"], i["value"]["count"]) for i in led["items"] if i["kind"] == "thread")
    assert len(holes) == 1 and holes[0]["value"]["count"] == 11 and holes[0]["value"]["count_printed"]
    assert holes[0]["value"]["purpose"] == "puddleweld" and "(11TOTAL)" in holes[0]["words"]
    assert threads == [(3, "M3x0.5", 9), (4, "M8x1.25", 4)], "page 4's four M8 are not page 3's nine M3"
    mat = next(i for i in led["items"] if i["kind"] == "material")
    assert mat["page"] == 3 and mat["value"] == "MILD STEEL" and mat["words"] == "MILDSTEEL"


def test_a_title_block_that_prints_only_the_metal_gives_the_metal():
    import part_index as pi
    got = pi._title_block_gauge_and_material("REV QTY BULKQTY M1 A 1 MILDSTEEL SHEET DATE DRAWNB")
    assert got == {"printed": "MILDSTEEL", "material": "MILD STEEL", "thickness_mm": None, "section": None}
    assert pi._title_block_gauge_and_material("BULKQTY M1 A SHEET DATE 304-STAINLESSSTEEL") is None, \
        "a legend's metal outside the field window is not the part's"


def test_each_labelled_tube_length_keeps_the_section_printed_on_its_own_sheet():
    p3 = ("15x30x2mm\nMSTOPTUBE\n3\n480\n(9x)M3x0.5 AA 30x30x2mm\nMSUPRIGHTS\nTOPFACE\n1394TUBE\nISOMETRIC")
    rail = {"part_number": "UPC0358141 M1", "description": "RAIL", "pages": [3, 4], "materials": ["MILD STEEL"],
            "quantity": 1,
            "section_stock": {"a": 15.0, "b": 30.0, "t": 2.0, "length_mm": 2564.0, "cut_lengths_mm": [1170.0, 1394.0],
                              "length_source": "tube_callouts", "pieces_counted_once": True}}
    upright = {"part_number": "UPC0358141 M4", "description": "UPRIGHT", "pages": [7]}
    summary = {"pages": [{"page_number": 3, "pdfplumber_text": p3}, {"page_number": 4, "pdfplumber_text": _P4}]}
    parts = [rail, upright]
    members = db.sheet_piece_member_records(parts, summary)
    by = {m["section_stock"]["length_mm"]: m for m in members}
    assert set(by) == {1394.0, 1170.0} and all(m["cut_list_member_of"] == "UPC0358141 M1" for m in members)
    top = by[1394.0]["section_stock"]
    assert (top["a"], top["b"], top["t"]) == (15.0, 30.0, 2.0) and top["profile_source"] == "same_sheet", \
        "the 30x30 on page 3 is the UPRIGHT's, not this piece's"
    bar = by[1170.0]["section_stock"]
    assert bar["profile_provisional"] is True and bar["length_page"] == 4, \
        "page 4 prints no profile: provisional, said, and an open gap"
    assert any("provisionally" in f for f in by[1170.0]["review_flags"])
    assert "section_stock" not in rail and rail["section_stock_on_members"] == [m["part_number"] for m in members]
    assert rail["section_stock_as_read"]["length_mm"] == 2564.0, "what was read is kept beside the pieces"
    import gap_fill as gf
    assert gf.gaps_of(by[1170.0]) == ["section_profile"] and gf.gaps_of(rail) == []
