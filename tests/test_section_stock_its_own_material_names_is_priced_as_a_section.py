"""Section stock its own material names is priced as a section, not as sheet (D-653).

12684-02-GA, 3 Nov 2026 (SCRUM-100/107/155): a steel tabletop frame with 33 hooks. Three parts are
drawn and stated as section stock, and the workbook charged all three through the Sheet Steel
block as flat sheet:

    M06 OUTER FRAME  '1/2" SQUARE STEEL TUBE', UNDEVELOPED TUBE 1500, stated 0.58 kg
                     -> a 1500 x 500 blank with no gauge, "DIMS REQUIRED", material GBP 0
    M07 CROSS BAR    '10mm SQUARE STEEL BAR', 484.6 long, x11, stated 0.37 kg
                     -> 484.6 x 10 strips of 10 mm plate, plus a Laser (Metal) row
    M02 ARM          mild steel, Ø5, 153.1 long, bent, x33, stated 0.02 kg, no ROD or BAR printed
                     -> a blank with no gauge, "DIMS REQUIRED", material GBP 0

The part's own printed material words sat on the record and nothing that decides "section or
sheet" read them; the a x b x t reader cannot read one size and a shape, nor an inch figure.
The rules under test are generic: the part's own material words reach the decision, an inch
size is read in millimetres, a solid bar is weighed as its whole section, a hollow one at a
working wall that the line says is one, and a stated weight checks the result.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import detail_page_geometry as dpg  # noqa: E402
import estimator as E  # noqa: E402
import section_profile as SP  # noqa: E402
import wb_populate as W  # noqa: E402


@pytest.fixture(autouse=True)
def _no_catalogue(monkeypatch):
    """The section rates under test are the engine's own, not whatever a catalogue holds."""
    monkeypatch.setattr(E, "_lookup_catalogue_tube_price", lambda *a, **k: None)
    monkeypatch.setattr(E, "_lookup_catalogue_section_stock_rate", lambda *a, **k: None)


def _frame(**extra):
    """12684-02-M06 as a drawing read leaves it: its own title block's material, the overall
    its sheet prints, its stated weight — and a name and a steel code that say nothing."""
    return dict({"part_number": "12684-02-M06", "description": "OUTER FRAME", "quantity": 1,
                 "normalized_material": "MILD_STEEL",
                 "material_text_as_printed": '1/2" SQUARE STEEL TUBE',
                 "material_stated": '1/2" SQUARE STEEL TUBE',
                 "overall_length_mm": 1500.0, "overall_width_mm": 500.0,
                 "all_dimensions_mm": ["1500", "500"], "weights": ["0.58KG"],
                 "page_roles": ["detail"]}, **extra)


def _cross_bar(**extra):
    return dict({"part_number": "12684-02-M07", "description": "CROSS BAR", "quantity": 11,
                 "normalized_material": "MILD_STEEL",
                 "material_text_as_printed": "10mm SQUARE STEEL BAR",
                 "material_stated": "10mm SQUARE STEEL BAR", "normalized_thickness_mm": 10.0,
                 "overall_length_mm": 484.6, "overall_width_mm": 10.0,
                 "all_dimensions_mm": ["484.6", "10"], "weights": ["0.37KG"],
                 "normalized_finish": "RAW", "page_roles": ["detail"]}, **extra)


def _arm(**extra):
    """12684-02-M02: the only round evidence is the Ø5 callout, which a drawing read holds as a
    diameter in hole_sizes_mm, beside the length its sheet prints and its stated weight."""
    return dict({"part_number": "12684-02-M02", "description": "ARM", "quantity": 33,
                 "normalized_material": "MILD_STEEL", "materials": ["MILD STEEL"],
                 "hole_sizes_mm": ["5"], "angles_deg": ["30", "93"],
                 "overall_length_mm": 153.1, "all_dimensions_mm": ["153.1", "5"],
                 "weights": ["0.02KG"], "page_roles": ["detail"]}, **extra)


# ── the reader: one material cell, one stock ────────────────────────────────────────────

def test_an_inch_size_is_read_in_millimetres():
    assert SP.inch_sizes_to_mm('1/2" SQUARE STEEL TUBE') == "12.7MM SQUARE STEEL TUBE"
    assert SP.inch_sizes_to_mm('1 1/2" TUBE') == "38.1MM TUBE"
    assert SP.inch_sizes_to_mm("3/4 IN SQ TUBE") == "19.05MM SQ TUBE"
    assert SP.inch_sizes_to_mm("3/16 ROD") == "3/16 ROD", "a fraction with no unit is not guessed"


def test_a_half_inch_square_tube_is_a_12_7_shs_with_no_wall_stated():
    got = SP.stock_in_material_words('1/2" SQUARE STEEL TUBE')
    assert (got["a"], got["b"], got["profile_form"], got["form"]) == (12.7, 12.7, "SHS",
                                                                      "box_section")
    assert got["t"] is None and got["wall_stated"] is False and got["solid"] is False


def test_a_ten_millimetre_square_bar_is_solid_square_bar():
    got = SP.stock_in_material_words("10mm SQUARE STEEL BAR")
    assert (got["a"], got["b"], got["t"], got["profile_form"], got["form"]) == (
        10.0, 10.0, 10.0, "FLAT", "square_bar")
    assert got["solid"] is True
    assert SP.section_kg_per_m(got["a"], got["b"], got["t"], got["profile_form"]) == \
        pytest.approx(0.785, rel=0.01), "a 10 x 10 solid square, not a 10 mm plate"


def test_a_rod_with_its_diameter_is_round_bar():
    got = SP.stock_in_material_words("5mm DIA ROD")
    assert (got["a"], got["profile_form"], got["form"], got["solid"]) == (5.0, "ROUND",
                                                                         "round_bar", True)


def test_an_inch_profile_reads_through_the_one_section_reader():
    got = SP.stock_in_material_words('1/2" x 1/2" x 1.5 SHS')
    assert (got["a"], got["b"], got["t"]) == (12.7, 12.7, 1.5)


@pytest.mark.parametrize("cell", ["MILD STEEL", "Ø5 MILD STEEL", "25MM TUBE", "10MM BAR",
                                  "50 x 10 FLAT BAR", "25 X 25 ANGLE", "MILD STEEL WIRE Ø8MM",
                                  "CR4 1.2MM", "SQUARE TUBE"])
def test_a_cell_that_names_no_one_stock_reads_nothing(cell):
    assert SP.stock_in_material_words(cell) is None


def test_cells_that_disagree_decide_nothing():
    assert SP.stock_in_own_material_words({"material_text_as_printed": "10mm SQUARE STEEL BAR",
                                        "material_stated": "12mm SQUARE STEEL BAR"}) is None
    assert SP.stock_in_own_material_words({"material_text_as_printed_candidates": [
        "10mm SQUARE STEEL BAR", "MILD STEEL"]}) is None


# ── the decision: the part's own words reach it ──────────────────────────────────────────

def test_the_parts_own_material_words_make_it_a_section_candidate():
    assert E._is_section_or_wire_candidate(_frame(), "MILD_STEEL")
    assert E._is_section_or_wire_candidate(_cross_bar(), "MILD_STEEL")
    plain = _frame(material_text_as_printed="MILD STEEL", material_stated=None)
    assert not E._is_section_or_wire_candidate(plain, "MILD_STEEL")


def test_a_measured_flat_is_sheet_whatever_its_cell_says():
    flat = _cross_bar(dxf_augmented=True, geometry_source="dxf_flat_pattern")
    assert E._own_material_section(flat) is None


def test_the_blank_readers_see_a_section_and_give_it_no_blank():
    assert dpg._is_section_stock(_frame()) and dpg.not_cut_from_a_blank(_frame())
    assert dpg._is_section_stock(_cross_bar()) and dpg.not_cut_from_a_blank(_cross_bar())


# ── the price: by weight over length, the line saying what it assumed ────────────────────

def test_the_outer_frame_is_costed_as_half_inch_shs_at_the_working_wall():
    part = _frame()
    me = E.estimate_material(part)
    assert me["stock_form"] == "tube" and me["cost_method"].startswith("section_stock")
    assert part["stock_form"] == "tube", "the route compiler's stock-form gate reads the part"
    ss = part["section_stock"]
    assert (ss["a"], ss["b"], ss["profile_form"], ss["t"]) == (12.7, 12.7, "SHS", 1.5)
    assert ss["wall_assumed"] is True and ss["source"] == "material_as_printed"
    assert me["stock_estimate"]["section_length_mm"] == 1500.0
    assert me["unit_material_mass_kg"] == pytest.approx(0.79, abs=0.01)
    assert me["extended_material_cost_gbp"] > 0, "never GBP 0 for want of a gauge"
    assert me["section_description"] == "12.7 x 12.7 x 1.5 SHS"
    chk = me["stock_estimate"]["stated_weight_check"]
    assert chk["stated_kg"] == 0.58 and chk["agrees"] and chk["ratio"] == pytest.approx(1.36,
                                                                                      abs=0.02)
    said = [f for f in part["review_flags"] if "costed as 12.7 x 12.7 x 1.5 SHS" in str(f)]
    assert said and "WORKING FIGURE" in said[0] and "'12.7MM SQUARE STEEL TUBE'" in said[0]
    assert "wall of about 1.06 mm" in said[0], "the stated weight's own wall is said beside it"
    asked = [q for q in part["manufacturing_questions"] if "What wall is" in q["issue"]]
    assert asked and "working figure" in asked[0]["assumption"]


def test_the_frame_reads_the_same_on_a_second_costing():
    part = _frame()
    first = E.estimate_material(part)
    second = E.estimate_material(part)
    assert second["extended_material_cost_gbp"] == first["extended_material_cost_gbp"]
    assert second["stock_estimate"]["section_read_from"] == "material_as_printed"
    assert second["stock_estimate"]["section_wall_assumed"] is True
    assert len([f for f in part["review_flags"] if "costed as 12.7" in str(f)]) == 1
    assert len([q for q in part["manufacturing_questions"] if "What wall" in q["issue"]]) == 1


def test_the_cross_bar_is_costed_as_solid_square_bar_by_its_weight():
    part = _cross_bar()
    me = E.estimate_material(part)
    assert me["stock_form"] == "tube" and me["cost_method"].startswith("section_stock")
    assert me["section_description"] == "10 x 10 square bar"
    assert me["unit_material_mass_kg"] == pytest.approx(0.38, abs=0.005)
    chk = me["stock_estimate"]["stated_weight_check"]
    assert chk["agrees"] and chk["ratio"] == pytest.approx(1.03, abs=0.02)
    # PER KG STAYS PER KG (SCRUM-182): the line is its weight at the rate it names, plus the
    # section's cut loss — not a share of a sheet.
    assert me["unit_material_cost_gbp"] == pytest.approx(
        me["unit_material_mass_kg"] * me["rate_gbp_per_kg"] * me["waste_factor_applied"],
        abs=0.02)
    assert not part["section_stock"].get("wall_assumed"), "a solid bar has no wall to assume"
    assert W._line_is_its_own_section_stock(me), "it is a section line on the bill, not sheet"


def test_a_section_with_its_own_cut_length_saws_that_length():
    part = _cross_bar()
    est = E.estimate_part(part, job_quantity=1)
    assert part["_saw_cut_list_pieces"] == [484.6]
    assert "laser_cutting" not in (est.get("labour_estimate") or {}).get("costs_gbp", {})


def test_a_weight_that_disagrees_is_said_and_asked():
    part = _cross_bar(weights=["1.2KG"])
    me = E.estimate_material(part)
    assert not me["stock_estimate"]["stated_weight_check"]["agrees"]
    assert any("OUTSIDE" in str(f) for f in part["review_flags"])
    assert any("Is 12684-02-M07 10 x 10 square bar" in q["issue"]
               for q in part["manufacturing_questions"])


# ── round bar: the bar path, by its own length ──────────────────────────────────────────

def test_the_arms_diameter_its_own_weight_confirms_is_round_bar():
    part = _arm()
    me = E.estimate_material(part)
    assert me["stock_form"] == "wire" and me["cost_method"] == "workbook_bar_formula"
    assert (me["wire_gauge_mm"], me["wire_length_mm"]) == (5.0, 153.1)
    assert me["unit_material_mass_kg"] == pytest.approx(0.0236, abs=0.0005)
    assert me["stock_estimate"]["round_stock_warrant"] == "weight_confirmed"
    assert me["extended_material_cost_gbp"] > 0
    assert part["stock_form"] == "wire" and part["wire_gauge_mm"] == 5.0
    assert any("nothing printed says ROD or BAR" in str(f) for f in part["review_flags"])
    assert any(q["issue"] == "Is 12684-02-M02 Ø5 round bar?"
               for q in part["manufacturing_questions"])


def test_the_round_bar_reading_is_the_same_on_a_second_costing():
    part = _arm()
    first = E.estimate_material(part)
    second = E.estimate_material(part)
    assert (second["cost_method"], second["wire_length_mm"],
            second["extended_material_cost_gbp"]) == (
        first["cost_method"], first["wire_length_mm"], first["extended_material_cost_gbp"])


@pytest.mark.parametrize("change", [
    {"weights": []},                                   # nothing confirms it: a hole is a hole
    {"weights": ["0.3KG"]},                            # the weight says it is not that rod
    {"normalized_thickness_mm": 2.0},                  # a gauge of its own says sheet
    {"hole_sizes_mm": ["5", "8"]},                     # two diameters are not one stock
    {"dxf_augmented": True, "geometry_source": "dxf_flat_pattern"},   # a measured flat
])
def test_a_lone_diameter_without_its_weight_behind_it_is_not_round_bar(change):
    part = _arm(**change)
    assert E._round_stock_from_own_evidence(part, "MILD_STEEL") is None


def test_a_rod_its_cell_names_is_priced_on_the_bar_path():
    part = _arm(hole_sizes_mm=[], weights=[], material_text_as_printed="5mm DIA ROD")
    me = E.estimate_material(part)
    assert me["stock_form"] == "wire" and me["wire_gauge_mm"] == 5.0
    assert me["stock_estimate"]["round_stock_warrant"] == "material_words"
    assert me["estimator_input_required"], "no weight confirms the length, so it is asked"
