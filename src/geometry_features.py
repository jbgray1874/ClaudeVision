import math
from typing import Any, Dict, List, Tuple


def _distance(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    return math.hypot(p2[0] - p1[0], p2[1] - p1[1])


def _quantize_point(point: Tuple[float, float], tolerance: float = 1.0) -> Tuple[int, int]:
    return (round(point[0] / tolerance), round(point[1] / tolerance))


def analyse_vector_features(drawings: List[Dict[str, Any]]) -> Dict[str, Any]:
    segments: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
    circle_candidates = 0
    arc_candidates = 0
    closed_profiles = 0
    line_lengths: List[float] = []
    midpoint_xs: List[float] = []

    for drawing in drawings:
        if drawing.get("closePath"):
            closed_profiles += 1
        for item in drawing.get("items", []):
            op = item[0]
            if op == "l":
                p1 = (float(item[1].x), float(item[1].y))
                p2 = (float(item[2].x), float(item[2].y))
                segments.append((p1, p2))
                line_lengths.append(_distance(p1, p2))
                midpoint_xs.append((p1[0] + p2[0]) / 2.0)
            elif op in {"c", "v", "y", "qu"}:
                arc_candidates += 1

    if arc_candidates:
        circle_candidates = max(0, round(arc_candidates * 0.35))

    adjacency: Dict[Tuple[int, int], int] = {}
    for p1, p2 in segments:
        adjacency[_quantize_point(p1)] = adjacency.get(_quantize_point(p1), 0) + 1
        adjacency[_quantize_point(p2)] = adjacency.get(_quantize_point(p2), 0) + 1

    connected_contour_groups = max(1, round(len(adjacency) / 8)) if adjacency else 0
    internal_loops = min(closed_profiles, max(0, circle_candidates + len([1 for degree in adjacency.values() if degree >= 4]) // 2))
    external_contours = max(0, closed_profiles - internal_loops)
    open_profiles = max(0, connected_contour_groups - closed_profiles)
    max_line_length_points = round(max(line_lengths), 2) if line_lengths else 0.0

    symmetry_detected = False
    if len(midpoint_xs) >= 4:
        mean_x = sum(midpoint_xs) / len(midpoint_xs)
        mirrored = sum(1 for value in midpoint_xs if abs((2 * mean_x) - value - mean_x) <= 5.0)
        symmetry_detected = mirrored >= max(2, len(midpoint_xs) // 4)

    long_lines = sorted(line_lengths, reverse=True)
    collinear_groups = 1 if long_lines and sum(1 for value in long_lines[:6] if value >= long_lines[0] * 0.7) >= 3 else 0
    feature_clusters = max(1, internal_loops + circle_candidates + 1) if drawings else 0

    return {
        "connected_contour_groups": connected_contour_groups,
        "internal_loops": internal_loops,
        "external_contours": external_contours,
        "open_profiles": open_profiles,
        "closed_profiles": closed_profiles,
        "arc_candidates": arc_candidates,
        "circle_candidates": circle_candidates,
        "collinear_groups": collinear_groups,
        "symmetry_detected": symmetry_detected,
        "feature_clusters": feature_clusters,
        "max_line_length_points": max_line_length_points,
    }
