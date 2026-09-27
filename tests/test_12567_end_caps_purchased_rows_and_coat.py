"""12567-01-GA full-bay kit at 163 off (26 Sep, the 14:46 book): six generic faults.

D-262  twelve P/P rows on the end header's table: "P/P" was read as an identity, so the
       grommets' 3 landed on the JST lead and the grommets, Velcro and EPDM tapes left the bill.
D-263  a P/P-coded LED driver and MAGNET21 were nested as steel, lasered, folded and powder
       coated — purchase-class and catalogue-family codes are bought-in by construction.
D-264  12567-05-01M END CAP, a measured 1.5 mm flat with two PEM studs on its own sheet, was
       made an assembly by the studs and lost its laser, fold and sheet row.
D-265  12567-05-02M's sheet says "symmetrically opposite — refer to drawing 12567-05-01M";
       no code marker, so no mirror; and the model offered 12 mm as its gauge with no flat.
D-266  12567-02-101, coated as one thing, had no area of its own: the case's powder was timed
       on nothing. The coat is over the sum of its members' blanks.
D-267  the shop's confirmed 1.0 mm rule was "NOT applied" by a quorum of readers of the drawn
       0.9 mm while the sheet, rightly, costed 1 mm.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import bought_in_policy as bip  # noqa: E402
import drawing_job_merge as djm  # noqa: E402
import estimator as est  # noqa: E402
import merge_boms as mb  # noqa: E402
import route_compiler as rc  # noqa: E402
import source_precedence as sp  # noqa: E402


# ── D-262: P/P rows keep their own identities through the dual-path reconcile ─────────────

def _row(item, code, desc, qty):
    return {"item_number": item, "part_ref": code, "description": desc, "quantity": qty}


def test_a_purchase_class_word_is_not_an_identity():
    assert mb._identity("P/P") == ""
    assert mb._identity("FIXING") == ""
    assert mb._identity("FIXING49") == "FIXING49"


def test_two_pp_rows_under_one_item_number_stay_two_lines():
    a = [_row("12", "P/P", "SEMI BLIND RUBBER GROMMET [G10-RSB350-12-00C]", 3),
         _row("13", "P/P", "25mm SELF-ADHESIVE VELCRO - LOOP, BLACK. 85mm", 1)]
    b = [_row("12", "P/P", "JST 1m MALE/FEMALE EXTENSION", 2)]
    rows, _ = mb.reconcile_page({"rows": a}, {"rows": b}, "12567-02-GA")
    descs = {str(r.get("description")): int(r["quantity"]) for r in rows}
    assert descs.get("SEMI BLIND RUBBER GROMMET [G10-RSB350-12-00C]") == 3
    assert descs.get("25mm SELF-ADHESIVE VELCRO - LOOP, BLACK. 85mm") == 1
    assert descs.get("JST 1m MALE/FEMALE EXTENSION") == 2


# ── D-263: purchase-class and catalogue-family codes are bought-in ────────────────────────

def test_a_pp_coded_article_is_bought_in_whatever_material_it_inherited():
    driver = {"part_number": "P/P-LED-POWER-DRIVER-3M",
              "description": "LED POWER DRIVER, 3m AC CABLE, UK 3-PIN PLUG",
              "normalized_material": "MILD_STEEL"}
    assert bip.is_bought_in(driver)
    assert "purchase class" in bip.bought_in_reason(driver)
    assert bip.is_bought_in({"part_number": "P/P", "description": "BUMPON"})


def test_a_word_and_a_number_is_a_catalogue_family_code():
    assert bip.is_bought_in({"part_number": "MAGNET21",
                             "description": "NEODYMIUM BAR MAGNET 50x10x1.50mm",
                             "normalized_material": "MILD_STEEL"})
    # a drawing number is never one, and a measured flat always outranks the shape
    assert not bip.is_bought_in({"part_number": "12567-03-01M", "description": "BACK PANEL",
                                 "normalized_material": "MILD_STEEL"})
    assert not bip.is_bought_in({"part_number": "MAGNET21", "flat_pattern_detected": True})


# ── D-264: a part carrying hardware on its own sheet is a cut part, not an assembly ───────

def _graph(children):
    parts = [
        {"part_number": "12567-05-GA", "description": "END CAPS"},
        {"part_number": "12567-05-01M", "description": "END CAP", "flat_pattern_detected": True,
         "geometry_source": "dxf", "normalized_material": "MILD_STEEL",
         "normalized_geometry": {"blank_length_mm": 409.5, "blank_width_mm": 88.0}},
        {"part_number": "BI-PEMSTUD", "description": "M6x20mm THREADED PEM STUD",
         "is_bought_in": True},
        {"part_number": "12567-05-03M", "description": "STIFFENER", "flat_pattern_detected": True,
         "normalized_material": "MILD_STEEL"},
    ]
    extract = {"top_assembly": {"part_number": "12567-05-GA"},
               "assemblies": [
                   {"part_number": "12567-05-GA", "children": [{"part_number": "12567-05-01M", "qty": 1}]},
                   {"part_number": "12567-05-01M", "children": children}]}
    g = rc.build_part_graph(parts, extract)
    return {n.part_number: n for n in g["nodes"]}


def test_a_measured_part_with_only_studs_under_it_stays_a_leaf():
    nodes = _graph([{"part_number": "BI-PEMSTUD", "qty": 2}])
    assert nodes["12567-05-01M"].kind == "leaf"
    assert nodes["12567-05-GA"].kind == "assembly"


def test_one_cut_child_makes_it_an_assembly_as_before():
    nodes = _graph([{"part_number": "BI-PEMSTUD", "qty": 2},
                    {"part_number": "12567-05-03M", "qty": 1}])
    assert nodes["12567-05-01M"].kind == "assembly"


def test_the_end_caps_laser_is_not_ruled_off_by_its_studs():
    parts = [
        {"part_number": "12567-05-GA", "description": "END CAPS"},
        {"part_number": "12567-05-01M", "description": "END CAP", "flat_pattern_detected": True,
         "geometry_source": "dxf", "normalized_material": "MILD_STEEL",
         "textual_operations": ["laser_cutting", "folding"], "is_sub_assembly": True},
        {"part_number": "BI-PEMSTUD", "description": "M6x20mm THREADED PEM STUD",
         "is_bought_in": True, "quantity": 2},
    ]
    extract = {"top_assembly": {"part_number": "12567-05-GA"},
               "assemblies": [
                   {"part_number": "12567-05-GA", "children": [{"part_number": "12567-05-01M", "qty": 1}]},
                   {"part_number": "12567-05-01M", "children": [{"part_number": "BI-PEMSTUD", "qty": 2}]}],
               "routes": [{"operation": "laser_cutting", "scope": "part",
                           "part_numbers": ["12567-05-01M"]}]}
    graph = rc.compile_job_route(parts, extract)
    ds = [d if isinstance(d, dict) else d.__dict__ for d in (graph.get("decisions") or [])]
    lasers = [d for d in ds if d.get("operation") == "laser_cutting"
              and d.get("target_id") == "12567-05-01M"]
    assert lasers and all(d.get("status") == "required" for d in lasers), lasers
    assert not [d for d in ds if d.get("operation") == "assembly"
                and d.get("target_id") == "12567-05-01M" and d.get("status") == "required"]


# ── D-265: the sheet names the hand ───────────────────────────────────────────────────────

_NOTE = ("THIS PART SYMMETRICALLY OPPOSITE TO HANDED VERSION - REFER TO DRAWING 12567-05-01M "
         "FOR ALL DETAILS\nEND CAP - HANDED\n12567-05-02M")


def _summary(text_p3=_NOTE):
    return {"pages": [
        {"page_number": 1, "text": "ITEM DWG NO. DESCRIPTION QTY 1 12567-05-01M END CAP 1 "
                                   "2 12567-05-02M END CAP - HANDED 1 REFER TO DRAWING 12567-05-01M"},
        {"page_number": 2, "text": "END CAP 12567-05-01M DOWN 90 R 1.32"},
        {"page_number": 3, "text": text_p3},
    ]}


def _hands():
    base = {"part_number": "12567-05-01M", "description": "END CAP", "pages": [1, 2],
            "flat_pattern_detected": True, "geometry_source": "dxf",
            "normalized_material": "MILD_STEEL", "normalized_thickness_mm": 1.5,
            "normalized_geometry": {"blank_length_mm": 409.5, "blank_width_mm": 88.0,
                                    "geometry_source": "dxf"}}
    hand = {"part_number": "12567-05-02M", "description": "END CAP - HANDED", "pages": [1, 3],
            "normalized_material": "MILD_STEEL"}
    return [base, hand]


def test_the_sheet_note_names_the_hand():
    parts = _hands()
    assert djm.stamp_mirror_notes(parts, _summary()) == 1
    assert parts[1]["mirror_of"] == "12567-05-01M"
    assert not parts[0].get("mirror_of")


def test_a_reference_without_an_opposite_hand_phrase_names_nothing():
    parts = _hands()
    assert djm.stamp_mirror_notes(
        parts, _summary("REFER TO DRAWING 12567-05-01M FOR NUTSERT POSITIONS")) == 0
    assert not parts[1].get("mirror_of")


def test_a_part_with_its_own_flat_is_not_a_hand():
    parts = _hands()
    parts[1]["flat_pattern_detected"] = True
    assert djm.stamp_mirror_notes(parts, _summary()) == 0


def test_the_named_hand_inherits_the_measured_flat():
    parts = _hands()
    djm.stamp_mirror_notes(parts, _summary())
    filled = djm.apply_mirror_geometry(parts)
    assert [f.get("part_number") for f in filled] == ["12567-05-02M"]
    ng = parts[1]["normalized_geometry"]
    assert (ng["blank_length_mm"], ng["blank_width_mm"]) == (409.5, 88.0)
    assert bip.has_fabrication_evidence(parts[1])


# ── D-266: an assembly coated as one is coated over its members' blanks ──────────────────

def test_the_case_is_coated_over_the_sum_of_its_panels():
    case = {"part_number": "12567-02-101", "description": "HEADER CASE FABRICATION",
            "quantity": 1, "inferred_operations": ["powder_coating", "welding"],
            "assembly_children": ["12567-02-01M", "12567-02-10M", "FIXING320"]}
    parts = [case,
             {"part_number": "12567-02-01M", "quantity": 1, "normalized_material": "MILD_STEEL",
              "normalized_geometry": {"blank_length_mm": 1000.0, "blank_width_mm": 500.0}},
             {"part_number": "12567-02-10M", "quantity": 4, "normalized_material": "MILD_STEEL",
              "normalized_geometry": {"blank_length_mm": 500.0, "blank_width_mm": 100.0}},
             {"part_number": "FIXING320", "quantity": 4, "is_bought_in": True,
              "normalized_geometry": {"blank_length_mm": 15.0, "blank_width_mm": 6.0}}]
    assert est.stamp_members_coated_area(parts) == 1
    # 1000x500 both faces = 1.0 m2; 500x100 both faces x4 = 0.4 m2; the stud is not coated
    assert abs(case["_powder_members_coated_m2"] - 1.4) < 1e-6


def test_a_member_that_carries_its_own_coat_is_not_counted_twice():
    case = {"part_number": "A", "quantity": 1, "inferred_operations": ["powder_coating"],
            "assembly_children": ["B", "C"]}
    parts = [case,
             {"part_number": "B", "quantity": 1, "textual_operations": ["powder_coating"],
              "normalized_geometry": {"blank_length_mm": 1000.0, "blank_width_mm": 500.0}},
             {"part_number": "C", "quantity": 2, "owning_assembly": "A",
              "normalized_geometry": {"blank_length_mm": 500.0, "blank_width_mm": 500.0}}]
    est.stamp_members_coated_area(parts)
    assert abs(case["_powder_members_coated_m2"] - 1.0) < 1e-6


def test_the_members_area_reaches_the_parents_powder_material():
    case = {"part_number": "12567-02-101", "description": "HEADER CASE WELDMENT",
            "quantity": 1, "normalized_material": "MILD_STEEL",
            "inferred_operations": ["powder_coating", "welding"],
            "is_assembly_parent": True, "_powder_members_coated_m2": 1.4}
    material = est.estimate_material(case)
    pc = material.get("powder_consumable") or {}
    assert abs(float(pc.get("coated_area_m2") or 0) - 1.4) < 1e-6
    assert pc.get("coated_area_source") == "sum_of_members_blanks"
    assert material.get("extended_material_cost_gbp") == 0.0


# ── D-267: a confirmed production rule is not outvoted by readers of the drawing ─────────

def test_readers_agreeing_on_the_drawn_gauge_do_not_refuse_the_shop_rule():
    part = {"part_number": "12567-02-09M"}
    sp.apply_field(part, "normalized_thickness_mm", 0.9, "dxf_filename")
    sp.apply_field(part, "normalized_thickness_mm", 0.9, "solidworks_api")
    sp.apply_field(part, "normalized_thickness_mm", 0.9, "drawing_deterministic")
    assert sp.apply_field(part, "normalized_thickness_mm", 1.0, "production_substitution")
    assert part["normalized_thickness_mm"] == 1.0
    assert not [f for f in part.get("review_flags") or [] if "NOT applied" in str(f)]


# ── 16:48 rerun (build 90a045e): four more ─────────────────────────────────────────────────
# D-268 the grommet row read two ways ("[G10-RSB350-12-00C]" / "IG10-RS8350-12-00C") became two
#       lines at x3 each — a supplier reference is not a word.
# D-269 "DIGITAL LED GCMP HEADER" in every title block flipped the steel case assemblies to LED:
#       02-101 tagged bought-in, 03-101 lost its coat and weld.
# D-270 05-02M took the base's blank and bends and had no Fold row — the operation was not mirrored.
# D-271 MAGNET21 and the P/P driver, bought by their codes, were refused the market rung because
#       operations lent by the page were still on the record when pricing ran.

def test_a_supplier_reference_is_not_a_word():
    a = [_row("12", "P/P", "SEMI BLIND RUBBER GROMMET [G10-RSB350-12-00C]", 3)]
    b = [_row("12", "P/P", "SEMI BLIND RUBBER GROMMET IG10-RS8350-12-00C", 3)]
    rows, _ = mb.reconcile_page({"rows": a}, {"rows": b}, "12567-02-GA")
    assert len(rows) == 1 and int(rows[0]["quantity"]) == 3
    # the words still tell two washers apart
    assert mb._desc_words({"description": "M6 WASHER"}) != mb._desc_words({"description": "M6 STAR WASHER"})


def test_the_project_title_does_not_flip_a_steel_assembly_to_led():
    import document_builder as db
    title = ("DIGITAL LED GCMP HEADER  SIDE HEADER FRAME ASM  12567-03-101  MATERIAL:  COLOUR:  "
             "SURFACE FINISH:  RAL5005 SIGNAL BLUE  MILD STEEL (CR4)  POWDER COATED - 30% GLOSS  "
             "Copt Oak, Loughborough LE12 9YE")
    summary = {"pages": [{"page_number": 1, "text_preview": title}]}
    frame = {"part_number": "12567-03-101", "description": "SIDE HEADER FRAME ASM",
             "materials": ["MILD STEEL"], "normalized_material": "MILD_STEEL", "pages": [1],
             "page_roles": ["assembly"], "textual_operations": ["welding", "powder_coating"],
             "is_sub_assembly": True, "geometry_rollup": {}}
    diffuser = {"part_number": "12567-03-08", "description": "DIFFUSER",
                "materials": ["MILD STEEL"], "material_inherited_from": "document_level",
                "pages": [1], "page_roles": ["detail"], "textual_operations": ["powder_coating"],
                "overall_length_mm": 1330.0, "overall_width_mm": 16.0, "geometry_rollup": {}}
    db._apply_post_build_fixes([frame, diffuser], summary)
    assert "powder_coating" in (frame.get("textual_operations") or [])
    assert "bought_in" not in (frame.get("page_roles") or [])
    assert "non_metal_material_corrected" not in (frame.get("review_flags") or [])
    # a part whose own words name a non-metal, on a steel it only inherited, still flips
    assert "bought_in" in (diffuser.get("page_roles") or [])
    assert "powder_coating" not in (diffuser.get("textual_operations") or [])


def test_the_named_hand_folds_as_the_base_does():
    parts = _hands()
    parts[0]["textual_operations"] = ["laser_cutting", "folding"]
    djm.stamp_mirror_notes(parts, _summary())
    djm.apply_mirror_geometry(parts)
    ops = (parts[1].get("textual_operations") or []) + (parts[1].get("inferred_operations") or [])
    assert "folding" in ops and "laser_cutting" in ops


def test_an_operation_the_page_lent_a_purchased_item_does_not_refuse_its_market_price():
    import pricing_service as ps
    magnet = {"part_number": "MAGNET21", "description": "NEODYMIUM BAR MAGNET 50x10x1.50mm",
              "normalized_material": "MILD_STEEL", "textual_operations": ["folding", "powder_coating"]}
    assert ps.is_something_you_can_buy(magnet)
    driver = {"part_number": "P/P-LED-POWER-DRIVER-3M", "description": "LED POWER DRIVER",
              "inferred_operations": ["powder_coating"]}
    assert ps.is_something_you_can_buy(driver)
    # a part we cut, with the same operations, is still not something you can buy
    assert not ps.is_something_you_can_buy({"part_number": "12567-03-06M", "description": "HOOK",
                                            "normalized_material": "MILD_STEEL",
                                            "textual_operations": ["folding"]})


# ── after the 16:48 book, four more ─────────────────────────────────────────────────────────
# D-272 02-10M's DXF measured 1477 x 346 against a model flat of 225.5 x 38.35 and was kept.
# D-273 the POWDER line, appended last, spilled to BOM Overflow with no price.
# D-274 every cascaded side-header line read "no reason recorded" beside its own trail.
# D-275 the handed cap took the base's flat and none of its studs: 2 charged where the kit takes 4.

def test_a_dxf_many_times_the_model_flat_is_extents_not_the_part():
    import geometry_arbitration as ga
    v = ga.arbitrate_flat(1477.31, 345.98, 225.5, 38.35)
    assert v["winner"] == ga.NATIVE and v.get("dxf_is_extents") and not v["unreconciled"]
    # a border a little wider than the part is still the DXF's to keep, flagged
    v2 = ga.arbitrate_flat(250.0, 45.0, 225.5, 38.35)
    assert v2["winner"] == ga.DXF and v2["unreconciled"]


def test_the_powder_line_stays_on_the_sheet_when_the_block_overflows():
    import wb_populate as wp
    parts = [{"part_number": f"FIXING{i}"} for i in range(6)]
    parts.append({"part_number": "POWDER", "_consumable_qty_unknown": True,
                  "_price_explicitly_withheld": True})
    kept = wp.pin_lines_that_price_themselves(parts, 5)
    assert [p["part_number"] for p in kept[:4]] == ["FIXING0", "FIXING1", "FIXING2", "POWDER"]
    assert [p["part_number"] for p in kept[4:]] == ["FIXING3", "FIXING4", "FIXING5"]
    assert wp.pin_lines_that_price_themselves(parts[:3], 5) == parts[:3]


def test_a_cascaded_quantity_is_explained_by_its_trail():
    import bom_and_route_extract as bre
    note = bre.quantity_difference_note(["12567-01-GA x1 -> 12567-03-GA x2 (BOM) -> 12567-03-101 x1"])
    assert "multiplied down the assembly tree" in note and "no reason" not in note
    assert "no reason recorded" in bre.quantity_difference_note([])


def test_the_named_hand_carries_the_bases_hardware():
    parts = [
        {"part_number": "12567-05-GA", "description": "END CAPS"},
        {"part_number": "12567-05-01M", "description": "END CAP", "flat_pattern_detected": True,
         "geometry_source": "dxf", "normalized_material": "MILD_STEEL", "quantity": 1},
        {"part_number": "12567-05-02M", "description": "END CAP - HANDED", "quantity": 1,
         "mirror_of": "12567-05-01M", "normalized_material": "MILD_STEEL",
         "normalized_geometry": {"blank_length_mm": 409.5, "blank_width_mm": 88.0,
                                 "geometry_source": "mirror_of_measured",
                                 "mirrored_from": "12567-05-01M"}},
        {"part_number": "BI-PEMSTUD", "description": "M6x20mm THREADED PEM STUD",
         "is_bought_in": True, "quantity": 2},
    ]
    extract = {"top_assembly": {"part_number": "12567-05-GA"},
               "assemblies": [
                   {"part_number": "12567-05-GA", "children": [
                       {"part_number": "12567-05-01M", "qty": 1}, {"part_number": "12567-05-02M", "qty": 1}]},
                   {"part_number": "12567-05-01M", "children": [{"part_number": "BI-PEMSTUD", "qty": 2}]}]}
    g = rc.build_part_graph(parts, extract)
    nodes = {n.part_number: n for n in g["nodes"]}
    assert {e.part_number: e.qty for e in nodes["12567-05-02M"].children} == {"BI-PEMSTUD": 2.0}
    assert nodes["12567-05-02M"].kind == "leaf" and nodes["12567-05-01M"].kind == "leaf"
    assert abs(g["quantities"]["BI-PEMSTUD"] - 4.0) < 1e-9


# D-276: a market lookup that found nothing is a MISSING price, not a market figure.

def test_an_ai_lookup_with_no_money_is_a_missing_price():
    import costed_facts as cf
    part = {"part_number": "P/P-POWER-CORD-UK-PLUG", "supplier": "xAI Grok LLM - INDICATIVE",
            "material_estimate": {"cost_method": "market_ai_indicative",
                                  "price_source": {"source_name": "xai"}}}
    empty = cf._price_origin(part, "bought_in", None, None, 0.0, None, False,
                             row_text="[AI ESTIMATE - INDICATIVE, NOT A QUOTE]")
    assert empty["firmness"] == cf.UNPRICED
    priced = cf._price_origin(part, "bought_in", None, 2.35, 2.35, None, False,
                              row_text="[AI ESTIMATE - INDICATIVE, NOT A QUOTE]")
    assert priced["firmness"] == cf.INDICATIVE_MARKET


# D-277: every class-coded table row no record stands for becomes a line of its own.

def test_class_coded_rows_without_records_each_become_a_line():
    import document_builder as db
    rows = [
        {"part_number": "P/P", "description": "LED POWER DRIVER, 3m AC CABLE, UK 3-PIN PLUG",
         "quantity": 1, "bom_parent": "12567-02-GA"},
        {"part_number": "P/P", "description": "10x3mm EPDM CLOSED CELL TAPE, LENGTH: 1230mm",
         "quantity": 2, "bom_parent": "12567-02-GA"},
        {"part_number": "P/P", "description": "10x3mm EPDM CLOSED CELL TAPE, LENGTH: 300mm",
         "quantity": 2, "bom_parent": "12567-02-GA"},
        {"part_number": "FIXING", "description": "M6 WASHER", "quantity": 4,
         "bom_parent": "12567-02-GA"},
        {"part_number": "//", "description": "PUCK ANTENNA", "quantity": 1},
        {"part_number": "12567-02-01M", "description": "FASCIA PANEL", "quantity": 1},
        {"part_number": "FIXING49", "description": "M6 THIN SHEET NUTSERT", "quantity": 4},
    ]
    parts = [{"part_number": "P/P-LED-POWER-DRIVER-3M", "description": "LED POWER DRIVER"},
             {"part_number": "FIXING49", "description": "M6 THIN SHEET NUTSERT"}]
    new = db.bought_in_rows_without_records(rows, parts)
    got = {r["part_number"]: r for r in new}
    descs = {r["description"] for r in new}
    assert {"P/P-10X3MM-EPDM-CLOSED-CELL-TAPE-LENGTH-1230MM",
            "P/P-10X3MM-EPDM-CLOSED-CELL-TAPE-LENGTH-300MM"} <= set(got)
    assert "M6 WASHER" in descs                       # the lone FIXING row is a line too
    assert "FASCIA PANEL" not in descs and "M6 THIN SHEET NUTSERT" not in descs
    assert "LED POWER DRIVER, 3m AC CABLE, UK 3-PIN PLUG" not in descs   # already a record
    tape = got["P/P-10X3MM-EPDM-CLOSED-CELL-TAPE-LENGTH-1230MM"]
    assert tape["quantity"] == 2 and tape["bom_parent"] == "12567-02-GA"
    assert tape["printed_code"] == "P/P" and "bought_in" in tape["page_roles"]


# D-278: a plate ruling needs a sheet body behind it.  D-279: the timer merges nested brackets.

def test_a_hand_that_takes_a_folded_bases_flat_is_not_a_plate():
    parts = _hands()
    parts[0]["textual_operations"] = ["laser_cutting", "folding"]
    parts[0]["solidworks_bend_features"] = 3
    # the hand's own model had no flat and no mass and read 12 x 409.5 x 88 as a plate
    parts[1]["native_flat_solid"] = True
    parts[1]["manufacturing_features"] = {"bend_count": 0, "bend_count_source": "solidworks_api"}
    djm.stamp_mirror_notes(parts, _summary())
    djm.apply_mirror_geometry(parts)
    hand = parts[1]
    assert not hand.get("native_flat_solid")
    ops = (hand.get("textual_operations") or []) + (hand.get("inferred_operations") or [])
    assert "folding" in ops
    assert any("plate ruling lifted" in str(f) for f in hand.get("review_flags") or [])


def test_nested_timing_brackets_count_their_seconds_once():
    import run_timing as rt
    assert abs(rt._union_seconds([(0.0, 10.0), (2.0, 5.0), (12.0, 13.0)]) - 11.0) < 1e-9
    assert rt._union_seconds([]) == 0.0


# D-280: a hand given its base's studs is asked for evidence its own record cannot show.

def test_a_hand_with_no_evidence_of_its_own_keeps_its_bases_leaf_kind():
    """21:57 book: 05-02M's own model had no sheet body (an envelope, not a flat) and its own
    DXF matched nothing measurable, so it showed no fabrication evidence of its own. Given the
    studs (D-275) it became an assembly and lost its laser, fold and sheet row."""
    parts = [
        {"part_number": "12567-05-GA", "description": "END CAPS"},
        {"part_number": "12567-05-01M", "description": "END CAP", "flat_pattern_detected": True,
         "geometry_source": "dxf", "dxf_measured_outline": True,
         "normalized_material": "MILD_STEEL", "quantity": 1},
        {"part_number": "12567-05-02M", "description": "END CAP - HANDED", "quantity": 1,
         "mirror_of": "12567-05-01M", "normalized_material": "MILD_STEEL",
         "dxf_measured_outline": False, "native_flat_solid": True,
         "normalized_geometry": {"blank_length_mm": 409.5, "blank_width_mm": 88.0,
                                 "geometry_source": "solidworks_api"}},
        {"part_number": "BI-PEMSTUD", "description": "M6x20mm THREADED PEM STUD",
         "is_bought_in": True, "quantity": 2},
    ]
    extract = {"top_assembly": {"part_number": "12567-05-GA"},
               "assemblies": [
                   {"part_number": "12567-05-GA", "children": [
                       {"part_number": "12567-05-01M", "qty": 1}, {"part_number": "12567-05-02M", "qty": 1}]},
                   {"part_number": "12567-05-01M", "children": [{"part_number": "BI-PEMSTUD", "qty": 2}]}]}
    g = rc.build_part_graph(parts, extract)
    nodes = {n.part_number: n for n in g["nodes"]}
    assert {e.part_number for e in nodes["12567-05-02M"].children} == {"BI-PEMSTUD"}
    assert nodes["12567-05-02M"].kind == "leaf", "the hand is the cut part its base is"
    assert nodes["12567-05-01M"].kind == "leaf"


def test_a_matched_but_unread_dxf_does_not_unmeasure_a_mirrored_flat():
    hand = {"part_number": "12567-05-02M", "dxf_source_file": "12567-05-02M.DXF",
            "dxf_measured_outline": False,
            "normalized_geometry": {"blank_length_mm": 409.5, "blank_width_mm": 88.0,
                                    "geometry_source": "mirror_of_measured",
                                    "mirrored_from": "12567-05-01M"}}
    assert bip.has_fabrication_evidence(hand)
    # and the exit it used to take still holds where nothing was mirrored
    assert not bip.has_fabrication_evidence({"part_number": "BI-KNOB",
                                             "dxf_measured_outline": False})


# D-281: the market figure's reproducibility verdict never reached the stamp the sheet reads.

def _market_stamp():
    """The shape the pricing chain actually produces: price_sources files the connector row's
    extra fields under the candidate's `metadata`, and the estimator copies that candidate in
    as `selected`."""
    result = {"selected": {"source": "web", "kind": "part_system_cost", "price": 4.2,
                           "currency": "GBP", "unit": "each", "confidence": 0.4,
                           "evidence": {"pricing_mode": "web_ai_llm_estimate"},
                           "metadata": {"pricing_mode": "web_ai_llm_estimate",
                                        "price_is_reproducible": True,
                                        "supplier_name": "xAI Grok LLM - INDICATIVE"}},
              "candidates": [], "audit_trail": []}
    return est._build_price_source_metadata(result, fallback_source="web", applied=True)


def test_a_cached_market_figure_reads_as_reproducible_on_the_stamp():
    import price_provenance as pp
    stamp = _market_stamp()
    assert pp.stamp_source_class(stamp) == "ai_estimate"
    assert pp.stamp_is_reproducible(stamp) is True
    # a stored job written before the verdict was lifted still reads as it was
    old = dict(stamp)
    old.pop("price_is_reproducible", None)
    assert pp.stamp_is_reproducible(old) is True


def test_a_cached_market_figure_prices_the_line_tagged_indicative():
    import wb_populate as wb
    pe = {"part_number": "MAGNET21", "description": "MAGNET",
          "cost_breakdown": {"system_cost": {"unit_cost_gbp": 4.2, "applied_to_total": True,
                                             "source": _market_stamp()}}}
    assert wb._price_is_reproducible(pe) is True
    pe["_price_is_reproducible"] = True
    line = wb.bom_line_pricing(pe, True, 4.2)
    assert line["withheld_gbp"] is None, "a figure that holds still prices the line"
    assert not pe.get("_price_explicitly_withheld")
    label, unrepeatable = wb._price_origin(pe)
    assert "INDICATIVE" in label and unrepeatable is False


# D-282: the POWDER line's area sum read blanks, and a coated assembly has none.

def test_a_case_coated_over_its_members_reaches_the_powder_area_sum():
    import wb_populate as wb
    case = {"part_number": "12567-02-101", "quantity": 1, "normalized_material": "MILD_STEEL",
            "material_estimate": {"cost_method": "weldment_parent_material_in_children",
                                  "powder_consumable": {"coated_area_m2": 1.4,
                                                        "coated_area_source": "sum_of_members_blanks"}}}
    panel = {"part_number": "12567-02-01M", "quantity": 1, "normalized_material": "MILD_STEEL",
             "material_estimate": {"stock_form": "sheet", "blank_length_mm": 1000.0,
                                   "blank_width_mm": 500.0}}
    coated = wb.route_coated_membership({"12567-02-101"})
    assert abs(wb.coated_sheet_area_m2([case, panel], coated) - 1.4) < 1e-9, (
        "the case's members' area is the case's area; the panel is not on the route and is "
        "not counted a second time")


def test_a_case_with_no_members_area_still_contributes_nothing():
    import wb_populate as wb
    case = {"part_number": "12567-03-101", "quantity": 1,
            "material_estimate": {"cost_method": "weldment_parent_material_in_children"}}
    assert wb.coated_sheet_area_m2([case], lambda p: True) == 0.0


# D-283: the members took the coat from the title block and held their flats under another key.

def test_a_member_whose_coat_came_from_the_title_block_still_gives_the_case_its_area():
    case = {"part_number": "12567-02-101", "quantity": 1,
            "inferred_operations": ["powder_coating", "welding"],
            "assembly_children": ["12567-02-01M", "12567-02-10M"]}
    parts = [case,
             # the fascia: coat stamped from the document's finish, flat under bounding_box_flat_mm
             {"part_number": "12567-02-01M", "quantity": 1, "normalized_material": "MILD_STEEL",
              "inferred_operations": ["powder_coating"], "finish_inherited_from": "document_level",
              "normalized_geometry": {"bounding_box_flat_mm": {"length": 1000.0, "width": 355.0}}},
             # a channel: same inherited coat, flat spelled the other way
             {"part_number": "12567-02-10M", "quantity": 4, "normalized_material": "MILD_STEEL",
              "inferred_operations": ["powder_coating"], "finish_inherited_from": "document_level",
              "normalized_geometry": {"blank_length_mm": 225.5, "blank_width_mm": 38.35}}]
    assert est.stamp_members_coated_area(parts) == 1
    expected = 1.0 * 0.355 * 2 + 0.2255 * 0.03835 * 2 * 4
    assert abs(case["_powder_members_coated_m2"] - expected) < 1e-6
    assert set(case["_powder_members_m2"]) == {"12567-02-01M", "12567-02-10M"}


def test_a_member_whose_own_sheet_states_the_coat_is_still_left_out():
    case = {"part_number": "A", "quantity": 1, "inferred_operations": ["powder_coating"],
            "assembly_children": ["B"]}
    own = {"part_number": "B", "quantity": 1, "textual_operations": ["powder_coating"],
           "surface_finishes": ["POWDER COATED RAL 9005"],
           "normalized_geometry": {"blank_length_mm": 1000.0, "blank_width_mm": 500.0}}
    assert est.stamp_members_coated_area([case, own]) == 0


def test_the_title_block_stamp_marks_the_coat_as_inherited():
    """The estimator's document-level finish stamp is the writer of the inherited op, so it
    is the writer of the mark; a part whose own text already carried the op is not marked."""
    summary = {"document_analysis": {"title_block": {"surface_finishes": ["POWDER COATED"]}}}
    parts = [{"part_number": "12567-02-01M", "normalized_material": "MILD_STEEL", "quantity": 1},
             {"part_number": "12567-05-01M", "normalized_material": "MILD_STEEL", "quantity": 1,
              "textual_operations": ["powder_coating"]}]
    try:
        est.estimate_document(parts, summary)
    except Exception:                                                # noqa: BLE001
        pass                     # the fixture is not a job; only the stamp is under test
    assert parts[0].get("finish_inherited_from") == "document_level"
    assert "powder_coating" in (parts[0].get("inferred_operations") or [])
    assert not est._member_carries_its_own_coat(parts[0])
    # 05-01M's own text carried the op; the document filled only its finish words, so the
    # coat is still its own (D-286)
    assert est._member_carries_its_own_coat(parts[1])


def test_the_powder_sum_reads_a_flat_under_any_spelling_and_leaves_out_route_named_members():
    import wb_populate as wb
    case = {"part_number": "12567-02-101", "quantity": 1, "normalized_material": "MILD_STEEL",
            "material_estimate": {"cost_method": "weldment_parent_material_in_children",
                                  "powder_consumable": {
                                      "coated_area_m2": 0.71 + 0.2,
                                      "coated_area_source": "sum_of_members_blanks",
                                      "coated_members_m2": {"12567-02-01M": 0.71,
                                                            "12567-02-10M": 0.2}}}}
    channel = {"part_number": "12567-02-10M", "quantity": 4, "normalized_material": "MILD_STEEL",
               "material_estimate": {"stock_form": "sheet"},
               "normalized_geometry": {"bounding_box_flat_mm": {"length": 225.5, "width": 38.35}}}
    coated = wb.route_coated_membership({"12567-02-101", "12567-02-10M"})
    got = wb.coated_sheet_area_m2([case, channel], coated)
    # the fascia through the case, the channel on its own line from its bounding-box flat
    expected = 0.71 + 0.2255 * 0.03835 * 2 * 4
    assert abs(got - expected) < 1e-6, got


# D-284: the record says the price reached the total; the sheet wrote £0.

def test_a_bought_in_the_sheet_leaves_at_nought_no_longer_claims_the_total():
    import wb_populate as wb
    import price_provenance as pp
    pe = {"part_number": "P/P-JST-SPLITTER", "quantity": 3,
          "cost_breakdown": {"system_cost": {"unit_cost_gbp": 1.15, "applied_to_total": True,
                                             "source": _market_stamp()}}}
    summary = {}
    assert wb.reconcile_price_stamp_with_sheet(pe, None, summary) is True
    sc = pe["cost_breakdown"]["system_cost"]
    assert sc["applied_to_total"] is False
    assert not pp.stamp_affects_total(sc["source"])
    assert pp.applied_ai_prices(pe) == []
    assert "P/P-JST-SPLITTER" in summary["withheld_price_lines"]


def test_a_line_the_sheet_priced_keeps_its_claim():
    import wb_populate as wb
    pe = {"part_number": "MAGNET21", "quantity": 2,
          "cost_breakdown": {"system_cost": {"unit_cost_gbp": 4.2, "applied_to_total": True,
                                             "source": _market_stamp()}}}
    assert wb.reconcile_price_stamp_with_sheet(pe, 4.2, {}) is False
    assert pe["cost_breakdown"]["system_cost"]["applied_to_total"] is True


# D-286: the real record — RAW on its own sheet, a powder op from another reader, no marker.

def test_a_raw_member_carrying_an_inherited_powder_op_gives_the_case_its_area():
    """Tested against the 21:57 JSON by the reviewer: D-283 stamped 0.069 m² on 02-101 (the
    channels) and skipped the fascia. The fascia says RAW, carries powder_coating already, and
    has no finish_inherited_from — the marker is only written by the reader that ADDS the op."""
    case = {"part_number": "12567-02-101", "quantity": 1,
            "inferred_operations": ["powder_coating", "welding"],
            "assembly_children": ["12567-02-01M", "12567-02-10M"]}
    fascia = {"part_number": "12567-02-01M", "quantity": 1, "normalized_material": "MILD_STEEL",
              "surface_finishes": ["RAW"], "inferred_operations": ["powder_coating"],
              "normalized_geometry": {"bounding_box_flat_mm": {"length": 2000.0, "width": 355.0}}}
    channel = {"part_number": "12567-02-10M", "quantity": 4, "normalized_material": "MILD_STEEL",
               "inferred_operations": ["powder_coating"], "finish_inherited_from": "document_level",
               "normalized_geometry": {"blank_length_mm": 225.5, "blank_width_mm": 38.35}}
    assert est.stamp_members_coated_area([case, fascia, channel]) == 1
    expected = 2.0 * 0.355 * 2 + 0.2255 * 0.03835 * 2 * 4
    assert abs(case["_powder_members_coated_m2"] - expected) < 1e-6, case["_powder_members_coated_m2"]
    assert case["_powder_members_m2"]["12567-02-01M"] > 1.4


def test_the_members_own_sheet_is_the_judge():
    raw = {"surface_finishes": ["RAW"], "inferred_operations": ["powder_coating"]}
    pointer = {"surface_finishes": ["SEE ASSEMBLY DRAWING"], "textual_operations": ["powder_coating"]}
    own = {"surface_finishes": ["POWDER COATED RAL 9005"], "inferred_operations": ["powder_coating"]}
    own_text = {"textual_operations": ["powder_coating"]}
    inherited = {"surface_finishes": ["POWDER COATED"], "inferred_operations": ["powder_coating"],
                 "finish_inherited_from": "document_level"}
    no_op = {"surface_finishes": ["POWDER COATED"]}
    assert not est._member_carries_its_own_coat(raw)
    assert not est._member_carries_its_own_coat(pointer), "a pointer states nothing about the part"
    assert est._member_carries_its_own_coat(own)
    assert est._member_carries_its_own_coat(own_text)
    assert not est._member_carries_its_own_coat(inherited)
    assert not est._member_carries_its_own_coat(no_op)
    # the document filled the finish; the part's own text carried the op — its own coat
    assert est._member_carries_its_own_coat({"surface_finishes": ["POWDER COATED"],
                                             "textual_operations": ["powder_coating"],
                                             "finish_inherited_from": "document_level"})


def test_the_title_block_stamp_marks_the_finish_it_fills_as_inherited_too():
    summary = {"document_analysis": {"title_block": {"surface_finishes": ["POWDER COATED"]}}}
    # already carries the op from another reader, states no finish of its own
    part = {"part_number": "12567-02-01M", "normalized_material": "MILD_STEEL", "quantity": 1,
            "inferred_operations": ["powder_coating"]}
    try:
        est.estimate_document([part], summary)
    except Exception:                                                # noqa: BLE001
        pass
    assert part.get("surface_finishes") == ["POWDER COATED"]
    assert part.get("finish_inherited_from") == "document_level"
    assert not est._member_carries_its_own_coat(part)


# D-287: a researched answer about a different article is not a price for this line.

def test_a_steel_sheet_listing_does_not_price_an_led_driver():
    import pricing_service as ps
    steel = {"found": True, "price_gbp": 0.80, "source_type": "web_search",
             "supplier_name": "Mild Steel Sheet 1.5mm CR4 — cut to size | Metals4U"}
    assert not ps.prices_this_article("LED DRIVER 24V 60W CONSTANT VOLTAGE", steel)
    driver = {"found": True, "price_gbp": 14.20, "source_type": "llm_market_estimate",
              "item_priced": "24V 60W constant-voltage LED driver, one unit"}
    assert ps.prices_this_article("LED DRIVER 24V 60W CONSTANT VOLTAGE", driver)


# D-288: the driver's £0.80 came from the MATERIALS catalogue, asked with its inherited steel.

def _steel_row_service():
    import pricing_service as ps
    svc = ps.PricingService(conn=object())
    asked = []

    def _fetch(sql, params):
        asked.append(list(params))
        return ("https://metals4u.co.uk/mild-steel-sheet", "MILD STEEL", 0.80, 1)
    svc._fetch_one_with_retry = _fetch
    return svc, asked


def test_a_purchased_component_is_not_priced_from_the_materials_catalogue():
    svc, asked = _steel_row_service()
    driver = {"part_number": "P/P-LED-DRIVER-24V", "description": "LED DRIVER 24V 60W",
              "is_bought_in": True, "page_roles": ["bought_in"],
              "normalized_material": "MILD_STEEL", "material_inherited_from": "document_level"}
    assert svc._get_supplier_catalog(driver) is None
    assert asked == [], "the materials catalogue was not even asked about a driver"


def test_a_made_part_still_takes_the_materials_catalogue_rung():
    svc, asked = _steel_row_service()
    bracket = {"part_number": "12567-02-04M", "description": "BRACKET",
               "normalized_material": "MILD_STEEL", "flat_pattern_detected": True,
               "geometry_source": "dxf", "dxf_measured_outline": True}
    got = svc._get_supplier_catalog(bracket)
    assert got and got["source"] == "estimating_supplier_catalog_url" and got["unit_price_gbp"] == 0.80
    assert asked and asked[0] == ["MILD_STEEL"]


def test_an_answer_that_names_nothing_is_not_refused_here():
    import pricing_service as ps
    assert ps.prices_this_article("MAGNET 21MM", {"found": True, "price_gbp": 0.35})
    assert ps.prices_this_article("", {"item_priced": "anything"})
    # plurals and compounds still count as the same article
    assert ps.prices_this_article("BINDING SCREW M4", {"item_priced": "M4 x 12 binding screws, one screw"})


def test_a_fabricated_leaf_at_nought_is_not_touched():
    """Its material is in the Sheet Steel block; the £0 BOM cell is by design and its stamps
    already say the bought-in figure was not applied."""
    import wb_populate as wb
    pe = {"part_number": "12567-02-01M", "_canonical_kind": "leaf",
          "cost_breakdown": {"system_cost": {"unit_cost_gbp": 9.73, "applied_to_total": False,
                                             "source": {"applied": True}}}}
    assert wb.reconcile_price_stamp_with_sheet(pe, None, {}) is False
