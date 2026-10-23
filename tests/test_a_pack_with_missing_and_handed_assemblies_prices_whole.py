"""D-505: a drawing pack with a missing sub-assembly drawing, a handed kit and unsized sheets
is priced whole and consistently — the generic faults the 12665-01-GA book exposed.

The 13 Oct 12:39 book (£647.22 at one off) and its reviewer: "material, assembly and routing
inconsistencies — not just a few prices awaiting confirmation":

  ONE SCOPE. Six parts the header called "set aside, not priced" still carried laser, fold
  and assembly rows with no material beside them. A line the declared product does not reach
  leaves the labour block exactly as it leaves the material blocks.

  A MISSING GA KEEPS ITS FAMILY. The header 12665-04-GA was listed but not drawn; its
  fascias and frame were drawn and set aside. An assembly that names no members takes the
  pack's drawings numbered under it that nothing else claims — as a question, never silently.

  A HANDED KIT IS THE KIT MIRRORED. 12665-03-GA-H became a 400 x 300 x 6 acrylic blank (laser,
  glue, hand work) while its own steel wing and lighting hung unlinked. A hand of an assembly
  takes the base's members, each by its own hand where the pack has one; the general material
  note never makes a kit or a purchase into a cut part.

  AN UNSIZED SHEET STILL HAS A SIZE. Four parts with their own detail sheets were refused a
  blank (the reader keeps only figures printed with "mm"), costed on a category default, their
  coat on 0.0055 m². The sheet's two largest printed figures, developed for its folds at the
  house flange allowance, are a labelled provisional blank.

  NO SILENT £0, AND THE FULLER FOLD COUNT. A bought line coded "-GA" (another job's drawing)
  may be researched; where no model and no flat exist and nobody wrote a fold count, the
  sheet's per-bend callouts beat a de-duplicated angle list.
"""
from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import route_compiler as rc                                            # noqa: E402
import part_code_conventions as pcc                                    # noqa: E402


def _p(pn, desc, **kw):
    return dict(part_number=pn, description=desc, quantity=kw.pop("q", 1), **kw)


def _island():
    parts = [_p("9001-01-GA", "ISLAND"), _p("9001-03-GA", "SIDE WING"),
             _p("9001-03-GA-H", "SIDE WING - HANDED"),
             _p("9001-03-01M", "WING", normalized_material="MILD_STEEL"),
             _p("9001-03-02X", "LIGHTING"), _p("FIXING-3.5", "SCREW", page_roles=["bought_in"]),
             _p("9001-03-01M-H", "WING H", normalized_material="MILD_STEEL"),
             _p("9001-03-02X-H", "LIGHTING H"),
             _p("9001-04-GA", "ISLAND NEW / PACKOUT HEADER"),
             _p("9001-04-201", "NEW FASCIA ASSEMBLY"),
             _p("9001-04-02M", "FASCIA", normalized_material="MILD_STEEL"),
             _p("9001-04-01M", "HEADER FRAME", normalized_material="MILD_STEEL"),
             _p("9001-04-301", "PACKOUT FASCIA ASSEMBLY"),
             _p("9001-04-04M", "PACKOUT FRONT", normalized_material="MILD_STEEL")]
    extract = {"top_assembly": {"part_number": "9001-01-GA"}, "assemblies": [
        {"part_number": "9001-01-GA", "children": [
            {"part_number": "9001-03-GA", "qty": 1}, {"part_number": "9001-03-GA-H", "qty": 1},
            {"part_number": "9001-04-GA", "qty": 1}]},
        {"part_number": "9001-03-GA", "children": [
            {"part_number": "9001-03-01M", "qty": 1}, {"part_number": "9001-03-02X", "qty": 1},
            {"part_number": "FIXING-3.5", "qty": 2}]},
        {"part_number": "9001-04-201", "children": [{"part_number": "9001-04-02M", "qty": 1}]},
        {"part_number": "9001-04-301", "children": [{"part_number": "9001-04-04M", "qty": 1}]},
    ]}
    return parts, extract


def _graph():
    parts, extract = _island()
    return rc.build_part_graph(parts, extract, declared_product="9001-01-GA")


def _kids(graph, pn):
    node = next(n for n in graph["nodes"] if n.part_number == pn)
    return {c.part_number: c.qty for c in node.children}


# ── a missing GA keeps its family ────────────────────────────────────────────────────

def test_an_assembly_with_no_drawing_takes_the_drawings_numbered_under_it():
    g = _graph()
    assert set(_kids(g, "9001-04-GA")) == {"9001-04-01M", "9001-04-201", "9001-04-301"}
    issue = next(i for i in g["issues"] if i.get("code") == "members_adopted_by_numbering")
    assert issue["assembly"] == "9001-04-GA"


def test_nothing_the_product_needs_is_set_aside_any_more():
    g = _graph()
    gone = rc.outside_product_identities(g["issues"])
    assert not gone, f"set aside: {sorted(gone)}"
    assert g["quantities"]["9001-04-02M"] == 1.0 and g["quantities"]["9001-04-04M"] == 1.0


def test_numbering_alone_proposes_a_member_but_does_not_charge_it():
    parts, extract = _island()
    parts.append(_p("9001-04-99M", "SPARE BRACKET", normalized_material="MILD_STEEL"))
    g = rc.build_part_graph(parts, extract, declared_product="9001-01-GA")
    assert "9001-04-99M" not in _kids(g, "9001-04-GA")
    proposed = next(i for i in g["issues"] if i.get("code") == "members_proposed_by_numbering")
    assert proposed["candidates"] == ["9001-04-99M"]
    assert "9001-04-99M" in rc.outside_product_identities(g["issues"]), "kept out of the price"


def test_the_assemblys_description_can_come_from_the_parts_list_row_alone():
    parts, extract = _island()
    parts = [p for p in parts if p["part_number"] != "9001-04-GA"]
    rows = [{"part_number": "9001-04-GA", "description": "ISLAND NEW / PACKOUT HEADER",
             "quantity": 1, "bom_parent": "9001-01-GA"}]
    g = rc.build_part_graph(parts, extract, bom_rows=rows, declared_product="9001-01-GA")
    assert set(_kids(g, "9001-04-GA")) == {"9001-04-01M", "9001-04-201", "9001-04-301"}


def test_a_drawing_another_assembly_owns_is_never_adopted():
    parts, extract = _island()
    extract["assemblies"].append({"part_number": "9001-03-GA",
                                  "children": [{"part_number": "9001-04-01M", "qty": 1}]})
    g = rc.build_part_graph(parts, extract, declared_product="9001-01-GA")
    assert "9001-04-01M" not in _kids(g, "9001-04-GA")


def test_the_adopted_line_says_so_on_its_record():
    parts, extract = _island()
    rc.apply_canonical_evidence_to_parts(parts, extract, summary={"declared_product": "9001-01-GA"})
    frame = next(p for p in parts if p["part_number"] == "9001-04-01M")
    flag = next(f for f in frame.get("review_flags") or []
                if "whose drawing is not in the pack" in str(f))
    assert "shares HEADER" in flag, "the corroboration is said, not just the numbering"


# ── a handed kit is the kit mirrored ─────────────────────────────────────────────────

def test_a_handed_assembly_takes_its_bases_members_by_their_own_hands():
    g = _graph()
    assert _kids(g, "9001-03-GA-H") == {"9001-03-01M-H": 1.0, "9001-03-02X-H": 1.0,
                                       "FIXING-3.5": 2.0}
    kinds = {n.part_number: n.kind for n in g["nodes"]}
    assert kinds["9001-03-GA-H"] == "assembly"
    assert g["quantities"]["FIXING-3.5"] == 4.0, "two screws in each hand"


def test_hardware_the_parent_already_lists_is_not_copied_into_the_hand():
    parts, extract = _island()
    extract["assemblies"][0]["children"].append({"part_number": "FIXING-3.5", "qty": 4})
    g = rc.build_part_graph(parts, extract, declared_product="9001-01-GA")
    assert "FIXING-3.5" not in _kids(g, "9001-03-GA-H")
    assert {"9001-03-01M-H", "9001-03-02X-H"} <= set(_kids(g, "9001-03-GA-H"))


def test_a_hand_with_any_stated_member_keeps_its_own_list():
    parts, extract = _island()
    extract["assemblies"].append({"part_number": "9001-03-GA-H",
                                  "children": [{"part_number": "9001-03-01M-H", "qty": 1}]})
    g = rc.build_part_graph(parts, extract, declared_product="9001-01-GA")
    assert _kids(g, "9001-03-GA-H") == {"9001-03-01M-H": 1.0}


def test_a_hand_of_a_cut_part_with_hardware_stays_a_part():
    flat = dict(dxf_augmented=True, blank_length_mm=300, blank_width_mm=200,
                geometry_source="dxf_flat_pattern", normalized_material="MILD_STEEL")
    parts = [_p("9002-GA", "TOP"), _p("9002-05-01M", "CAP", **flat),
             _p("9002-05-01M-H", "CAP H", **flat),
             _p("PEM-M6", "PEM STUD", page_roles=["bought_in"])]
    extract = {"top_assembly": {"part_number": "9002-GA"}, "assemblies": [
        {"part_number": "9002-GA", "children": [{"part_number": "9002-05-01M", "qty": 1},
                                               {"part_number": "9002-05-01M-H", "qty": 1}]},
        {"part_number": "9002-05-01M", "children": [{"part_number": "PEM-M6", "qty": 2}]}]}
    g = rc.build_part_graph(parts, extract, declared_product="9002-GA")
    kinds = {n.part_number: n.kind for n in g["nodes"]}
    assert kinds["9002-05-01M-H"] == kinds["9002-05-01M"] == "leaf", \
        "a cut part carrying studs is a part; so is its other hand (D-280)"


def test_numbering_conventions_read_through_a_hand():
    assert pcc.carries_assembly_role("12665-03-GA-H")
    assert pcc.purchased_suffix("12665-03-02X-H") == "X"
    assert pcc.material_suffix("12665-03-01M-H") == "M"
    assert not pcc.carries_assembly_role("ABC-LEFT")
    assert pcc.strip_assembly_role("12665-03-GA-H") == "12665-03-GA-H", \
        "the role is never stripped off a hand — it would merge the hand onto its base"


def test_the_general_material_note_never_makes_a_kit_or_a_purchase_a_cut_part():
    from source_connectors.llm_full_job import apply_full_job_to_pre_estimate
    parts = [_p("9001-03-GA-H", "SIDE WING - HANDED"), _p("P/P-JST-SPLITTER", "JST Y SPLITTER"),
             _p("9001-02-01M", "BACK PANEL")]
    job = {"found": True, "drawing_info": {"material_general": "ACRYLIC",
                                           "finish_general": "POWDER COATED"},
           "parts": [{"part_number": "9001-03-GA-H"},
                     {"part_number": "P/P-JST-SPLITTER", "is_bought_in": True},
                     {"part_number": "9001-02-01M"}]}
    apply_full_job_to_pre_estimate(parts, job)
    kit, cable, panel = parts
    assert not kit.get("normalized_material") and not kit.get("normalized_finish")
    assert not cable.get("normalized_material")
    assert panel.get("normalized_material"), "a part we cut still takes the general note"


def test_the_acrylic_route_stands_down_for_kits_and_purchases():
    from estimator import _acrylic_route_stands_down
    assert _acrylic_route_stands_down({"part_number": "9001-03-GA-H"})
    assert _acrylic_route_stands_down({"part_number": "P/P-JST-SPLITTER",
                                       "page_roles": ["bought_in"]})
    assert not _acrylic_route_stands_down({"part_number": "9001-05-01A",
                                           "normalized_material": "ACRYLIC"})


def test_an_assemblys_hand_is_not_told_its_mirror_failed():
    from drawing_job_merge import apply_mirror_geometry
    parts = [_p("9001-03-GA-H", "SIDE WING - HANDED")]
    apply_mirror_geometry(parts)
    assert not any("MIRROR NOT APPLIED" in str(f) for f in parts[0].get("review_flags") or [])


# ── one scope for material and labour ────────────────────────────────────────────────

def test_a_route_naming_a_set_aside_part_charges_it_nothing():
    parts = [_p("9003-GA", "PRODUCT"), _p("9003-01M", "PANEL", normalized_material="MILD_STEEL"),
             _p("7777-01M", "OTHER JOB PANEL", normalized_material="MILD_STEEL")]
    extract = {"top_assembly": {"part_number": "9003-GA"},
               "assemblies": [{"part_number": "9003-GA",
                               "children": [{"part_number": "9003-01M", "qty": 1}]}],
               "routes": [{"operation": "laser_cutting", "scope": "part",
                           "part_numbers": ["9003-01M", "7777-01M"]}]}
    route = rc.compile_job_route(parts, extract, declared_product="9003-GA")
    targets = {d.get("target_id") for d in route["decisions"]
               if d.get("operation") == "laser_cutting" and d.get("status") == "required"}
    assert "7777-01M" not in targets and "9003-01M" in targets
    assert any(i.get("code") == "route_participant_outside_the_product"
               for i in route["issues"])


def test_the_labour_block_follows_the_set_aside_ledger():
    import wb_populate as wb
    summary = {"estimate_summary": {"canonical_route_shadow": {"decisions": [
        {"decision_id": "d1", "operation": "laser_cutting", "status": "required",
         "target_id": "A-01M", "participants": ["A-01M"], "scope": "part", "qty_per_unit": 1},
        {"decision_id": "d2", "operation": "laser_cutting", "status": "required",
         "target_id": "B-01M", "participants": ["B-01M"], "scope": "part", "qty_per_unit": 1}],
        "nodes": [{"part_number": "A-01M", "qty_per_unit": 1},
                  {"part_number": "B-01M", "qty_per_unit": 1}], "issues": []}},
        "set_aside_outside_product": [{"part_number": "B-01M",
                                       "reason": "not_linked_to_the_product"}]}
    pes = [{"part_number": p, "normalized_material": "MILD_STEEL",
            "normalized_thickness_mm": 1.5, "quantity": 1} for p in ("A-01M", "B-01M")]
    groups = wb.canonical_labour_groups(summary, pes, 1)
    charged = {p for g in groups.values() for p in (g.get("parts") or [])}
    assert charged == {"A-01M"}


# ── an unsized sheet still has a size ───────────────────────────────────────────────

fitz = pytest.importorskip("fitz")


def _sheet(tmp_path, words):
    doc = fitz.open()
    page = doc.new_page(width=1191, height=842)                     # A3 landscape
    for (x, y), text, rot in words:
        page.insert_text((x, y), text, fontsize=9, rotate=rot)
    path = tmp_path / "sheet.pdf"
    doc.save(str(path))
    doc.close()
    return {"page_number": 8, "source_pdf_path": str(path), "source_page_number": 1}


def test_the_sheets_printed_figures_are_read_and_the_title_block_left_out(tmp_path):
    import detail_page_geometry as dpg
    page = _sheet(tmp_path, [((200, 200), "1500", 0), ((150, 400), "400", 90),
                             ((300, 300), "50", 0), ((320, 330), "8", 0),
                             ((1000, 800), "2026", 0), ((900, 780), "3500", 0)])
    assert sorted(dpg.printed_dimension_values(page)) == [50.0, 400.0, 1500.0]


def test_a_folded_part_gets_a_developed_provisional_blank(tmp_path):
    import detail_page_geometry as dpg
    page = _sheet(tmp_path, [((200, 200), "1500", 0), ((150, 400), "400", 90)])
    part = {"part_number": "9001-03-01M", "normalized_material": "MILD_STEEL",
            "normalized_thickness_mm": 1.5, "textual_operations": ["folding"],
            "fold_count_textual": 2}
    blank = dpg.provisional_blank_from_sheets(part, [page])
    assert blank["formed"] == (1500.0, 400.0)
    assert (blank["length"], blank["width"]) == (1500.0, 450.0), "two 25 mm flanges"
    assert "house allowance" in blank["working"]


def test_figures_that_run_one_way_give_no_blank(tmp_path):
    import detail_page_geometry as dpg
    page = _sheet(tmp_path, [((200, 200), "1500", 0), ((300, 300), "400", 0)])
    part = {"part_number": "9001-03-01M", "normalized_material": "MILD_STEEL",
            "normalized_thickness_mm": 1.5}
    assert dpg.provisional_blank_from_sheets(part, [page]) is None
    assert "two axes" in part["_provisional_blank_refused"]


def test_a_flat_pattern_on_the_sheet_is_not_developed_again(tmp_path):
    import detail_page_geometry as dpg
    page = _sheet(tmp_path, [((200, 200), "1550", 0), ((150, 400), "450", 90),
                             ((200, 120), "FLAT PATTERN", 0)])
    part = {"part_number": "9001-03-01M", "normalized_material": "MILD_STEEL",
            "normalized_thickness_mm": 1.5, "fold_count_textual": 2}
    blank = dpg.provisional_blank_from_sheets(part, [page])
    assert (blank["length"], blank["width"]) == (1550.0, 450.0) and blank["developed"]


def test_stated_flange_depths_are_used_before_the_allowance(tmp_path):
    import detail_page_geometry as dpg
    page = _sheet(tmp_path, [((200, 200), "1500", 0), ((150, 400), "400", 90)])
    part = {"part_number": "9001-03-01M", "normalized_material": "MILD_STEEL",
            "normalized_thickness_mm": 1.5, "fold_count_textual": 2,
            "fold_values_mm": ["40", "40"]}
    blank = dpg.provisional_blank_from_sheets(part, [page])
    assert (blank["length"], blank["width"]) == (1500.0, 480.0)
    assert "the drawing states" in blank["working"] and "house allowance" not in blank["working"]


def test_the_weight_checks_the_blank_it_does_not_decide_it(tmp_path):
    """Review of D-508: a blank legitimately weighs MORE than its finished part (cut-outs are
    bought and thrown away), so heavier is kept and asked; only a blank LIGHTER than the part
    cut from it — impossible — is refused."""
    import detail_page_geometry as dpg
    page = _sheet(tmp_path, [((200, 200), "1500", 0), ((150, 400), "400", 90)])
    heavier = {"part_number": "9001-03-01M", "normalized_material": "MILD_STEEL",
               "normalized_thickness_mm": 1.5, "stated_weight_g": 1500}     # ~0.13 m² of steel
    kept = dpg.provisional_blank_from_sheets(heavier, [page])
    assert kept is not None and "cut-outs" in kept["working"] and "asked" in kept["working"]
    lighter = dict(heavier, stated_weight_g=14000)                         # ~1.19 m² of steel
    assert dpg.provisional_blank_from_sheets(lighter, [page]) is None
    assert "LESS than the finished part" in lighter["_provisional_blank_refused"]
    ok = dict(heavier, stated_weight_g=7000)                                # ~0.59 m²
    assert "agrees" in dpg.provisional_blank_from_sheets(ok, [page])["working"]


def test_the_weight_is_read_where_the_title_block_puts_it(tmp_path):
    """D-506 read only stated_weight_g/kg; 12665's sheets carry WEIGHT as text in `weights`
    ("70g", "2.9kg"), so the check never ran. Both units, and the title-block copy, count."""
    import detail_page_geometry as dpg
    assert dpg._stated_weight_kg({"weights": ["70g"]}) == pytest.approx(0.07)
    assert dpg._stated_weight_kg({"weights": "2.9 KG"}) == pytest.approx(2.9)
    assert dpg._stated_weight_kg({"title_block": {"weights": ["1.99kg"]}}) == pytest.approx(1.99)
    assert dpg._stated_weight_kg({"weights": ["9000kg"]}) is None
    page = _sheet(tmp_path, [((200, 200), "1500", 0), ((150, 400), "400", 90)])
    part = {"part_number": "9001-03-01M", "normalized_material": "MILD_STEEL",
            "normalized_thickness_mm": 1.5, "weights": ["14kg"]}
    assert dpg.provisional_blank_from_sheets(part, [page]) is None


def test_a_refused_overall_is_replaced_by_the_provisional_blank(tmp_path):
    import detail_page_geometry as dpg
    page = _sheet(tmp_path, [((200, 200), "1500", 0), ((150, 400), "400", 90)])
    page["page_analysis"] = {"dimensions": {"overall_length_mm": 8.0, "overall_width_mm": 5.0}}
    part = {"part_number": "9001-05-01M", "pages": [8], "normalized_material": "MILD_STEEL",
            "normalized_thickness_mm": 1.5,
            "normalized_geometry": {"blank_length_mm": 350, "blank_width_mm": 250,
                                    "blank_length_mm_source": "geometry_inference",
                                    "_inferred": True}}
    dpg.apply_detail_page_geometry([part], {"pages": [page]})
    ng = part["normalized_geometry"]
    assert (ng["blank_length_mm"], ng["blank_width_mm"]) == (1500.0, 400.0)
    assert ng["blank_length_mm_source"] == dpg.PROVISIONAL_SOURCE
    assert part["blank_is_inferred"] is True
    assert any("PROVISIONAL BLANK" in str(f) for f in part["review_flags"])
    assert not any("fallback envelope" in str(f) for f in part["review_flags"])


def test_a_sheet_with_too_little_printed_says_unresolved_as_before(tmp_path):
    import detail_page_geometry as dpg
    page = _sheet(tmp_path, [((200, 200), "1500", 0)])
    page["page_analysis"] = {"dimensions": {"overall_length_mm": 8.0, "overall_width_mm": 5.0}}
    part = {"part_number": "9001-05-02M", "pages": [8], "normalized_material": "MILD_STEEL",
            "normalized_thickness_mm": 1.5}
    dpg.apply_detail_page_geometry([part], {"pages": [page]})
    assert any("fallback envelope" in str(f) for f in part["review_flags"])


def test_the_provisional_source_ranks_between_a_default_and_a_printed_overall():
    import source_precedence as sp
    assert sp.rank("geometry_inference") < sp.rank("printed_extents_provisional") \
        < sp.rank("pdf_overall_dims")
    assert not sp.was_measured("printed_extents_provisional")


# ── no silent £0, and the fuller fold count ──────────────────────────────────────────

def test_a_bought_line_coded_ga_may_be_researched():
    from pricing_service import is_something_you_can_buy
    hook = {"part_number": "9370-66-GA", "description": "200mm Euro Hook",
            "page_roles": ["bought_in"], "quantity": 9}
    assert is_something_you_can_buy(hook, structure_decides=False)
    kit = dict(hook, assembly_children=["9370-66-01"])
    assert not is_something_you_can_buy(kit, structure_decides=False)
    drawn = {"part_number": "9001-04-GA", "description": "HEADER"}
    assert not is_something_you_can_buy(drawn, structure_decides=False)


def test_sheet_callouts_beat_a_deduplicated_angle_list_when_nothing_else_counts():
    import fold_count as fc
    part = {"angles_deg": ["90", "45"], "drawing_bend_callouts": 7}
    out = fc.press_brake_folds(part)
    assert out["count"] == 7 and out["source"] == fc.CALLOUTS_ONLY
    assert not out["measured"]


def test_a_fold_count_the_drawing_office_wrote_still_stands():
    import fold_count as fc
    part = {"fold_count_textual": 2, "drawing_bend_callouts": 7}
    out = fc.press_brake_folds(part)
    assert out["count"] == 2 and "callouts" in (out["disagreement"] or "")


def test_callouts_past_the_drawn_bend_lines_are_not_charged():
    import fold_count as fc
    part = {"angles_deg": ["90"], "drawing_bend_callouts": 7,
            "geometry_rollup": {"dashed_long_axis_lines": 4}}
    out = fc.press_brake_folds(part)
    # Not the seven callouts. Since D-592a not the lone 90° either — an angle is not a fold
    # count — so the drawn bend lines are the charge, and the callouts are still said.
    assert out["count"] == 4 and out["source"] == fc.DASHED_PROXY
    assert "callouts" in (out["disagreement"] or "")


def test_a_model_still_has_to_confirm_callouts_over_a_flat():
    import fold_count as fc
    part = {"bend_count_dxf": 3, "drawing_bend_callouts": 7}
    assert fc.press_brake_folds(part)["count"] == 3
