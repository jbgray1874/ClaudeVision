from typing import Any, Dict, List



def _dedupe(values: List[Any]) -> List[Any]:
    seen: List[Any] = []
    for value in values:
        if value not in seen and value not in (None, "", []):
            seen.append(value)
    return seen



def merge_page_analysis(summary: Dict[str, Any], geometry_pages: List[Dict[str, Any]]) -> Dict[str, Any]:
    geo_lookup = {item["page_number"]: item for item in geometry_pages}
    for page in summary["pages"]:
        page_num = page["page_number"]
        page["geometry_summary"] = geo_lookup.get(page_num, {})
    return summary



def build_part_index(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    parts: Dict[str, Dict[str, Any]] = {}

    for row in summary.get("document_analysis", {}).get("bom_rows", []):
        pn = row["part_number"]
        parts[pn] = {
            "part_number": pn,
            "item_number": row.get("item_number"),
            "description": row.get("description"),
            "quantity": row.get("quantity", 1),
            "pages": [],
            "materials": [],
            "surface_finishes": [],
            "colours": [],
            "revisions": [],
            "drawing_numbers": [],
            "thicknesses_mm": [],
            "dates": [],
            "sheet_refs": [],
            "all_dimensions_mm": [],
            "angles_deg": [],
            "hole_sizes_mm": [],
            "radii_mm": [],
            "pitch_values_mm": [],
            "fold_values_mm": [],
            "flat_pattern_detected": False,
            "mirrored_detected": False,
            "hanging_hole_detected": False,
            "slot_detected": False,
            "textual_operations": [],
            "geometry_rollup": {
                "vector_path_count": 0,
                "line_segments": 0,
                "rectangles": 0,
                "curves": 0,
                "filled_paths": 0,
                "estimated_cut_length_mm": 0.0,
                "estimated_hole_count": 0,
                "estimated_circle_like_features": 0,
                "estimated_slot_like_features": 0,
                "estimated_bend_line_count": 0,
                "estimated_pierce_count": 0,
                "contour_complexity": 0,
            },
        }

    for page in summary["pages"]:
        page_part_numbers = page["pattern_summary"].get("part_numbers", [])
        page_analysis = page.get("page_analysis", {})
        title_block = page_analysis.get("title_block", {})
        cues = page_analysis.get("feature_cues", {})
        ops = page_analysis.get("inferred_operations", [])
        geometry = page.get("geometry_summary", {})

        for pn in page_part_numbers:
            if pn not in parts:
                parts[pn] = {
                    "part_number": pn,
                    "item_number": None,
                    "description": None,
                    "quantity": 1,
                    "pages": [],
                    "materials": [],
                    "surface_finishes": [],
                    "colours": [],
                    "revisions": [],
                    "drawing_numbers": [],
                    "thicknesses_mm": [],
                    "dates": [],
                    "sheet_refs": [],
                    "all_dimensions_mm": [],
                    "angles_deg": [],
                    "hole_sizes_mm": [],
                    "radii_mm": [],
                    "pitch_values_mm": [],
                    "fold_values_mm": [],
                    "flat_pattern_detected": False,
                    "mirrored_detected": False,
                    "hanging_hole_detected": False,
                    "slot_detected": False,
                    "textual_operations": [],
                    "geometry_rollup": {
                        "vector_path_count": 0,
                        "line_segments": 0,
                        "rectangles": 0,
                        "curves": 0,
                        "filled_paths": 0,
                        "estimated_cut_length_mm": 0.0,
                        "estimated_hole_count": 0,
                        "estimated_circle_like_features": 0,
                        "estimated_slot_like_features": 0,
                        "estimated_bend_line_count": 0,
                        "estimated_pierce_count": 0,
                        "contour_complexity": 0,
                    },
                }

            part = parts[pn]
            if page["page_number"] not in part["pages"]:
                part["pages"].append(page["page_number"])

            part["materials"].extend(title_block.get("materials", []))
            part["surface_finishes"].extend(title_block.get("surface_finishes", []))
            part["colours"].extend(title_block.get("colours", []))
            part["revisions"].extend(title_block.get("revisions", []))
            part["drawing_numbers"].extend(title_block.get("drawing_numbers", []))
            part["thicknesses_mm"].extend(title_block.get("thicknesses_mm", []))
            part["dates"].extend(title_block.get("dates", []))
            part["sheet_refs"].extend(title_block.get("sheet_refs", []))
            part["all_dimensions_mm"].extend(cues.get("all_dimensions_mm", []))
            part["angles_deg"].extend(cues.get("angles_deg", []))
            part["hole_sizes_mm"].extend(cues.get("hole_sizes_mm", []))
            part["radii_mm"].extend(cues.get("radii_mm", []))
            part["pitch_values_mm"].extend(cues.get("pitch_values_mm", []))
            part["fold_values_mm"].extend(cues.get("fold_values_mm", []))
            part["flat_pattern_detected"] = part["flat_pattern_detected"] or cues.get("flat_pattern_detected", False)
            part["mirrored_detected"] = part["mirrored_detected"] or cues.get("mirrored_detected", False)
            part["hanging_hole_detected"] = part["hanging_hole_detected"] or cues.get("hanging_hole_detected", False)
            part["slot_detected"] = part["slot_detected"] or cues.get("slot_detected", False)
            part["textual_operations"].extend(ops)

            rollup = part["geometry_rollup"]
            for key in rollup:
                rollup[key] += geometry.get(key, 0)

    result: List[Dict[str, Any]] = []
    for _, part in parts.items():
        for key in [
            "materials",
            "surface_finishes",
            "colours",
            "revisions",
            "drawing_numbers",
            "thicknesses_mm",
            "dates",
            "sheet_refs",
            "all_dimensions_mm",
            "angles_deg",
            "hole_sizes_mm",
            "radii_mm",
            "pitch_values_mm",
            "fold_values_mm",
            "textual_operations",
        ]:
            part[key] = _dedupe(part[key])
        result.append(part)

    return sorted(result, key=lambda item: item.get("part_number") or "")



def build_document_writeup(summary: Dict[str, Any]) -> Dict[str, Any]:
    parts = build_part_index(summary)
    observations: List[str] = []

    for part in parts:
        pn = part["part_number"]
        if part["flat_pattern_detected"]:
            observations.append(f"{pn}: flat pattern detected, likely profile or laser cutting required.")
        if part["hole_sizes_mm"] or part["geometry_rollup"]["estimated_hole_count"]:
            hole_sizes = ", ".join(part["hole_sizes_mm"]) or "geometry-derived hole features"
            observations.append(f"{pn}: hole features detected ({hole_sizes}).")
        if part["angles_deg"] or "folding" in part["textual_operations"]:
            observations.append(f"{pn}: fold or bend work indicated.")
        if part["surface_finishes"]:
            observations.append(f"{pn}: finish detected ({', '.join(part['surface_finishes'])}).")
        if part["materials"]:
            observations.append(f"{pn}: material detected ({', '.join(part['materials'])}).")
        if part["slot_detected"] or part["geometry_rollup"]["estimated_slot_like_features"]:
            observations.append(f"{pn}: slot-like geometry or text cues detected.")

    return {
        "document_overview": {
            "source_file": summary["source_file"],
            "page_count": summary["page_count"],
            "detected_labels": summary["detected_labels"],
            "pattern_summary": summary["pattern_summary"],
            "document_analysis": summary.get("document_analysis", {}),
        },
        "parts": parts,
        "manufacturing_observations": observations,
    }
