from datetime import datetime, timezone
import re
from typing import Any, Dict, List, Optional
def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
def _extract_scale_from_text(text: str) -> Optional[float]:
    """
    Scan raw page text for SCALE N:M when title_block.scale is empty.
    Three patterns tried in priority order:
      1. 'SCALE: N:M' or 'SCALE - N:M'  (explicit separator)
      2. 'SCALE N:M'                     (space-separated)
      3. N:M within 30 chars of 'SCALE'  (loose proximity — guards against bare ratio
         false-positives on timestamps, sheet refs and drawing codes)
    The bare ratio-only fallback is intentionally omitted: '19:07', '1/10', and
    drawing codes like 'SHEET 1:1' outside a SCALE label context are too common
    in SOLIDWORKS title blocks to safely match without the keyword anchor.
    """
    if not text:
        return None
    upper = text.upper()
    for pattern in (
        r"SCALE\s*[-:]\s*(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)",
        r"SCALE\s+(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)",
    ):
        match = re.search(pattern, upper)
        if match:
            num, den = float(match.group(1)), float(match.group(2))
            if num > 0 and den > 0:
                return den / num
    # Proximity fallback: ratio within 30 chars of SCALE keyword
    for scale_pos in [m.start() for m in re.finditer(r"\bSCALE\b", upper)]:
        window = upper[scale_pos:scale_pos + 30]
        m = re.search(r"(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)", window)
        if m:
            num, den = float(m.group(1)), float(m.group(2))
            if num > 0 and den > 0 and 0.05 <= den / num <= 20.0:
                return den / num
    return None
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
def calibrate_page_geometry(
    page_analysis: Dict[str, Any],
    geometry_summary: Dict[str, Any],
    page_size_points: List[float] | None = None,
    page_role: Optional[str] = None,
    page_text: Optional[str] = None,
) -> Dict[str, Any]:
    # DXF geometry is already in millimetres — no PDF point scaling.
    if isinstance(geometry_summary, dict) and (
        geometry_summary.get("source") == "dxf" or geometry_summary.get("dxf_native_mm")
    ):
        geometry_reliability = float(
            (geometry_summary.get("confidence", {}) or {}).get("geometry_reliability", 0.0) or 0.0
        )
        return {
            "calibrated": True,
            "method": "dxf_native_units",
            "point_to_mm": 1.0,
            "reference_dimensions_mm": list(geometry_summary.get("dimension_values_mm") or [])[:8],
            "matched_vector_spans": 0,
            "calibration_confidence": round(min(1.0, 0.85 + 0.15 * geometry_reliability), 2),
            "geometry_reliability": round(geometry_reliability, 2),
            "scale_ratio": 1.0,
            "scale_text_used": "dxf:1:1",
            "calibrated_at": _utc_now(),
        }
    # page_text is optional; page_analysis may also carry pdfplumber_text (injected by file_scan / geometry_analysis).
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
    raw_text = ""
    if isinstance(page_analysis, dict):
        raw_text = (
            str(page_analysis.get("pdfplumber_text") or "")
            + " "
            + str((page_analysis.get("title_block") or {}).get("raw_text") or "")
            + " "
            + str(page_analysis.get("normalized_text") or "")
        )
    if page_text:
        raw_text = f"{raw_text} {page_text}"
    if not raw_text.strip() and isinstance(geometry_summary, dict):
        raw_text = str(geometry_summary)
    if not calibrated and raw_text.strip():
        parsed_from_text = _extract_scale_from_text(raw_text)
        if parsed_from_text is not None:
            scale_ratio = parsed_from_text
            scale_text_used = f"text_scan:{parsed_from_text}"
            point_to_mm = round((25.4 / 72.0) * parsed_from_text, 6)
            return {
                "calibrated": True,
                "method": "scale_from_page_text",
                "point_to_mm": point_to_mm,
                "reference_dimensions_mm": reference_dimensions_mm,
                "matched_vector_spans": matched_vector_spans,
                "calibration_confidence": 0.82,
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
    elif page_role and str(page_role).lower() in {"detail", "section"}:
        calibrated = True
        method = "section_view_fallback"
        serialized = f"{page_analysis} {geometry_summary}".upper()
        # FIXED: Changed from blind 5× scale guess to 1:1 default when scale cannot be determined.
        # The previous code assumed detail views are always at 5:1 scale, which caused severe
        # inflation: 2621-01C saw 8172pts × 5× ≈ 14446mm (actual part is ~500mm).
        # Now default to 1:1 (conservative), which flags the uncertainty to the credibility gate.
        # This allows downstream logic to decide whether to trust the geometry.
        point_to_mm = round((25.4 / 72.0) * 1.0, 6)
        calibration_confidence = max(0.45, 0.5 + 0.25 * geometry_reliability)
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
