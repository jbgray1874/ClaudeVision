import csv
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
    material = _first(part.get("materials", []))
    thickness = _safe_float(_first(part.get("thicknesses_mm", [])))
    dims = infer_primary_dimensions(part)
    blank_length, blank_width = estimate_blank_size(dims)

    if not material or thickness is None or blank_length is None or blank_width is None:
        return {
            "material": material,
            "thickness_mm": thickness,
            "blank_length_mm": blank_length,
            "blank_width_mm": blank_width,
            "blank_area_m2": None,
            "material_mass_kg": None,
            "material_cost_gbp": None,
            "stock_estimate": select_sheet_size(material, blank_length, blank_width),
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
        "material_mass_kg": round(mass_kg, 3) if mass_kg is not None else None,
        "material_cost_gbp": round(material_cost, 2) if material_cost is not None else None,
        "stock_estimate": select_sheet_size(material, blank_length, blank_width),
    }


def estimate_process_times(part: Dict[str, Any]) -> Dict[str, Any]:
    geom = part.get("geometry_rollup", {})
    ops = part.get("textual_operations", [])

    cut_length_mm = geom.get("estimated_cut_length_mm", 0.0) or 0.0
    pierces = geom.get("estimated_pierce_count", 0) or 0
    holes = max(geom.get("estimated_hole_count", 0) or 0, len(part.get("hole_sizes_mm", [])))
    bends = max(
        geom.get("estimated_bend_line_count", 0) or 0,
        len(part.get("angles_deg", [])),
        len(part.get("fold_values_mm", [])),
    )
    bend_length_mm = sum([_safe_float(value) or 0.0 for value in part.get("fold_values_mm", [])])

    times_min: Dict[str, float] = {}

    if "laser_cutting" in ops:
        rule = LABOUR_RULES["laser_cutting"]
        minutes = rule["setup_min"] + ((pierces * rule["pierce_sec_each"]) + (cut_length_mm * rule["cut_sec_per_mm"])) / 60.0
        times_min["laser_cutting"] = round(minutes, 2)

    if "hole_machining" in ops:
        rule = LABOUR_RULES["hole_machining"]
        minutes = rule["setup_min"] + (holes * rule["sec_per_hole"]) / 60.0
        times_min["hole_machining"] = round(minutes, 2)

    if "folding" in ops:
        rule = LABOUR_RULES["folding"]
        minutes = rule["setup_min"] + (bends * rule["sec_per_bend"] + bend_length_mm * rule["sec_per_mm_bend_length"]) / 60.0
        times_min["folding"] = round(minutes, 2)

    if "powder_coating" in ops:
        times_min["powder_coating"] = round(LABOUR_RULES["powder_coating"]["min_per_part"], 2)

    if "handling" in ops:
        times_min["handling"] = round(LABOUR_RULES["handling"]["min_per_part"], 2)

    return {
        "cut_length_mm": round(cut_length_mm, 2),
        "pierce_count": pierces,
        "hole_count": holes,
        "bend_count": bends,
        "bend_length_mm": round(bend_length_mm, 2),
        "times_min": times_min,
        "total_time_min": round(sum(times_min.values()), 2),
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
    process = estimate_process_times(part)
    labour = estimate_labour_costs(process)
    unit_total = round(
        (material.get("material_cost_gbp") or 0.0) + (labour.get("total_labour_cost_gbp") or 0.0),
        2,
    )

    return {
        "part_number": part.get("part_number"),
        "description": part.get("description"),
        "quantity": quantity,
        "material_estimate": material,
        "process_estimate": process,
        "labour_estimate": labour,
        "unit_total_cost_gbp": unit_total,
        "extended_total_cost_gbp": round(unit_total * quantity, 2),
        "notes": [
            "Geometry-derived timings are heuristic until calibrated against known jobs.",
            "Primary dimensions are inferred from extracted values; verify against the drawing before quoting.",
        ],
    }


def estimate_document(parts: List[Dict[str, Any]]) -> Dict[str, Any]:
    part_estimates = [estimate_part(part) for part in parts]
    return {
        "part_estimates": part_estimates,
        "document_total_estimated_cost_gbp": round(sum(item["extended_total_cost_gbp"] for item in part_estimates), 2),
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
                "operations": _join(part.get("textual_operations", [])),
                "process_notes": _join(part.get("process_notes", [])),
                "estimated_cut_length_mm": process_estimate.get("cut_length_mm"),
                "estimated_hole_count": process_estimate.get("hole_count"),
                "estimated_slot_like_features": part.get("geometry_rollup", {}).get("estimated_slot_like_features"),
                "estimated_bend_line_count": process_estimate.get("bend_count"),
                "blank_length_mm": material_estimate.get("blank_length_mm"),
                "blank_width_mm": material_estimate.get("blank_width_mm"),
                "material_cost_gbp": material_estimate.get("material_cost_gbp"),
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
