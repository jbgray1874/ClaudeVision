import math
from typing import Any, Dict, List, Tuple
def _distance(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    return math.hypot(p2[0] - p1[0], p2[1] - p1[1])
def _quantize_point(point: Tuple[float, float], tolerance: float = 1.0) -> Tuple[int, int]:
    return (round(point[0] / tolerance), round(point[1] / tolerance))
def _arc_is_circular(item: Any) -> bool:
    try:
        points = [item[i] for i in range(1, len(item)) if hasattr(item[i], "x")]
        if len(points) < 2:
            return True
        xs = [p.x for p in points]
        ys = [p.y for p in points]
        width = max(xs) - min(xs)
        height = max(ys) - min(ys)
        if width <= 0 or height <= 0:
            return True
        ratio = width / height
        return 0.7 <= ratio <= 1.3
    except Exception:
        return True
def analyse_vector_features(drawings: List[Dict[str, Any]]) -> Dict[str, Any]:
    segments: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
    circle_candidates = 0
    arc_items: List[Any] = []
    arc_candidates = 0
    closed_profiles = 0
    line_lengths: List[float] = []
    midpoint_xs: List[float] = []
    dashed_long_axis_lines = 0
    stroked_path_count = 0
    narrow_stroke_path_count = 0
    total_paths = 0
    filtered_by_width = 0
    kept_by_width = 0
    for drawing in drawings:
        total_paths += 1
        stroke_width = float(drawing.get("width", 0.0) or 0.0)
        # Relaxed filter for this SOLIDWORKS pack: keep thin but real profile lines.
        if stroke_width < 0.12:
            filtered_by_width += 1
            continue
        kept_by_width += 1
        if drawing.get("closePath"):
            closed_profiles += 1
        if drawing.get("type") in {"s", "fs"}:
            stroked_path_count += 1
        if stroke_width <= 0.3:
            narrow_stroke_path_count += 1
        for item in drawing.get("items", []):
            op = item[0]
            if op == "l":
                p1 = (float(item[1].x), float(item[1].y))
                p2 = (float(item[2].x), float(item[2].y))
                length = _distance(p1, p2)
                if length < 8.0:
                    continue
                segments.append((p1, p2))
                line_lengths.append(length)
                midpoint_xs.append((p1[0] + p2[0]) / 2.0)
                if length > 40:
                    dx = abs(p2[0] - p1[0])
                    dy = abs(p2[1] - p1[1])
                    is_axis_aligned = (dx <= 2.0) or (dy <= 2.0)
                    dashes = str(drawing.get("dashes", "")).strip()
                    is_dashed = bool(dashes and dashes != "[] 0")
                    if is_axis_aligned and is_dashed:
                        dashed_long_axis_lines += 1
            elif op in {"c", "v", "y", "qu"}:
                arc_candidates += 1
                arc_items.append(item)
    circle_candidates = sum(1 for item in arc_items if _arc_is_circular(item))
    adjacency: Dict[Tuple[int, int], int] = {}
    for p1, p2 in segments:
        adjacency[_quantize_point(p1)] = adjacency.get(_quantize_point(p1), 0) + 1
        adjacency[_quantize_point(p2)] = adjacency.get(_quantize_point(p2), 0) + 1
    connected_contour_groups = max(1, round(len(adjacency) / 8)) if adjacency else 0
    internal_loops = min(closed_profiles, max(0, circle_candidates + len([1 for degree in adjacency.values() if degree >= 4]) // 2))
    external_contours = max(0, closed_profiles - internal_loops)
    open_profiles = max(0, connected_contour_groups - closed_profiles)
    max_line_length_points = round(max(line_lengths), 2) if line_lengths else 0.0
    # ADDED: Sanity cap on extracted cut_length to prevent summing section views and borders.
    # If we have segment data, cap the total at 5× the perimeter of the max line extent.
    # This prevents cases like 2621-01C (actual ~500mm perimeter, extracted 8172pts from
    # summing section views and dimensions).
    raw_cut_length_points = sum(line_lengths) if line_lengths else 0.0
    if raw_cut_length_points > 0 and max_line_length_points > 0:
        # Estimate perimeter as ~4× the longest edge (rough heuristic for rectangular parts)
        estimated_perimeter_points = max_line_length_points * 4.0
        max_reasonable_cut_length = estimated_perimeter_points * 5.0  # Allow 5× for complexity
        if raw_cut_length_points > max_reasonable_cut_length:
            cut_length_points = min(raw_cut_length_points, max_reasonable_cut_length)
        else:
            cut_length_points = raw_cut_length_points
    else:
        cut_length_points = raw_cut_length_points
    symmetry_detected = False
    if len(midpoint_xs) >= 4:
        mean_x = sum(midpoint_xs) / len(midpoint_xs)
        mirrored = sum(1 for value in midpoint_xs if abs((2 * mean_x) - value - mean_x) <= 3.0)
        symmetry_detected = mirrored >= max(2, len(midpoint_xs) // 4)
    long_lines = sorted(line_lengths, reverse=True)
    collinear_groups = 1 if long_lines and sum(1 for value in long_lines[:6] if value >= long_lines[0] * 0.7) >= 3 else 0
    feature_clusters = max(1, internal_loops + circle_candidates + 1) if drawings else 0
    geometry_reliability = 0.0
    if closed_profiles >= 3 or len(segments) > 60 or arc_candidates > 0:
        geometry_reliability += 0.60
    if dashed_long_axis_lines > 0:
        geometry_reliability += 0.35
    if stroked_path_count > 0 and narrow_stroke_path_count < max(15, stroked_path_count * 0.75):
        geometry_reliability += 0.25
    geometry_reliability = round(min(1.0, geometry_reliability), 2)
    print(
        f"   [DEBUG] Geometry features: {total_paths} total paths | "
        f"Filtered by width: {filtered_by_width} | Kept: {kept_by_width} | "
        f"Reliability: {geometry_reliability}"
    )
    return {
        "connected_contour_groups": connected_contour_groups,
        "internal_loops": internal_loops,
        "external_contours": external_contours,
        "open_profiles": open_profiles,
        "closed_profiles": closed_profiles,
        "arc_candidates": arc_candidates,
        "circle_candidates": circle_candidates,
        "dashed_long_axis_lines": dashed_long_axis_lines,
        "collinear_groups": collinear_groups,
        "symmetry_detected": symmetry_detected,
        "feature_clusters": feature_clusters,
        "max_line_length_points": max_line_length_points,
        "estimated_cut_length_mm": cut_length_points,
        "confidence": {
            "geometry_reliability": geometry_reliability,
            "circle_candidates": round(0.6 * geometry_reliability, 2) if circle_candidates > 0 else 0.0,
            "bend_lines": round(0.7 * geometry_reliability, 2) if dashed_long_axis_lines > 0 else 0.0,
        },
    }
