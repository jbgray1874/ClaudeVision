import re
from typing import Any, Dict, List

from feature_synthesis import infer_bend_count as _infer_bend_count_impl
from feature_synthesis import infer_hole_count as _infer_hole_count_impl
from feature_synthesis import synthesize_manufacturing_features as _synthesize_manufacturing_features_impl
from process_router import build_process_routing as _build_process_routing_impl
from part_index import PartIndexDeps, build_part_index as _build_part_index_impl
from document_validation import build_document_validation as _build_document_validation_impl

def _dedupe(values: List[Any]) -> List[Any]:
    seen: List[Any] = []
    for value in values:
        if value not in seen and value not in (None, "", []):
            seen.append(value)
    return seen


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_assembly_identifier(part_number: Any) -> bool:
    if not part_number:
        return False
    normalized = str(part_number).strip().upper().replace(" ", "")
    return normalized.endswith("-GA")


def _is_good_description(value: Any) -> bool:
    if not value:
        return False
    normalized = str(value).strip()
    if len(normalized) < 3:
        return False
    upper = normalized.upper()
    bad_tokens = [
        "CLIENT:",
        "PROJECT TITLE:",
        "DWG NO.",
        "DRAWING NO",
        "MODIFIED BY:",
        "DRAWN BY:",
        "SURFACE FINISH:",
        "COLOUR:",
        "MATERIAL:",
        "SHEET SIZE:",
        "SCALE:",
    ]
    return not any(token in upper for token in bad_tokens)


def _is_reference_like_part(part_number: Any) -> bool:
    if not part_number:
        return False
    upper = str(part_number).strip().upper()
    return upper.startswith(("FIXING", "REF", "PA -", "PA-")) or "-REF" in upper or "_REF" in upper


def _is_valid_part_identifier(part_number: Any) -> bool:
    if not part_number:
        return False
    upper = str(part_number).strip().upper()
    if _is_assembly_identifier(upper) or _is_reference_like_part(upper):
        return False
    if upper in {
        "ALUMINIUM",
        "ALUMINUM",
        "MILD STEEL",
        "STAINLESS STEEL",
        "TIMBER",
        "TIMBER-BASED",
        "PLYWOOD",
        "PVC",
    }:
        return False
    if upper.endswith((" - ALUMINIUM", " - ALUMINUM", " - STEEL", " - TIMBER", " - PLYWOOD")):
        return False
    if upper in {"A-A", "B-B", "C-C", "D-D", "E-E", "F-F"}:
        return False
    if upper.startswith(("SCALE ", "DRAWING ", "REV ", "DESCRIPTION ")):
        return False
    if re.search(r"\s-\s[A-Z]{3,}$", upper):
        return False
    if len(upper) > 40:
        return False
    return True


def _is_component_sheet(
    page_role: Any,
    title_block: Dict[str, Any],
    page_target_part_numbers: List[str],
    cues: Dict[str, Any],
    ops: List[str],
) -> bool:
    if page_role == "detail":
        return True
    if len(page_target_part_numbers) != 1:
        return False
    if title_block.get("materials") or title_block.get("surface_finishes") or title_block.get("thicknesses_mm"):
        return True
    if cues.get("flat_pattern_detected") or cues.get("angles_deg") or cues.get("hole_sizes_mm"):
        return True
    meaningful_ops = [operation for operation in ops if operation != "handling"]
    return bool(meaningful_ops)


def _prefer_local_title_block_values(page_role: Any, values: List[Any], allow_on_assembly: bool = False) -> List[Any]:
    if not values:
        return []
    if page_role == "detail":
        return values
    if allow_on_assembly:
        return values
    return []


def _prefer_local_scalar(page_role: Any, value: Any, allow_on_assembly: bool = False) -> Any:
    if value in (None, "", []):
        return None
    if page_role == "detail":
        return value
    if allow_on_assembly:
        return value
    return None


def _effective_part_page_role(page_role: Any, title_block_drawing_numbers: List[str], component_sheet: bool) -> Any:
    valid_component_numbers = [
        value for value in title_block_drawing_numbers
        if _is_valid_part_identifier(value)
    ]
    if component_sheet and len(valid_component_numbers) == 1 and not _is_assembly_identifier(valid_component_numbers[0]):
        return "detail"
    return page_role


def _first_numeric_thickness(values: List[Any]) -> Any:
    for value in values:
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _should_assign_dimensions(page_role: Any, component_sheet: bool) -> bool:
    return page_role == "detail" or component_sheet


def _pick_part_dimensions(part: Dict[str, Any], dimensions: Dict[str, Any]) -> Dict[str, Any]:
    flat_pattern_dims = dimensions.get("flat_pattern_dimensions_mm", []) or []
    if len(flat_pattern_dims) >= 2:
        numbers = sorted(
            [
                _safe_float(value)
                for value in flat_pattern_dims[:2]
                if _safe_float(value) is not None
            ],
            reverse=True,
        )
        if len(numbers) == 2:
            return {
                "overall_length_mm": numbers[0],
                "overall_width_mm": numbers[1],
            }

    overall_sizes = dimensions.get("overall_sizes_mm", []) or []
    if overall_sizes:
        first_size = overall_sizes[0]
        match = re.search(r"(\d+(?:\.\d+)?)\s*[xX]\s*(\d+(?:\.\d+)?)", str(first_size))
        if match:
            left = _safe_float(match.group(1))
            right = _safe_float(match.group(2))
            if left is not None and right is not None:
                ordered = sorted([left, right], reverse=True)
                return {
                    "overall_length_mm": ordered[0],
                    "overall_width_mm": ordered[1],
                }

    length = _safe_float(dimensions.get("overall_length_mm"))
    width = _safe_float(dimensions.get("overall_width_mm"))
    if length is not None and width is not None:
        ordered = sorted([length, width], reverse=True)
        return {
            "overall_length_mm": ordered[0],
            "overall_width_mm": ordered[1],
        }

    values = sorted(
        [
            _safe_float(value) for value in part.get("all_dimensions_mm", [])
            if _safe_float(value) is not None and _safe_float(value) >= 10.0
        ],
        reverse=True,
    )
    return {
        "overall_length_mm": values[0] if len(values) > 0 else None,
        "overall_width_mm": values[1] if len(values) > 1 else None,
    }


def _build_normalized_geometry(part: Dict[str, Any]) -> Dict[str, Any]:
    features = part.get("manufacturing_features", {})
    geometry_confidence = features.get("geometry_reliability", 0.0) or 0.0
    length = _safe_float(part.get("overall_length_mm"))
    width = _safe_float(part.get("overall_width_mm"))
    thickness = _safe_float(part.get("normalized_thickness_mm"))

    bend_angles = [value for value in part.get("angles_deg", []) if value not in (None, "")]
    bend_count = features.get("bend_count", 0) or 0
    flat_length = length
    flat_width = width
    if length is not None and width is not None:
        # Scale bend/blank allowance with bend count and thickness rather than fixed +20mm.
        thickness_for_allowance = thickness if thickness is not None else 1.5
        bend_radius = max(1.0, thickness_for_allowance)
        allowance = max(6.0, min(40.0, 2.0 * bend_radius * max(1, bend_count)))
        flat_length = round(length + allowance, 2)
        flat_width = round(width + allowance, 2)

    formed_height = None
    if bend_angles:
        angle_numbers = [_safe_float(value) for value in bend_angles if _safe_float(value) is not None]
        if angle_numbers:
            formed_height = round(max(angle_numbers), 2)
    if formed_height is None and bend_count > 0 and thickness is not None:
        formed_height = round(max(5.0, bend_count * thickness * 10.0), 2)

    blank_area_m2 = None
    if flat_length is not None and flat_width is not None:
        blank_area_m2 = round((flat_length * flat_width) / 1_000_000.0, 4)

    nesting_class = "unknown"
    if flat_length is not None and flat_width is not None:
        if flat_length >= 2000 or flat_width >= 1000:
            nesting_class = "large_format"
        elif flat_length >= flat_width * 5:
            nesting_class = "linear"
        elif bend_count > 0 or part.get("slot_detected"):
            nesting_class = "awkward"
        else:
            nesting_class = "compact"

    stock_form = part.get("manufacturing_interpretation", {}).get("stock_form") or ("sheet" if part.get("flat_pattern_detected") or flat_length or flat_width else "unknown")
    profile_type = "flat"
    if bend_count > 0:
        profile_type = "folded"
    elif part.get("hanging_hole_detected"):
        profile_type = "hook"

    return {
        "stock_form": stock_form,
        "profile_type": profile_type,
        "bounding_box_flat_mm": {
            "length": flat_length,
            "width": flat_width,
            "height": thickness,
        },
        "bounding_box_formed_mm": {
            "length": length,
            "width": width,
            "height": formed_height,
        },
        "developed_length_mm": flat_length,
        "developed_width_mm": flat_width,
        "projected_area_m2": round((length * width) / 1_000_000.0, 4) if length is not None and width is not None else None,
        "blank_area_m2": blank_area_m2,
        "smallest_enclosing_rectangle_mm": {
            "length": flat_length,
            "width": flat_width,
        },
        "longest_edge_mm": length,
        "cut_length_mm": features.get("cut_length_mm"),
        "raw_cut_length_mm": features.get("raw_cut_length_mm"),
        "pierce_count": part.get("geometry_rollup", {}).get("estimated_pierce_count", 0),
        "hole_count": features.get("hole_count", 0),
        "slot_count": features.get("slot_count", 0),
        "bend_count": bend_count,
        "bend_angles_deg": bend_angles,
        "major_radii_mm": part.get("radii_mm", []),
        "nesting_class": nesting_class,
        "geometry_confidence": round(max(geometry_confidence, part.get("confidence", {}).get("dimensions", 0.0) or 0.0), 2),
    }


def _build_part_risk_flags(part: Dict[str, Any]) -> List[str]:
    flags: List[str] = []
    geometry = part.get("normalized_geometry", {})
    flat = geometry.get("bounding_box_flat_mm", {})
    length = _safe_float(flat.get("length"))
    width = _safe_float(flat.get("width"))
    if length is not None and width is not None and (length >= 2000 or width >= 1000):
        flags.append("large_flat")
    if (part.get("manufacturing_features", {}).get("bend_count", 0) or 0) >= 3:
        flags.append("many_bends")
    if part.get("hanging_hole_detected"):
        flags.append("hanging_holes")
    if part.get("manufacturing_features", {}).get("welding_required"):
        flags.append("weld_required")
    return flags


def _clean_finish_values(values: List[Any]) -> List[Any]:
    cleaned: List[Any] = []
    for value in values:
        if value in (None, "", []):
            continue
        upper = str(value).strip().upper()
        if upper in {"SEE ASSEMBLY DRAWING", "SEE INDIVIDUAL DRAWINGS", "N/A"}:
            continue
        cleaned.append(value)
    return _dedupe(cleaned)


def merge_page_analysis(summary: Dict[str, Any], geometry_pages: List[Dict[str, Any]]) -> Dict[str, Any]:
    geo_lookup = {item["page_number"]: item for item in geometry_pages}
    for page in summary["pages"]:
        page["geometry_summary"] = geo_lookup.get(page["page_number"], {})
    return summary


def _empty_geometry_rollup() -> Dict[str, Any]:
    return {
        "vector_path_count": 0,
        "line_segments": 0,
        "rectangles": 0,
        "curves": 0,
        "filled_paths": 0,
        "approx_total_line_length_points": 0.0,
        "approx_total_curve_length_points": 0.0,
        "estimated_cut_length_mm": 0.0,
        "estimated_hole_count": 0,
        "estimated_circle_like_features": 0,
        "estimated_slot_like_features": 0,
        "estimated_bend_line_count": 0,
        "estimated_pierce_count": 0,
        "contour_complexity": 0,
        "closed_path_count": 0,
        "long_axis_aligned_lines": 0,
        "dashed_long_axis_lines": 0,
        "confidence": {
            "geometry_reliability": 0.0,
            "estimated_cut_length_mm": 0.0,
            "estimated_hole_count": 0.0,
            "estimated_slot_like_features": 0.0,
            "estimated_bend_line_count": 0.0,
        },
    }


def _empty_part_record(part_number: str, item_number: Any = None, description: Any = None, quantity: Any = 1) -> Dict[str, Any]:
    return {
        "part_number": part_number,
        "item_number": item_number,
        "description": description,
        "quantity": quantity,
        "pages": [],
        "page_roles": [],
        "materials": [],
        "surface_finishes": [],
        "colours": [],
        "revisions": [],
        "drawing_numbers": [],
        "thicknesses_mm": [],
        "dates": [],
        "sheet_refs": [],
        "scales": [],
        "clients": [],
        "project_titles": [],
        "all_dimensions_mm": [],
        "overall_sizes_mm": [],
        "overall_length_mm": None,
        "overall_width_mm": None,
        "angles_deg": [],
        "hole_sizes_mm": [],
        "radii_mm": [],
        "pitch_values_mm": [],
        "fold_values_mm": [],
        "slot_sizes_mm": [],
        "edge_distances_mm": [],
        "fold_count_textual": 0,
        "process_notes": [],
        "process_note_types": [],
        "review_flags": [],
        "confidence": {},
        "normalized_material": None,
        "normalized_finish": None,
        "normalized_thickness_mm": None,
        "flat_pattern_detected": False,
        "mirrored_detected": False,
        "hanging_hole_detected": False,
        "slot_detected": False,
        "assembly_candidate": False,
        "textual_operations": [],
        "feature_rollup": {
            "hole_feature_count": 0,
            "slot_feature_count": 0,
            "bend_feature_count": 0,
            "radius_feature_count": 0,
            "tap_feature_count": 0,
            "weld_feature_count": 0,
        },
        "manufacturing_interpretation": {},
        "geometry_rollup": _empty_geometry_rollup(),
        "normalized_geometry": {},
        "risk_flags": [],
    }


def _rollup_geometry(target: Dict[str, Any], geometry: Dict[str, Any]) -> None:
    for key in target:
        if isinstance(target[key], dict):
            source = geometry.get(key, {})
            if isinstance(source, dict):
                for subkey, value in source.items():
                    if isinstance(target[key].get(subkey, 0.0), (int, float)) and isinstance(value, (int, float)):
                        target[key][subkey] = max(target[key].get(subkey, 0.0), value)
            continue
        incoming = geometry.get(key, 0)
        if isinstance(target[key], (int, float)) and isinstance(incoming, (int, float)):
            target[key] += incoming


def _build_process_routing(part: Dict[str, Any]) -> List[Dict[str, Any]]:
    return _build_process_routing_impl(part)


def _infer_hole_count(part: Dict[str, Any], geometry_confidence: float) -> int:
    return _infer_hole_count_impl(part, geometry_confidence)


def _infer_bend_count(part: Dict[str, Any], geometry_confidence: float) -> int:
    return _infer_bend_count_impl(part, geometry_confidence)


def _synthesize_manufacturing_features(part: Dict[str, Any]) -> Dict[str, Any]:
    return _synthesize_manufacturing_features_impl(part)


def _interpret_part(part: Dict[str, Any]) -> Dict[str, Any]:
    operations = part.get("textual_operations", [])
    geometry_confidence = part["geometry_rollup"].get("confidence", {}).get("geometry_reliability", 0.0) if isinstance(part["geometry_rollup"].get("confidence"), dict) else 0.0
    geometry_bend_count = part["geometry_rollup"].get("estimated_bend_line_count", 0) if geometry_confidence >= 0.45 else 0
    feature_rollup = {
        "hole_feature_count": max(len(part.get("hole_sizes_mm", [])), part["geometry_rollup"].get("estimated_hole_count", 0)),
        "slot_feature_count": max(len(part.get("slot_sizes_mm", [])), part["geometry_rollup"].get("estimated_slot_like_features", 0)),
        "bend_feature_count": max(len(part.get("angles_deg", [])), len(part.get("fold_values_mm", [])), part.get("fold_count_textual", 0), geometry_bend_count),
        "radius_feature_count": len(part.get("radii_mm", [])),
        "tap_feature_count": 1 if "tapping" in operations else 0,
        "weld_feature_count": 1 if "welding" in operations else 0,
        "countersink_feature_count": 1 if "countersinking" in operations else 0,
        "flat_pattern_count": 1 if part.get("flat_pattern_detected") else 0,
    }
    part["feature_rollup"] = feature_rollup
    part["manufacturing_features"] = _synthesize_manufacturing_features(part)
    routing = _build_process_routing(part)
    review_needed = not part.get("normalized_material") or not part.get("normalized_thickness_mm") or part["geometry_rollup"].get("estimated_cut_length_mm", 0.0) == 0.0

    part["manufacturing_interpretation"] = {
        "routing": routing,
        "stock_form": "sheet" if part.get("flat_pattern_detected") else "unknown",
        "requires_flat_blank": bool(part.get("flat_pattern_detected") or part.get("overall_length_mm") or part.get("overall_width_mm")),
        "process_family": "fabrication" if operations else "review_required",
        "setup_driven_operations": [step["operation"] for step in routing if step["operation"] in {"laser_cutting", "hole_machining", "folding", "tapping", "countersinking", "welding"}],
        "run_driven_operations": [step["operation"] for step in routing if step["operation"] in {"laser_cutting", "hole_machining", "folding", "powder_coating", "handling"}],
        "routing_confidence": round(sum(part.get("confidence", {}).values()) / max(1, len(part.get("confidence", {}))), 2) if part.get("confidence") else 0.0,
        "review_required": review_needed,
        "geometry_reliability": geometry_confidence,
    }
    part["normalized_geometry"] = _build_normalized_geometry(part)
    part["risk_flags"] = _build_part_risk_flags(part)
    return part


def build_part_index(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    return _build_part_index_impl(
        summary,
        deps=PartIndexDeps(
            dedupe=_dedupe,
            is_valid_part_identifier=_is_valid_part_identifier,
            empty_part_record=_empty_part_record,
            is_component_sheet=_is_component_sheet,
            effective_part_page_role=_effective_part_page_role,
            prefer_local_title_block_values=_prefer_local_title_block_values,
            prefer_local_scalar=_prefer_local_scalar,
            is_good_description=_is_good_description,
            should_assign_dimensions=_should_assign_dimensions,
            pick_part_dimensions=_pick_part_dimensions,
            first_numeric_thickness=_first_numeric_thickness,
            rollup_geometry=_rollup_geometry,
            clean_finish_values=_clean_finish_values,
            is_assembly_identifier=_is_assembly_identifier,
            interpret_part=_interpret_part,
        ),
    )


def build_document_validation(summary: Dict[str, Any], parts: List[Dict[str, Any]]) -> Dict[str, Any]:
    return _build_document_validation_impl(summary, parts)


def build_document_writeup(summary: Dict[str, Any]) -> Dict[str, Any]:
    parts = build_part_index(summary)
    observations: List[str] = []
    manual_review_items: List[Dict[str, Any]] = []
    assembly_pages = [page["page_number"] for page in summary["pages"] if page.get("page_role", {}).get("primary_role") == "assembly"]
    detail_pages = [page["page_number"] for page in summary["pages"] if page.get("page_role", {}).get("primary_role") == "detail"]

    assembly_relations = {
        "assembly_pages": assembly_pages,
        "detail_pages": detail_pages,
        "bom_part_numbers": [row["part_number"] for row in summary.get("document_analysis", {}).get("bom_rows", [])],
        "mirrored_parts": [part["part_number"] for part in parts if part.get("mirrored_detected")],
        "assembly_identifiers": [value for value in summary.get("pattern_summary", {}).get("part_numbers", []) if _is_assembly_identifier(value)],
    }

    for part in parts:
        pn = part["part_number"]
        if part["flat_pattern_detected"]:
            observations.append(f"{pn}: flat pattern detected, likely laser or profile cutting required.")
        if part["hole_sizes_mm"] or part["geometry_rollup"]["estimated_hole_count"]:
            hole_sizes = ", ".join(part["hole_sizes_mm"]) or "geometry-derived hole features"
            observations.append(f"{pn}: hole features detected ({hole_sizes}).")
        if part["angles_deg"] or "folding" in part["textual_operations"]:
            observations.append(f"{pn}: fold or bend work indicated.")
        if part["surface_finishes"]:
            observations.append(f"{pn}: finish detected ({', '.join(part['surface_finishes'])}).")
        if part["materials"]:
            observations.append(f"{pn}: material detected ({', '.join(part['materials'])}).")
        if part["slot_detected"] or part["geometry_rollup"]["estimated_slot_like_features"]:
            observations.append(f"{pn}: slot-like geometry or text cues detected.")
        if part["process_notes"]:
            observations.append(f"{pn}: process notes detected ({'; '.join(part['process_notes'][:3])}).")
        if part["review_flags"]:
            manual_review_items.append(
                {
                    "part_number": pn,
                    "issues": part["review_flags"],
                    "confidence": part.get("confidence", {}),
                }
            )

    validation = build_document_validation(summary, parts)

    return {
        "document_overview": {
            "source_file": summary["source_file"],
            "page_count": summary["page_count"],
            "detected_labels": summary["detected_labels"],
            "pattern_summary": summary["pattern_summary"],
            "document_analysis": summary.get("document_analysis", {}),
        },
        "validation": validation,
        "assembly_relations": assembly_relations,
        "parts": parts,
        "manufacturing_observations": observations,
        "manual_review_items": manual_review_items,
    }
