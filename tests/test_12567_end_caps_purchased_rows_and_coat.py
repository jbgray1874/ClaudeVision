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
