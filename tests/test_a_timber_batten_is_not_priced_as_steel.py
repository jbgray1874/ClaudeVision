"""A solid timber batten is priced as timber, not as steel section (D-599c).

The HPP fixture's 13:52 book: eight 600 x 50 x 38 timber blocks came from the vision read as a
solid flat bar, wall = thickness = 38. The rule that a hollow section cannot be timber took the
"wall" as a tube wall, forced the material to mild steel, and the steel section trade rate priced
8.9 kg of steel at GBP 67.85 a block, GBP 542.80 for eight.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import concept_scan  # noqa: E402
import estimator  # noqa: E402


def _part(form, section, material="TIMBER", wall=0):
    answer = {"product": {"name": "X"}, "unit_operations": ["assembly"], "parts": [{
        "name": "RADIAL WOOD BLOCKING", "kind": "fabricated", "sighted_material": "wood",
        "material_guess": material, "assumed_blank_mm": {"length": 600, "width": 50, "thickness": 38},
        "stock": {"form": form, "section_mm": section, "wall_mm": wall, "length_mm": 600,
                  "aperture_mm": [], "wire_mm": 0},
        "quantity": 8, "operations": ["saw", "glue"], "why_size": "drawing"}]}
    parts = concept_scan.parts_from_concept(answer, "JOB")
    parts = parts if isinstance(parts, list) else parts.get("parts", parts)
    return [p for p in parts if "BLOCKING" in str(p.get("description", ""))][0]


def test_a_solid_timber_bar_stays_timber_at_its_own_rate():
    p = _part("flat_bar", [50, 38])
    got = estimator.estimate_material(p)
    assert got["material"] == "TIMBER"
    assert got["unit_material_mass_kg"] < 1.0, "0.68 kg of timber, never 8.9 kg of steel"
    assert got["unit_material_cost_gbp"] < 2.0
    assert not any("overridden to MILD STEEL" in f for f in p.get("review_flags", []))


def test_a_hollow_section_tagged_timber_is_still_steel():
    """The rule's own case is kept: a 25 x 25 x 1.5 tube cannot be timber."""
    p = _part("box_section", [25, 25], wall=1.5)
    p["section_stock"].update({"a": 25.0, "b": 25.0, "t": 1.5})
    got = estimator.estimate_material(p)
    assert got["material"] == "MILD STEEL"
    assert any("overridden to MILD STEEL" in f for f in p.get("review_flags", []))


def test_the_section_trade_rate_is_for_metal_only():
    steel = estimator.estimate_material(_part("flat_bar", [50, 38], material="MILD STEEL"))
    timber = estimator.estimate_material(_part("flat_bar", [50, 38]))
    assert steel["unit_material_cost_gbp"] > 20 * timber["unit_material_cost_gbp"]
