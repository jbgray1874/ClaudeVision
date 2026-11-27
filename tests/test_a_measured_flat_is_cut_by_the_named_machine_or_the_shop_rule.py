"""An acrylic part with a measured flat is cut by something: the machine its sheet names, or
the shop's rule for the material — never by nothing (D-440).

8188-08-015 WAVE LAYER 1, a 2,355 x 100 acrylic layer with a DXF flat, drawn on the waves
sub-assembly sheet (p.6) which prints both LASERED EDGES and CNC IN TWO HALVES. The acrylic
route kept its laser only on a laser signal and dropped it otherwise, adding no cutter in its
place: the moment the wave read as acrylic (D-426, before costing) its only cutting operation
vanished, and the 17:37 book cut three acrylic waves for nothing.

Now the sheet that draws the part is read for the cutter's words, legend removed
(config CUT_METHOD_WORDS): one method named is stamped, two named is a manufacturing question
and the shop rule (config CUT_METHOD_BY_MATERIAL: acrylic is lasered unless CNC is called for)
prices the working figure. Where the drawing names the router, the router is charged at its
department's rate and the laser is not. A named guillotine or saw stands as before.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import cut_method_reader as cmr                                       # noqa: E402
import estimator                                                      # noqa: E402
import wb_populate as wp                                              # noqa: E402

_LEGEND = """GENERAL TOLERANCES: FINISH SPECIFICATIONS: THIS DRAWING IS THE PROPERTY OF
LINEAR DIMENSIONS UP TO 120mm +/-0.5mm • POWDERCOATING: BETWEEN 80 - 120 MICRON
WELD SPECIFICATION: • CHROME PLATING: NICKEL LAYER = 8 - 12 MICRON.
• ALL WELDS TO BE TIG UNLESS STATED • LASER CUT EDGES TO BE DEBURRED
CHINA MATERIAL SPECIFICATIONS: • Q195 UP TO 3mm THICK FOR POWDER COATED STEEL
• ALWAYS REMOVE BURRS AND SHARP CORNERS
"""

_WAVES_SHEET = """ITEM NO. PartNo Description QTY.
1 8188-08-014 WAVE LAYER 2 1
2 8188-08-013 WAVE LAYER 3 1
3 8188-08-015 WAVE LAYER 1 1
LASERED EDGES. CNC IN TWO HALVES AND BONDED.
REAR FOLDED FOOT BUTTS UP AGAINST PANEL BEHIND TO ENSURE CORRECT SPACING.
WAVES SUB ASSY MATERIAL: FINISH: COLOUR: WEIGHT: 24419.60g DRAWING No 8188-08-SA04 1:10 H
"""


# ── the reader ──────────────────────────────────────────────────────────────────────────

def test_both_words_on_the_sheet_are_both_read():
    assert cmr.cut_methods_named(_WAVES_SHEET + _LEGEND) == {"laser": ["LASERED"], "router": ["CNC"]}


def test_the_legends_laser_is_not_the_sheets_cutter():
    assert cmr.cut_methods_named(_LEGEND) == {}


def test_only_cnc_named_is_the_router():
    sheet = _WAVES_SHEET.replace("LASERED EDGES. ", "")
    assert cmr.cut_methods_named(sheet + _LEGEND) == {"router": ["CNC"]}


def _wave(pn="8188-08-015", desc="WAVE LAYER 1", **over):
    part = {"part_number": pn, "description": desc, "quantity": 1, "pages": [6],
            "page_roles": ["assembly"], "normalized_material": "ACRYLIC", "thickness_mm": 3.0}
    part.update(over)
    return part


def _pages(text):
    return [{"page_number": "6", "pypdf_text": text}]


def test_one_machine_named_is_stamped_with_its_source():
    part = _wave()
    sheet = _WAVES_SHEET.replace("LASERED EDGES. ", "")
    assert cmr.apply_cut_method_from_sheets([part], _pages(sheet + _LEGEND)) == 1
    assert part["cut_method"] == "router"
    assert "p.6" in part["cut_method_source"] and "CNC" in part["cut_method_source"]


def test_two_machines_named_is_a_question_not_a_stamp():
    part = _wave()
    assert cmr.apply_cut_method_from_sheets([part], _pages(_WAVES_SHEET + _LEGEND)) == 1
    assert "cut_method" not in part
    qs = part.get("manufacturing_questions") or []
    assert len(qs) == 1 and "LASERED" in qs[0]["issue"] and "CNC" in qs[0]["issue"], qs
    assert "shop rule" in qs[0]["assumption"]


def test_a_stamped_part_an_assembly_and_a_purchase_are_left_alone():
    stamped = _wave(pn="8188-08-014", desc="WAVE LAYER 2", cut_method="laser")
    parent = _wave(pn="8188-08-SA04", desc="WAVES SUB ASSY", is_assembly_parent=True)
    bought = _wave(pn="8188-08-020", desc="MAG TAPE", is_bought_in=True)
    assert cmr.apply_cut_method_from_sheets([stamped, parent, bought],
                                            _pages(_WAVES_SHEET + _LEGEND)) == 0
    assert stamped["cut_method"] == "laser"
    assert "cut_method" not in parent and "cut_method" not in bought
    assert not parent.get("manufacturing_questions")


# ── the costing ─────────────────────────────────────────────────────────────────────────

def _measured_wave(**over):
    """015 as the live run holds it: acrylic, a DXF flat 2,354.72 x 99.99, folds inferred."""
    return _wave(overall_length_mm=2354.72, overall_width_mm=99.99,
                 normalized_geometry={"blank_length_mm": 2354.72, "blank_width_mm": 99.99},
                 inferred_operations=["laser_cutting", "folding", "handling"],
                 manufacturing_interpretation={"stock_form": "sheet", "requires_flat_blank": True,
                                               "run_driven_operations": ["laser_cutting", "folding",
                                                                         "handling"],
                                               "routing": []},
                 **over)


def test_no_machine_named_the_shop_rule_lasers_acrylic_and_says_so():
    part = _measured_wave()
    pe = estimator.estimate_part(part, 1)
    rt = pe["process_estimate"]["run_times_min_per_unit"]
    assert rt.get("laser_cutting", 0) > 0, rt
    assert "cnc_routing" not in rt
    assert float(pe["labour_estimate"]["costs_gbp"].get("laser_cutting") or 0) > 0
    flags = " ".join(str(f) for f in part.get("review_flags") or [])
    assert "shop rule for ACRYLIC" in flags and "confirm laser or CNC" in flags, flags
    assert part["operation_sources"]["laser_cutting"] == "acrylic_route_rule"
    assert wp._map_operation("laser_cutting", part) == "Laser (Acrylic)"


def test_the_sheet_naming_the_router_charges_the_cnc_and_not_the_laser():
    part = _measured_wave(cut_method="router",
                          cut_method_source="the sheet that draws it (p.6): CNC")
    pe = estimator.estimate_part(part, 1)
    rt = pe["process_estimate"]["run_times_min_per_unit"]
    assert "laser_cutting" not in rt, rt
    assert rt.get("cnc_routing", 0) > 0, rt
    assert float(pe["labour_estimate"]["costs_gbp"].get("cnc_routing") or 0) > 0
    assert float(pe["labour_estimate"]["costs_gbp"].get("laser_cutting") or 0) == 0
    assert part["operation_sources"]["cnc_routing"] == "acrylic_route_rule"
    flags = " ".join(str(f) for f in part.get("review_flags") or [])
    assert "cut on the CNC, not the laser" in flags and "p.6" in flags, flags


def test_a_named_guillotine_is_a_cutter_and_the_rule_stays_silent():
    part = _measured_wave(cut_method="guillotine")
    pe = estimator.estimate_part(part, 1)
    rt = pe["process_estimate"]["run_times_min_per_unit"]
    assert "laser_cutting" not in rt and "cnc_routing" not in rt, rt
    flags = " ".join(str(f) for f in part.get("review_flags") or [])
    assert "shop rule" not in flags


def test_a_part_with_no_measured_flat_gets_no_cutter_from_the_rule():
    part = _wave(inferred_operations=["handling"])
    pe = estimator.estimate_part(part, 1)
    rt = pe["process_estimate"]["run_times_min_per_unit"]
    assert "laser_cutting" not in rt and "cnc_routing" not in rt, rt


def test_the_question_from_the_sheet_still_prices_the_working_figure_on_the_laser():
    """Both words on p.6: the question is on the part and the shop rule lasers it meanwhile."""
    part = _measured_wave()
    cmr.apply_cut_method_from_sheets([part], _pages(_WAVES_SHEET + _LEGEND))
    pe = estimator.estimate_part(part, 1)
    rt = pe["process_estimate"]["run_times_min_per_unit"]
    assert rt.get("laser_cutting", 0) > 0, rt
    assert part["manufacturing_questions"][0]["issue"].startswith("8188-08-015")
