import math
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    import fitz  # type: ignore
except ImportError:  # pragma: no cover
    fitz = None


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


def analyse_page_geometry(page: Any) -> Dict[str, Any]:
    drawings = page.get_drawings()

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
    title_block_band_top = page.rect.height * 0.72

    for drawing in drawings:
        items = drawing.get("items", [])
        rect = drawing.get("rect")
        if drawing.get("fill"):
            fill_paths += 1
        contour_complexity += len(items)
        if drawing.get("closePath"):
            closed_path_count += 1
        if drawing.get("type") in {"s", "fs"}:
            stroked_path_count += 1
        if float(drawing.get("width", 0.0) or 0.0) <= 0.3:
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
                line_segments += 1
                approx_total_line_length_points += length
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

    if curve_count:
        circle_like_count = max(0, round(curve_count * 0.35))
    estimated_hole_count = max(circle_like_count, short_closed_rectangles, small_internal_loop_features)
    internal_feature_count += estimated_hole_count + slot_like_count + small_internal_loop_features
    estimated_pierce_count = max(closed_path_count, internal_feature_count)
    estimated_bend_line_count = dashed_long_axis_lines

    geometry_reliability = 0.0
    if closed_path_count > 0 or rect_count > 0 or curve_count > 0:
        geometry_reliability += 0.45
    if dashed_long_axis_lines > 0:
        geometry_reliability += 0.35
    if stroked_path_count > 0 and narrow_stroke_path_count < max(10, stroked_path_count * 0.7):
        geometry_reliability += 0.2
    geometry_reliability = round(min(1.0, geometry_reliability), 2)

    total_cut_length_mm = round((approx_total_line_length_points + approx_total_curve_length_points) * POINT_TO_MM, 2)

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
        "units_note": "Lengths derived from PDF page points converted to mm; treat as heuristic until calibrated against drawing scale.",
    }


def analyse_document_geometry(pdf_path: Path) -> List[Dict[str, Any]]:
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
