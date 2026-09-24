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
