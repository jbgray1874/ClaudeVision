"""A section is sawn, an oval is oval, a joint is welded once, a box is a box (D-531).

The 0356453 hanging-rail book's review, 14 Oct 2026: "Sawing was returned but dropped. Oval
uprights priced using rectangular stock. Weld scope overlaps. Packaging labelling conflicts."
The saved read already named the saw, the oval and the welds, so each loss is the engine's:

  * a section with no cut list had no piece to saw, so the saw the read returned priced at
    nothing — though the part is cut from a stock length like any other;
  * "OVAL TUBE" fell through to the rectangular box-section words and was weighed and priced
    as RHS of the same outside size;
  * each member charged its own weld and dress, and the unit charged the same joints again;
  * the box calculator's £59.73 read "Box calculator config rates" in the supplier cell and
    "AI market figure" on the row, the flag and the report.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import concept_scan as cs  # noqa: E402
import costed_facts as cf  # noqa: E402
import estimator as E  # noqa: E402
from section_profile import section_kg_per_m  # noqa: E402


def _member(name, said, L, W, T, qty=1, ops=("saw", "welding", "powder_coating")):
    return {"name": name, "kind": "fabricated", "material_guess": "MILD STEEL",
            "sighted_material": said, "quantity": qty, "operations": list(ops),
            "assumed_blank_mm": {"length": L, "width": W, "thickness": T}}


def _rail(unit_ops=("welding", "assembly")):
    return {"product": {"name": "HANGING RAIL",
                        "assumed_overall_mm": {"height": 1500, "width": 450, "depth": 600}},
            "unit_operations": list(unit_ops),
            "parts": [_member("UPRIGHT", "30 x 15 oval tube", 1450, 30, 15, 2),
                      _member("BASE FOOT", "40 x 10 flatbar", 600, 40, 10, 2),
                      _member("TOP RAIL", "25 dia round tube", 450, 25, 25, 1)]}


# ── a section cut from a stock length is sawn ────────────────────────────────────────────

def test_a_section_with_no_cut_list_is_still_sawn_to_length():
    rec = cs.parts_from_concept({"product": {"name": "R"}, "parts": [
        _member("UPRIGHT", "30 x 15 oval tube", 1450, 30, 15, 2, ops=("saw", "powder_coating"))]},
        "J")[0]
    out = E.estimate_part(rec)
    run = (out.get("process_estimate") or {}).get("run_times_min_per_unit") or {}
    assert run.get("saw", 0) > 0, "the read returned the saw; one cut a piece is charged"


def test_a_piece_bought_cut_to_its_own_length_is_not_sawn(monkeypatch):
    real = E.estimate_material

    def _bought_cut(part, *a, **k):
        m = dict(real(part, *a, **k) or {})
        m["cost_method"] = "catalogue_section_price"
        return m

    monkeypatch.setattr(E, "estimate_material", _bought_cut)
    rec = cs.parts_from_concept({"product": {"name": "R"}, "parts": [
        _member("UPRIGHT", "30 x 15 oval tube", 1450, 30, 15, 2, ops=("saw", "powder_coating"))]},
        "J")[0]
    out = E.estimate_part(rec)
    run = (out.get("process_estimate") or {}).get("run_times_min_per_unit") or {}
    assert not run.get("saw"), "a catalogue piece at its own length arrives cut"


# ── an oval is its own form ──────────────────────────────────────────────────────────────

def test_oval_tube_words_make_an_oval_not_a_box_section():
    s = cs.resolve_stock(_member("UPRIGHT", "30 x 15 oval tube", 1450, 30, 15))
    assert s["form"] == "oval_tube" and s["profile_form"] == "OVAL"
    assert s["section_mm"] == [30.0, 15.0] and s["wall_mm"] == 1.5 and s["wall_assumed"]


def test_an_oval_is_weighed_as_an_ellipse_and_lighter_than_the_rhs_around_it():
    oval = section_kg_per_m(30, 15, 1.5, "OVAL")
    rhs = section_kg_per_m(30, 15, 1.5, "RHS")
    assert oval == pytest.approx(3.141592653589793 / 4 * (30 * 15 - 27 * 12) * 7850 / 1e6)
    assert oval < rhs


def test_an_oval_member_is_costed_at_its_oval_mass():
    rec = cs.parts_from_concept({"product": {"name": "R"}, "parts": [
        _member("UPRIGHT", "30 x 15 oval tube", 1450, 30, 15, 1, ops=("saw",))]}, "J")[0]
    assert rec["section_stock"]["profile_form"] == "OVAL"
    me = E.estimate_part(rec)["material_estimate"]
    assert me["unit_material_mass_kg"] == pytest.approx(
        section_kg_per_m(30, 15, 1.5, "OVAL") * 1.45, abs=0.01)


def test_run_together_stock_words_are_read():
    assert cs.resolve_stock(_member("FOOT", "40 x 10 flatbar", 600, 40, 10))["form"] == "flat_bar"
    s = cs.resolve_stock(_member("RAIL", "25 dia roundtube", 450, 25, 25))
    assert s["profile_form"] == "CHS"


# ── a joint is welded once, on the unit ──────────────────────────────────────────────────

def test_a_welded_unit_owns_the_joints_and_its_members_do_not_charge_them_again():
    ans = _rail()
    recs = cs.parts_from_concept(ans, "J")
    unit = cs.unit_assembly_part(recs, ans, "J")
    assert "welding" in unit["inferred_operations"]
    assert unit["weld_joint_count"] == 4, "five welded pieces make at least four joints"
    for r in recs:
        assert not {"welding", "spot_welding"} & set(r["inferred_operations"]), r["part_number"]
        assert "saw" in r["inferred_operations"]
        assert any("charged once" in f for f in r["review_flags"])
        # ...and coated with the unit after welding, not hung on its own (D-537)
        assert "powder_coating" not in r["inferred_operations"]
        assert r["coat_charged_on"] == unit["part_number"]
    assert "powder_coating" in unit["inferred_operations"]


def test_a_weld_the_brief_states_on_a_member_stays_on_it():
    ans = _rail()
    recs = cs.parts_from_concept(ans, "J")
    recs[0]["weld_stated_by_brief"] = True
    cs.joints_once_on_the_unit({"part_number": "J-CPT00", "inferred_operations": ["welding"]},
                               recs)
    assert "welding" in recs[0]["inferred_operations"]
    assert "welding" not in recs[1]["inferred_operations"]


def test_an_unwelded_unit_leaves_its_members_alone():
    # One welded member line welds to nothing else in the unit: the unit stays unwelded and the
    # member keeps its own weld. (Two or more welded member lines are welded to one another,
    # and make the unit welded — D-537, tests/test_a_welded_unit_is_welded_and_coated_once.)
    ans = _rail(unit_ops=("assembly",))
    for p in ans["parts"][1:]:
        p["operations"] = [o for o in p["operations"] if o != "welding"]
    recs = cs.parts_from_concept(ans, "J")
    unit = cs.unit_assembly_part(recs, ans, "J")
    assert "welding" not in (unit.get("inferred_operations") or [])
    assert "welding" in recs[0]["inferred_operations"]


# ── a box-calculator figure is named as the box calculator, everywhere ───────────────────

def _shelf():
    return [{"part_number": "12399-77J", "description": "KD V2 SHELF", "quantity": 1,
             "normalized_material": "MFC", "normalized_thickness_mm": 18.0,
             "blank_length_mm": 1198.0, "blank_width_mm": 398.0,
             "textual_operations": ["cnc_routing"],
             "normalized_geometry": {"blank_length_mm": 1198.0, "blank_width_mm": 398.0},
             "pages": [1], "page_roles": ["detail"]}]


def _summary(parts):
    return {"declared_product": "12399-77J", "drawing_number": "12399-77J",
            "manufacturing_writeup": {"parts": parts},
            "document_analysis": {"bom_rows": []}, "llm_full_extract": {}, "pages": []}


def test_the_box_calculator_line_says_one_basis_on_every_surface():
    parts = _shelf()
    E.estimate_document(parts, summary=_summary(parts))
    pkg = next(p for p in parts if p.get("part_number") == "PACKAGING")
    if ((pkg.get("commercial_line") or {}).get("price_source") or {}).get(
            "source_class") != "box_calculator":
        pytest.skip("the box calculator is not the basis this config chose for the shelf")
    words = " ".join([str(pkg.get("description")), " ".join(map(str, pkg["review_flags"])),
                      str(pkg["commercial_line"].get("note"))])
    assert "box calculator" in str(pkg["description"])
    assert "AI market" not in words and "AI MARKET" not in words
    assert pkg["cost_source"] == "box_calculator_allowance"
    assert pkg["review_flags"][0].startswith("BOX CALCULATOR £")
    assert "prices live from the system" not in pkg["commercial_line"]["note"]
    unit = float(pkg["unit_cost_gbp"])
    origin = cf._price_origin(pkg, "commercial", None, unit, unit, None, False)
    assert origin["class"] == "box_calculator" and origin["firmness"] == cf.INDICATIVE_HOUSE


def test_a_priced_placeholder_names_its_box_calculator_method():
    part = {"part_number": "PACKAGING", "_commercial_placeholder": True, "quantity": 1,
            "cost_source": "box_calculator_allowance",
            "unit_material_cost_gbp": 59.73, "unit_cost_gbp": 59.73}
    E.estimate_part(part)
    assert part["material_estimate"]["cost_method"] == "commercial_line_box_calculator"
