"""A part priced from a measured flat must have a way to become that flat.

12312-01-GA: the 03A Foamex back panel (its own DXF, nested and charged) and the 04G card
graphic reached the book with a material charge and no cutting row, and nothing said so.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from drawing_job_merge import propose_missing_cuts               # noqa: E402
from route_compiler import compile_job_route                      # noqa: E402
import costed_facts as cf                                         # noqa: E402


def _parts():
    return [
        {"part_number": "12312-01-03A", "description": "BACK PANEL", "material": "FOAMED PVC",
         "thickness_mm": 3, "geometry_source": "dxf", "quantity": 1},
        {"part_number": "12312-01-04G", "description": "SIDE GRAPHIC", "material": "CARD",
         "geometry_source": "dxf", "page_roles": ["bought_in"], "quantity": 2},
        {"part_number": "X-01M", "description": "PANEL", "normalized_material": "MILD_STEEL",
         "material": "MILD STEEL", "geometry_source": "dxf", "quantity": 1},
        {"part_number": "X-02M", "description": "PANEL", "material": "MILD STEEL",
         "geometry_source": "dxf", "textual_operations": ["laser_cutting"], "quantity": 1},
        {"part_number": "X-03", "description": "BRACKET", "material": "MILD STEEL", "quantity": 1},
    ]


def test_foamex_with_a_flat_is_routed_and_the_machine_is_asked():
    parts = _parts()
    propose_missing_cuts(parts)
    foam = parts[0]
    assert foam["inferred_operations"] == ["cnc_routing"]
    assert "FOAMED PVC" in foam["route_gap"]["issue"]
    g = compile_job_route(parts, {})
    assert ("12312-01-03A", "cnc_routing", "required") in {
        (d["target_id"], d["operation"], d["status"]) for d in g["decisions"]}


def test_a_card_graphic_is_asked_not_given_a_machine():
    parts = _parts()
    propose_missing_cuts(parts)
    card = parts[1]
    assert not card.get("inferred_operations")
    assert "nothing cuts it" in card["route_gap"]["issue"]


def test_the_shop_rule_applies_and_an_existing_cut_is_left_alone():
    parts = _parts()
    propose_missing_cuts(parts)
    assert parts[2]["inferred_operations"] == ["laser_cutting"] and not parts[2].get("route_gap")
    assert not parts[3].get("inferred_operations")
    assert not parts[4].get("inferred_operations"), "no measured flat, nothing proposed"


def test_the_gap_reaches_the_review_list():
    parts = _parts()
    propose_missing_cuts(parts)
    job = cf.costed_job({"manufacturing_writeup": {"parts": parts},
                         "estimate_summary": {"part_estimates": parts}})
    issues = [d["issue"] for d in job["decisions_required"]
              if d["kind"] == "manufacturing_decision"]
    assert any("12312-01-04G" in i for i in issues) and any("12312-01-03A" in i for i in issues)


def test_the_labour_row_names_the_drawings_material_and_the_substitute():
    """16:04 rerun: the CNC row still read "3mm ACRYLIC" — material_priced_as never reached
    the workbook's record; the substitution flag did."""
    from wb_populate import labour_row_description, material_shown_on_row
    flag = {"severity": "warning", "flag": "material_unpriceable_substituted",
            "detail": ("FOAMED PVC is not priceable by this engine -- no sheet rate and no "
                       "GBP/kg -- and ACRYLIC, read from inference, is. Priced from ACRYLIC.")}
    assert material_shown_on_row({"review_flags": [flag]}, "ACRYLIC") == \
        "FOAMED PVC (priced as ACRYLIC)"
    assert material_shown_on_row({"material_priced_as": {
        "arbitrated_material": "FOAMED PVC", "priced_material": "ACRYLIC"}}, "ACRYLIC") == \
        "FOAMED PVC (priced as ACRYLIC)"
    assert material_shown_on_row({}, "MILD_STEEL") == "MILD_STEEL"
    src = (ROOT / "src" / "wb_populate.py").read_text(encoding="utf-8")
    assert "_shown = material_shown_on_row(pe, _mat)" in src
    row = labour_row_description("CNC", "FOAMED PVC (priced as ACRYLIC)", 3, ["12312-01-03A"])
    assert "FOAMED PVC" in row and "priced as ACRYLIC" in row


def test_pmma_takes_the_acrylic_rule_and_the_laser_survives_the_acrylic_route():
    """12633-10: the files say PMMA, the title block ACRYLIC. The shop rule is ACRYLIC ->
    laser; and the estimator's acrylic route drops laser unless the part carries a laser
    signal, so the proposal must set one."""
    parts = [{"part_number": "12633-10-01P", "description": "FRONT PANEL", "material": "PMMA",
              "thickness_mm": 5, "geometry_source": "dxf", "quantity": 2}]
    propose_missing_cuts(parts)
    assert parts[0]["inferred_operations"] == ["laser_cutting"]
    assert parts[0]["cut_method"] == "laser" and not parts[0].get("route_gap")


def test_a_general_arrangement_dxf_is_never_proposed_as_a_cut():
    parts = [{"part_number": "12633-10-GA", "description": "CONSUMABLE HOLDER",
              "material": "ACRYLIC", "geometry_source": "dxf", "quantity": 1}]
    assert propose_missing_cuts(parts) == [] and not parts[0].get("inferred_operations")
