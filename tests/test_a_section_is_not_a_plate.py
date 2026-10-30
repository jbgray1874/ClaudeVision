"""A section, a mesh and a count keep their meaning from the read to the price (D-528).

The 0356456 tote trolley book came back at £6,131 a unit. The read had three numbers per part —
length, width, thickness — so a 25 x 25 box section, a 60 x 40 angle and a 25 x 25 mesh each
became a 25, 40 and 25 mm plate; the brief's "60 x 40 angle runners" and "25 x 25 mesh base"
were then read as 40 runners and 25 meshes over the read's 8 and 1. The mesh alone was
£2,870 of nested 25 mm steel, the order weighed over a tonne, and the shipment counted 22
pallets. Nothing checked the bill against the sheet's 49 kg, because the sheet prints it as
"49KG" with no WEIGHT label.

Each step that lost the meaning is pinned here: the count parser, the stock the read names, the
record the costing reads, the weight the check and the shipment use.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import concept_scan as cs  # noqa: E402
import palletising  # noqa: E402
from section_profile import section_kg_per_m  # noqa: E402


def _part(name, said, L, W, T, qty=1, ops=None, material="MILD STEEL", **extra):
    return dict({"name": name, "kind": "fabricated", "sighted_material": said,
                 "material_guess": material, "quantity": qty,
                 "assumed_blank_mm": {"length": L, "width": W, "thickness": T},
                 "operations": list(ops or ["welding"])}, **extra)


TOTE_SHEET = "\n".join([
    "Material:", "MILD STEEL", "1.", "25 X 25 BOX SECTION", "2.", "16MM MELAMINE", "3.",
    "6MM TOTE STOPS", "4.", "60 X 40 ANGLE RUNNERS", "5.", "25 X 25 MESH", "6.",
    "1.5MM STEEL SHEET SIDES", "480", "630", "415", "620", "880", "TOTE TROLLEY",
    "STANDARD STATION", "49KG"])


# ── the count parser: the last term of a size is not a count ─────────────────────────────

def test_a_sizes_last_number_is_never_a_brief_count():
    brief = ("Materials as listed on the sheet:\n1. 25 x 25 box section frame\n"
             "4. 60 x 40 angle runners\n5. 25 x 25 mesh base\n")
    said = [s["said"] for s in cs.brief_stated_counts(brief)]
    assert not any(s.startswith(("40 ", "25 ")) for s in said), said


def test_the_counts_a_brief_does_state_still_count():
    got = {(s["count"], " ".join(s["words"])) for s in cs.brief_stated_counts(
        "6 slotted corner posts, headers x3, five front shelves; 60 x 40 x 3 angle, 8 runners")}
    assert {(6, "slotted corner posts"), (3, "headers"), (5, "front shelves"),
            (8, "runners")} <= got


# ── the stock a line is cut from, each size in its own field ─────────────────────────────

def test_a_box_section_written_as_a_plate_is_the_section():
    s = cs.resolve_stock(_part("FRAME VERTICALS", "25 x 25 box section", 880, 25, 25, 4))
    assert s["form"] == "box_section" and s["section_mm"] == [25.0, 25.0]
    assert s["length_mm"] == 880.0 and s["wall_assumed"] and s["wall_mm"] == 1.5


def test_an_angle_keeps_both_legs_and_is_weighed_as_an_angle():
    s = cs.resolve_stock(_part("ANGLE RUNNERS", "", 415, 60, 40, 8))
    assert s["form"] == "angle" and s["section_mm"] == [60.0, 40.0]
    assert s["profile_form"] == "ANGLE"
    assert section_kg_per_m(60, 40, 3, "ANGLE") == pytest.approx(3 * 97 * 7850 / 1e6)
    assert section_kg_per_m(60, 40, 3, "ANGLE") < section_kg_per_m(60, 40, 3, "RHS")


def test_a_mesh_is_a_grid_of_wire_not_a_plate_its_grid_thick():
    s = cs.resolve_stock(_part("BASE MESH", "mesh", 415, 620, 25))
    assert s["form"] == "mesh" and s["aperture_mm"] == [25.0, 25.0]
    assert s["wire_assumed"] and s["wire_mm"] == 3.0
    assert s["wire_length_mm"] == (620 // 25 + 1) * 415 + (415 // 25 + 1) * 620 or \
        s["wire_length_mm"] == (415 // 25 + 1) * 620 + (620 // 25 + 1) * 415
    assert any("not a 25 mm plate" in n for n in s["notes"])
    mass = cs.stock_mass_kg(_part("BASE MESH", "mesh", 415, 620, 25))
    assert 0.5 < mass < 3.0, "a 415 x 620 mesh of 3 mm wire is about a kilo, not fifty"


def test_the_reads_own_stock_fields_come_first():
    s = cs.resolve_stock(_part("SIDE", "", 880, 25, 25, stock={
        "form": "box_section", "section_mm": [30, 20], "wall_mm": 2, "length_mm": 900}))
    assert s["section_mm"] == [30.0, 20.0] and s["wall_mm"] == 2.0
    assert s["length_mm"] == 900.0 and not s["wall_assumed"]


def test_a_line_cut_from_its_siblings_section_is_that_section():
    parts = [_part("FRAME VERTICALS", "25 x 25 box section", 880, 25, 25, 4),
             _part("FRAME HORIZONTALS", "mild steel", 415, 25, 25, 8)]
    v, h = cs.resolve_stocks(parts)
    assert h["form"] == "box_section" and h["length_mm"] == 415.0
    assert "FRAME VERTICALS" in h["notes"][0]


def test_a_thick_plate_nothing_explains_is_held_and_asked():
    s = cs.resolve_stock(_part("BASE", "mild steel", 600, 400, 25))
    assert s["form"] == "held"
    recs = cs.parts_from_concept({"parts": [_part("BASE", "mild steel", 600, 400, 25)]}, "J")
    flags = " ".join(recs[0]["review_flags"])
    assert "concept_stock_check" in str(recs[0]) or "state the stock" in flags


def test_sheet_and_board_are_untouched():
    assert cs.resolve_stock(_part("SIDE PANEL", "1.5mm sheet", 880, 620, 1.5)) == {}
    assert cs.resolve_stock(_part("TOP", "melamine", 480, 630, 16, material="MFMDF")) == {}


# ── the record the costing reads ─────────────────────────────────────────────────────────

def test_a_section_line_becomes_section_stock_sawn_not_lasered():
    rec = cs.parts_from_concept({"parts": [_part(
        "ANGLE RUNNERS", "60 x 40 angle", 415, 60, 40, 8,
        ops=["laser_cutting", "welding"])]}, "J")[0]
    ss = rec["section_stock"]
    assert (ss["a"], ss["b"], ss["t"], ss["length_mm"]) == (60.0, 40.0, 3.0, 415.0)
    assert ss["profile_form"] == "ANGLE" and rec["stock_form"] == "tube"
    assert rec["normalized_thickness_mm"] == 3.0, "the wall, never the 40 mm leg"
    assert rec["inferred_operations"][0] == "saw" and "laser_cutting" not in rec["inferred_operations"]
    assert any("60 x 40 x 3 angle, 415 mm long" in f for f in rec["review_flags"])


def test_a_mesh_line_becomes_wire_and_is_not_lasered():
    rec = cs.parts_from_concept({"parts": [_part(
        "BASE MESH", "25 x 25 mesh", 415, 620, 25, ops=["laser_cutting", "welding"])]}, "J")[0]
    assert rec["stock_form"] == "wire" and rec["wire_gauge_mm"] == 3.0
    assert rec["wire_length_mm"] > 20000
    assert rec["manufacturing_interpretation"]["stock_form"] == "wire"
    assert "laser_cutting" not in rec["inferred_operations"]
    assert rec["normalized_thickness_mm"] == 3.0


def test_the_estimator_never_prices_an_angle_from_a_box_section_row(monkeypatch):
    import estimator as E

    def _no(*a, **k):
        raise AssertionError("an angle asked the hollow-section catalogue")
    monkeypatch.setattr(E, "_lookup_catalogue_tube_price", _no)
    monkeypatch.setattr(E, "_lookup_catalogue_section_stock_rate", _no)
    rec = cs.parts_from_concept({"parts": [_part("ANGLE RUNNERS", "60 x 40 angle",
                                                 415, 60, 40, 8)]}, "J")[0]
    me = E.estimate_material(rec)
    assert me["stock_form"] == "tube" and me["cost_method"].startswith("section_stock")
    assert me["unit_material_mass_kg"] == pytest.approx(
        section_kg_per_m(60, 40, 3, "ANGLE") * 0.415, rel=0.01)


def test_the_estimator_costs_a_mesh_as_its_wire():
    import estimator as E
    rec = cs.parts_from_concept({"parts": [_part("BASE MESH", "25 x 25 mesh",
                                                 415, 620, 25)]}, "J")[0]
    me = E.estimate_material(rec)
    assert me["stock_form"] == "wire" and me["unit_material_mass_kg"] < 3.0
    assert me["cost_per_part_gbp"] < 20, "a mesh panel of wire, not £2,870 of plate"


# ── the weight: the check reads it, the shipment uses it ─────────────────────────────────

def test_a_lone_kg_figure_on_the_title_block_is_the_stated_weight():
    assert cs.sheet_stated_facts(TOTE_SHEET).get("stated_weight_kg") == 49.0
    assert "stated_weight_kg" not in cs.sheet_stated_facts("49KG\n12KG")


def test_a_gauge_that_names_its_part_is_not_the_products_gauge():
    assert "thickness_mm" not in cs.sheet_stated_facts(TOTE_SHEET)
    assert cs.sheet_stated_facts("2mm STEEL CONSTRUCTION")["thickness_mm"] == 2.0


def test_the_briefs_weight_is_used_where_the_sheet_gives_none():
    assert cs.brief_stated_weight("Overall ~480 x 630 x 1035 mm, 49 kg stated on the drawing.") == 49.0
    assert cs.brief_stated_weight("holds 20 bags at 1.5 kg each") == 0.0
    assert cs.brief_stated_weight("max load 50kg, unit weighs 12 kg") == 0.0
    bill = {"parts": [_part("PLATE", "mild steel", 1000, 1000, 10, 2)]}
    chk = cs.sheet_check(bill, "", brief="Unit, 20 kg stated on the drawing.")
    assert chk["stated_weight_kg"] == 20.0 and chk["stated_weight_from"] == "enquiry brief"
    assert any("oversized or counted twice" in f for f in chk["failures"])


def test_a_section_is_weighed_by_the_metre_and_not_failed_on_the_sheet_gauge():
    bill = {"parts": [_part("FRAME VERTICALS", "25 x 25 box section", 880, 25, 25, 4),
                      _part("BASE MESH", "25 x 25 mesh", 415, 620, 25),
                      _part("SIDES", "1.5mm sheet", 880, 620, 1.5, 2)]}
    chk = cs.sheet_check(bill, "1.2MM MILD STEEL THROUGHOUT\n49KG")
    assert chk["sighted_weight_kg"] < 20
    assert not any("FRAME VERTICALS is" in f or "BASE MESH is" in f for f in chk["failures"])
    assert any("SIDES is 1.5 mm" in f for f in chk["failures"]), "a sheet line is still held to it"


def test_the_shipment_weighs_a_section_by_its_costed_mass():
    import estimator as E
    recs = cs.parts_from_concept({"parts": [
        _part("FRAME VERTICALS", "25 x 25 box section", 880, 25, 25, 4),
        _part("BASE MESH", "25 x 25 mesh", 415, 620, 25)]}, "J")
    for r in recs:
        r["material_estimate"] = E.estimate_material(r)
    plan = palletising.plan_shipment(recs, 1)
    assert plan["order_weight_kg"] < 10 and plan["pallet_count"] == 1


# ── the prompt asks for the stock ─────────────────────────────────────────────────────────

def test_the_read_is_asked_for_the_stock_and_its_sizes():
    assert cs.CONCEPT_PROMPT_VERSION in ("c6", "c7", "c8")   # c7 (D-599) keeps the stock rules
    for word in ('"stock"', "section_mm", "wall_mm", "aperture_mm", "wire_mm",
                 "NEVER a count", "NEVER a thickness"):
        assert word in cs._PROMPT, word
