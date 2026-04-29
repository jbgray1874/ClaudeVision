from typing import Any, Dict, List


def calibrate_page_geometry(page_analysis: Dict[str, Any], geometry_summary: Dict[str, Any], page_size_points: List[float] | None = None) -> Dict[str, Any]:
    dimensions = page_analysis.get("dimensions", {}) if isinstance(page_analysis, dict) else {}
    overall_length_mm = dimensions.get("overall_length_mm")
    overall_width_mm = dimensions.get("overall_width_mm")
    max_line_length_points = geometry_summary.get("vector_features", {}).get("max_line_length_points") or 0.0

    calibrated = False
    point_to_mm = 25.4 / 72.0
    method = "page_points_default"
    reference_dimensions_mm: List[float] = []
    matched_vector_spans = 0
    calibration_confidence = 0.0

    if overall_length_mm and max_line_length_points:
        calibrated = True
        point_to_mm = round(float(overall_length_mm) / float(max_line_length_points), 6)
        method = "max_vector_span_to_overall_length"
        reference_dimensions_mm.append(float(overall_length_mm))
        matched_vector_spans = 1
        calibration_confidence = 0.72
    elif overall_width_mm and page_size_points:
        longer_page_side = max(page_size_points)
        if longer_page_side:
            calibrated = True
            point_to_mm = round(float(overall_width_mm) / float(longer_page_side), 6)
            method = "page_extent_to_overall_width"
            reference_dimensions_mm.append(float(overall_width_mm))
            matched_vector_spans = 1
            calibration_confidence = 0.42

    return {
        "calibrated": calibrated,
        "method": method,
        "point_to_mm": point_to_mm,
        "reference_dimensions_mm": reference_dimensions_mm,
        "matched_vector_spans": matched_vector_spans,
        "calibration_confidence": round(calibration_confidence, 2),
    }
