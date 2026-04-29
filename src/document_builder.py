import re
from typing import Any, Dict, List


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

    flat_length = length
    flat_width = width
    if length is not None and width is not None:
        flat_length = round(length + 20.0, 2)
        flat_width = round(width + 20.0, 2)

    bend_angles = [value for value in part.get("angles_deg", []) if value not in (None, "")]
    bend_count = features.get("bend_count", 0) or 0
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
                    target[key][subkey] = max(target[key].get(subkey, 0.0), value)
            continue
        target[key] += geometry.get(key, 0)


def _build_process_routing(part: Dict[str, Any]) -> List[Dict[str, Any]]:
    routing: List[Dict[str, Any]] = []
    operations = part.get("textual_operations", [])
    if "laser_cutting" in operations:
        routing.append({"operation": "laser_cutting", "phase": "profile", "driver": "cut_length_and_pierces", "source": "geometry_or_flat_pattern"})
    if "hole_machining" in operations:
        routing.append({"operation": "hole_machining", "phase": "secondary", "driver": "hole_count", "source": "text_or_geometry"})
    if "tapping" in operations:
        routing.append({"operation": "tapping", "phase": "secondary", "driver": "thread_features", "source": "process_notes"})
    if "countersinking" in operations:
        routing.append({"operation": "countersinking", "phase": "secondary", "driver": "csk_features", "source": "process_notes"})
    if "folding" in operations:
        routing.append({"operation": "folding", "phase": "forming", "driver": "bend_count_and_length", "source": "angles_folds_geometry"})
    if "welding" in operations:
        routing.append({"operation": "welding", "phase": "assembly", "driver": "weld_notes", "source": "process_notes"})
    if "powder_coating" in operations:
        routing.append({"operation": "powder_coating", "phase": "finish", "driver": "finish_requirement", "source": "title_block"})
    routing.append({"operation": "handling", "phase": "logistics", "driver": "part_count", "source": "default"})
    return routing


def _infer_hole_count(part: Dict[str, Any], geometry_confidence: float) -> int:
    text_hole_sizes = len(part.get("hole_sizes_mm", []))
    geometry_hole_count = part["geometry_rollup"].get("estimated_hole_count", 0) if geometry_confidence >= 0.55 else 0
    pitch_values = [_safe_float(value) for value in part.get("pitch_values_mm", []) if _safe_float(value) is not None]
    largest_span = max(
        [
            value for value in [
                _safe_float(part.get("overall_length_mm")),
                _safe_float(part.get("overall_width_mm")),
            ] if value is not None
        ],
        default=None,
    )
    if geometry_hole_count:
        return max(text_hole_sizes, geometry_hole_count)
    if pitch_values and largest_span and (text_hole_sizes or part.get("hanging_hole_detected")):
        pitch = max(pitch_values)
        if pitch > 0:
            # Pitch-based hole series are usually closer to span/pitch + 1 than
            # a rounded ratio, which tends to overcount on shorter brackets.
            estimated_from_pitch = max(1, int(largest_span / pitch) + 1)
            return max(text_hole_sizes, estimated_from_pitch)
    if "hole_machining" in part.get("textual_operations", []) and text_hole_sizes:
        return max(1, text_hole_sizes)
    return text_hole_sizes


def _infer_bend_count(part: Dict[str, Any], geometry_confidence: float) -> int:
    angle_count = len(part.get("angles_deg", []))
    fold_value_count = len(part.get("fold_values_mm", []))
    fold_text_count = part.get("fold_count_textual", 0)
    geometry_bends = part["geometry_rollup"].get("estimated_bend_line_count", 0) if geometry_confidence >= 0.55 else 0
    dashed_lines = part["geometry_rollup"].get("dashed_long_axis_lines", 0)
    overall_length = part.get("overall_length_mm") or 0
    overall_width = part.get("overall_width_mm") or 0
    long_strip = bool(overall_length and overall_width and overall_length >= overall_width * 8)

    if angle_count == 1 and fold_value_count == 0 and long_strip:
        # Common sheet-metal profile case: one section angle often describes two mirrored bends.
        return 2

    text_signal = max(angle_count, fold_value_count, fold_text_count)
    if text_signal and geometry_bends:
        return min(max(text_signal, 1) + 1, geometry_bends)
    if text_signal:
        return text_signal
    if dashed_lines:
        return max(1, min(dashed_lines, 2 if long_strip else dashed_lines))
    return geometry_bends


def _synthesize_manufacturing_features(part: Dict[str, Any]) -> Dict[str, Any]:
    geometry_confidence = part["geometry_rollup"].get("confidence", {}).get("geometry_reliability", 0.0) if isinstance(part["geometry_rollup"].get("confidence"), dict) else 0.0
    text_hole_count = len(part.get("hole_sizes_mm", []))
    text_slot_count = len(part.get("slot_sizes_mm", [])) + (1 if part.get("slot_detected") else 0)
    geometry_hole_count = part["geometry_rollup"].get("estimated_hole_count", 0) if geometry_confidence >= 0.55 else 0
    geometry_slot_count = part["geometry_rollup"].get("estimated_slot_like_features", 0) if geometry_confidence >= 0.55 else 0
    bend_count = _infer_bend_count(part, geometry_confidence)
    hole_count = _infer_hole_count(part, geometry_confidence)
    slot_count = max(text_slot_count, geometry_slot_count)
    finish_required = bool(part.get("normalized_finish") or part.get("surface_finishes"))
    fold_required = bend_count > 0 or "folding" in part.get("textual_operations", [])
    laser_required = bool(part.get("flat_pattern_detected") or "laser_cutting" in part.get("textual_operations", []))
    drilling_required = hole_count > 0 or "hole_machining" in part.get("textual_operations", [])
    tapping_required = "tapping" in part.get("textual_operations", [])
    countersink_required = "countersinking" in part.get("textual_operations", [])
    welding_required = "welding" in part.get("textual_operations", [])

    confidence = {
        "holes": round(max(0.65 if text_hole_count else 0.0, 0.45 * geometry_confidence if geometry_hole_count else 0.0), 2),
        "slots": round(max(0.65 if text_slot_count else 0.0, 0.45 * geometry_confidence if geometry_slot_count else 0.0), 2),
        "bends": round(max(0.75 if (len(part.get("angles_deg", [])) or len(part.get("fold_values_mm", [])) or part.get("fold_count_textual", 0)) else 0.0, 0.55 * geometry_confidence if bend_count else 0.0), 2),
        "laser_required": round(max(0.8 if part.get("flat_pattern_detected") else 0.0, 0.6 if "laser_cutting" in part.get("textual_operations", []) else 0.0), 2),
        "finish_required": round(0.85 if finish_required else 0.0, 2),
    }

    return {
        "laser_required": laser_required,
        "fold_required": fold_required,
        "drilling_required": drilling_required,
        "finish_required": finish_required,
        "tapping_required": tapping_required,
        "countersink_required": countersink_required,
        "welding_required": welding_required,
        "flat_pattern_present": bool(part.get("flat_pattern_detected")),
        "hole_count": hole_count,
        "slot_count": slot_count,
        "bend_count": bend_count,
        "radius_count": len(part.get("radii_mm", [])),
        "hole_sizes_mm": part.get("hole_sizes_mm", []),
        "slot_sizes_mm": part.get("slot_sizes_mm", []),
        "bend_angles_deg": part.get("angles_deg", []),
        "fold_values_mm": part.get("fold_values_mm", []),
        "cut_length_mm": round((part["geometry_rollup"].get("estimated_cut_length_mm", 0.0) or 0.0) * max(0.25, geometry_confidence), 2),
        "raw_cut_length_mm": round(part["geometry_rollup"].get("estimated_cut_length_mm", 0.0) or 0.0, 2),
        "geometry_reliability": geometry_confidence,
        "feature_confidence": confidence,
        "source_summary": {
            "textual_operations": part.get("textual_operations", []),
            "process_note_types": part.get("process_note_types", []),
            "geometry_features": part["geometry_rollup"].get("inferred_features", {}) if isinstance(part["geometry_rollup"].get("inferred_features"), dict) else {},
        },
    }


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
    parts: Dict[str, Dict[str, Any]] = {}
    document_bom_lookup = {
        row["part_number"]: row
        for row in summary.get("document_analysis", {}).get("bom_rows", [])
        if _is_valid_part_identifier(row.get("part_number"))
    }
    document_primary_thickness = summary.get("document_analysis", {}).get("primary_fields", {}).get("thickness_mm")

    for row in summary.get("document_analysis", {}).get("bom_rows", []):
        pn = row["part_number"]
        if not _is_valid_part_identifier(pn):
            continue
        parts[pn] = _empty_part_record(
            part_number=pn,
            item_number=row.get("item_number"),
            description=row.get("description"),
            quantity=row.get("quantity", 1),
        )

    for page in summary["pages"]:
        page_analysis = page.get("page_analysis", {})
        title_block = page_analysis.get("title_block", {})
        dimensions = page_analysis.get("dimensions", {})
        cues = page_analysis.get("feature_cues", {})
        process_notes = page_analysis.get("process_notes", {})
        review_flags = page_analysis.get("review_flags", [])
        confidence = page_analysis.get("confidence", {})
        ops = page_analysis.get("inferred_operations", [])
        geometry = page.get("geometry_summary", {})
        page_role = page.get("page_role", {}).get("primary_role")
        page_part_numbers = page.get("page_analysis", {}).get("title_block", {}).get("part_numbers", []) or page["pattern_summary"].get("part_numbers", [])
        title_block_drawing_numbers = title_block.get("drawing_numbers", [])
        page_target_part_numbers: List[str] = []

        if page_role == "detail":
            page_target_part_numbers.extend(
                [
                    value for value in title_block_drawing_numbers
                    if _is_valid_part_identifier(value)
                ]
            )
            if not page_target_part_numbers:
                page_target_part_numbers.extend(
                    [
                        value for value in page_part_numbers
                        if _is_valid_part_identifier(value)
                    ]
                )
        else:
            if len(title_block_drawing_numbers) == 1 and _is_valid_part_identifier(title_block_drawing_numbers[0]):
                page_target_part_numbers.extend(title_block_drawing_numbers)

        page_target_part_numbers = _dedupe(page_target_part_numbers)

        component_sheet = _is_component_sheet(page_role, title_block, page_target_part_numbers, cues, ops)
        effective_page_role = _effective_part_page_role(page_role, title_block_drawing_numbers, component_sheet)

        for pn in page_target_part_numbers:
            if not _is_valid_part_identifier(pn):
                continue
            if pn not in parts:
                parts[pn] = _empty_part_record(part_number=pn)

            part = parts[pn]
            if page["page_number"] not in part["pages"]:
                part["pages"].append(page["page_number"])
            if effective_page_role:
                part["page_roles"].append(effective_page_role)

            allow_local_component_data = bool(component_sheet)

            part["materials"].extend(_prefer_local_title_block_values(effective_page_role, title_block.get("materials", []), allow_on_assembly=allow_local_component_data))
            part["surface_finishes"].extend(_prefer_local_title_block_values(effective_page_role, title_block.get("surface_finishes", []), allow_on_assembly=allow_local_component_data))
            part["colours"].extend(_prefer_local_title_block_values(effective_page_role, title_block.get("colours", []), allow_on_assembly=allow_local_component_data))
            part["revisions"].extend(_prefer_local_title_block_values(effective_page_role, title_block.get("revisions", []), allow_on_assembly=True))
            part["drawing_numbers"].extend([value for value in _prefer_local_title_block_values(effective_page_role, title_block.get("drawing_numbers", []), allow_on_assembly=True) if _is_valid_part_identifier(value)])
            part["thicknesses_mm"].extend(_prefer_local_title_block_values(effective_page_role, title_block.get("thicknesses_mm", []), allow_on_assembly=allow_local_component_data))
            part["dates"].extend(_prefer_local_title_block_values(effective_page_role, title_block.get("dates", []), allow_on_assembly=True))
            part["sheet_refs"].extend(_prefer_local_title_block_values(effective_page_role, title_block.get("sheet_refs", []), allow_on_assembly=True))
            part["scales"].extend(_prefer_local_title_block_values(effective_page_role, title_block.get("scale", []), allow_on_assembly=True))
            part["clients"].extend(_prefer_local_title_block_values(effective_page_role, title_block.get("clients", []), allow_on_assembly=allow_local_component_data))
            part["project_titles"].extend(_prefer_local_title_block_values(effective_page_role, title_block.get("project_titles", []), allow_on_assembly=allow_local_component_data))
            part["overall_sizes_mm"].extend(dimensions.get("overall_sizes_mm", []))
            part["all_dimensions_mm"].extend(dimensions.get("all_dimensions_mm", []))
            part["angles_deg"].extend(cues.get("angles_deg", []))
            part["hole_sizes_mm"].extend(cues.get("hole_sizes_mm", []))
            part["radii_mm"].extend(cues.get("radii_mm", []))
            part["pitch_values_mm"].extend(cues.get("pitch_values_mm", []))
            part["fold_values_mm"].extend(cues.get("fold_values_mm", []))
            part["slot_sizes_mm"].extend(cues.get("slot_sizes_mm", []))
            part["edge_distances_mm"].extend(cues.get("edge_distances_mm", []))
            part["fold_count_textual"] = max(part.get("fold_count_textual", 0), cues.get("fold_count_textual", 0))
            part["process_notes"].extend(process_notes.get("note_snippets", []))
            part["process_note_types"].extend(process_notes.get("detected_note_types", []))
            part["review_flags"].extend(review_flags)
            part["flat_pattern_detected"] = part["flat_pattern_detected"] or cues.get("flat_pattern_detected", False)
            part["mirrored_detected"] = part["mirrored_detected"] or cues.get("mirrored_detected", False)
            part["hanging_hole_detected"] = part["hanging_hole_detected"] or cues.get("hanging_hole_detected", False)
            part["slot_detected"] = part["slot_detected"] or cues.get("slot_detected", False)
            part["assembly_candidate"] = part["assembly_candidate"] or effective_page_role == "assembly"
            part["textual_operations"].extend(ops)
            part["normalized_material"] = part["normalized_material"] or _prefer_local_scalar(effective_page_role, title_block.get("normalized", {}).get("primary_material"), allow_on_assembly=allow_local_component_data)
            part["normalized_finish"] = part["normalized_finish"] or _prefer_local_scalar(effective_page_role, title_block.get("normalized", {}).get("primary_finish"), allow_on_assembly=allow_local_component_data)
            part["normalized_thickness_mm"] = part["normalized_thickness_mm"] or _prefer_local_scalar(effective_page_role, title_block.get("normalized", {}).get("primary_thickness_mm"), allow_on_assembly=allow_local_component_data)

            if part["description"] is None and pn in document_bom_lookup:
                part["description"] = document_bom_lookup[pn].get("description")

            if part["description"] is None:
                descriptions = title_block.get("descriptions", [])
                if descriptions:
                    for description in descriptions:
                        if _is_good_description(description):
                            part["description"] = description
                            break

            if part["quantity"] in (None, 1):
                quantities = title_block.get("quantities", [])
                if pn in document_bom_lookup and document_bom_lookup[pn].get("quantity"):
                    part["quantity"] = document_bom_lookup[pn].get("quantity")
                elif quantities:
                    try:
                        part["quantity"] = int(quantities[0])
                    except (TypeError, ValueError):
                        pass

            if _should_assign_dimensions(effective_page_role, component_sheet):
                page_dims = _pick_part_dimensions(part, dimensions)
                if part["overall_length_mm"] is None and page_dims.get("overall_length_mm") is not None:
                    part["overall_length_mm"] = page_dims["overall_length_mm"]
                if part["overall_width_mm"] is None and page_dims.get("overall_width_mm") is not None:
                    part["overall_width_mm"] = page_dims["overall_width_mm"]

            if part["normalized_thickness_mm"] is None:
                part["normalized_thickness_mm"] = _first_numeric_thickness(part.get("thicknesses_mm", []))
            if not part["thicknesses_mm"] and part["normalized_thickness_mm"] is not None:
                part["thicknesses_mm"] = [str(part["normalized_thickness_mm"])]

            for key, value in confidence.items():
                part["confidence"].setdefault(key, []).append(value)

            _rollup_geometry(part["geometry_rollup"], geometry)

    for part in parts.values():
        if part.get("pages"):
            continue
        pn = part.get("part_number")
        if not pn:
            continue
        matching_pages = [
            page for page in summary["pages"]
            if pn in (page.get("normalized_text") or "")
        ]
        if not matching_pages:
            continue
        matching_pages = sorted(matching_pages, key=lambda item: (0 if item.get("page_role", {}).get("primary_role") == "detail" else 1, item.get("page_number", 9999)))
        chosen_page = matching_pages[0]
        chosen_role = chosen_page.get("page_role", {}).get("primary_role")
        part["pages"].append(chosen_page["page_number"])
        if chosen_role:
            part["page_roles"].append(chosen_role)

    result: List[Dict[str, Any]] = []
    for part in parts.values():
        for key in [
            "page_roles",
            "materials",
            "surface_finishes",
            "colours",
            "revisions",
            "drawing_numbers",
            "thicknesses_mm",
            "dates",
            "sheet_refs",
            "scales",
            "clients",
            "project_titles",
            "all_dimensions_mm",
            "overall_sizes_mm",
            "angles_deg",
            "hole_sizes_mm",
            "radii_mm",
            "pitch_values_mm",
            "fold_values_mm",
            "slot_sizes_mm",
            "edge_distances_mm",
            "process_notes",
            "process_note_types",
            "textual_operations",
        ]:
            part[key] = _dedupe(part[key])
        if part.get("normalized_material"):
            part["materials"] = [part["normalized_material"]]
        if part.get("normalized_finish"):
            part["surface_finishes"] = [part["normalized_finish"]]
        else:
            part["surface_finishes"] = _clean_finish_values(part.get("surface_finishes", []))
        part["review_flags"] = _dedupe(part["review_flags"])
        if not part.get("drawing_numbers") and not _is_assembly_identifier(part.get("part_number")):
            part["drawing_numbers"] = [part["part_number"]]
        if part.get("normalized_thickness_mm") is None and document_primary_thickness is not None:
            part["normalized_thickness_mm"] = document_primary_thickness
            if not part.get("thicknesses_mm"):
                part["thicknesses_mm"] = [str(document_primary_thickness)]
        part["confidence"] = {
            key: round(sum(values) / len(values), 2) if values else 0.0
            for key, values in part.get("confidence", {}).items()
        }
        _interpret_part(part)
        result.append(part)

    return sorted(result, key=lambda item: item.get("part_number") or "")


def build_document_validation(summary: Dict[str, Any], parts: List[Dict[str, Any]]) -> Dict[str, Any]:
    issues: List[Dict[str, Any]] = []
    if not parts:
        issues.append({"severity": "error", "code": "no_parts_extracted", "reason": "No manufacturable parts were extracted from the document."})

    assembly_pages = [page for page in summary["pages"] if page.get("page_role", {}).get("primary_role") == "assembly"]
    detail_pages = [page for page in summary["pages"] if page.get("page_role", {}).get("primary_role") == "detail"]
    if detail_pages and not parts:
        issues.append({"severity": "error", "code": "detail_pages_without_parts", "reason": "Detail pages were detected but no part records were created."})

    for part in parts:
        if len(part.get("materials", [])) > 2:
            issues.append({"severity": "warning", "code": "mixed_materials", "part_number": part.get("part_number"), "reason": "Part accumulated multiple materials, suggesting assembly contamination."})
        if len(part.get("surface_finishes", [])) > 2:
            issues.append({"severity": "warning", "code": "mixed_finishes", "part_number": part.get("part_number"), "reason": "Part accumulated multiple finishes, suggesting assembly contamination."})
        if part.get("page_roles") and "assembly" in part.get("page_roles", []) and "detail" not in part.get("page_roles", []):
            issues.append({"severity": "info", "code": "assembly_only_part_record", "part_number": part.get("part_number"), "reason": "Part record is derived from assembly pages only."})
        if not part.get("normalized_material") and part.get("manufacturing_features", {}).get("laser_required"):
            issues.append({"severity": "warning", "code": "missing_material_for_fabrication", "part_number": part.get("part_number"), "reason": "Fabrication cues exist but no reliable material was extracted."})

    status = "ok_for_pricing"
    if any(issue["severity"] == "error" for issue in issues):
        status = "failed_part_extraction"
    elif any(issue["severity"] == "warning" for issue in issues):
        status = "needs_review"

    return {
        "status": status,
        "part_count": len(parts),
        "assembly_page_count": len(assembly_pages),
        "detail_page_count": len(detail_pages),
        "issues": issues,
    }


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
