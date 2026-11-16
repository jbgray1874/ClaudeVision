import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

try:
    import fitz  # type: ignore
except ImportError:  # pragma: no cover
    fitz = None

from geometry_calibration import calibrate_page_geometry
from geometry_features import analyse_vector_features


POINT_TO_MM = 25.4 / 72.0


def _distance(p1: Any, p2: Any) -> float:
    return math.hypot(p2.x - p1.x, p2.y - p1.y)


def _rect_metrics(rect: Any) -> Tuple[float, float, float]:
    width = abs(rect.width)
    height = abs(rect.height)
    perimeter = 2 * (width + height)
    return width, height, perimeter


def _is_axis_aligned_line(p1: Any, p2: Any, tolerance: float = 0.5) -> bool:
    return abs(p1.x - p2.x) <= tolerance or abs(p1.y - p2.y) <= tolerance


def _is_dashed(path: Dict[str, Any]) -> bool:
    dashes = str(path.get("dashes", "")).strip()
    return bool(dashes and dashes != "[] 0")


def _analyse_drawing_list(drawings: List[Dict[str, Any]], page_height_points: float) -> Dict[str, Any]:
    line_segments = 0
    curve_count = 0
    rect_count = 0
    fill_paths = 0
    approx_total_line_length_points = 0.0
    approx_total_curve_length_points = 0.0
    circle_like_count = 0
    slot_like_count = 0
    estimated_hole_count = 0
    estimated_bend_line_count = 0
    estimated_pierce_count = 0
    contour_complexity = 0
    long_axis_aligned_lines = 0
    dashed_long_axis_lines = 0
    short_closed_rectangles = 0
    closed_path_count = 0
    internal_feature_count = 0
    stroked_path_count = 0
    narrow_stroke_path_count = 0
    small_internal_loop_features = 0
    title_block_band_top = page_height_points * 0.72
    max_line_length_points = 0.0

    for drawing in drawings:
        stroke_width = float(drawing.get("width", 0.0) or 0.0)
        if stroke_width < 0.18:
            # Ignore ultra-thin construction/dimension lines.
            continue
        items = drawing.get("items", [])
        rect = drawing.get("rect")
        if drawing.get("fill"):
            fill_paths += 1
        contour_complexity += len(items)
        if drawing.get("closePath"):
            closed_path_count += 1
        if drawing.get("type") in {"s", "fs"}:
            stroked_path_count += 1
        if stroke_width <= 0.3:
            narrow_stroke_path_count += 1
        if rect is not None:
            rect_width = abs(rect.width)
            rect_height = abs(rect.height)
            many_segments = len(items) >= 8 and all(item[0] == "l" for item in items[: min(len(items), 12)])
            compact_size = 4.0 <= max(rect_width, rect_height) <= 16.0 and min(rect_width, rect_height) >= 4.0
            outside_title_block = rect.y0 < title_block_band_top
            if many_segments and compact_size and outside_title_block:
                small_internal_loop_features += 1

        for item in items:
            op = item[0]

            if op == "l":
                p1, p2 = item[1], item[2]
                length = _distance(p1, p2)
                if length < 8.0:
                    continue
                line_segments += 1
                approx_total_line_length_points += length
                max_line_length_points = max(max_line_length_points, length)
                if _is_axis_aligned_line(p1, p2) and length > 40:
                    long_axis_aligned_lines += 1
                    if _is_dashed(drawing):
                        dashed_long_axis_lines += 1

            elif op == "re":
                rect = item[1]
                width, height, perimeter = _rect_metrics(rect)
                rect_count += 1
                approx_total_line_length_points += perimeter
                if min(width, height) <= 20:
                    slot_like_count += 1
                    short_closed_rectangles += 1
                if width <= 25 and height <= 25:
                    internal_feature_count += 1

            elif op in {"c", "v", "y", "qu"}:
                curve_count += 1
                approx_total_curve_length_points += 12.0
                if rect is not None:
                    rw = abs(rect.width)
                    rh = abs(rect.height)
                    if rw > 0 and rh > 0:
                        aspect_ratio = max(rw, rh) / max(1e-6, min(rw, rh))
                        # Near-square curve bounds are more likely true circular holes;
                        # elongated bounds are more likely slots/fillets.
                        if aspect_ratio <= 1.2:
                            circle_like_count += 1
                        elif aspect_ratio >= 1.8:
                            slot_like_count += 1

    if curve_count and circle_like_count == 0:
        circle_like_count = max(0, round(curve_count * 0.2))
    estimated_hole_count = max(circle_like_count, short_closed_rectangles, small_internal_loop_features)
    internal_feature_count += estimated_hole_count + slot_like_count + small_internal_loop_features
    estimated_pierce_count = max(closed_path_count, internal_feature_count)
    estimated_bend_line_count = dashed_long_axis_lines

    geometry_reliability = 0.0
    # Strong signal: closed/curved geometry is present.
    if closed_path_count > 0 or rect_count > 0 or curve_count > 0:
        geometry_reliability += 0.35
    # SOLIDWORKS detail sheets are often line-dominant/open-path drawings.
    if line_segments >= 120:
        geometry_reliability += 0.25
    if contour_complexity >= 700:
        geometry_reliability += 0.15
    # Bend cues from dashed long-axis lines.
    if dashed_long_axis_lines > 0:
        geometry_reliability += 0.2
    # Reward pages where meaningful strokes are not dominated by ultra-thin noise.
    if stroked_path_count > 0 and narrow_stroke_path_count < max(10, stroked_path_count * 0.8):
        geometry_reliability += 0.15
    geometry_reliability = round(min(1.0, geometry_reliability), 2)

    total_cut_length_mm = round((approx_total_line_length_points + approx_total_curve_length_points) * POINT_TO_MM, 2)
    vector_features = analyse_vector_features(drawings)
    feature_rel = float((vector_features.get("confidence", {}) or {}).get("geometry_reliability", 0.0) or 0.0)
    # Use the stronger of analysis-level and feature-level reliability so line-rich
    # SOLIDWORKS detail pages are not unfairly down-scored.
    geometry_reliability = round(max(geometry_reliability, feature_rel), 2)

    return {
        "vector_path_count": len(drawings),
        "line_segments": line_segments,
        "rectangles": rect_count,
        "curves": curve_count,
        "filled_paths": fill_paths,
        "approx_total_line_length_points": round(approx_total_line_length_points, 2),
        "approx_total_curve_length_points": round(approx_total_curve_length_points, 2),
        "estimated_cut_length_mm": total_cut_length_mm,
        "estimated_hole_count": estimated_hole_count,
        "estimated_circle_like_features": circle_like_count,
        "estimated_slot_like_features": slot_like_count,
        "estimated_bend_line_count": estimated_bend_line_count,
        "estimated_pierce_count": estimated_pierce_count,
        "contour_complexity": contour_complexity,
        "closed_path_count": closed_path_count,
        "long_axis_aligned_lines": long_axis_aligned_lines,
        "dashed_long_axis_lines": dashed_long_axis_lines,
        "max_line_length_points": round(max_line_length_points, 2),
        "vector_features": vector_features,
        "raw_geometry": {
            "vector_path_count": len(drawings),
            "line_segments": line_segments,
            "rectangles": rect_count,
            "curves": curve_count,
            "filled_paths": fill_paths,
            "closed_path_count": closed_path_count,
            "long_axis_aligned_lines": long_axis_aligned_lines,
            "dashed_long_axis_lines": dashed_long_axis_lines,
            "stroked_path_count": stroked_path_count,
            "narrow_stroke_path_count": narrow_stroke_path_count,
            "small_internal_loop_features": small_internal_loop_features,
        },
        "inferred_features": {
            "estimated_cut_length_mm": total_cut_length_mm,
            "estimated_hole_count": estimated_hole_count,
            "estimated_slot_like_features": slot_like_count,
            "estimated_bend_line_count": estimated_bend_line_count,
            "estimated_pierce_count": estimated_pierce_count,
            "small_internal_loop_features": small_internal_loop_features,
        },
        "confidence": {
            "geometry_reliability": geometry_reliability,
            "estimated_cut_length_mm": round(0.55 * geometry_reliability, 2) if total_cut_length_mm > 0 else 0.0,
            "estimated_hole_count": round(0.65 * geometry_reliability, 2) if estimated_hole_count > 0 else 0.0,
            "estimated_slot_like_features": round(0.68 * geometry_reliability, 2) if slot_like_count > 0 else 0.0,
            "estimated_bend_line_count": round(0.7 * geometry_reliability, 2) if estimated_bend_line_count > 0 else 0.0,
        },
        "_raw": {
            "estimated_cut_length_mm": total_cut_length_mm,
            "estimated_pierce_count": estimated_pierce_count,
            "estimated_hole_count": estimated_hole_count,
            "vector_path_count": len(drawings),
        },
        "units_note": "Lengths derived from PDF page points converted to mm; treat as heuristic until calibrated against drawing scale.",
    }


def _get_pdf_path_from_pages(processed_pages: List[Dict[str, Any]]) -> Optional[str]:
    """Recover source PDF path from page metadata (source_pdf_path / full_path)."""
    for page in processed_pages:
        fp = page.get("source_pdf_path") or page.get("full_path")
        if fp:
            return str(fp)
    return None


def analyse_page_geometry(page: Any) -> Dict[str, Any]:
    drawings = page.get_drawings()
    return _analyse_drawing_list(drawings, float(page.rect.height))


def _analyse_geometry_from_pdf(pdf_path: Path) -> List[Dict[str, Any]]:
    if fitz is None:
        return []

    document = fitz.open(str(pdf_path))
    pages: List[Dict[str, Any]] = []
    try:
        for idx, page in enumerate(document, start=1):
            summary = analyse_page_geometry(page)
            summary["page_number"] = idx
            summary["page_size_points"] = [round(page.rect.width, 2), round(page.rect.height, 2)]
            pages.append(summary)
    finally:
        document.close()
    return pages


def calibrate_document_geometry(summary: Dict[str, Any], geometry_pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    page_lookup = {page.get("page_number"): page for page in summary.get("pages", [])}
    calibrated: List[Dict[str, Any]] = []
    for geometry in geometry_pages:
        page_number = geometry.get("page_number")
        page_summary = page_lookup.get(page_number, {})
        page_analysis = page_summary.get("page_analysis", {})
        page_role = (page_summary.get("page_role", {}) or {}).get("primary_role")
        calibration = calibrate_page_geometry(
            page_analysis,
            geometry,
            geometry.get("page_size_points"),
            page_role=page_role,
        )
        # Confidence boost when page has strong BOM cues / detail role.
        vector_conf = ((geometry.get("vector_features") or {}).get("confidence") or {})
        base_rel = float(vector_conf.get("geometry_reliability", 0.0) or 0.0)
        bom_rows = (page_analysis.get("bom_rows") or [])
        boost = 0.0
        if len(bom_rows) >= 3:
            boost += 0.2
        if page_role == "detail":
            boost += 0.1
        if boost > 0:
            boosted = round(min(1.0, base_rel + boost), 2)
            vector_conf["geometry_reliability"] = boosted
            geometry.setdefault("confidence", {})["geometry_reliability"] = boosted
        geometry["scale_calibration"] = calibration
        calibrated.append(geometry)
    return calibrated


def _analyse_geometry_from_processed_pages(processed_pages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Open the source PDF via fitz and run _analyse_drawing_list() on real vector paths.
    Falls back to analyse_vector_features() on vision_extraction when fitz cannot run.
    """
    import logging

    results: List[Dict[str, Any]] = []
    total_reliability = 0.0
    pdf_path_str = _get_pdf_path_from_pages(processed_pages)
    fitz_page_drawings: Dict[int, List[Dict[str, Any]]] = {}

    if fitz is not None and pdf_path_str:
        try:
            doc = fitz.open(pdf_path_str)
            try:
                for fitz_page in doc:
                    idx = fitz_page.number + 1
                    fitz_page_drawings[idx] = fitz_page.get_drawings()
            finally:
                doc.close()
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "geometry_analysis: fitz failed to open %s — falling back to vision drawings: %s",
                pdf_path_str,
                exc,
            )

    for page in processed_pages:
        page_number = int(page.get("page_number") or 0)
        page_analysis = dict(page.get("page_analysis", {}) or {})
        page_role = (page.get("page_role", {}) or {}).get("primary_role")
        page_width = float(page.get("page_width", 0.0) or 0.0)
        page_height = float(page.get("page_height", 0.0) or 0.0)
        page_size_points = [page_width, page_height]
        page_text = str(page.get("pdfplumber_text") or page.get("pypdf_text") or "")
        if page_text and not page_analysis.get("pdfplumber_text"):
            page_analysis["pdfplumber_text"] = page_text

        if page_number in fitz_page_drawings:
            geometry_raw = _analyse_drawing_list(fitz_page_drawings[page_number], page_height)
            geometry = {
                "connected_contour_groups": geometry_raw.get("line_segments", 0) // max(1, 8),
                "internal_loops": geometry_raw.get("estimated_hole_count", 0),
                "external_contours": geometry_raw.get("closed_path_count", 0),
                "open_profiles": 0,
                "closed_profiles": geometry_raw.get("closed_path_count", 0),
                "arc_candidates": geometry_raw.get("curves", 0),
                "circle_candidates": geometry_raw.get("estimated_circle_like_features", 0),
                "dashed_long_axis_lines": geometry_raw.get("dashed_long_axis_lines", 0),
                "collinear_groups": 0,
                "symmetry_detected": False,
                "feature_clusters": max(1, geometry_raw.get("estimated_hole_count", 0) + 1),
                "max_line_length_points": geometry_raw.get("max_line_length_points", 0.0),
                "confidence": geometry_raw.get("confidence", {"geometry_reliability": 0.0}),
                "_raw": geometry_raw,
                "estimated_cut_length_mm": geometry_raw.get("estimated_cut_length_mm", 0.0),
                "estimated_pierce_count": geometry_raw.get("estimated_pierce_count", 0),
                "estimated_bend_line_count": geometry_raw.get("estimated_bend_line_count", 0),
                "vector_features": geometry_raw.get("vector_features", {}),
            }
        else:
            fallback_drawings = ((page.get("vision_extraction") or {}).get("drawings")) or []
            geometry = analyse_vector_features(fallback_drawings)

        calibration = calibrate_page_geometry(
            page_analysis,
            {
                "vector_features": geometry.get("vector_features") or geometry,
                "confidence": geometry.get("confidence", {}),
            },
            page_size_points,
            page_role=page_role,
            page_text=page_text,
        )

        bom_rows = page_analysis.get("bom_rows") or []
        if len(bom_rows) > 3:
            cur = float(geometry.get("confidence", {}).get("geometry_reliability", 0.0) or 0.0)
            geometry.setdefault("confidence", {})["geometry_reliability"] = round(min(1.0, cur + 0.25), 2)
        if page_role == "detail":
            cur = float(geometry.get("confidence", {}).get("geometry_reliability", 0.0) or 0.0)
            geometry.setdefault("confidence", {})["geometry_reliability"] = round(min(1.0, cur + 0.10), 2)

        page_result = {
            "page_number": page_number,
            "geometry": geometry,
            "calibration": calibration,
        }
        results.append(page_result)
        total_reliability += float((geometry.get("confidence") or {}).get("geometry_reliability", 0.0) or 0.0)

    avg_reliability = round(total_reliability / len(results), 2) if results else 0.0
    return {
        "pages": results,
        "document_geometry_reliability": avg_reliability,
        "overall_confidence": round((avg_reliability + 0.3) / 1.3, 2),
        "fitz_available": fitz is not None,
        "pdf_path_recovered": bool(pdf_path_str),
        "pages_with_fitz_drawings": len(fitz_page_drawings),
    }


def analyse_document_geometry(
    input_data: Union[Path, str, List[Dict[str, Any]]],
    pdf_path: Optional[Union[Path, str]] = None,
) -> Union[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Backward-compatible geometry entrypoint:
    - Path input: returns per-page geometry list (legacy behavior)
    - Processed page list input: returns document geometry dict (new SOLIDWORKS flow)
    """
    if isinstance(input_data, list):
        if pdf_path is not None:
            path_str = str(pdf_path)
            for page in input_data:
                page.setdefault("source_pdf_path", path_str)
        return _analyse_geometry_from_processed_pages(input_data)
    return _analyse_geometry_from_pdf(Path(input_data))
