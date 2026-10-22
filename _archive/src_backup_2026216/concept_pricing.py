from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


def _safe_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class ConceptRateCard:
    frame_base_gbp: float = 325.0
    volume_factor_gbp_per_m3: float = 185.0
    mesh_factor_gbp_per_m2: float = 18.0
    shelf_each_gbp: float = 42.0
    door_each_gbp: float = 65.0
    spring_lock_each_gbp: float = 18.0
    padlock_each_gbp: float = 32.0
    branding_panel_each_gbp: float = 28.0
    plastic_bin_each_gbp: float = 16.0
    rail_each_gbp: float = 9.0
    separator_each_gbp: float = 4.5
    decoupler_supply_and_fix_gbp: float = 48.0
    packaging_each_gbp: float = 22.0
    finishing_factor_pct: float = 8.0
    install_labour_gbp: float = 36.0
    contingency_pct: float = 12.0


def _estimate_frame_and_mesh(assembly_summary: Dict[str, Any], features: Dict[str, Any], rates: ConceptRateCard) -> Dict[str, Any]:
    dims = assembly_summary.get("overall_dimensions_mm", {}) or {}
    length = _safe_float(dims.get("length"))
    depth = _safe_float(dims.get("depth"))
    height = _safe_float(dims.get("height_including_wheels"))
    shelves = _safe_int(features.get("shelves", {}).get("count")) or 0

    volume_m3 = None
    mesh_area_m2 = None
    if length is not None and depth is not None and height is not None:
        volume_m3 = round((length * depth * height) / 1_000_000_000.0, 4)
        footprint = (length * depth) / 1_000_000.0
        side_area = (2 * length * height + 2 * depth * height) / 1_000_000.0
        shelf_area = footprint * max(shelves, 1)
        mesh_area_m2 = round(side_area + shelf_area, 4)

    base = rates.frame_base_gbp
    volume_component = (volume_m3 or 0.0) * rates.volume_factor_gbp_per_m3
    mesh_component = (mesh_area_m2 or 0.0) * rates.mesh_factor_gbp_per_m2
    subtotal = round(base + volume_component + mesh_component, 2)

    return {
        "line_item": "frame_and_mesh",
        "description": "Tubular frame and wire mesh enclosure",
        "quantity": 1,
        "unit_cost_gbp": subtotal,
        "extended_cost_gbp": subtotal,
        "workings": {
            "base_gbp": base,
            "volume_m3": volume_m3,
            "volume_component_gbp": round(volume_component, 2),
            "mesh_area_m2": mesh_area_m2,
            "mesh_component_gbp": round(mesh_component, 2),
        },
        "assumptions": [
            "Budgetary frame allowance derived from overall envelope volume and mesh surface area.",
            "No cut-list, weld map, or tube stock optimisation available at concept stage.",
        ],
    }


def _simple_line_item(name: str, description: str, quantity: int, unit_cost_gbp: float, assumptions: List[str]) -> Dict[str, Any]:
    extended = round(quantity * unit_cost_gbp, 2)
    return {
        "line_item": name,
        "description": description,
        "quantity": quantity,
        "unit_cost_gbp": round(unit_cost_gbp, 2),
        "extended_cost_gbp": extended,
        "workings": {
            "quantity": quantity,
            "unit_cost_gbp": round(unit_cost_gbp, 2),
        },
        "assumptions": assumptions,
    }


def build_concept_part_rows(features: Dict[str, Any], cost_breakdown: Dict[str, Any]) -> List[Dict[str, Any]]:
    items_by_name = {item["line_item"]: item for item in cost_breakdown.get("line_items", [])}
    parts: List[Dict[str, Any]] = []

    mapping = [
        ("frame_and_mesh", "FRAME ASSEMBLY", "concept assembly"),
        ("shelves", "ADJUSTABLE STEEL SHELVES", "concept component"),
        ("doors", "DOOR SET", "concept component"),
        ("spring_locks", "SPRING LOCKS", "bought-in"),
        ("padlock", "CODE PADLOCK", "bought-in"),
        ("branding_panels", "BRANDING PANELS", "bought-in"),
        ("plastic_bins", "PLASTIC BINS", "bought-in"),
        ("rails", "INTERNAL RAILS", "bought-in"),
        ("separators", "INTERNAL SEPARATORS", "bought-in"),
        ("anti_theft_decoupler", "ANTI-THEFT DECOUPLER", "bought-in"),
        ("packaging", "INDIVIDUAL PACKAGING", "commercial"),
        ("installation", "INSTALLATION / FIT-OUT", "commercial"),
        ("finishing", "FINISHING ALLOWANCE", "commercial"),
        ("contingency", "CONCEPT CONTINGENCY", "commercial"),
    ]

    for key, description, category in mapping:
        item = items_by_name.get(key)
        if not item:
            continue
        parts.append(
            {
                "part_number": key.upper(),
                "description": description,
                "quantity": item.get("quantity", 1),
                "category": category,
                "specification": features.get(key, {}),
                "costing": {
                    "unit_cost_gbp": item.get("unit_cost_gbp"),
                    "extended_cost_gbp": item.get("extended_cost_gbp"),
                    "assumptions": item.get("assumptions", []),
                    "workings": item.get("workings", {}),
                },
                "confidence": {
                    "pricing": 0.45 if category == "commercial" else 0.55,
                },
                "review_flags": [
                    "concept_pricing_only",
                ],
            }
        )
    return parts


def estimate_concept_pricing(brief: Dict[str, Any]) -> Dict[str, Any]:
    rates = ConceptRateCard()
    assembly_summary = brief.get("assembly_summary", {}) or {}
    features = brief.get("features", {}) or {}

    line_items: List[Dict[str, Any]] = []
    line_items.append(_estimate_frame_and_mesh(assembly_summary, features, rates))

    shelf_count = _safe_int(features.get("shelves", {}).get("count")) or 0
    if shelf_count:
        line_items.append(
            _simple_line_item(
                "shelves",
                "Adjustable steel shelves",
                shelf_count,
                rates.shelf_each_gbp,
                ["Allowance per adjustable shelf including shelf support hardware."],
            )
        )

    door_count = _safe_int(features.get("doors", {}).get("count")) or 0
    if door_count:
        line_items.append(
            _simple_line_item(
                "doors",
                "Door leaves and hinge hardware",
                door_count,
                rates.door_each_gbp,
                ["Allowance per door leaf with hinges, excluding detailed latch engineering."],
            )
        )

    spring_lock_count = _safe_int(features.get("locks", {}).get("spring_locks")) or 0
    if spring_lock_count:
        line_items.append(
            _simple_line_item(
                "spring_locks",
                "Spring locks",
                spring_lock_count,
                rates.spring_lock_each_gbp,
                ["Bought-in lock hardware concept allowance."],
            )
        )

    padlock_digits = features.get("locks", {}).get("padlock", {}).get("digits")
    if padlock_digits:
        line_items.append(
            _simple_line_item(
                "padlock",
                "Code padlock",
                1,
                rates.padlock_each_gbp,
                ["Bought-in padlock allowance based on specified code padlock requirement."],
            )
        )

    panel_count = _safe_int(features.get("branding", {}).get("panel_count")) or 0
    if panel_count:
        line_items.append(
            _simple_line_item(
                "branding_panels",
                "Branding panels",
                panel_count,
                rates.branding_panel_each_gbp,
                ["Allowance per branding panel excluding final artwork production."],
            )
        )

    bin_count = _safe_int(features.get("bins", {}).get("count")) or 0
    if bin_count:
        line_items.append(
            _simple_line_item(
                "plastic_bins",
                "Plastic bins",
                bin_count,
                rates.plastic_bin_each_gbp,
                ["Bought-in bin allowance based on stated nominal size."],
            )
        )

    rail_count = _safe_int(features.get("internal_fixtures", {}).get("rails")) or 0
    if rail_count:
        line_items.append(
            _simple_line_item(
                "rails",
                "Internal rails",
                rail_count,
                rates.rail_each_gbp,
                ["Allowance per internal rail from concept spec."],
            )
        )

    separator_count = _safe_int(features.get("internal_fixtures", {}).get("separators")) or 0
    if separator_count:
        line_items.append(
            _simple_line_item(
                "separators",
                "Internal separators",
                separator_count,
                rates.separator_each_gbp,
                ["Allowance per separator from concept spec."],
            )
        )

    if features.get("security_accessory", {}).get("anti_theft_decoupler", {}).get("supply_required"):
        line_items.append(
            _simple_line_item(
                "anti_theft_decoupler",
                "Anti-theft decoupler supply and fixing",
                1,
                rates.decoupler_supply_and_fix_gbp,
                ["Allowance includes supply and fixing as stated in concept brief."],
            )
        )

    if brief.get("commercial_requirements", {}).get("packaging"):
        line_items.append(
            _simple_line_item(
                "packaging",
                "Individual packaging",
                1,
                rates.packaging_each_gbp,
                ["Single-pack allowance from concept brief wording."],
            )
        )

    if brief.get("commercial_requirements", {}).get("installation_scope"):
        line_items.append(
            _simple_line_item(
                "installation",
                "Installation / fit-out allowance",
                1,
                rates.install_labour_gbp,
                ["Concept-stage installation labour allowance for listed accessories/fit-out."],
            )
        )

    subtotal_before_finish = round(sum(item["extended_cost_gbp"] for item in line_items), 2)
    finishing_cost = round(subtotal_before_finish * (rates.finishing_factor_pct / 100.0), 2)
    if finishing_cost:
        line_items.append(
            _simple_line_item(
                "finishing",
                "Finishing allowance",
                1,
                finishing_cost,
                ["Applied as a percentage uplift for epoxy/powder finish at concept stage."],
            )
        )

    subtotal_before_contingency = round(sum(item["extended_cost_gbp"] for item in line_items), 2)
    contingency_cost = round(subtotal_before_contingency * (rates.contingency_pct / 100.0), 2)
    if contingency_cost:
        line_items.append(
            _simple_line_item(
                "contingency",
                "Concept contingency",
                1,
                contingency_cost,
                ["Applied to cover unknowns due to non-design-originated source data."],
            )
        )

    grand_total = round(sum(item["extended_cost_gbp"] for item in line_items), 2)
    margin_options = [
        {"name": "low", "markup_pct": 10, "sell_price_gbp": round(grand_total * 1.10, 2)},
        {"name": "standard", "markup_pct": 20, "sell_price_gbp": round(grand_total * 1.20, 2)},
        {"name": "premium", "markup_pct": 35, "sell_price_gbp": round(grand_total * 1.35, 2)},
    ]

    return {
        "pricing_model": "concept_budgetary_v1",
        "line_items": line_items,
        "totals": {
            "grand_total_gbp": grand_total,
            "margin_options": margin_options,
        },
        "assumptions": [
            "Concept-stage pricing only; no manufacturing drawing pack available.",
            "Bought-in items and accessories are budget allowances until supplier prices are matched.",
            "Frame and mesh costs are inferred from envelope size and stated features.",
        ],
        "confidence": {
            "overall_pricing_confidence": 0.42,
            "pricing_transparency": "medium",
        },
    }
