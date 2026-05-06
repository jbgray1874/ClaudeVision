from datetime import datetime, timezone
import re
from typing import Any, Dict, List, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_scale(scale_text: Optional[str]) -> Optional[float]:
    if not scale_text:
        return None
    text = str(scale_text).strip().upper()
    if text in {"FULL", "1:1", "1 : 1"}:
        return 1.0
    if text in {"NTS", "NOT TO SCALE", "N/A", "-"}:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)", text)
    if not match:
        return None
    num = float(match.group(1))
    den = float(match.group(2))
    if num <= 0 or den <= 0:
        return None
    return den / num


def calibrate_page_geometry(page_analysis: Dict[str, Any], geometry_summary: Dict[str, Any], page_size_points: List[float] | None = None) -> Dict[str, Any]:
    dimensions = page_analysis.get("dimensions", {}) if isinstance(page_analysis, dict) else {}
    overall_length_mm = dimensions.get("overall_length_mm")
    overall_width_mm = dimensions.get("overall_width_mm")
    max_line_length_points = geometry_summary.get("vector_features", {}).get("max_line_length_points") or 0.0
    geometry_reliability = float(
        (geometry_summary.get("confidence", {}) or {}).get("geometry_reliability", 0.0) or 0.0
    )

    calibrated = False
    point_to_mm = 25.4 / 72.0
    method = "page_points_default"
    reference_dimensions_mm: List[float] = []
    matched_vector_spans = 0
    calibration_confidence = 0.0
    scale_ratio = None
    scale_text_used = None

    title_block = page_analysis.get("title_block", {}) if isinstance(page_analysis, dict) else {}
    raw_scales = title_block.get("scale") or title_block.get("scales") or []
    scale_texts: List[str] = []
    if isinstance(raw_scales, list):
        scale_texts = [str(s) for s in raw_scales if s]
    elif isinstance(raw_scales, str) and raw_scales:
        scale_texts = [raw_scales]
    for scale_text in scale_texts:
        parsed = _parse_scale(scale_text)
        if parsed is not None:
            scale_ratio = parsed
            scale_text_used = scale_text
            point_to_mm = round((25.4 / 72.0) * parsed, 6)
            calibrated = True
            method = "scale_from_title_block"
            calibration_confidence = 0.90
            return {
                "calibrated": calibrated,
                "method": method,
                "point_to_mm": point_to_mm,
                "reference_dimensions_mm": reference_dimensions_mm,
                "matched_vector_spans": matched_vector_spans,
                "calibration_confidence": round(calibration_confidence, 2),
                "geometry_reliability": round(geometry_reliability, 2),
                "scale_ratio": scale_ratio,
                "scale_text_used": scale_text_used,
                "calibrated_at": _utc_now(),
            }

    if overall_length_mm and max_line_length_points > 0 and geometry_reliability >= 0.45:
        calibrated = True
        point_to_mm = round(float(overall_length_mm) / float(max_line_length_points), 6)
        method = "max_vector_span_to_overall_length"
        reference_dimensions_mm.append(float(overall_length_mm))
        matched_vector_spans = 1
        calibration_confidence = min(0.9, 0.55 + 0.45 * geometry_reliability)
    elif overall_width_mm and page_size_points:
        longer_page_side = max(page_size_points)
        if longer_page_side:
            calibrated = True
            point_to_mm = round(float(overall_width_mm) / float(longer_page_side), 6)
            method = "page_extent_to_overall_width"
            reference_dimensions_mm.append(float(overall_width_mm))
            matched_vector_spans = 1
            calibration_confidence = max(0.3, 0.35 + 0.25 * geometry_reliability)

    return {
        "calibrated": calibrated,
        "method": method,
        "point_to_mm": point_to_mm,
        "reference_dimensions_mm": reference_dimensions_mm,
        "matched_vector_spans": matched_vector_spans,
        "calibration_confidence": round(calibration_confidence, 2),
        "geometry_reliability": round(geometry_reliability, 2),
        "scale_ratio": scale_ratio,
        "scale_text_used": scale_text_used,
        "calibrated_at": _utc_now(),
    }
