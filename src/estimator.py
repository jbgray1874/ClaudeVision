import csv
from datetime import date
from math import floor
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from config import (
    CSV_HEADERS,
    HOURLY_RATES_GBP,
    LABOUR_RULES,
    MATERIAL_DENSITY_KG_PER_M3,
    MATERIAL_PRICE_GBP_PER_KG,
    NESTING_RULES,
    STANDARD_SHEET_SIZES_MM,
)


def _first(values: List[Any]) -> Any:
    return values[0] if values else None


def _join(values: List[Any]) -> str:
    return "; ".join(str(value) for value in values if value not in (None, ""))


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


def infer_primary_dimensions(part: Dict[str, Any]) -> Dict[str, Optional[float]]:
    normalized_geometry = part.get("normalized_geometry", {})
    flat_box = normalized_geometry.get("bounding_box_flat_mm", {}) if isinstance(normalized_geometry, dict) else {}
    flat_length = _safe_float(flat_box.get("length"))
    flat_width = _safe_float(flat_box.get("width"))
    if flat_length is not None and flat_width is not None:
        return {
            "overall_length_mm": flat_length,
            "overall_width_mm": flat_width,
            "all_dimensions_mm": sorted([flat_length, flat_width], reverse=True),
        }

    dims = sorted(
        [_safe_float(value) for value in part.get("all_dimensions_mm", []) if _safe_float(value) is not None],
        reverse=True,
    )
    overall_length = part.get("overall_length_mm") or (dims[0] if len(dims) > 0 else None)
    overall_width = part.get("overall_width_mm") or (dims[1] if len(dims) > 1 else None)
    return {
        "overall_length_mm": overall_length,
        "overall_width_mm": overall_width,
        "all_dimensions_mm": dims,
    }


def estimate_blank_size(dimensions: Dict[str, Optional[float]]) -> Tuple[Optional[float], Optional[float]]:
    length = dimensions.get("overall_length_mm")
    width = dimensions.get("overall_width_mm")
    if length is None or width is None:
        return None, None

    blank_length = length + (2 * NESTING_RULES["edge_margin_mm"])
    blank_width = width + (2 * NESTING_RULES["edge_margin_mm"])
    return round(blank_length, 2), round(blank_width, 2)


def select_sheet_size(material: Optional[str], blank_length: Optional[float], blank_width: Optional[float]) -> Dict[str, Any]:
    if blank_length is None or blank_width is None:
        return {"candidate_sheet_size_mm": None, "parts_per_sheet": None, "utilisation_pct": None}

    sizes = STANDARD_SHEET_SIZES_MM.get(material or "", STANDARD_SHEET_SIZES_MM["DEFAULT"])
    spacing = NESTING_RULES["part_spacing_mm"]
    edge_margin = NESTING_RULES["edge_margin_mm"]

    best = None
    for sheet_length, sheet_width in sizes:
        for part_length, part_width in [(blank_length, blank_width), (blank_width, blank_length)]:
            pitch_x = part_length + spacing
            pitch_y = part_width + spacing
            nx = floor((sheet_length - edge_margin) / pitch_x) if pitch_x > 0 else 0
            ny = floor((sheet_width - edge_margin) / pitch_y) if pitch_y > 0 else 0
            qty = max(0, nx) * max(0, ny)
            if qty <= 0:
                continue
            part_area = blank_length * blank_width
            sheet_area = sheet_length * sheet_width
            utilisation = (qty * part_area / sheet_area) * 100.0
            candidate = {
                "candidate_sheet_size_mm": [sheet_length, sheet_width],
                "parts_per_sheet": qty,
                "utilisation_pct": round(utilisation, 2),
            }
            if best is None or candidate["parts_per_sheet"] > best["parts_per_sheet"]:
                best = candidate

    return best or {"candidate_sheet_size_mm": None, "parts_per_sheet": None, "utilisation_pct": None}


def estimate_material(part: Dict[str, Any]) -> Dict[str, Any]:
    material = part.get("normalized_material") or _first(part.get("materials", []))
    thickness = _safe_float(part.get("normalized_thickness_mm") or _first(part.get("thicknesses_mm", [])))
    quantity = _safe_int(part.get("quantity")) or 1
    dims = infer_primary_dimensions(part)
    blank_length, blank_width = estimate_blank_size(dims)

    if not material or thickness is None or blank_length is None or blank_width is None:
        return {
            "material": material,
            "thickness_mm": thickness,
            "blank_length_mm": blank_length,
            "blank_width_mm": blank_width,
            "blank_area_m2": None,
            "unit_material_mass_kg": None,
            "unit_material_cost_gbp": None,
            "extended_material_cost_gbp": None,
            "stock_estimate": select_sheet_size(material, blank_length, blank_width),
            "price_source": {
                "supplier_source": "config_default_material_rates",
                "price_date": None,
                "source_type": "config",
                "unit": "GBP_per_kg",
                "currency": "GBP",
            },
        }

    area_m2 = (blank_length * blank_width) / 1_000_000.0
    thickness_m = thickness / 1000.0
    density = MATERIAL_DENSITY_KG_PER_M3.get(material)
    price_per_kg = MATERIAL_PRICE_GBP_PER_KG.get(material)
    if density is None or price_per_kg is None:
        mass_kg = None
        material_cost = None
    else:
        mass_kg = area_m2 * thickness_m * density
        material_cost = mass_kg * price_per_kg * (1 + NESTING_RULES["waste_factor_pct"] / 100.0)

    return {
        "material": material,
        "thickness_mm": thickness,
        "blank_length_mm": blank_length,
        "blank_width_mm": blank_width,
        "blank_area_m2": round(area_m2, 4),
        "unit_material_mass_kg": round(mass_kg, 3) if mass_kg is not None else None,
        "unit_material_cost_gbp": round(material_cost, 2) if material_cost is not None else None,
        "extended_material_cost_gbp": round((material_cost or 0.0) * quantity, 2) if material_cost is not None else None,
        "stock_estimate": select_sheet_size(material, blank_length, blank_width),
        "stock_form": part.get("manufacturing_interpretation", {}).get("stock_form"),
        "requires_flat_blank": part.get("manufacturing_interpretation", {}).get("requires_flat_blank"),
        "price_source": {
            "supplier_source": "config_default_material_rates",
            "price_date": str(date.today()),
            "source_type": "config",
            "unit": "GBP_per_kg",
            "currency": "GBP",
        },
    }


def estimate_process_times(part: Dict[str, Any], quantity: int = 1) -> Dict[str, Any]:
    geom = part.get("geometry_rollup", {})
    ops = part.get("textual_operations", [])
    manufacturing_features = part.get("manufacturing_features", {})
    geometry_confidence = 0.0
    if isinstance(geom.get("confidence"), dict):
        geometry_confidence = geom["confidence"].get("geometry_reliability", 0.0) or 0.0

    raw_cut_length_mm = manufacturing_features.get("raw_cut_length_mm", geom.get("estimated_cut_length_mm", 0.0) or 0.0)
    cut_length_mm = manufacturing_features.get("cut_length_mm", raw_cut_length_mm * max(0.25, geometry_confidence) if raw_cut_length_mm else 0.0)
    pierces = geom.get("estimated_pierce_count", 0) or 0
    holes = manufacturing_features.get("hole_count", max(geom.get("estimated_hole_count", 0) or 0, len(part.get("hole_sizes_mm", []))))
    bends = manufacturing_features.get("bend_count", max(len(part.get("angles_deg", [])), len(part.get("fold_values_mm", [])), part.get("fold_count_textual", 0) or 0))
    bend_length_mm = sum([_safe_float(value) or 0.0 for value in part.get("fold_values_mm", [])])

    setup_times_min: Dict[str, float] = {}
    run_times_min: Dict[str, float] = {}

    if "laser_cutting" in ops:
        rule = LABOUR_RULES["laser_cutting"]
        setup_times_min["laser_cutting"] = round(rule["setup_min"], 2)
        run_times_min["laser_cutting"] = round(((pierces * rule["pierce_sec_each"]) + (cut_length_mm * rule["cut_sec_per_mm"])) / 60.0, 2)

    if "hole_machining" in ops:
        rule = LABOUR_RULES["hole_machining"]
        setup_times_min["hole_machining"] = round(rule["setup_min"], 2)
        run_times_min["hole_machining"] = round((holes * rule["sec_per_hole"]) / 60.0, 2)

    if "folding" in ops:
        rule = LABOUR_RULES["folding"]
        setup_times_min["folding"] = round(rule["setup_min"], 2)
        run_times_min["folding"] = round((bends * rule["sec_per_bend"] + bend_length_mm * rule["sec_per_mm_bend_length"]) / 60.0, 2)

    if "powder_coating" in ops:
        run_times_min["powder_coating"] = round(LABOUR_RULES["powder_coating"]["min_per_part"], 2)

    if "handling" in ops:
        run_times_min["handling"] = round(LABOUR_RULES["handling"]["min_per_part"], 2)

    unit_times_min: Dict[str, float] = {}
    total_times_min: Dict[str, float] = {}
    for op in set(setup_times_min) | set(run_times_min):
        unit_times_min[op] = round(setup_times_min.get(op, 0.0) + run_times_min.get(op, 0.0), 2)
        total_times_min[op] = round(setup_times_min.get(op, 0.0) + (run_times_min.get(op, 0.0) * quantity), 2)

    return {
        "cut_length_mm": round(cut_length_mm, 2),
        "raw_cut_length_mm": round(raw_cut_length_mm, 2),
        "pierce_count": pierces,
        "hole_count": holes,
        "bend_count": bends,
        "bend_length_mm": round(bend_length_mm, 2),
        "setup_times_min": setup_times_min,
        "run_times_min_per_unit": run_times_min,
        "unit_times_min": unit_times_min,
        "times_min": total_times_min,
        "unit_time_min": round(sum(unit_times_min.values()), 2),
        "total_time_min": round(sum(total_times_min.values()), 2),
        "feature_rollup": part.get("feature_rollup", {}),
        "manufacturing_features": manufacturing_features,
        "routing": part.get("manufacturing_interpretation", {}).get("routing", []),
        "geometry_reliability": geometry_confidence,
    }


def estimate_labour_costs(process: Dict[str, Any]) -> Dict[str, Any]:
    breakdown: Dict[str, float] = {}
    for op, minutes in process.get("times_min", {}).items():
        rate = HOURLY_RATES_GBP.get(op)
        if rate is None:
            continue
        breakdown[op] = round((minutes / 60.0) * rate, 2)

    return {
        "costs_gbp": breakdown,
        "total_labour_cost_gbp": round(sum(breakdown.values()), 2),
    }


def estimate_part(part: Dict[str, Any]) -> Dict[str, Any]:
    quantity = _safe_int(part.get("quantity")) or 1
    material = estimate_material(part)
    process = estimate_process_times(part, quantity=quantity)
    labour = estimate_labour_costs(process)
    extended_material_cost = material.get("extended_material_cost_gbp") or 0.0
    total_labour_cost = labour.get("total_labour_cost_gbp") or 0.0
    extended_total = round(extended_material_cost + total_labour_cost, 2)
    unit_total = round(extended_total / quantity, 2) if quantity else extended_total
    margin_options = [
        {"name": "low", "markup_pct": 10, "unit_sell_price_gbp": round(unit_total * 1.10, 2), "extended_sell_price_gbp": round(extended_total * 1.10, 2)},
        {"name": "standard", "markup_pct": 20, "unit_sell_price_gbp": round(unit_total * 1.20, 2), "extended_sell_price_gbp": round(extended_total * 1.20, 2)},
        {"name": "premium", "markup_pct": 35, "unit_sell_price_gbp": round(unit_total * 1.35, 2), "extended_sell_price_gbp": round(extended_total * 1.35, 2)},
    ]

    return {
        "part_number": part.get("part_number"),
        "description": part.get("description"),
        "quantity": quantity,
        "material_estimate": material,
        "process_estimate": process,
        "labour_estimate": labour,
        "normalized_geometry": part.get("normalized_geometry", {}),
        "cost_breakdown": {
            "material": {
                "unit_material_mass_kg": material.get("unit_material_mass_kg"),
                "unit_material_cost_gbp": material.get("unit_material_cost_gbp"),
                "extended_material_cost_gbp": material.get("extended_material_cost_gbp"),
                "supplier_source": material.get("price_source", {}).get("supplier_source"),
                "price_date": material.get("price_source", {}).get("price_date"),
            },
            "labour": {
                "unit_time_min": process.get("unit_time_min"),
                "total_time_min": process.get("total_time_min"),
                "costs_gbp": labour.get("costs_gbp", {}),
                "total_labour_cost_gbp": labour.get("total_labour_cost_gbp"),
            },
            "overhead": {
                "unit_overhead_cost_gbp": None,
                "extended_overhead_cost_gbp": None,
            },
            "unit_total_cost_gbp": unit_total,
            "extended_total_cost_gbp": extended_total,
            "margin_options": margin_options,
            "assumptions": {
                "material_price_source": material.get("price_source", {}),
                "labour_model": "config_default_labour_rules",
                "geometry_basis": "normalized_geometry",
            },
        },
        "risk_flags": part.get("risk_flags", []),
        "alternative_processes": [],
        "unit_total_cost_gbp": unit_total,
        "extended_total_cost_gbp": extended_total,
        "notes": [
            "Geometry-derived timings are heuristic until calibrated against known jobs.",
            "Primary dimensions are inferred from extracted values; verify against the drawing before quoting.",
        ],
    }


def estimate_document(parts: List[Dict[str, Any]]) -> Dict[str, Any]:
    part_estimates = [estimate_part(part) for part in parts]
    material_total = round(sum((item.get("material_estimate", {}).get("extended_material_cost_gbp") or 0.0) for item in part_estimates), 2)
    labour_total = round(sum((item.get("labour_estimate", {}).get("total_labour_cost_gbp") or 0.0) for item in part_estimates), 2)
    operation_totals: Dict[str, float] = {}
    for item in part_estimates:
        for op, cost in item.get("labour_estimate", {}).get("costs_gbp", {}).items():
            operation_totals[op] = round(operation_totals.get(op, 0.0) + (cost or 0.0), 2)
    document_total = round(sum(item["extended_total_cost_gbp"] for item in part_estimates), 2)
    return {
        "part_estimates": part_estimates,
        "document_total_estimated_cost_gbp": document_total,
        "cost_breakdown": {
            "material": {
                "total": material_total,
                "per_part": [
                    {
                        "part_number": item.get("part_number"),
                        "extended_material_cost_gbp": item.get("material_estimate", {}).get("extended_material_cost_gbp"),
                        "supplier_source": item.get("material_estimate", {}).get("price_source", {}).get("supplier_source"),
                        "price_date": item.get("material_estimate", {}).get("price_source", {}).get("price_date"),
                    }
                    for item in part_estimates
                ],
            },
            "labour": {
                "total": labour_total,
                "by_operation": operation_totals,
            },
            "overhead": {},
            "margin_options": ["low", "standard", "premium"],
            "pricing_metadata": {
                "latest_price_date": max(
                    [item.get("material_estimate", {}).get("price_source", {}).get("price_date") for item in part_estimates if item.get("material_estimate", {}).get("price_source", {}).get("price_date")],
                    default=None,
                ),
                "supplier_sources": sorted(
                    {
                        item.get("material_estimate", {}).get("price_source", {}).get("supplier_source")
                        for item in part_estimates
                        if item.get("material_estimate", {}).get("price_source", {}).get("supplier_source")
                    }
                ),
                "pricing_basis": "config_default",
            },
        },
    }


def build_estimate_input_rows(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    estimate_lookup = {item["part_number"]: item for item in summary.get("estimate_summary", {}).get("part_estimates", [])}

    for part in summary.get("manufacturing_writeup", {}).get("parts", []):
        estimate = estimate_lookup.get(part.get("part_number"), {})
        material_estimate = estimate.get("material_estimate", {})
        process_estimate = estimate.get("process_estimate", {})
        labour_estimate = estimate.get("labour_estimate", {})
        rows.append(
            {
                "source_file": summary["source_file"],
                "part_number": part.get("part_number"),
                "description": part.get("description"),
                "quantity": part.get("quantity"),
                "page_roles": _join(part.get("page_roles", [])),
                "material": _join(part.get("materials", [])),
                "thickness_mm": _join(part.get("thicknesses_mm", [])),
                "finish": _join(part.get("surface_finishes", [])),
                "colour": _join(part.get("colours", [])),
                "revision": _join(part.get("revisions", [])),
                "dates": _join(part.get("dates", [])),
                "overall_length_mm": part.get("overall_length_mm"),
                "overall_width_mm": part.get("overall_width_mm"),
                "overall_sizes_mm": _join(part.get("overall_sizes_mm", [])),
                "dimensions_mm": _join(part.get("all_dimensions_mm", [])),
                "angles_deg": _join(part.get("angles_deg", [])),
                "hole_sizes_mm": _join(part.get("hole_sizes_mm", [])),
                "slot_sizes_mm": _join(part.get("slot_sizes_mm", [])),
                "manufacturing_features": _join(
                    [
                        f"laser={part.get('manufacturing_features', {}).get('laser_required')}",
                        f"fold={part.get('manufacturing_features', {}).get('fold_required')}",
                        f"holes={part.get('manufacturing_features', {}).get('hole_count')}",
                        f"slots={part.get('manufacturing_features', {}).get('slot_count')}",
                        f"bends={part.get('manufacturing_features', {}).get('bend_count')}",
                        f"finish={part.get('manufacturing_features', {}).get('finish_required')}",
                    ]
                ),
                "operations": _join(part.get("textual_operations", [])),
                "process_notes": _join(part.get("process_notes", [])),
                "estimated_cut_length_mm": process_estimate.get("cut_length_mm"),
                "estimated_hole_count": process_estimate.get("hole_count"),
                "estimated_slot_like_features": part.get("geometry_rollup", {}).get("estimated_slot_like_features"),
                "estimated_bend_line_count": process_estimate.get("bend_count"),
                "blank_length_mm": material_estimate.get("blank_length_mm"),
                "blank_width_mm": material_estimate.get("blank_width_mm"),
                "material_cost_gbp": material_estimate.get("extended_material_cost_gbp"),
                "total_time_min": process_estimate.get("total_time_min"),
                "unit_labour_cost_gbp": labour_estimate.get("total_labour_cost_gbp"),
                "unit_total_cost_gbp": estimate.get("unit_total_cost_gbp"),
                "extended_total_cost_gbp": estimate.get("extended_total_cost_gbp"),
            }
        )
    return rows


def append_rows_to_csv(csv_path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    row_list = list(rows)
    if not row_list:
        return
    write_header = not csv_path.exists()
    with csv_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_HEADERS)
        if write_header:
            writer.writeheader()
        writer.writerows(row_list)
