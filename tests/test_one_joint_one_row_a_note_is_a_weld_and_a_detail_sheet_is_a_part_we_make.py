"""Harrods 9439-01-04 Table Standing POS Holder, 5 Oct 18:53 book on 2e63a1d (D-397). The
route was mostly the right shape — £277.90 at one off — and three things were the engine's:

* the weld on the frame assembly 101 was charged TWICE: the extract's route named the three
  leaves it joins and resolved to 101, the engine's inference named 101 itself, and two route
  ids made two events, two Weld (CO2) rows at £29.24 — then the second was asked as
  "inferred, not drawn" beside the first, which quoted the sheet;
* 101's own sheet prints "WELD & DRESS" and "TAC WELD UNDERSIDE" and draws no symbol, and
  nothing read the words as the drawing's statement;
* the two A4 GRAPHIC LENSES, each with a detail sheet (PETG, 297 x 212, 2 mm, 151 g), kept
  a bought-in page role for want of a material suffix and were priced from the parts table at
  £1.68 instead of cut on the acrylic laser;
* and the pack-completeness check called 101, the lens and the graphic "drawings this pack
  does not contain" on a seven-sheet PDF whose sheets 2, 6 and 7 are theirs.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import bought_in_policy as bip                                        # noqa: E402
import invariants                                                     # noqa: E402
import route_compiler as rc                                           # noqa: E402
import weld_symbols as ws                                             # noqa: E402


# ── one joint, one event ─────────────────────────────────────────────────────────────────

def _pack():
    parts = [{"part_number": "H-101", "description": "FRAME ASSEMBLY", "quantity": 1,
              "is_assembly_parent": True, "page_roles": ["assembly"],
              "inferred_operations": ["welding"],
              "operation_sources": {"welding": "inference"}}]
    parts += [{"part_number": p, "description": p, "quantity": 1, "page_roles": ["detail"],
               "normalized_material": "MILD_STEEL", "textual_operations": ["laser_cutting"]}
              for p in ("H-001", "H-002", "H-003")]
    extract = {"assemblies": [{"part_number": "H-101", "children": [
        {"part_number": "H-001", "qty": 1}, {"part_number": "H-002", "qty": 1},
        {"part_number": "H-003", "qty": 2}]}],
        # The extract's two readings of one joint, as the 18:53 run had them: the route that
        # quotes the sheet and names the leaves, and the inferred route that names 101.
        "routes": [{"operation": "welding", "part_numbers": ["H-001", "H-002", "H-003"],
                    "scope": "assembly", "evidence": "TAC WELD", "sequence": 10},
                   {"operation": "welding", "part_numbers": ["H-101"], "scope": "assembly",
                    "inferred": True, "sequence": 10,
                    "notes": "views show TAC WELD and WELD & DRESS callouts"}]}
    return parts, extract


def test_two_readings_of_the_assemblys_weld_are_one_event():
    parts, extract = _pack()
    out = rc.compile_job_route(parts, extract, declared_product="H-101")
    _d = lambda d: d if isinstance(d, dict) else d.__dict__
    welds = [_d(d) for d in out["decisions"]
             if _d(d)["operation"] == "welding" and _d(d)["status"] == rc.REQUIRED]
    assert len(welds) == 1, [(w["target_id"], w["source"], w["participants"]) for w in welds]
    assert welds[0]["target_id"] == "H-101"
    assert set(welds[0]["participants"]) >= {"H-001", "H-002", "H-003"}
    assert welds[0]["source"] != "inference"          # the quoted reading won
    assert any(i.get("code") == "joining_events_merged_on_assembly" for i in out["issues"])


# ── a note on the sheet states the weld ──────────────────────────────────────────────────

def test_the_sheets_own_weld_note_is_the_drawings_statement():
    assert ws.sheet_weld_note("WELD & DRESS SCALE 1 : 1 TAC WELD UNDERSIDE") == \
        {"note": "WELD & DRESS", "dress": True}
    assert ws.sheet_weld_note("TAC WELD UNDERSIDE")["dress"] is False
    assert ws.sheet_weld_note("BAG PRICING HOOK WELDMENT") == {}          # a title
    assert ws.sheet_weld_note("FRAME WELD ASSEMBLY") == {}
    assert ws.sheet_weld_note("") == {}


def test_a_part_whose_sheet_carries_the_note_is_welded_by_the_drawing():
    frame = {"part_number": "H-101", "inferred_operations": ["welding"],
             "operation_sources": {"welding": "inference"}}
    leaf = {"part_number": "H-001"}
    by_part = {"H-101": {"notes": "WELD & DRESS TAC WELD UNDERSIDE", "text": ""},
               "H-001": {"notes": "MILD STEEL RAW 105G", "text": ""}}
    assert ws.apply_sheet_weld_notes([frame, leaf], by_part) == ["H-101"]
    assert "welding" in frame["textual_operations"] and "dress_welds" in frame["textual_operations"]
    assert frame["operation_sources"]["welding"] == "drawing_deterministic"
    assert frame["weld_stated_by_note"] == "WELD & DRESS"
    assert "textual_operations" not in leaf
    ruled = {"part_number": "H-101", "operations_ruled_out": {"welding": "bolted"}}
    assert ws.apply_sheet_weld_notes([ruled], by_part) == []


def test_the_legend_default_is_never_a_note():
    """sheet_weld_facts strips the legend before the note reader sees the lines."""
    from extractor_patterns import strip_specification_legend
    lines = "WELD SPECIFICATION: ALL WELDS TO BE TIG UNLESS STATED MATERIAL: MILD STEEL RAW"
    assert ws.sheet_weld_note(strip_specification_legend(lines)) == {}


# ── a detail sheet of a cut material is a part we make ───────────────────────────────────

def test_a_lens_with_its_own_detail_sheet_is_made_not_bought():
    lens = {"part_number": "H-004", "description": "A4 GRAPHIC LENS",
            "page_roles": ["detail", "bought_in"], "normalized_material": "PETG",
            "normalized_thickness_mm": 2.0, "overall_sizes_mm": ["297", "212"],
            "materials": ["PETG"]}
    assert bip.own_sheet_details_a_cut_part(lens)
    assert bip.bought_in_reason(lens) == ""
    # the same page role on an article with no sheet material of its own stays bought
    article = {"part_number": "H-ACC", "description": "THUMBSCREW", "page_roles": ["bought_in"],
               "normalized_material": "BOUGHT_IN"}
    assert bip.bought_in_reason(article)
    inherited = {"part_number": "H-005", "page_roles": ["detail", "bought_in"],
                 "normalized_material": "MILD_STEEL", "material_inherited_from": "H-GA",
                 "normalized_thickness_mm": 2.0}
    assert not bip.own_sheet_details_a_cut_part(inherited)


# ── a part traced to a sheet of the pack is not a missing drawing ────────────────────────

def test_a_bom_line_traced_to_a_detail_sheet_is_in_the_pack():
    summary = {
        "pages": [{"page_number": 1}, {"page_number": 2}],
        "document_analysis": {"bom_rows": [
            {"part_number": "9439-01-04-101", "description": "A4 FRAME ASSEMBLY", "quantity": 1},
            {"part_number": "9439-01-04-004", "description": "A4 GRAPHIC LENS", "quantity": 2},
            {"part_number": "9439-01-04-009", "description": "A MISSING BRACKET", "quantity": 1},
        ]},
        "parts": [
            {"part_number": "9439-01-04-101", "pages": [2], "page_roles": ["detail"]},
            {"part_number": "9439-01-04-004", "pages": [6], "page_roles": ["detail", "bought_in"]},
            {"part_number": "9439-01-04-009", "pages": [1], "page_roles": ["assembly_bom"]},
        ],
    }
    out = invariants.check_the_pack_contains_the_drawings_its_bom_names(summary)
    missing = {m["part_number"] for v in out for m in ((v.get("detail") or {}).get("missing") or [])}
    assert "9439-01-04-009" in missing
    assert "9439-01-04-101" not in missing and "9439-01-04-004" not in missing


# ── D-398: the 19:20 book on 4dc941c ─────────────────────────────────────────────────────
# One weld and one dress, but the lenses were still bought at £1.68: document_builder's
# non-metal correction read "not steel" as "purchased" on any part, tagged the lens bought-in,
# stripped its laser and cleared its gauge before bought_in_policy ever saw it. And the joint
# rows' Part No. cells listed the three members instead of naming the frame.

def _lens_pack():
    import document_builder as db
    page6 = ("A4 GRAPHIC LENS  9439-01-04-004  MATERIAL: PETG  THICKNESS: 2  FINISH: NATURAL  "
             "297 x 212  151 g  SCALE 1 : 1")
    summary = {"pages": [{"page_number": 1, "text_preview": "TABLE STANDING POS HOLDER MILD STEEL"},
                         {"page_number": 6, "text_preview": page6}]}
    lens = {"part_number": "9439-01-04-004", "description": "A4 GRAPHIC LENS", "quantity": 2,
            "materials": ["MILD STEEL"], "material_inherited_from": "9439-01-04-GA",
            "normalized_material": "MILD_STEEL", "normalized_thickness_mm": 2.0,
            "pages": [6], "page_roles": ["detail"],
            "textual_operations": ["laser_cutting", "powder_coating"],
            "overall_length_mm": 297.0, "overall_width_mm": 212.0, "geometry_rollup": {}}
    return db, summary, lens


def test_a_petg_lens_with_its_own_sheet_is_cut_here_not_bought():
    db, summary, lens = _lens_pack()
    db._apply_post_build_fixes([lens], summary)
    assert "bought_in" not in (lens.get("page_roles") or []), lens.get("page_roles")
    assert "detail" in lens["page_roles"]
    assert "laser_cutting" in (lens.get("textual_operations") or [])
    assert "powder_coating" not in (lens.get("textual_operations") or [])   # a metal coat
    assert str(lens.get("normalized_material") or "").upper() == "PETG"
    assert lens.get("normalized_thickness_mm") == 2.0                        # its own gauge
    assert lens.get("material_inherited_from") is None
    assert any("never bought" in f for f in lens.get("review_flags") or [])
    assert not bip.bought_in_reason(lens), bip.bought_in_reason(lens)


def test_a_graphic_or_an_led_with_no_sheet_material_is_still_a_purchase():
    db, summary, lens = _lens_pack()
    summary["pages"][1]["text_preview"] = "A4 GRAPHIC  9439-01-04-005  SUPPLIED BY OTHERS  VINYL"
    graphic = dict(lens, part_number="9439-01-04-005", description="GRAPHIC A4",
                   normalized_thickness_mm=None)
    db._apply_post_build_fixes([graphic], summary)
    assert "bought_in" in graphic["page_roles"]
    assert "laser_cutting" not in (graphic.get("textual_operations") or [])


# ── an assembly-scoped row names the assembly and lists what it covers ───────────────────

def test_an_assembly_rows_part_cell_names_the_assembly_and_the_members_it_covers():
    import wb_populate as wp
    named, joins = wp.row_parts_for("assembly", "9439-01-04-101",
                                    ["9439-01-04-001", "9439-01-04-002", "9439-01-04-003",
                                     "9439-01-04-101"])
    assert named == ["9439-01-04-101"]
    assert joins == ["9439-01-04-001", "9439-01-04-002", "9439-01-04-003"]
    # a part-scoped row names its participants as before, and covers nothing
    assert wp.row_parts_for("part", "9439-01-04-002", ["9439-01-04-002"]) == \
        (["9439-01-04-002"], [])
    assert wp.row_parts_for("part", "9439-01-04-002", []) == (["9439-01-04-002"], [])
    assert wp.row_parts_for("assembly", "", ["A", "B"]) == (["A", "B"], [])


# ── a drawing number with its title after it is that drawing ─────────────────────────────

def test_the_gas_number_with_its_title_is_the_ga():
    import product_identity as pi
    ga = "9439-01-04-GA A4 CHAMPAGNE"
    assert pi.drawing_number_and_title(ga) == ("9439-01-04-GA", "A4 CHAMPAGNE")
    assert pi.names_the_product("9439-01-04", ga)
    assert pi.names_the_product("9439-01-04-GA", ga)
    assert pi.names_the_product("9439-01-04", "9439-01-04 GA A4 CHAMPAGNE REV C")
    # never a sheet under it, and never a sub-sheet written with a space
    assert not pi.names_the_product("9439-01-04", "9439-01-04-101 FRAME ASSEMBLY")
    assert not pi.names_the_product("11650-06", "11650-06 SA01 CABINET TOP")
    assert not pi.names_the_product("9439-01", ga)
    assert pi.drawing_number_and_title("9439-01-04-GA") == ("", "")
    # so the job's numbering resolves the GA with no "matches no assembly" left to say
    ids = {ga, "9439-01-04-101", "9439-01-04-001", "9439-01-04-004"}
    assert pi.numbering_prefix("9439-01-04", ids) == ""
    assert [i for i in ids if pi.names_the_product("9439-01-04", i)] == [ga]


# ── D-399: the 6 Oct 08:16 book on cfc2b2c ───────────────────────────────────────────────
# One weld, one dress, the product resolved — and the lens still bought at £1.68, now with a
# Diamond Polish row beside it. The sheet's MATERIAL: PETG was read (page 6 yields PETG,
# NATURAL, 151g) and never reached the record: two readers let the word GRAPHIC in "A4
# GRAPHIC LENS" call the part bought before the material was looked at, and the SolidWorks
# connector refused the solid's 2 mm because a plastic sheet has no flat pattern and no mass.

def test_a_name_is_what_the_part_holds_when_its_sheet_states_a_stock():
    import json_normaliser as jn
    lens = {"part_number": "9439-01-04-004", "description": "A4 GRAPHIC LENS",
            "materials": ["PETG"], "page_roles": ["detail"], "quantity": 2}
    assert bip.own_sheet_states_a_stock_material(lens)
    assert jn.normalise_material_for_part(lens) != "BOUGHT_IN"
    # the name still decides where the sheet states nothing, or states a thing we buy
    graphic = {"part_number": "9439-01-04-005", "description": "GRAPHIC A4-SUPPLIED BY OTHERS",
               "materials": [], "page_roles": ["detail"]}
    assert jn.normalise_material_for_part(graphic) == "BOUGHT_IN"
    ticket = {"part_number": "12527-22-03X", "description": "TICKET", "materials": ["PAPER"],
              "page_roles": ["detail"]}
    assert jn.normalise_material_for_part(ticket) == "BOUGHT_IN"
    assert not bip.own_sheet_states_a_stock_material(ticket)
    inherited = {"part_number": "H-9", "description": "GRAPHIC PANEL", "materials": [],
                 "normalized_material": "MILD_STEEL", "material_inherited_from": "document_level",
                 "page_roles": ["detail"]}
    assert not bip.own_sheet_states_a_stock_material(inherited)


def test_the_special_finishing_rule_yields_to_the_parts_own_sheet():
    import estimator as est
    lens = {"part_number": "9439-01-04-004", "description": "A4 GRAPHIC LENS",
            "materials": ["PETG"], "page_roles": ["detail"], "quantity": 2}
    assert not est._is_special_bought_in_item(lens)
    assert any("what it holds" in f for f in lens["review_flags"])
    # SDI's own -X purchasing suffix still decides, and so does a graphic with no material
    assert est._is_special_bought_in_item({"part_number": "12552-01-01X",
                                           "description": "62012RS Ball Bearing",
                                           "page_roles": ["assembly"]})
    assert est._is_special_bought_in_item({"part_number": "12301-08-04X",
                                           "description": "HEADER GRAPHIC SET",
                                           "materials": ["VINYL"], "page_roles": ["detail"]})
    assert est._is_special_bought_in_item({"part_number": "P/P-GRAPHIC", "description": "GRAPHIC PANEL",
                                           "materials": [], "page_roles": ["bought_in"]})


def test_a_plastic_sheets_solid_thickness_is_its_gauge():
    from source_connectors import solidworks as sw
    lens = {"part_number": "9439-01-04-004", "description": "A4 GRAPHIC LENS",
            "materials": ["PETG"], "normalized_material": "ACRYLIC", "page_roles": ["detail"],
            "pages": [6], "quantity": 2}
    nat = sw.NativePart(part_number="9439-01-04-004", material="Acrylic (Medium-high impact)",
                        material_source="applied_library", thickness_mm=2.0,
                        bbox_mm=[297.0, 212.0, 2.0], mass_kg=None)
    job = sw.NativeJob(found=True, part_signals={"9439-01-04-004": nat})
    sw.apply_native_to_pre_estimate([lens], job)
    assert lens.get("normalized_thickness_mm") == 2.0, lens.get("review_flags")
    assert not any("NOT used as the gauge" in f for f in lens.get("review_flags") or [])
    # a folded steel end cap with no sheet body is still refused (D-265)
    cap = {"part_number": "12567-05-02M", "description": "END CAP", "materials": ["MILD STEEL"],
           "normalized_material": "MILD_STEEL", "page_roles": ["detail"], "pages": [3]}
    nat2 = sw.NativePart(part_number="12567-05-02M", material="Mild Steel", thickness_mm=12.0,
                         bbox_mm=[120.0, 60.0, 12.0], mass_kg=None)
    sw.apply_native_to_pre_estimate([cap], sw.NativeJob(found=True, part_signals={"12567-05-02M": nat2}))
    assert cap.get("normalized_thickness_mm") in (None, 0, "")
    assert any("NOT used as the gauge" in f for f in cap.get("review_flags") or [])


# ── D-400: a blob weld is a weld note (M&S 9598-02-01M, read before the first run) ───────

def test_a_blob_weld_at_both_ends_is_the_sheets_statement_of_the_weld():
    assert ws.sheet_weld_note("BLOB WELD BOTH ENDS TO STOP FOLD OPENING DOWN 180° R 0.5 UP 90° R 1") == \
        {"note": "BLOB WELD", "dress": False}
    assert ws.sheet_weld_note("WELD BOTH ENDS")["note"]
    assert ws.sheet_weld_note("WELD EACH END")["note"]
    assert ws.sheet_weld_note("TO STOP FOLD OPENING") == {}            # the reason, not a weld
    assert ws.sheet_weld_note("BLOB OF SEALANT BOTH ENDS") == {}


# ── D-402: the 6 Oct 14:15 book on e21761e — the graphic's own material and size ─────────
#
# 9598-02-02G GRAPHIC: its sheet states MATERIAL: 400 MIC, 210 x 148.5 x 0.40, 1.95 g. The
# book charged it as an 18 mm TIMBER panel, 841 x 471.61 — £9.19 of board and £9.34 of CNC
# on a printed card, about £20.52 of the £47.38 unit figure. Boilerplate text and the frame's
# geometry overrode the part's own field and its own model.

def test_the_sheets_own_material_field_is_its_answer_however_unresolved():
    import extractor_patterns as ep
    legend = ("FINISH: TBC COLOUR: TBC WEIGHT: 1.95g GENERAL TOLERANCES: LINEAR DIMENSIONS UP TO "
              "120mm +/-0.5mm CHINA MATERIAL SPECIFICATIONS: • Q195 UP TO 3mm THICK FOR POWDER "
              "COATED STEEL • 304 - STAINLESS STEEL • 6063 - ALUMINIUM FOR EXTRUSION TIMBER "
              "PRODUCTS: • WHERE SPECIFIED ALL TIMBER-BASED PRODUCTS MUST BE FSC CERTIFIED "
              "DRAWING No 9598-02-02G")
    assert ep.extract_title_block_fields("MATERIAL: 400 MIC " + legend)["materials"] == ["400 MIC"]
    # the same sheet read with the value before its label (PyMuPDF's order): no labelled
    # value, and the page scan runs — the legend's words are never a part's material
    assert ep.extract_title_block_fields("400 MIC FINISH: MATERIAL: " + legend)["materials"] == []
    # a GA that points at its components, and a field naming a stock the arms do not take
    assert ep.extract_title_block_fields(
        "MATERIAL: REFER TO INDIVIDUAL COMPONENT DRAWINGS " + legend)["materials"] == []
    assert ep.extract_title_block_fields(
        "MATERIAL: CORIAN GLACIER WHITE SOLID SURFACE 12 MM " + legend)["materials"] == []
    assert ep.material_field_states_something("MATERIAL: CORIAN GLACIER WHITE SOLID SURFACE 12 MM")
    assert not ep.material_field_states_something("MATERIAL: 2MM FINISH: TBC")
    # a real callout still reads, including one that shares a word with the legend's grade
    assert ep.extract_title_block_fields("MATERIAL: MILD STEEL " + legend)["materials"] == ["MILD STEEL"]
    assert ep.extract_title_block_fields(
        "MATERIAL: STAINLESS STEEL 304 " + legend)["materials"] == ["STAINLESS STEEL"]


def test_a_stock_named_by_weight_is_a_print_stock_and_the_name_rule_agrees():
    import estimator as est
    import json_normaliser as jn
    assert jn.normalise_material("400 MIC") == "BOUGHT_IN"
    assert jn.normalise_material("300 GSM SILK") == "BOUGHT_IN"
    assert jn.normalise_material("BETWEEN 80 - 120 MICRON") is None     # a coating band, not a stock
    graphic = {"part_number": "9598-02-02G", "description": "GRAPHIC", "materials": ["400 MIC"],
               "page_roles": ["detail"], "quantity": 1}
    assert jn.normalise_material_for_part(graphic) == "BOUGHT_IN"
    assert est._is_special_bought_in_item({**graphic, "normalized_material": "BOUGHT_IN"})
    assert not bip.own_sheet_states_a_stock_material({**graphic, "normalized_material": "BOUGHT_IN"})


def test_a_family_default_gauge_never_re_enters_as_the_drawings_reading():
    import document_builder as db
    import estimator as est
    part = {"part_number": "X-01J", "description": "BACK PANEL", "materials": ["MDF"],
            "pages": [1], "page_roles": ["detail"], "quantity": 1, "thicknesses_mm": [],
            "geometry_rollup": {}, "textual_operations": [], "review_flags": []}
    summary = {"pages": [{"page_number": 1, "text": "MATERIAL: MDF",
                          "page_role": {"primary_role": "detail"}}],
               "document_analysis": {}}
    db._apply_post_build_fixes([part], summary)
    assert part.get("normalized_thickness_mm") == 18.0
    assert part.get("thickness_source") == "inference"
    assert not part.get("thicknesses_mm")
    # the estimator charges the reading the record holds, not a list entry nobody printed
    assert est._safe_thickness_and_stage(part) == (18.0, "normalized")


def test_a_flat_plastic_solid_gives_its_blank_from_its_own_extents():
    from source_connectors import solidworks as sw
    lens = {"part_number": "9439-01-04-004", "description": "A4 GRAPHIC LENS",
            "materials": ["PETG"], "normalized_material": "ACRYLIC", "page_roles": ["detail"],
            "pages": [6], "quantity": 2, "blank_length_mm": 841.0, "blank_width_mm": 471.61,
            "blank_length_mm_source": "document_text_largest_numbers",
            "blank_width_mm_source": "document_text_largest_numbers"}
    nat = sw.NativePart(part_number="9439-01-04-004", material="Acrylic (Medium-high impact)",
                        material_source="applied_library", thickness_mm=2.0,
                        bbox_mm=[297.0, 212.0, 2.0], mass_kg=None)
    sw.apply_native_to_pre_estimate([lens], sw.NativeJob(found=True, part_signals={"9439-01-04-004": nat}))
    assert (lens["blank_length_mm"], lens["blank_width_mm"]) == (297.0, 212.0)
    assert lens["blank_length_mm_source"] == "solidworks_api"
    assert lens["normalized_geometry"]["blank_length_mm"] == 297.0
    assert any("extents" in f and "replaces 841 x 471.61mm" in f for f in lens["review_flags"])
    # a DXF-backed part keeps its measured flat: the extents are a fallback, never an override
    cut = {"part_number": "9439-01-04-005", "description": "LENS", "materials": ["PETG"],
           "normalized_material": "ACRYLIC", "page_roles": ["detail"], "pages": [7], "quantity": 1,
           "geometry_source": "dxf", "blank_length_mm": 300.0, "blank_width_mm": 210.0}
    nat2 = sw.NativePart(part_number="9439-01-04-005", material="PETG", thickness_mm=2.0,
                         bbox_mm=[297.0, 212.0, 2.0], mass_kg=None)
    sw.apply_native_to_pre_estimate([cut], sw.NativeJob(found=True, part_signals={"9439-01-04-005": nat2}))
    assert (cut["blank_length_mm"], cut["blank_width_mm"]) == (300.0, 210.0)


def test_the_gauge_advisory_names_the_gauge_the_sheet_charged():
    raw = {"part_number": "X-02G", "normalized_thickness_mm": 0.4, "thickness_source": "solidworks_api",
           "_displaced": {"normalized_thickness_mm": [{"value": 18.0, "source": "inference"}]}}
    charged = {"part_number": "X-02G", "normalized_thickness_mm": 18.0,
               "thickness_source": "thicknesses_mm_list"}
    out = invariants.check_two_sources_disagree_about_the_gauge(
        {"parts": [raw], "estimate_summary": {"part_estimates": [charged]}})
    assert out and "X-02G costed at 18.0mm from thicknesses_mm_list, but solidworks_api says 0.4mm" in out[0]["message"]
    assert "higher-ranked" not in out[0]["message"]
    # the control: costed row and raw record agree, the displaced reading is the other side
    agree = {"part_number": "X-02G", "normalized_thickness_mm": 0.4, "thickness_source": "solidworks_api"}
    out2 = invariants.check_two_sources_disagree_about_the_gauge(
        {"parts": [raw], "estimate_summary": {"part_estimates": [agree]}})
    assert out2 and "costed at 0.4mm from solidworks_api, but inference says 18.0mm" in out2[0]["message"]


def test_bend_callouts_are_counted_on_the_layer_that_reads_every_glyph(monkeypatch):
    import drawing_job_merge as djm
    summary = {"pages": [{"page_number": 2, "source_pdf_path": "",
                          "pdfplumber_text": "UP 90° R 1 DOWN 180° R 0.5 DOWN 180° R 0.5"}]}
    monkeypatch.setattr(djm, "_mupdf_page_text", lambda pg, d: "UP  90°  R 1 \nDOWN  180°  R 0.5 \n")
    part = {"part_number": "X-01M", "pages": [2], "page_roles": ["detail"]}
    assert djm.stamp_drawing_bend_callouts([part], summary) == 1
    assert part["drawing_bend_callouts"] == 2
    # no PDF on disk: the text layers are all there is, and the largest reading stands (D-259)
    monkeypatch.setattr(djm, "_mupdf_page_text", lambda pg, d: "")
    part = {"part_number": "X-01M", "pages": [2], "page_roles": ["detail"]}
    djm.stamp_drawing_bend_callouts([part], summary)
    assert part["drawing_bend_callouts"] == 3


# ── D-403: the 6 Oct 15:44 (9598-02) and 16:35 (9598-03) books on 5e0e065 ───────────────
#
# 9598-03-01M, a 1.2 mm frame with a measured DXF flat, was given Tube and Tubebend rows
# (£34.51 at one off) inferred by the vision read from the press-brake radii on its sheet;
# 9598-02-02G's sheet asked "confirm which is right" between its own "400 MIC" and the
# lexicon's BOUGHT_IN; a deburr row stood on the border's "REMOVE BURRS AND SHARP CORNERS" as
# a note read from the sheet; and "callouts read 3" named neither its layer nor its strings.

def test_a_flat_pattern_is_not_a_tube():
    from source_connectors import llm_full_job as lfj
    frame = {"part_number": "9598-03-01M", "description": "METAL FRAME", "quantity": 1,
             "geometry_source": "dxf_flat_pattern", "dxf_augmented": True,
             "textual_operations": ["laser_cutting"]}
    routes = [{"operation": "tube_bending", "part_numbers": ["9598-03-01M"], "inferred": True,
               "evidence": "Bend notes and radii visible on part drawing page 2", "sequence": 20},
              {"operation": "tube_cut", "part_numbers": ["9598-03-01M"], "inferred": True, "sequence": 10},
              {"operation": "folding", "part_numbers": ["9598-03-01M"], "inferred": False,
               "evidence": "UP 90° R 1", "sequence": 20}]
    lfj.apply_routes_to_parts([frame], {"routes": routes})
    assert "folding" in frame["textual_operations"]
    assert not {"tube_bending", "tube_cut"} & set(frame["textual_operations"])
    assert set(frame["operations_ruled_out"]) == {"tube_bending", "tube_cut"}
    assert frame["operation_ruling_sources"] == {"tube_bending": "dxf", "tube_cut": "dxf"}
    assert any("press-brake" in f for f in frame["review_flags"])
    # and the compiled route meets the ruling, not the claim
    res = rc.compile_job_route([frame], {"routes": routes})
    status = {d["operation"]: d["status"] for d in res["decisions"]}
    assert status["tube_bending"] == rc.RULED_OUT and status["tube_cut"] == rc.RULED_OUT
    assert status["folding"] == rc.REQUIRED and status["laser_cutting"] == rc.REQUIRED
    # the control: a tube with a section and no flat keeps its tube work
    tube = {"part_number": "T-01M", "description": "FRAME TUBE", "quantity": 1,
            "section_stock": {"a": 30, "b": 30, "t": 2, "length_mm": 1532},
            "textual_operations": []}
    lfj.apply_routes_to_parts([tube], {"routes": [
        {"operation": "tube_bending", "part_numbers": ["T-01M"], "inferred": True, "sequence": 20}]})
    assert "tube_bending" in tube["textual_operations"] and not tube.get("operations_ruled_out")


def test_a_legend_only_cue_is_an_inference_for_every_operation():
    import extractor_patterns as ep
    from source_connectors import llm_full_job as lfj
    assert ep.cites_only_specification_legend("ALWAYS REMOVE BURRS AND SHARP CORNERS")
    assert ep.cites_only_specification_legend("REMOVE BURRS AND SHARP CORNERS")
    assert ep.cites_only_specification_legend("ALL WELDS TO BE TIG UNLESS STATED")
    for own in ("WELD & DRESS", "BLOB WELD BOTH ENDS TO STOP FOLD OPENING", "UP 90° R 1",
                "Bend notes and radii visible on part drawing page 2", ""):
        assert not ep.cites_only_specification_legend(own), own
    part = {"part_number": "X-01M", "quantity": 1, "textual_operations": []}
    routes = [{"operation": "deburring", "part_numbers": ["X-01M"], "inferred": False,
               "evidence": "REMOVE BURRS AND SHARP CORNERS", "sequence": 30},
              {"operation": "folding", "part_numbers": ["X-01M"], "inferred": False,
               "evidence": "UP 90° R 1", "sequence": 20}]
    lfj.apply_routes_to_parts([part], {"routes": routes})
    assert part["operation_sources"] == {"deburring": "inference", "folding": "llm_full_extract"}
    res = rc.compile_job_route([part], {"routes": routes})
    by_op = {d["operation"]: d for d in res["decisions"]}
    assert by_op["deburring"]["source"] == "inference"
    assert by_op["folding"]["source"] == "llm_full_extract"
    assert any(i.get("code") == "route_cites_only_the_specification_legend"
               and i.get("operation") == "deburring" for i in res["issues"])


def test_a_callout_and_its_lexicon_reading_are_one_fact():
    import source_precedence as sp
    card = {"part_number": "9598-02-02G", "normalized_material": "400 MIC",
            "material_source": "drawing_deterministic"}
    assert sp.apply_field(card, "normalized_material", "BOUGHT_IN", "inference") is False
    assert card["normalized_material"] == "400 MIC" and not card.get("review_flags")
    steel = {"part_number": "X", "normalized_material": "MILD STEEL",
             "material_source": "drawing_deterministic"}
    sp.apply_field(steel, "normalized_material", "MILD_STEEL", "dxf_filename")
    assert not steel.get("review_flags")
    sp.apply_field(steel, "normalized_material", "ACRYLIC", "inference")          # a real disagreement
    assert any("confirm which is right" in f for f in steel["review_flags"])


def test_the_callout_count_names_its_layer_and_its_strings(monkeypatch):
    import drawing_job_merge as djm
    import fold_count as fc
    summary = {"pages": [{"page_number": 2, "source_pdf_path": "",
                          "pdfplumber_text": "UP 90° R 1 DOWN 180° R 0.5 DOWN 180° R 0.5"}]}
    monkeypatch.setattr(djm, "_mupdf_page_text", lambda pg, d: "")
    part = {"part_number": "X-01M", "pages": [2], "page_roles": ["detail"], "bend_count_dxf": 2,
            "geometry_source": "dxf", "dxf_augmented": True}
    djm.stamp_drawing_bend_callouts([part], summary)
    assert part["drawing_bend_callout_evidence"] == {
        "layer": "pdfplumber_text", "callouts": ["UP 90°", "DOWN 180°", "DOWN 180°"], "page": 2}
    folds = fc.press_brake_folds(part)
    assert folds["count"] == 2
    assert "read 3 (UP 90°, DOWN 180°, DOWN 180° on the pdfplumber_text layer of page 2)" in folds["disagreement"]


def test_a_bought_lines_description_carries_the_size_its_own_record_holds():
    import wb_populate as wb
    assert wb._own_size_mm({"normalized_geometry": {"bbox_mm": [210.0, 148.5, 0.4]}}) == (210.0, 148.5)
    assert wb._own_size_mm({"blank_length_mm": 471.61, "blank_width_mm": 212}) == (471.61, 212.0)
    assert wb._own_size_mm({"normalized_geometry": {"bbox_mm": [19.0, 1.9]}}) is None   # one dimension is not a size
    assert wb._own_size_mm({}) is None


# ── D-404: the 6 Oct 17:10 book's portal quotation (9598-03, 20 off) ─────────────────────
#
# "Material: Mild Steel, 400 Mic, Refer To Individual Component Drawings". The last phrase is
# the GA's title-block pointer: the extract returned it as the drawing's general material, the
# bumpers inherited it, and the quotation listed it as what the product is made of.

def test_a_pointer_note_is_never_a_material_on_the_quotation():
    import display_material as dm
    import drawing_facts as df
    from client_quote_html import _materials_line
    import extractor_patterns as ep
    assert ep.is_cross_reference_note("REFER TO INDIVIDUAL COMPONENT DRAWINGS")
    assert df._is_pointer("REFER TO INDIVIDUAL COMPONENT DRAWINGS")
    assert df._is_pointer("SEE ASSEMBLY DRAWING") and not df._is_pointer("MILD STEEL")
    bumper = {"part_number": "FIXING1270", "description": "BUMPER", "page_roles": ["bought_in"],
              "normalized_material": "REFER TO INDIVIDUAL COMPONENT DRAWINGS",
              "material_source": "llm_full_extract"}
    assert dm.display_material(bumper, "bought_in")["basis"] == dm.NOTHING
    assert dm.describes_the_product(bumper, "bought_in") is None
    frame = {"part_number": "9598-03-01M", "description": "METAL FRAME", "page_roles": ["detail"],
             "normalized_material": "MILD STEEL", "material_source": "drawing_deterministic"}
    assert _materials_line([frame, bumper]) == "Mild Steel"


def test_a_general_note_that_points_elsewhere_is_not_inherited():
    from source_connectors import llm_full_job as lfj
    parts = [{"part_number": "FIXING1270", "description": "BUMPER", "quantity": 4,
              "page_roles": ["bought_in"]}]
    job = {"found": True,
           "drawing_info": {"material_general": "REFER TO INDIVIDUAL COMPONENT DRAWINGS",
                            "finish_general": "REFER TO INDIVIDUAL COMPONENT DRAWINGS"},
           "parts": [{"part_number": "FIXING1270", "description": "BUMPER", "qty": 4}],
           "routes": []}
    lfj.apply_full_job_to_pre_estimate(parts, job)
    assert not parts[0].get("normalized_material")
    assert not parts[0].get("normalized_finish")
    assert not any("GENERAL" in f for f in parts[0].get("review_flags") or [])


# ── D-405: the 6 Oct 17:30 book on ad4259c (9598-03, 20 off) ─────────────────────────────
#
# "the drawing's fold callouts read 3" on a sheet printing UP 90° and DOWN 180°: the note rung
# counted the word FOLD in "BLOB WELD BOTH ENDS TO STOP FOLD OPENING" beside the two callouts.

def test_a_sheets_fold_statement_is_its_callouts_and_a_bare_word_beside_them_is_a_reference():
    import extractor_patterns as ep
    note = ep.fold_note_count(
        "BLOB WELD BOTH ENDS TO STOP FOLD OPENING  471.61  212  UP  90°  R 1  DOWN  180°  R 0.5")
    assert note == {"count": 2, "evidence": ["UP 90°", "DOWN 180°"]}
    assert ep.fold_note_count("FOLD 20mm RETURN, BEND AS SHOWN")["count"] == 2   # no callouts: words count
    assert ep.fold_note_count("MILD STEEL 1.2")["count"] == 0
    cues = ep.extract_feature_cues("UP 90° R 1 DOWN 180° R 0.5 TO STOP FOLD OPENING")
    assert cues["fold_count_textual"] == 2
    assert cues["fold_count_textual_evidence"] == ["UP 90°", "DOWN 180°"]


def test_the_fold_sentence_names_what_the_note_rung_counted():
    import fold_count as fc
    part = {"part_number": "X-01M", "fold_count_textual": 3,
            "fold_count_textual_evidence": ["UP 90°", "DOWN 180°", "FOLD"],
            "bend_count_dxf": 2, "geometry_source": "dxf", "dxf_augmented": True}
    out = fc.press_brake_folds(part)
    assert out["count"] == 2
    assert "read 3 (UP 90°, DOWN 180°, FOLD on its own sheet)" in out["disagreement"]


# ── D-406: M&S 12675-01, 7 Oct 17:52 book (design-intent pack on a drawings run) ─────────
#
# Three concept sheets titled DESIGN INTENT, every material field "SEE PART DRAWINGS", no parts
# list, no part sheets. The engine minted a part per drawing number: "40 x 20mm … OVAL TUBE"
# became a 40 x 20 blank of 20 mm stainless, "ESTIMATED BAG WEIGHT - 1.5kg" its weight, and the
# report said the pack read cleanly beside three failed checks.

_V2_SHEET = ("DESIGN INTENT ONLY 12 x CUSTOMER BAGS BRUSHED STAINLESS STEEL 5mm STAINLESSS STEEL BASE "
             "ON 18mm BLACK MFMDF WITH FEET 5mm STAINLESS STEEL ARMS LASERED 40 x 20mm STAINLESS STEEL "
             "FLAT SIDED OVAL TUBE CAPPED AND FINISHED ON TOP ESTIMATED BAG WEIGHT - 1.5kg "
             "WEIGHT: 34.82kg 600 x 400 BASE 1500 930")


def test_a_design_intent_sheet_is_not_a_detail_sheet_and_mints_no_part():
    import file_scan as fs
    role = fs._infer_page_role(_V2_SHEET, "", "12675-01-02 BLOCK MODEL V2 DRAWING No BAG STAND V2 - "
                               "DESIGN INTENT MATERIAL: SEE PART DRAWINGS")
    assert role["primary_role"] == "design_intent" and "design_intent_detected" in role["signals"]
    # a real detail sheet and a GA with a parts list keep their roles
    assert fs._infer_page_role("UP 90° R 1 DOWN 180° FLAT PATTERN", "",
                               "9598-03-01M DRAWING No METAL FRAME MATERIAL: MILD STEEL")["primary_role"] == "detail"
    assert fs._infer_page_role("ITEM DWG NO. DESCRIPTION QTY 1 9598-03-01M METAL FRAME 1 2 FIXING1270 BUMPER 4",
                               "ITEM DWG NO QTY 1 9598-03-01M 1", "9598-03-GA DRAWING No")["primary_role"] == "assembly"
    assert fs.design_intent_pages({"pages": [{"page_number": 1, "page_role": {"primary_role": "design_intent"}},
                                             {"page_number": 2, "page_role": {"primary_role": "detail"}}]}) == [1]
    # the part index reads the role before it mints: a design-intent page contributes nothing
    src = (ROOT / "src" / "part_index.py").read_text(encoding="utf-8")
    assert 'if page_role == "design_intent":' in src


def test_a_section_callout_is_neither_a_gauge_nor_a_blank():
    import extractor_patterns as ep
    assert ep._extract_thickness_fallbacks(_V2_SHEET) == ["5", "18"]        # not the tube's 20
    dims = ep.classify_dimensions(_V2_SHEET)
    assert "600 x 400" in dims["overall_sizes_mm"] and "40 x 20" not in dims["overall_sizes_mm"]
    assert ep.names_a_section("30 x 30 x 2mm SHS UPRIGHT", 0, 13)
    assert not ep.names_a_section("471.61 x 212 BLANK 1.2mm MILD STEEL", 0, 12)
    # a plain blank keeps its gauge reading
    assert "2" in ep._extract_thickness_fallbacks("BLANK 300 x 200 2mm MILD STEEL")


def test_a_weight_the_sheet_qualifies_as_something_elses_is_not_the_parts():
    import extractor_patterns as ep
    assert ep.extract_title_block_fields(_V2_SHEET)["weights"] == ["34.82kg"]
    assert ep.strip_weights_not_the_parts("ESTIMATED BAG WEIGHT - 1.5kg WEIGHT: 0.40kg").strip().endswith("WEIGHT: 0.40kg")
    assert ep.extract_title_block_fields("MAX LOADING: WEIGHT: 398.43g")["weights"] == ["398.43g"]


def test_the_report_never_says_the_pack_read_cleanly_beside_a_failed_check():
    import job_report_html as jr
    dq = {"dxf_matched": 0, "dxf_unmatched": 0, "dxf_ambiguous": 0, "validation_issues": [],
          "parts_without_dxf": [], "filename_space_issues": [], "low_confidence": []}
    clean = jr._render_drawing_analysis(dict(dq), {"pages": [], "invariants": {"violations": []}})
    assert "No significant drawing faults detected" in clean
    failed = jr._render_drawing_analysis(dict(dq), {
        "pages": [{"page_number": 1, "page_role": {"primary_role": "design_intent"}}],
        "invariants": {"violations": [{"code": "native_extract_refused", "severity": "blocking"},
                                      {"code": "blank_and_cut_path_disagree", "severity": "blocking"}]}})
    assert "No significant drawing faults detected" not in failed
    assert "Consistency checks failed" in failed and "SolidWorks extract refused" in failed
    assert "Design-intent sheets" in failed


# ── D-407: the sheet's charge and the engine's material basis (12675-01, 18:32 book) ─────

def test_a_nested_line_charged_at_another_order_of_magnitude_from_its_engine_basis_fails():
    s = {"final_estimate": {"material_rows": [
            {"part_number": "12675-01-02", "block": "steel", "qty_per_unit": 1,
             "total_value_gbp": 0.05, "charged_cell": "Estimate!M93"},
            {"part_number": "FIXING1270", "block": "bought_in", "qty_per_unit": 4, "total_value_gbp": 0.37}]},
         "estimate_summary": {"part_estimates": [
            {"part_number": "12675-01-02", "material_estimate": {"unit_material_cost_gbp": 112.26,
                                                                  "cost_method": "stated_weight"}},
            {"part_number": "FIXING1270", "material_estimate": {"unit_material_cost_gbp": 9.0}}]}}
    out = invariants.check_the_sheets_charge_agrees_with_the_engines_material_basis(s)
    assert out and out[0]["severity"] == invariants.BLOCKING
    assert "12675-01-02 charged £0.05 a unit (Estimate!M93) against an engine basis of £112.26" in out[0]["message"]
    assert "FIXING1270" not in out[0]["message"]                      # a bought-in is not a nested line
    # the control: a nested line whose two readings agree, and a cheap line, pass
    s["final_estimate"]["material_rows"][0]["total_value_gbp"] = 110.0
    assert invariants.check_the_sheets_charge_agrees_with_the_engines_material_basis(s) == []
    s["final_estimate"]["material_rows"][0]["total_value_gbp"] = 0.05
    s["estimate_summary"]["part_estimates"][0]["material_estimate"]["unit_material_cost_gbp"] = 0.4
    assert invariants.check_the_sheets_charge_agrees_with_the_engines_material_basis(s) == []


def test_a_dxf_that_is_a_drawing_of_a_part_never_mints_a_part(tmp_path):
    import ezdxf
    import drawing_job_merge as djm
    sheet = tmp_path / "12675-01-02 Block Model V2.dxf"
    d = ezdxf.new("R2000"); ms = d.modelspace()
    ms.add_line((0, 0), (420, 0)); ms.add_line((420, 0), (420, 297))
    ms.add_linear_dim(base=(0, -10), p1=(0, 0), p2=(420, 0))
    ms.add_text("12675-01-02 BLOCK MODEL V2").set_placement((10, 10))
    d.saveas(sheet)
    report = {}
    assert djm.dxf_may_mint_a_part(sheet, report, "12675-01-02") is False
    assert report["unmatched_dxf"][0]["reason"].startswith("drawing_export_not_a_flat")
    flat = tmp_path / "X-01M_1.2mm MS.dxf"
    f = ezdxf.new("R2000"); fm = f.modelspace()
    fm.add_lwpolyline([(0, 0), (200, 0), (200, 100), (0, 100)], close=True)
    f.saveas(flat)
    assert djm.dxf_may_mint_a_part(flat, {}, "X-01M") is True
