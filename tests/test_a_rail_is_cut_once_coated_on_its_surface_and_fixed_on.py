"""A rail is cut once, coated on its surface and fixed on (D-532).

The 0356453 hanging rail, 20:20 book (£422.55 at 1 off), on the D-531 engine. The read was a
good one; the engine still lost five things between it and the price:

  * the 50 x 10 flat-bar feet carried a Tube (laser) row AND a Saw row — the rule that rules
    the laser out covered hollow tube only;
  * the read called the uprights "tube" and wrote "40x20 oval" only in its size note, and the
    brief's materials line said "40 × 20 oval tube frame" — they were costed as round tube;
  * the brief's "UPC ID plate (20 x 10 mm)" reached the line with no size;
  * every made piece was welded, so the fixings allowance found nothing to fix — and the four
    bolted castors and the plate went on with no fixings;
  * the welded frame was coated over its members' flat blanks (0.327 m2) where their outer
    surfaces are about 0.43 m2, and the castors and plate — bought finished — turned the coat
    into a "mixed members" question for a person.

And the brief reader took "frame 700 wide" and "rail (660 long)" as 700 frames and 660 rails.
"""
from __future__ import annotations

import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import concept_scan as cs  # noqa: E402
import estimator as E  # noqa: E402
import route_compiler as rc  # noqa: E402
from section_profile import section_outer_perimeter_mm  # noqa: E402

BRIEF = ("Materials as listed on the sheet:\n1. 40 × 20 oval tube frame\n2. 19 mm round tube "
         "rails\n3. 50 mm flat bar 10 mm thick feet\n4. one UPC ID plate (20 x 10 mm), bought "
         "in\n5. 70 mm swivel castors, bought in")
OPS = ["saw", "welding", "powder_coating", "dress_welds"]


def _sec(name, qty, form, sec, length, why=""):
    return {"name": name, "kind": "fabricated", "material_guess": "MILD STEEL",
            "sighted_material": "MILD STEEL", "quantity": qty, "operations": list(OPS),
            "why_size": why, "stock": {"form": form, "section_mm": sec, "length_mm": length},
            "assumed_blank_mm": {"length": length, "width": sec[0], "thickness": sec[1]}}


def _rail():
    return {"product": {"name": "HANGING RAIL",
                        "assumed_overall_mm": {"height": 905, "width": 495, "depth": 700}},
            "unit_operations": ["assembly", "powder_coating"],
            "parts": [_sec("UPRIGHT", 2, "tube", [40, 20], 800),
                      _sec("CROSS RAIL", 4, "tube", [19, 19], 660),
                      _sec("BASE BAR", 2, "flat_bar", [50, 10], 495),
                      {"name": "UPC ID PLATE", "kind": "bought_in", "quantity": 1},
                      {"name": "70MM SWIVEL CASTOR", "kind": "bought_in", "quantity": 4}]}


def _records():
    ans = _rail()
    recs = cs.parts_from_concept(ans, "J", brief=BRIEF)
    return [cs.unit_assembly_part(recs, ans, "J")] + recs


# ── a section is cut once ────────────────────────────────────────────────────────────────

def _decisions(parts):
    return {(d["target_id"], d["operation"]): d for d in rc.compile_job_route(parts)["decisions"]}


def test_a_flat_bar_with_no_flat_pattern_is_sawn_not_lasered():
    bar = {"part_number": "J-BAR", "description": "BASE BAR", "quantity": 2,
           "normalized_material": "MILD STEEL", "textual_operations": ["laser_cutting"],
           "inferred_operations": ["saw"],
           "section_stock": {"a": 50, "b": 10, "t": 10, "length_mm": 495, "profile_form": "FLAT"}}
    d = _decisions([bar])
    assert d[("J-BAR", "laser_cutting")]["status"] == "not_applicable"
    assert "cut from a stock length" in d[("J-BAR", "laser_cutting")]["reason"]
    assert d[("J-BAR", "saw")]["status"] == "required"


def test_a_section_with_its_own_flat_pattern_is_still_profiled():
    bar = {"part_number": "J-BAR", "description": "BASE BAR", "quantity": 2,
           "normalized_material": "MILD STEEL", "textual_operations": ["laser_cutting"],
           "dxf_augmented": True,
           "section_stock": {"a": 50, "b": 10, "t": 10, "length_mm": 495, "profile_form": "FLAT"}}
    assert _decisions([bar])[("J-BAR", "laser_cutting")]["status"] == "required"


# ── an oval is oval wherever the pack says so ────────────────────────────────────────────

def test_the_reads_own_size_note_names_the_oval():
    s = cs.resolve_stock(_sec("UPRIGHT", 2, "tube", [40, 20], 800,
                              why="40x20 oval stated in materials list page 1"))
    assert s["form"] == "oval_tube" and s["profile_form"] == "OVAL"


def test_the_briefs_materials_line_names_the_oval_by_its_size():
    s = cs.resolve_stocks([_sec("UPRIGHT", 2, "tube", [40, 20], 800)], brief=BRIEF)[0]
    assert s["form"] == "oval_tube" and "brief" in s["notes"][-1]
    two = BRIEF + "\n6. 40 x 20 box section brace"
    assert cs.resolve_stocks([_sec("UPRIGHT", 2, "tube", [40, 20], 800)], brief=two)[0][
        "form"] != "oval_tube", "two forms at one size is not a statement about this line"


def test_a_tube_with_two_sides_is_rectangular_not_round():
    s = cs.resolve_stock(_sec("BRACE", 1, "tube", [40, 20], 500))
    assert s["form"] == "box_section" and s["profile_form"] == ""


def test_the_oval_upright_is_costed_at_its_oval_mass():
    up = next(r for r in _records() if r["description"] == "UPRIGHT")
    me = E.estimate_part(up)["material_estimate"]
    from section_profile import section_kg_per_m
    assert me["unit_material_mass_kg"] == pytest.approx(
        section_kg_per_m(40, 20, 1.5, "OVAL") * 0.8, abs=0.01)


# ── a bought item keeps the size the brief states ───────────────────────────────────────

def test_a_bought_line_takes_its_stated_size_from_the_brief():
    plate = next(r for r in _records() if "ID PLATE" in r["description"])
    assert plate["description"] == "UPC ID PLATE 20 x 10 MM"
    assert plate["concept_stated_size_mm"] == [20.0, 10.0]
    assert "20 x 10 mm (stated)" in plate["research_description"]
    assert not plate.get("blank_length_mm"), "stated, never nested"


def test_a_one_word_name_is_too_loose_to_match_a_brief_line():
    assert cs.stated_item_size("PLATE", BRIEF) is None


# ── bought hardware is fixed on ──────────────────────────────────────────────────────────

def test_bolted_castors_and_a_plate_get_fixings_on_an_all_welded_frame():
    recs = _records()
    mech = cs.mechanically_fitted(recs)
    assert mech["fixings"] == 4 * 4 + 2 * 1
    fx = cs.fixings_allowance_line(recs, "J", 1)
    assert fx["quantity"] == 18
    assert "4 per J-CPT05 × 4" in fx["review_flags"][-1] and "2 per J-CPT04 × 1" in fx["review_flags"][-1]
    assert "CONCEPT_FASTENED_BOUGHT_ITEMS" in fx["review_flags"][-1]


def test_a_bought_item_its_words_say_is_welded_takes_no_fixings():
    recs = _records()
    plate = next(r for r in recs if "ID PLATE" in r["description"])
    plate["description"] += " (welded on)"
    assert cs.mechanically_fitted(recs)["fixings"] == 16


def test_an_all_welded_frame_with_no_bought_hardware_still_gets_none():
    ans = _rail()
    ans["parts"] = ans["parts"][:3]
    recs = cs.parts_from_concept(ans, "J", brief=BRIEF)
    assert cs.fixings_allowance_line(recs, "J", 1) is None


# ── a welded frame is coated on its sections' surfaces ──────────────────────────────────

def test_one_perimeter_for_every_section_form():
    assert section_outer_perimeter_mm(19, 19, "CHS") == pytest.approx(math.pi * 19)
    assert section_outer_perimeter_mm(50, 10, "FLAT") == pytest.approx(120)
    ha, hb = 20, 10
    assert section_outer_perimeter_mm(40, 20, "OVAL") == pytest.approx(
        math.pi * (3 * (ha + hb) - ((3 * ha + hb) * (ha + 3 * hb)) ** 0.5))


def test_the_units_coat_is_its_members_outer_surfaces():
    parts = _records()
    E.estimate_document(parts, summary={"declared_product": parts[0]["part_number"],
                                        "manufacturing_writeup": {"parts": parts},
                                        "document_analysis": {"bom_rows": []},
                                        "llm_full_extract": {}, "pages": []})
    want = (section_outer_perimeter_mm(40, 20, "OVAL") * 800 * 2
            + section_outer_perimeter_mm(19, 19, "CHS") * 660 * 4
            + 120 * 495 * 2) / 1e6
    assert parts[0]["_powder_members_coated_m2"] == pytest.approx(want, abs=0.002)
    assert want == pytest.approx(0.431, abs=0.002)


def test_a_section_part_coats_its_outer_surface():
    parts = _records()
    rail = next(r for r in parts if r["description"] == "CROSS RAIL")
    # Welded into the unit, it is coated with it (D-537) — over its outer surface.
    assert rail["coat_charged_on"] == parts[0]["part_number"]
    assert E._section_outer_area_m2(rail) == pytest.approx(math.pi * 19 * 660 / 1e6, abs=1e-4)
    # A section coated on its own line is coated on the same surface.
    loose = dict(rail, inferred_operations=["saw", "powder_coating"])
    loose.pop("coat_charged_on")
    det = E.estimate_part(loose)["process_estimate"]["powder_coating_detail"]
    assert det["coated_area_source"] == "section_outer_surface"
    assert det["coated_m2"] == pytest.approx(math.pi * 19 * 660 / 1e6, abs=1e-4)


def test_bought_hardware_does_not_make_the_coat_a_mixed_question():
    r = rc.compile_job_route(_records())
    assert not [i for i in r["issues"] if i.get("code") == "powder_scope_mixed_members"]


# ── a size is not a count ────────────────────────────────────────────────────────────────

def test_a_number_before_a_dimension_word_is_a_size():
    got = {(s["count"], " ".join(s["words"])) for s in cs.brief_stated_counts(
        "Overall (frame 700 wide, uprights 1625 tall). Top rail (660 long), bars 630 long, "
        "headers x3, 4 castors")}
    assert got == {(3, "headers"), (4, "castors")}
