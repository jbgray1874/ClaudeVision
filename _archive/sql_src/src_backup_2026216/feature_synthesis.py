from typing import Any, Dict, List


def _safe_float(value: Any) -> Any:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def infer_hole_count(part: Dict[str, Any], geometry_confidence: float) -> int:
    text_hole_sizes = len(part.get("hole_sizes_mm", []))
    geometry_hole_count = part["geometry_rollup"].get("estimated_hole_count", 0) if geometry_confidence >= 0.55 else 0
    pitch_values = [_safe_float(value) for value in part.get("pitch_values_mm", []) if _safe_float(value) is not None]
    largest_span = max(
        [value for value in [_safe_float(part.get("overall_length_mm")), _safe_float(part.get("overall_width_mm"))] if value is not None],
        default=None,
    )
    pitch_hole_count = 0
    if pitch_values and largest_span and (text_hole_sizes or part.get("hanging_hole_detected")):
        pitch = max(pitch_values)
        if pitch > 0:
            pitch_hole_count = max(1, int(largest_span / pitch) + 1)
    if pitch_hole_count:
        return max(text_hole_sizes, geometry_hole_count, pitch_hole_count)
    if geometry_hole_count:
        return max(text_hole_sizes, geometry_hole_count)
    if "hole_machining" in part.get("textual_operations", []) and text_hole_sizes:
        return max(1, text_hole_sizes)
    return text_hole_sizes


def infer_bend_count(part: Dict[str, Any], geometry_confidence: float) -> int:
    angle_count = len(part.get("angles_deg", []))
    fold_value_count = len(part.get("fold_values_mm", []))
    fold_text_count = part.get("fold_count_textual", 0)
    geometry_bends = part["geometry_rollup"].get("estimated_bend_line_count", 0) if geometry_confidence >= 0.55 else 0
    dashed_lines = part["geometry_rollup"].get("dashed_long_axis_lines", 0)
    overall_length = part.get("overall_length_mm") or 0
    overall_width = part.get("overall_width_mm") or 0
    long_strip = bool(overall_length and overall_width and overall_length >= overall_width * 8)

    if angle_count == 1 and fold_value_count == 0 and long_strip:
        text_blob = " ".join([str(part.get("description") or ""), " ".join(str(v) for v in part.get("process_notes", []))]).upper()
        angle_value = _safe_float((part.get("angles_deg") or [None])[0])
        repeated_angle_text = False
        if angle_value is not None:
            repeated_angle_text = text_blob.count(str(int(round(angle_value)))) >= 2
        fold_values = [_safe_float(v) for v in part.get("fold_values_mm", []) if _safe_float(v) is not None]
        mirrored_fold_values = len(fold_values) >= 2 and abs(fold_values[0] - fold_values[1]) <= 0.5
        if repeated_angle_text or mirrored_fold_values:
            return 2

    text_signal = max(angle_count, fold_value_count, fold_text_count)
    if text_signal and geometry_bends:
        return min(max(text_signal, 1) + 1, geometry_bends)
    if text_signal:
        return text_signal
    if dashed_lines:
        return max(1, min(dashed_lines, 2 if long_strip else dashed_lines))
    return geometry_bends


def synthesize_manufacturing_features(part: Dict[str, Any]) -> Dict[str, Any]:
    geometry_confidence = part["geometry_rollup"].get("confidence", {}).get("geometry_reliability", 0.0) if isinstance(part["geometry_rollup"].get("confidence"), dict) else 0.0
    text_hole_count = len(part.get("hole_sizes_mm", []))
    text_slot_count = len(part.get("slot_sizes_mm", [])) + (1 if part.get("slot_detected") else 0)
    geometry_hole_count = part["geometry_rollup"].get("estimated_hole_count", 0) if geometry_confidence >= 0.55 else 0
    geometry_slot_count = part["geometry_rollup"].get("estimated_slot_like_features", 0) if geometry_confidence >= 0.55 else 0
    bend_count = infer_bend_count(part, geometry_confidence)
    hole_count = infer_hole_count(part, geometry_confidence)
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
            "geometry_rollup": part.get("geometry_rollup", {}),
        },
    }
