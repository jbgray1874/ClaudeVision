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
        page["geometry_summary"] = geo_lookup.get(page["page_number"], {})
    return summary


def _empty_geometry_rollup() -> Dict[str, Any]:
    return {
        "vector_path_count": 0,
        "line_segments": 0,
        "rectangles": 0,
        "curves": 0,
        "filled_paths": 0,
        "approx_total_line_length_points": 0.0,
        "approx_total_curve_length_points": 0.0,
        "estimated_cut_length_mm": 0.0,
        "estimated_hole_count": 0,
        "estimated_circle_like_features": 0,
        "estimated_slot_like_features": 0,
        "estimated_bend_line_count": 0,
        "estimated_pierce_count": 0,
        "contour_complexity": 0,
    }


def _empty_part_record(part_number: str, item_number: Any = None, description: Any = None, quantity: Any = 1) -> Dict[str, Any]:
    return {
        "part_number": part_number,
        "item_number": item_number,
        "description": description,
        "quantity": quantity,
        "pages": [],
        "page_roles": [],
        "materials": [],
        "surface_finishes": [],
        "colours": [],
        "revisions": [],
        "drawing_numbers": [],
        "thicknesses_mm": [],
        "dates": [],
        "sheet_refs": [],
        "scales": [],
        "clients": [],
        "project_titles": [],
        "all_dimensions_mm": [],
        "overall_sizes_mm": [],
        "overall_length_mm": None,
        "overall_width_mm": None,
        "angles_deg": [],
        "hole_sizes_mm": [],
        "radii_mm": [],
        "pitch_values_mm": [],
        "fold_values_mm": [],
        "slot_sizes_mm": [],
        "edge_distances_mm": [],
        "process_notes": [],
        "process_note_types": [],
        "flat_pattern_detected": False,
        "mirrored_detected": False,
        "hanging_hole_detected": False,
        "slot_detected": False,
        "assembly_candidate": False,
        "textual_operations": [],
        "geometry_rollup": _empty_geometry_rollup(),
    }


def _rollup_geometry(target: Dict[str, Any], geometry: Dict[str, Any]) -> None:
    for key in target:
        target[key] += geometry.get(key, 0)


def build_part_index(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    parts: Dict[str, Dict[str, Any]] = {}

    for row in summary.get("document_analysis", {}).get("bom_rows", []):
        pn = row["part_number"]
        parts[pn] = _empty_part_record(
            part_number=pn,
            item_number=row.get("item_number"),
            description=row.get("description"),
            quantity=row.get("quantity", 1),
        )

    for page in summary["pages"]:
        page_part_numbers = page["pattern_summary"].get("part_numbers", [])
        page_analysis = page.get("page_analysis", {})
        title_block = page_analysis.get("title_block", {})
        dimensions = page_analysis.get("dimensions", {})
        cues = page_analysis.get("feature_cues", {})
        process_notes = page_analysis.get("process_notes", {})
        ops = page_analysis.get("inferred_operations", [])
        geometry = page.get("geometry_summary", {})
        page_role = page.get("page_role", {}).get("primary_role")

        for pn in page_part_numbers:
            if pn not in parts:
                parts[pn] = _empty_part_record(part_number=pn)

            part = parts[pn]
            if page["page_number"] not in part["pages"]:
                part["pages"].append(page["page_number"])
            if page_role:
                part["page_roles"].append(page_role)

            part["materials"].extend(title_block.get("materials", []))
            part["surface_finishes"].extend(title_block.get("surface_finishes", []))
            part["colours"].extend(title_block.get("colours", []))
            part["revisions"].extend(title_block.get("revisions", []))
            part["drawing_numbers"].extend(title_block.get("drawing_numbers", []))
            part["thicknesses_mm"].extend(title_block.get("thicknesses_mm", []))
            part["dates"].extend(title_block.get("dates", []))
            part["sheet_refs"].extend(title_block.get("sheet_refs", []))
            part["scales"].extend(title_block.get("scale", []))
            part["clients"].extend(title_block.get("clients", []))
            part["project_titles"].extend(title_block.get("project_titles", []))
            part["overall_sizes_mm"].extend(dimensions.get("overall_sizes_mm", []))
            part["all_dimensions_mm"].extend(dimensions.get("all_dimensions_mm", []))
            part["angles_deg"].extend(cues.get("angles_deg", []))
            part["hole_sizes_mm"].extend(cues.get("hole_sizes_mm", []))
            part["radii_mm"].extend(cues.get("radii_mm", []))
            part["pitch_values_mm"].extend(cues.get("pitch_values_mm", []))
            part["fold_values_mm"].extend(cues.get("fold_values_mm", []))
            part["slot_sizes_mm"].extend(cues.get("slot_sizes_mm", []))
            part["edge_distances_mm"].extend(cues.get("edge_distances_mm", []))
            part["process_notes"].extend(process_notes.get("note_snippets", []))
            part["process_note_types"].extend(process_notes.get("detected_note_types", []))
            part["flat_pattern_detected"] = part["flat_pattern_detected"] or cues.get("flat_pattern_detected", False)
            part["mirrored_detected"] = part["mirrored_detected"] or cues.get("mirrored_detected", False)
            part["hanging_hole_detected"] = part["hanging_hole_detected"] or cues.get("hanging_hole_detected", False)
            part["slot_detected"] = part["slot_detected"] or cues.get("slot_detected", False)
            part["assembly_candidate"] = part["assembly_candidate"] or page_role == "assembly"
            part["textual_operations"].extend(ops)

            if part["description"] is None:
                descriptions = title_block.get("descriptions", [])
                if descriptions:
                    part["description"] = descriptions[0]

            if part["quantity"] in (None, 1):
                quantities = title_block.get("quantities", [])
                if quantities:
                    try:
                        part["quantity"] = int(quantities[0])
                    except (TypeError, ValueError):
                        pass

            if part["overall_length_mm"] is None and dimensions.get("overall_length_mm") is not None:
                part["overall_length_mm"] = dimensions["overall_length_mm"]
            if part["overall_width_mm"] is None and dimensions.get("overall_width_mm") is not None:
                part["overall_width_mm"] = dimensions["overall_width_mm"]

            _rollup_geometry(part["geometry_rollup"], geometry)

    result: List[Dict[str, Any]] = []
    for part in parts.values():
        for key in [
            "page_roles",
            "materials",
            "surface_finishes",
            "colours",
            "revisions",
            "drawing_numbers",
            "thicknesses_mm",
            "dates",
            "sheet_refs",
            "scales",
            "clients",
            "project_titles",
            "all_dimensions_mm",
            "overall_sizes_mm",
            "angles_deg",
            "hole_sizes_mm",
            "radii_mm",
            "pitch_values_mm",
            "fold_values_mm",
            "slot_sizes_mm",
            "edge_distances_mm",
            "process_notes",
            "process_note_types",
            "textual_operations",
        ]:
            part[key] = _dedupe(part[key])
        result.append(part)

    return sorted(result, key=lambda item: item.get("part_number") or "")


def build_document_writeup(summary: Dict[str, Any]) -> Dict[str, Any]:
    parts = build_part_index(summary)
    observations: List[str] = []
    assembly_pages = [page["page_number"] for page in summary["pages"] if page.get("page_role", {}).get("primary_role") == "assembly"]
    detail_pages = [page["page_number"] for page in summary["pages"] if page.get("page_role", {}).get("primary_role") == "detail"]

    assembly_relations = {
        "assembly_pages": assembly_pages,
        "detail_pages": detail_pages,
        "bom_part_numbers": [row["part_number"] for row in summary.get("document_analysis", {}).get("bom_rows", [])],
        "mirrored_parts": [part["part_number"] for part in parts if part.get("mirrored_detected")],
    }

    for part in parts:
        pn = part["part_number"]
        if part["flat_pattern_detected"]:
            observations.append(f"{pn}: flat pattern detected, likely laser or profile cutting required.")
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
        if part["process_notes"]:
            observations.append(f"{pn}: process notes detected ({'; '.join(part['process_notes'][:3])}).")

    return {
        "document_overview": {
            "source_file": summary["source_file"],
            "page_count": summary["page_count"],
            "detected_labels": summary["detected_labels"],
            "pattern_summary": summary["pattern_summary"],
            "document_analysis": summary.get("document_analysis", {}),
        },
        "assembly_relations": assembly_relations,
        "parts": parts,
        "manufacturing_observations": observations,
    }
