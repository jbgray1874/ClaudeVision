import math
from typing import Any, Dict, List, Tuple

import fitz


POINT_TO_MM = 25.4 / 72.0


def _distance(p1: fitz.Point, p2: fitz.Point) -> float:
    return math.hypot(p2.x - p1.x, p2.y - p1.y)



def _rect_metrics(rect: fitz.Rect) -> Tuple[float, float, float]:
    width = abs(rect.width)
    height = abs(rect.height)
    perimeter = 2 * (width + height)
    return width, height, perimeter



def analyse_page_geometry(page: fitz.Page) -> Dict[str, Any]:
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

    for drawing in drawings:
        items = drawing.get("items", [])
        if drawing.get("fill"):
            fill_paths += 1
        contour_complexity += len(items)

        for item in items:
            op = item[0]

            if op == "l":
                p1, p2 = item[1], item[2]
                length = _distance(p1, p2)
                line_segments += 1
                approx_total_line_length_points += length
                estimated_pierce_count += 1
                if length > 20:
                    estimated_bend_line_count += 1

            elif op == "re":
                rect = item[1]
                width, height, perimeter = _rect_metrics(rect)
                rect_count += 1
                approx_total_line_length_points += perimeter
                estimated_pierce_count += 1
                if min(width, height) <= 20:
                    slot_like_count += 1

            elif op in {"c", "v", "y"}:
                curve_count += 1
                approx_total_curve_length_points += 12.0
                estimated_pierce_count += 1

    # Heuristic: if a path contains curves and modest path count, treat some as holes/circular cutouts
    if curve_count:
        circle_like_count = max(0, round(curve_count * 0.35))
        estimated_hole_count = circle_like_count

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
        "units_note": "Lengths derived from PDF page points converted to mm; treat as heuristic until calibrated against drawing scale.",
    }



def analyse_document_geometry(pdf_path) -> List[Dict[str, Any]]:
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