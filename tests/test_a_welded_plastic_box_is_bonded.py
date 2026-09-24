"""On acrylic, "weld" is a solvent weld: the joint is bonded, not dropped.

12633-10-GA, a clear PMMA box of six butt panels: the weld cue on the GA was correctly stripped as
a metal process and nothing replaced it, so the box was costed with no bonding at all.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import estimator                                                  # noqa: E402


def _ga(material):
    return {"part_number": "12633-10-GA", "description": "CONSUMABLE HOLDER",
            "material": material, "normalized_material": material,
            "is_assembly_parent": True, "assembly_children": ["A", "B", "C", "D", "E", "F"],
            "quantity": 1, "textual_operations": ["welding"]}


def test_an_acrylic_assembly_with_a_weld_cue_is_glued_not_welded():
    ga = _ga("ACRYLIC")
    costs = (estimator.estimate_part(ga, job_quantity=1).get("labour_estimate") or {}).get("costs_gbp") or {}
    assert "glue" in costs and "welding" not in costs and "dress_welds" not in costs
    assert ga.get("acrylic_bonded") is True


def test_timber_keeps_the_strip_alone():
    ga = _ga("MDF")
    costs = (estimator.estimate_part(ga, job_quantity=1).get("labour_estimate") or {}).get("costs_gbp") or {}
    assert "glue" not in costs and "welding" not in costs


def test_a_plastic_assembly_of_loose_panels_is_bonded_without_a_weld_note():
    """12633-00-GA: three acrylic sub-assemblies, no fixings, no weld note anywhere."""
    ga = _ga("ACRYLIC")
    ga["textual_operations"] = []
    ga["assembly_children"] = ["12633-02-01P", "12633-02-02P", "12633-02-03P"]
    costs = (estimator.estimate_part(ga, job_quantity=1).get("labour_estimate") or {}).get("costs_gbp") or {}
    assert "glue" in costs


def test_an_assembly_with_fixings_is_screwed_not_glued():
    ga = _ga("ACRYLIC")
    ga["textual_operations"] = []
    ga["assembly_children"] = ["X-01P", "X-02P", "FIXING43"]
    costs = (estimator.estimate_part(ga, job_quantity=1).get("labour_estimate") or {}).get("costs_gbp") or {}
    assert "glue" not in costs


def test_an_assembly_of_other_material_is_left_alone():
    ga = _ga("MILD STEEL")
    ga["textual_operations"] = []
    costs = (estimator.estimate_part(ga, job_quantity=1).get("labour_estimate") or {}).get("costs_gbp") or {}
    assert "glue" not in costs


def test_an_assembly_with_no_material_of_its_own_is_bonded_when_its_children_are_acrylic():
    """12633-00-GA: the wine lifter and beer plinth were minted from the SolidWorks tree with
    no material, so the assembly's own material could not say it was acrylic."""
    ga = {"part_number": "12633-02-GA", "description": "BEER PLINTH", "is_assembly_parent": True,
          "assembly_children": ["12633-02-01P", "12633-02-02P"], "quantity": 1,
          "child_materials": ["ACRYLIC", "ACRYLIC"]}
    costs = (estimator.estimate_part(ga, job_quantity=1).get("labour_estimate") or {}).get("costs_gbp") or {}
    assert "glue" in costs


def test_the_children_materials_are_stamped_before_costing():
    src = (ROOT / "src" / "estimator.py").read_text(encoding="utf-8")
    i = src.index('_ap["child_materials"]')
    assert i < src.index("part_estimate = estimate_part(part, job_quantity=_order_qty)")


def test_an_acrylic_base_takes_its_linebend_from_the_charged_fold_count():
    """12633-01-01P: two bends in the SolidWorks tree and no Linebend row."""
    p = {"part_number": "12633-01-01P", "description": "BASE", "material": "ACRYLIC",
         "normalized_material": "ACRYLIC", "thickness_mm": 5, "normalized_thickness_mm": 5,
         "geometry_source": "dxf", "quantity": 1, "cut_method": "laser",
         "inferred_operations": ["laser_cutting"],
         "normalized_geometry": {"blank_length_mm": 450, "blank_width_mm": 292.1},
         "solidworks_bend_features": 2, "drawing_bend_callouts": 2}
    costs = (estimator.estimate_part(p, job_quantity=1).get("labour_estimate") or {}).get("costs_gbp") or {}
    assert "linebend" in costs


def test_a_model_bend_the_drawing_never_calls_out_is_not_charged():
    """12633-02-01P: one SolidWorks bend feature on a flat 400 x 71 plate, no callout."""
    p = {"part_number": "12633-02-01P", "description": "BOTTOM PANEL", "material": "ACRYLIC",
         "normalized_material": "ACRYLIC", "thickness_mm": 5, "normalized_thickness_mm": 5,
         "geometry_source": "dxf", "quantity": 1, "cut_method": "laser",
         "inferred_operations": ["laser_cutting"],
         "normalized_geometry": {"blank_length_mm": 400, "blank_width_mm": 71},
         "solidworks_bend_features": 1}
    costs = (estimator.estimate_part(p, job_quantity=1).get("labour_estimate") or {}).get("costs_gbp") or {}
    assert "linebend" not in costs
    flags = " | ".join(str(f) for f in p.get("review_flags") or [])
    assert "is CHARGED" not in flags and "fold(s) charged" not in flags
    assert "no Linebend charged" in flags


def test_bend_callouts_are_counted_off_the_parts_own_sheet():
    from drawing_job_merge import stamp_drawing_bend_callouts
    parts = [{"part_number": "12633-01-01P", "pages": [3]},
             {"part_number": "12633-02-01P", "pages": [5]}]
    summary = {"pages": [{"page_number": 3, "pdfplumber_text": "FLAT PATTERN UP  105°  R 1 DOWN  105°  R 1"},
                         {"page_number": 5, "pdfplumber_text": "BOTTOM PANEL 400 71 5"}]}
    assert stamp_drawing_bend_callouts(parts, summary) == 1
    assert parts[0]["drawing_bend_callouts"] == 2 and "drawing_bend_callouts" not in parts[1]


def test_the_joint_method_is_one_decision_naming_every_bonded_assembly():
    import costed_facts as cf
    parts = [{"part_number": "12633-01-GA", "acrylic_bonded": True},
             {"part_number": "12633-02-GA", "acrylic_bonded": True},
             {"part_number": "12633-03-01P"}]
    job = cf.costed_job({"manufacturing_writeup": {"parts": parts},
                         "estimate_summary": {"part_estimates": []}})
    hits = [d for d in job["decisions_required"] if "joined" in str(d.get("issue"))]
    assert len(hits) == 1 and "12633-01-GA" in hits[0]["part"] and "12633-02-GA" in hits[0]["part"]
