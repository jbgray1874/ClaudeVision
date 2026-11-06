"""
Merge flat-pattern DXF geometry into PDF scan summaries.

Policy:
  - DXF wins: area/extents, cut length, holes, bends, geometry reliability.
  - PDF wins: BOM, quantities, materials, finish, client, revision, assembly structure.
  - No matching DXF: PDF geometry unchanged (typically ~0.97 reliability, not 1.0).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import config
from document_builder import _empty_geometry_rollup, _interpret_part, _rollup_geometry
from dxf_reader import (
    analyse_dxf_document_geometry,
    extract_dxf_geometry,
    extract_dxf_pages,
    extract_flat_pattern_data,
    is_dxf_path,
)

try:
    from dxf_reader import _parse_filename
except ImportError:
    _parse_filename = None  # type: ignore

from estimator import estimate_document


def _normalize_part_key(part_number: str) -> str:
    return re.sub(r"\s+", "", str(part_number or "")).upper()


def part_number_from_dxf_path(path: Path) -> Optional[str]:
    """Extract BOM part number from a flat DXF filename (e.g. 9376-01-001)."""
    if _parse_filename is not None:
        try:
            parsed = _parse_filename(path)
            if parsed.get("part_number"):
                return str(parsed["part_number"]).upper().replace(" ", "")
        except Exception:
            pass
    stem = path.stem.upper().replace("_", "-")
    cfg = getattr(config, "DRAWING_JOB_DISCOVERY", {}) or {}
    patterns: Sequence[str] = cfg.get(
        "part_number_from_dxf_patterns",
        [r"(?P<pn>\d{4,5}-\d{2}-\d{3}[A-Z]?)"],
    )
    for pattern in patterns:
        match = re.search(pattern, stem, flags=re.IGNORECASE)
        if match:
            return match.group("pn").upper().replace(" ", "")
    return None


def job_prefix_from_path(path: Path) -> Optional[str]:
    """Job family prefix such as 9376-01 from drawing or DXF names."""
    match = re.search(r"(\d{4,5}-\d{2})\b", path.stem, flags=re.IGNORECASE)
    return match.group(1).upper() if match else None


def is_ignored_ga_dxf(path: Path) -> bool:
    """GA / assembly sheet DXFs are not flat-pattern geometry sources."""
    name = path.name.upper()
    if "-GA_" in name or "_GA_" in name:
        return True
    if re.search(r"[-_]GA[-_.]", name, flags=re.IGNORECASE):
        return True
    cfg = getattr(config, "DRAWING_JOB_DISCOVERY", {}) or {}
    for token in cfg.get("ignore_dxf_name_tokens", ["-GA-", "_GA_"]):
        if token.upper() in name:
            return True
    return False


def is_flat_part_dxf(path: Path) -> bool:
    return is_dxf_path(path) and not is_ignored_ga_dxf(path) and bool(part_number_from_dxf_path(path))


def thickness_mm_from_dxf_filename(path: Path) -> Optional[float]:
    if _parse_filename is not None:
        try:
            parsed = _parse_filename(path)
            if parsed.get("thickness_mm") is not None:
                return float(parsed["thickness_mm"])
        except Exception:
            pass
    stem_norm = re.sub(
        r"(\d+)_(\d+mm)",
        lambda m: f"{m.group(1)}.{m.group(2)}",
        path.stem,
        flags=re.IGNORECASE,
    )
    match = re.search(r"(\d+(?:\.\d+)?)mm", stem_norm, flags=re.IGNORECASE)
    if match:
        return float(match.group(1))
    return None


def build_geometry_summary_for_dxf(dxf_path: Path) -> Tuple[Dict[str, Any], Dict[str, Any], float]:
    pages = extract_dxf_pages(dxf_path)
    geo_results = analyse_dxf_document_geometry(pages, dxf_path)
    page0 = (geo_results.get("pages") or [{}])[0]
    geometry = page0.get("geometry", {}) if isinstance(page0, dict) else {}
    reliability = float(
        (geometry.get("confidence") or {}).get("geometry_reliability", 0.0)
        or geo_results.get("document_geometry_reliability", 0.0)
        or 0.0
    )
    raw = extract_dxf_geometry(dxf_path)
    return geometry, raw, reliability


def apply_dxf_geometry_to_part(part: Dict[str, Any], dxf_path: Path) -> Dict[str, Any]:
    """
    Augment a part dict with DXF geometry.

    Priority:
      1. extract_flat_pattern_data — exact area, perimeter, weight, bends
         (geometry_score = 1.0, geometry_source = dxf_flat_pattern)
      2. build_geometry_summary_for_dxf — bbox extents, geometry rollup
         (fallback when flat-pattern detection fails)
    """
    geometry, raw, reliability = build_geometry_summary_for_dxf(dxf_path)
    part["geometry_rollup"] = _empty_geometry_rollup()
    _rollup_geometry(part["geometry_rollup"], geometry)

    flat: Optional[Dict[str, Any]] = None
    try:
        flat = extract_flat_pattern_data(dxf_path)
    except Exception:
        flat = None

    if flat and flat.get("flat_pattern_detected") and float(flat.get("blank_area_mm2") or 0) > 0:
        ng = part.get("normalized_geometry") or {}
        ng.update({
            "blank_length_mm": flat["blank_length_mm"],
            "blank_width_mm": flat["blank_width_mm"],
            "blank_area_mm2": flat["blank_area_mm2"],
            "perimeter_mm": flat["perimeter_mm"],
            "weight_kg": flat["weight_kg"],
            "weight_g": flat["weight_g"],
            "geometry_source": "dxf_flat_pattern",
            "geometry_confidence": 1.0,
        })
        part["normalized_geometry"] = ng
        part["geometry_score"] = 1.0
        part["flat_pattern_detected"] = True
        part["overall_length_mm"] = flat["blank_length_mm"]
        part["overall_width_mm"] = flat["blank_width_mm"]
        reliability = 1.0

        if flat.get("thickness_mm") and part.get("normalized_thickness_mm") is None:
            part["normalized_thickness_mm"] = flat["thickness_mm"]
            if not part.get("thicknesses_mm"):
                part["thicknesses_mm"] = [str(flat["thickness_mm"])]

        if flat.get("material_from_filename") and not part.get("normalized_material"):
            part["normalized_material"] = flat["material_from_filename"]

        weight_g = float(flat.get("weight_g") or 0.0)
        if weight_g > 0:
            weight_label = f"{weight_g:.2f}g"
            weights = list(part.get("weights") or [])
            if weight_label not in weights:
                weights.append(weight_label)
            part["weights"] = weights
            part["dxf_weight_g"] = weight_g
            part["dxf_weight_kg"] = float(flat.get("weight_kg") or weight_g / 1000.0)

        if flat.get("bend_count", 0) > 0:
            part["bend_count_dxf"] = flat["bend_count"]
            part["flange_lengths_mm"] = flat["flange_lengths_mm"]
            part["bend_positions_mm"] = flat["bend_positions_mm"]
            part["symmetric_flanges"] = flat.get("symmetric_flanges", False)
            part["fold_count_textual"] = max(part.get("fold_count_textual", 0), int(flat["bend_count"]))

        if flat.get("corner_notch_count", 0) > 0:
            part["corner_notch_count"] = flat["corner_notch_count"]
            part["notch_length_mm"] = flat.get("notch_length_mm")

        if flat.get("hole_diameters_mm"):
            existing = [float(h) for h in part.get("hole_sizes_mm", []) if h is not None]
            part["hole_sizes_mm"] = sorted(set(existing + [float(h) for h in flat["hole_diameters_mm"]]))

        dxf_raw = {
            "estimated_cut_length_mm": flat["perimeter_mm"],
            "blank_area_mm2": flat["blank_area_mm2"],
            "weight_kg": flat["weight_kg"],
            "drawing_extents_mm": [flat["blank_length_mm"], flat["blank_width_mm"]],
            "estimated_hole_count": flat["hole_count"],
            "estimated_bend_line_count": flat["bend_count"],
            "estimated_pierce_count": raw.get("estimated_pierce_count"),
        }
    else:
        extents = raw.get("drawing_extents_mm") or []
        if isinstance(extents, (list, tuple)) and len(extents) >= 2:
            a = float(extents[0] or 0)
            b = float(extents[1] or 0)
            if a > 0 and b > 0:
                length, width = sorted([a, b], reverse=True)
                part["overall_length_mm"] = length
                part["overall_width_mm"] = width
                part["flat_pattern_detected"] = True

        thk = thickness_mm_from_dxf_filename(dxf_path)
        if thk is not None and part.get("normalized_thickness_mm") is None:
            part["normalized_thickness_mm"] = thk
            if not part.get("thicknesses_mm"):
                part["thicknesses_mm"] = [str(thk)]

        holes = raw.get("hole_diameters_mm") or geometry.get("hole_diameters_mm") or []
        if holes:
            existing = [float(h) for h in part.get("hole_sizes_mm", []) if h is not None]
            part["hole_sizes_mm"] = sorted(set(existing + [float(h) for h in holes]))

        dxf_raw = {
            "estimated_cut_length_mm": raw.get("estimated_cut_length_mm"),
            "blank_area_mm2": None,
            "weight_kg": None,
            "drawing_extents_mm": list(extents) if extents else [],
            "estimated_hole_count": raw.get("estimated_hole_count"),
            "estimated_bend_line_count": raw.get("estimated_bend_line_count"),
            "estimated_pierce_count": raw.get("estimated_pierce_count"),
        }

    part["geometry_source"] = (
        "dxf_flat_pattern" if (flat and flat.get("flat_pattern_detected")) else "dxf"
    )
    part["geometry_source_path"] = str(dxf_path.resolve())
    part["dxf_augmented"] = True
    part["dxf_geometry_reliability"] = reliability
    part["dxf_raw_geometry"] = dxf_raw

    _interpret_part(part)
    return part


def _lookup_part(parts_by_key: Dict[str, Dict[str, Any]], part_number: str) -> Optional[Dict[str, Any]]:
    key = _normalize_part_key(part_number)
    if key in parts_by_key:
        return parts_by_key[key]
    suffix = key.split("-")[-1]
    for candidate_key, part in parts_by_key.items():
        if candidate_key.endswith(suffix) or candidate_key.replace("-", "") == key.replace("-", ""):
            return part
    return None


def augment_summary_with_dxf(
    summary: Dict[str, Any],
    dxf_paths: Sequence[Path],
    *,
    reestimate: bool = True,
) -> Dict[str, Any]:
    writeup = summary.get("manufacturing_writeup") or {}
    parts: List[Dict[str, Any]] = writeup.get("parts") or []
    parts_by_key = {_normalize_part_key(p.get("part_number", "")): p for p in parts if p.get("part_number")}

    report: Dict[str, Any] = {
        "matched": [],
        "unmatched_dxf": [],
        "skipped": [],
        "parts_without_dxf": [],
    }

    matched_keys: set[str] = set()

    for dxf_path in dxf_paths:
        path = Path(dxf_path)
        if not path.is_file():
            report["skipped"].append({"path": str(path), "reason": "missing_file"})
            continue
        if not is_dxf_path(path):
            report["skipped"].append({"path": str(path), "reason": "not_dxf"})
            continue
        if is_ignored_ga_dxf(path):
            report["skipped"].append({"path": str(path), "reason": "ga_dxf_ignored"})
            continue

        pn = part_number_from_dxf_path(path)
        if not pn:
            report["unmatched_dxf"].append({"path": str(path), "reason": "no_part_number_in_filename"})
            continue

        part = _lookup_part(parts_by_key, pn)
        if not part:
            report["unmatched_dxf"].append({"path": str(path), "part_number": pn, "reason": "no_bom_part"})
            continue

        apply_dxf_geometry_to_part(part, path)
        matched_keys.add(_normalize_part_key(part.get("part_number", pn)))
        dxf_raw = part.get("dxf_raw_geometry") or {}
        report["matched"].append(
            {
                "part_number": part.get("part_number"),
                "dxf": str(path.resolve()),
                "geometry_reliability": part.get("dxf_geometry_reliability"),
                "geometry_source": part.get("geometry_source"),
                "blank_area_mm2": dxf_raw.get("blank_area_mm2"),
                "weight_kg": dxf_raw.get("weight_kg"),
                "weight_g": part.get("dxf_weight_g"),
                "bend_count_dxf": part.get("bend_count_dxf"),
            }
        )

    for key, part in parts_by_key.items():
        if key not in matched_keys and part.get("geometry_rollup", {}).get("confidence", {}).get(
            "geometry_reliability", 0
        ):
            report["parts_without_dxf"].append(
                {
                    "part_number": part.get("part_number"),
                    "geometry_reliability": (part.get("geometry_rollup", {}).get("confidence") or {}).get(
                        "geometry_reliability"
                    ),
                }
            )

    summary["dxf_augmentation"] = report
    summary["geometry_source_policy"] = "dxf_wins_geometry_pdf_wins_bom"

    if reestimate:
        summary["estimate_summary"] = estimate_document(parts, summary=summary)

    return summary


def discover_flat_dxf_files(
    pdf_path: Path,
    *,
    part_numbers: Optional[Sequence[str]] = None,
    extra_roots: Optional[Sequence[Path]] = None,
) -> List[Path]:
    cfg = getattr(config, "DRAWING_JOB_DISCOVERY", {}) or {}
    if not cfg.get("enabled", True):
        return []

    job_prefix = job_prefix_from_path(pdf_path)
    pn_set = {_normalize_part_key(p) for p in (part_numbers or []) if p}

    roots: List[Path] = [pdf_path.parent]
    subdir = cfg.get("dxf_subdir", "DXF")
    if subdir:
        roots.append(pdf_path.parent / subdir)
    roots.append(config.DRAWINGS_DIR)
    if subdir:
        roots.append(config.DRAWINGS_DIR / subdir)
    if extra_roots:
        roots.extend(extra_roots)

    glob_pat = cfg.get("flat_dxf_glob", "*.[Dd][Xx][Ff]")
    found: Dict[str, Path] = {}

    for root in roots:
        if not root.exists():
            continue
        for path in root.glob(glob_pat):
            if not path.is_file() or not is_flat_part_dxf(path):
                continue
            pn = part_number_from_dxf_path(path)
            if not pn:
                continue
            pn_key = _normalize_part_key(pn)
            if job_prefix and not pn_key.startswith(_normalize_part_key(job_prefix)):
                if pn_set and pn_key not in pn_set:
                    continue
            found[str(path.resolve())] = path

    return sorted(found.values(), key=lambda p: p.name.lower())


def collect_dxf_paths_for_pdf_scan(
    pdf_path: Path,
    summary: Dict[str, Any],
    *,
    attach_dxf_paths: Optional[Sequence[Path]] = None,
    auto_discover_dxf: bool = True,
) -> List[Path]:
    paths: Dict[str, Path] = {}
    for raw in attach_dxf_paths or []:
        path = Path(raw)
        if path.is_file():
            paths[str(path.resolve())] = path

    if auto_discover_dxf:
        part_numbers = [
            p.get("part_number")
            for p in (summary.get("manufacturing_writeup") or {}).get("parts", [])
            if p.get("part_number")
        ]
        for path in discover_flat_dxf_files(pdf_path, part_numbers=part_numbers):
            paths[str(path.resolve())] = path

    return sorted(paths.values(), key=lambda p: p.name.lower())


def merge_dxf_into_json_file(
    json_path: Path,
    dxf_paths: Sequence[Path],
    *,
    output_path: Optional[Path] = None,
    reestimate: bool = True,
) -> Path:
    import json

    with json_path.open("r", encoding="utf-8") as handle:
        summary = json.load(handle)

    summary = augment_summary_with_dxf(summary, dxf_paths, reestimate=reestimate)
    from json_normaliser import normalise_json

    summary = normalise_json(summary)

    out = output_path or json_path
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, default=str)
    return out
