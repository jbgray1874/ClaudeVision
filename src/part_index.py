from dataclasses import dataclass
from typing import Any, Callable, Dict, List


@dataclass(frozen=True)
class PartIndexDeps:
    dedupe: Callable[..., Any]
    is_valid_part_identifier: Callable[..., Any]
    empty_part_record: Callable[..., Any]
    is_component_sheet: Callable[..., Any]
    effective_part_page_role: Callable[..., Any]
    prefer_local_title_block_values: Callable[..., Any]
    prefer_local_scalar: Callable[..., Any]
    is_good_description: Callable[..., Any]
    should_assign_dimensions: Callable[..., Any]
    pick_part_dimensions: Callable[..., Any]
    first_numeric_thickness: Callable[..., Any]
    rollup_geometry: Callable[..., Any]
    clean_finish_values: Callable[..., Any]
    is_assembly_identifier: Callable[..., Any]
    interpret_part: Callable[..., Any]


def build_part_index(summary: Dict[str, Any], deps: PartIndexDeps) -> List[Dict[str, Any]]:
    dedupe = deps.dedupe
    is_valid_part_identifier = deps.is_valid_part_identifier
    empty_part_record = deps.empty_part_record
    is_component_sheet = deps.is_component_sheet
    effective_part_page_role = deps.effective_part_page_role
    prefer_local_title_block_values = deps.prefer_local_title_block_values
    prefer_local_scalar = deps.prefer_local_scalar
    is_good_description = deps.is_good_description
    should_assign_dimensions = deps.should_assign_dimensions
    pick_part_dimensions = deps.pick_part_dimensions
    first_numeric_thickness = deps.first_numeric_thickness
    rollup_geometry = deps.rollup_geometry
    clean_finish_values = deps.clean_finish_values
    is_assembly_identifier = deps.is_assembly_identifier
    interpret_part = deps.interpret_part

    parts: Dict[str, Dict[str, Any]] = {}
    document_bom_lookup = {
        row["part_number"]: row
        for row in summary.get("document_analysis", {}).get("bom_rows", [])
        if is_valid_part_identifier(row.get("part_number"))
    }
    document_primary_thickness = summary.get("document_analysis", {}).get("primary_fields", {}).get("thickness_mm")

    for row in summary.get("document_analysis", {}).get("bom_rows", []):
        pn = row["part_number"]
        if not is_valid_part_identifier(pn):
            continue
        parts[pn] = empty_part_record(
            part_number=pn,
            item_number=row.get("item_number"),
            description=row.get("description"),
            quantity=row.get("quantity", 1),
        )

    for page in summary["pages"]:
        page_analysis = page.get("page_analysis", {})
        title_block = page_analysis.get("title_block", {})
        dimensions = page_analysis.get("dimensions", {})
        cues = page_analysis.get("feature_cues", {})
        process_notes = page_analysis.get("process_notes", {})
        review_flags = page_analysis.get("review_flags", [])
        confidence = page_analysis.get("confidence", {})
        ops = page_analysis.get("inferred_operations", [])
        geometry = page.get("geometry_summary", {})
        page_role = page.get("page_role", {}).get("primary_role")
        page_part_numbers = page.get("page_analysis", {}).get("title_block", {}).get("part_numbers", []) or page["pattern_summary"].get("part_numbers", [])
        title_block_drawing_numbers = title_block.get("drawing_numbers", [])
        page_target_part_numbers: List[str] = []

        if page_role == "detail":
            page_target_part_numbers.extend(
                [value for value in title_block_drawing_numbers if is_valid_part_identifier(value)]
            )
            if not page_target_part_numbers:
                page_target_part_numbers.extend(
                    [value for value in page_part_numbers if is_valid_part_identifier(value)]
                )
        else:
            if len(title_block_drawing_numbers) == 1 and is_valid_part_identifier(title_block_drawing_numbers[0]):
                page_target_part_numbers.extend(title_block_drawing_numbers)

        page_target_part_numbers = dedupe(page_target_part_numbers)
        component_sheet = is_component_sheet(page_role, title_block, page_target_part_numbers, cues, ops)
        effective_page_role = effective_part_page_role(page_role, title_block_drawing_numbers, component_sheet)

        for pn in page_target_part_numbers:
            if not is_valid_part_identifier(pn):
                continue
            if pn not in parts:
                parts[pn] = empty_part_record(part_number=pn)

            part = parts[pn]
            if page["page_number"] not in part["pages"]:
                part["pages"].append(page["page_number"])
            if effective_page_role:
                part["page_roles"].append(effective_page_role)

            allow_local_component_data = bool(component_sheet)
            part["materials"].extend(prefer_local_title_block_values(effective_page_role, title_block.get("materials", []), allow_on_assembly=allow_local_component_data))
            part["surface_finishes"].extend(prefer_local_title_block_values(effective_page_role, title_block.get("surface_finishes", []), allow_on_assembly=allow_local_component_data))
            part["colours"].extend(prefer_local_title_block_values(effective_page_role, title_block.get("colours", []), allow_on_assembly=allow_local_component_data))
            part["revisions"].extend(prefer_local_title_block_values(effective_page_role, title_block.get("revisions", []), allow_on_assembly=True))
            part["drawing_numbers"].extend(
                [value for value in prefer_local_title_block_values(effective_page_role, title_block.get("drawing_numbers", []), allow_on_assembly=True) if is_valid_part_identifier(value)]
            )
            part["thicknesses_mm"].extend(prefer_local_title_block_values(effective_page_role, title_block.get("thicknesses_mm", []), allow_on_assembly=allow_local_component_data))
            part["dates"].extend(prefer_local_title_block_values(effective_page_role, title_block.get("dates", []), allow_on_assembly=True))
            part["sheet_refs"].extend(prefer_local_title_block_values(effective_page_role, title_block.get("sheet_refs", []), allow_on_assembly=True))
            part["scales"].extend(prefer_local_title_block_values(effective_page_role, title_block.get("scale", []), allow_on_assembly=True))
            part["clients"].extend(prefer_local_title_block_values(effective_page_role, title_block.get("clients", []), allow_on_assembly=allow_local_component_data))
            part["project_titles"].extend(prefer_local_title_block_values(effective_page_role, title_block.get("project_titles", []), allow_on_assembly=allow_local_component_data))
            part["overall_sizes_mm"].extend(dimensions.get("overall_sizes_mm", []))
            part["all_dimensions_mm"].extend(dimensions.get("all_dimensions_mm", []))
            part["angles_deg"].extend(cues.get("angles_deg", []))
            part["hole_sizes_mm"].extend(cues.get("hole_sizes_mm", []))
            part["radii_mm"].extend(cues.get("radii_mm", []))
            part["pitch_values_mm"].extend(cues.get("pitch_values_mm", []))
            part["fold_values_mm"].extend(cues.get("fold_values_mm", []))
            part["slot_sizes_mm"].extend(cues.get("slot_sizes_mm", []))
            part["edge_distances_mm"].extend(cues.get("edge_distances_mm", []))
            part["fold_count_textual"] = max(part.get("fold_count_textual", 0), cues.get("fold_count_textual", 0))
            part["process_notes"].extend(process_notes.get("note_snippets", []))
            part["process_note_types"].extend(process_notes.get("detected_note_types", []))
            part["review_flags"].extend(review_flags)
            part["flat_pattern_detected"] = part["flat_pattern_detected"] or cues.get("flat_pattern_detected", False)
            part["mirrored_detected"] = part["mirrored_detected"] or cues.get("mirrored_detected", False)
            part["hanging_hole_detected"] = part["hanging_hole_detected"] or cues.get("hanging_hole_detected", False)
            part["slot_detected"] = part["slot_detected"] or cues.get("slot_detected", False)
            part["assembly_candidate"] = part["assembly_candidate"] or effective_page_role == "assembly"
            part["textual_operations"].extend(ops)
            part["normalized_material"] = part["normalized_material"] or prefer_local_scalar(effective_page_role, title_block.get("normalized", {}).get("primary_material"), allow_on_assembly=allow_local_component_data)
            part["normalized_finish"] = part["normalized_finish"] or prefer_local_scalar(effective_page_role, title_block.get("normalized", {}).get("primary_finish"), allow_on_assembly=allow_local_component_data)
            part["normalized_thickness_mm"] = part["normalized_thickness_mm"] or prefer_local_scalar(effective_page_role, title_block.get("normalized", {}).get("primary_thickness_mm"), allow_on_assembly=allow_local_component_data)

            if part["description"] is None and pn in document_bom_lookup:
                part["description"] = document_bom_lookup[pn].get("description")
            if part["description"] is None:
                for description in title_block.get("descriptions", []):
                    if is_good_description(description):
                        part["description"] = description
                        break

            if part["quantity"] in (None, 1):
                quantities = title_block.get("quantities", [])
                if pn in document_bom_lookup and document_bom_lookup[pn].get("quantity"):
                    part["quantity"] = document_bom_lookup[pn].get("quantity")
                elif quantities:
                    try:
                        part["quantity"] = int(quantities[0])
                    except (TypeError, ValueError):
                        pass

            if should_assign_dimensions(effective_page_role, component_sheet):
                page_dims = pick_part_dimensions(part, dimensions)
                if part["overall_length_mm"] is None and page_dims.get("overall_length_mm") is not None:
                    part["overall_length_mm"] = page_dims["overall_length_mm"]
                if part["overall_width_mm"] is None and page_dims.get("overall_width_mm") is not None:
                    part["overall_width_mm"] = page_dims["overall_width_mm"]

            if part["normalized_thickness_mm"] is None:
                part["normalized_thickness_mm"] = first_numeric_thickness(part.get("thicknesses_mm", []))
            if not part["thicknesses_mm"] and part["normalized_thickness_mm"] is not None:
                part["thicknesses_mm"] = [str(part["normalized_thickness_mm"])]

            for key, value in confidence.items():
                part["confidence"].setdefault(key, []).append(value)
            rollup_geometry(part["geometry_rollup"], geometry)

    for part in parts.values():
        if part.get("pages"):
            continue
        pn = part.get("part_number")
        if not pn:
            continue
        matching_pages = [page for page in summary["pages"] if pn in (page.get("normalized_text") or "")]
        if not matching_pages:
            continue
        matching_pages = sorted(
            matching_pages,
            key=lambda item: (0 if item.get("page_role", {}).get("primary_role") == "detail" else 1, item.get("page_number", 9999)),
        )
        chosen_page = matching_pages[0]
        chosen_role = chosen_page.get("page_role", {}).get("primary_role")
        part["pages"].append(chosen_page["page_number"])
        if chosen_role:
            part["page_roles"].append(chosen_role)

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
            part[key] = dedupe(part[key])
        if part.get("normalized_material"):
            part["materials"] = [part["normalized_material"]]
        if part.get("normalized_finish"):
            part["surface_finishes"] = [part["normalized_finish"]]
        else:
            part["surface_finishes"] = clean_finish_values(part.get("surface_finishes", []))
        part["review_flags"] = dedupe(part["review_flags"])
        if not part.get("drawing_numbers") and not is_assembly_identifier(part.get("part_number")):
            part["drawing_numbers"] = [part["part_number"]]
        if part.get("normalized_thickness_mm") is None and document_primary_thickness is not None:
            part["normalized_thickness_mm"] = document_primary_thickness
            if not part.get("thicknesses_mm"):
                part["thicknesses_mm"] = [str(document_primary_thickness)]
        part["confidence"] = {
            key: round(sum(values) / len(values), 2) if values else 0.0
            for key, values in part.get("confidence", {}).items()
        }
        interpret_part(part)
        result.append(part)

    return sorted(result, key=lambda item: item.get("part_number") or "")
