from pathlib import Path
from typing import Any, Dict, List, Optional

from extractor_patterns import normalize_text


def _dedupe(values: List[Any]) -> List[Any]:
    seen: List[Any] = []
    for value in values:
        if value not in (None, "", []) and value not in seen:
            seen.append(value)
    return seen


def _safe_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_dimension_values(values: List[Any]) -> List[float]:
    cleaned: List[float] = []
    for value in values:
        number = _safe_float(value)
        if number is None:
            continue
        if number < 1.0:
            continue
        if number > 10000:
            continue
        cleaned.append(round(number, 3))
    return _dedupe(cleaned)


def _summarize_part(part: Dict[str, Any]) -> Dict[str, Any]:
    geometry = part.get("geometry_rollup", {})
    dimensions = _clean_dimension_values(part.get("all_dimensions_mm", []))

    return {
        "part_number": part.get("part_number"),
        "description": part.get("description"),
        "quantity": part.get("quantity"),
        "page_roles": _dedupe(part.get("page_roles", [])),
        "pages": part.get("pages", []),
        "materials": _dedupe(part.get("materials", [])),
        "thicknesses_mm": _clean_dimension_values(part.get("thicknesses_mm", [])),
        "surface_finishes": _dedupe(part.get("surface_finishes", [])),
        "colours": _dedupe(part.get("colours", [])),
        "revisions": _dedupe(part.get("revisions", [])),
        "drawing_numbers": _dedupe(part.get("drawing_numbers", [])),
        "overall_length_mm": _safe_float(part.get("overall_length_mm")),
        "overall_width_mm": _safe_float(part.get("overall_width_mm")),
        "overall_sizes_mm": _dedupe(part.get("overall_sizes_mm", [])),
        "classified_dimensions_mm": dimensions,
        "angles_deg": _clean_dimension_values(part.get("angles_deg", [])),
        "hole_sizes_mm": _clean_dimension_values(part.get("hole_sizes_mm", [])),
        "slot_sizes_mm": _dedupe(part.get("slot_sizes_mm", [])),
        "radii_mm": _clean_dimension_values(part.get("radii_mm", [])),
        "pitch_values_mm": _clean_dimension_values(part.get("pitch_values_mm", [])),
        "fold_values_mm": _clean_dimension_values(part.get("fold_values_mm", [])),
        "process_notes": _dedupe(part.get("process_notes", [])),
        "process_note_types": _dedupe(part.get("process_note_types", [])),
        "operations": _dedupe(part.get("textual_operations", [])),
        "flat_pattern_detected": bool(part.get("flat_pattern_detected")),
        "mirrored_detected": bool(part.get("mirrored_detected")),
        "slot_detected": bool(part.get("slot_detected")),
        "hanging_hole_detected": bool(part.get("hanging_hole_detected")),
        "assembly_candidate": bool(part.get("assembly_candidate")),
        "geometry_summary": {
            "estimated_cut_length_mm": geometry.get("estimated_cut_length_mm"),
            "estimated_hole_count": geometry.get("estimated_hole_count"),
            "estimated_slot_like_features": geometry.get("estimated_slot_like_features"),
            "estimated_bend_line_count": geometry.get("estimated_bend_line_count"),
            "estimated_pierce_count": geometry.get("estimated_pierce_count"),
            "contour_complexity": geometry.get("contour_complexity"),
        },
    }


def _build_retrieval_text(record: Dict[str, Any]) -> str:
    parts = record.get("parts", [])
    doc = record.get("document", {})

    fragments: List[str] = [
        record.get("job_key", ""),
        doc.get("source_file", ""),
        " ".join(doc.get("drawing_numbers", [])),
        " ".join(doc.get("revisions", [])),
        " ".join(doc.get("materials", [])),
        " ".join(doc.get("surface_finishes", [])),
        " ".join(doc.get("part_numbers", [])),
        " ".join(doc.get("manufacturing_observations", [])),
    ]

    for part in parts:
        fragments.extend(
            [
                str(part.get("part_number", "")),
                str(part.get("description", "")),
                " ".join(part.get("materials", [])),
                " ".join(str(value) for value in part.get("thicknesses_mm", [])),
                " ".join(str(value) for value in part.get("hole_sizes_mm", [])),
                " ".join(str(value) for value in part.get("angles_deg", [])),
                " ".join(part.get("operations", [])),
                " ".join(part.get("process_notes", [])),
            ]
        )

    return normalize_text(" ".join(fragment for fragment in fragments if fragment))[:12000]


def transform_scan_summary_to_historical_job_record(
    summary: Dict[str, Any],
    spreadsheet_analysis: Optional[Dict[str, Any]] = None,
    job_key: Optional[str] = None,
) -> Dict[str, Any]:
    document_analysis = summary.get("document_analysis", {})
    title_block = document_analysis.get("title_block", {})
    manufacturing_writeup = summary.get("manufacturing_writeup", {})
    estimate_summary = summary.get("estimate_summary", {})

    parts = [_summarize_part(part) for part in manufacturing_writeup.get("parts", [])]

    record = {
        "schema_version": "historical_job_record.v1",
        "job_key": job_key or Path(summary.get("source_file", "job")).stem,
        "document": {
            "source_file": summary.get("source_file"),
            "full_path": summary.get("full_path"),
            "page_count": summary.get("page_count"),
            "scanned_at": summary.get("scanned_at"),
            "drawing_numbers": _dedupe(title_block.get("drawing_numbers", [])),
            "revisions": _dedupe(title_block.get("revisions", [])),
            "dates": _dedupe(title_block.get("dates", [])),
            "materials": _dedupe(title_block.get("materials", [])),
            "surface_finishes": _dedupe(title_block.get("surface_finishes", [])),
            "colours": _dedupe(title_block.get("colours", [])),
            "part_numbers": _dedupe(summary.get("pattern_summary", {}).get("part_numbers", [])),
            "bom_rows": document_analysis.get("bom_rows", []),
            "page_roles": _dedupe(
                [page.get("page_role", {}).get("primary_role") for page in summary.get("pages", []) if page.get("page_role")]
            ),
            "manufacturing_observations": manufacturing_writeup.get("manufacturing_observations", []),
            "estimated_document_total_gbp": estimate_summary.get("document_total_estimated_cost_gbp"),
        },
        "parts": parts,
        "spreadsheet_context": spreadsheet_analysis or None,
        "retrieval_fields": {
            "part_numbers": _dedupe(summary.get("pattern_summary", {}).get("part_numbers", [])),
            "materials": _dedupe([material for part in parts for material in part.get("materials", [])]),
            "thicknesses_mm": _dedupe([value for part in parts for value in part.get("thicknesses_mm", [])]),
            "operations": _dedupe([operation for part in parts for operation in part.get("operations", [])]),
            "estimated_total_cost_gbp": estimate_summary.get("document_total_estimated_cost_gbp"),
            "surface_finishes": _dedupe([finish for part in parts for finish in part.get("surface_finishes", [])]),
        },
    }
    record["retrieval_text"] = _build_retrieval_text(record)
    return record
