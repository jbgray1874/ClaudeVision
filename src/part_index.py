import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from bought_in_policy import is_bought_in as _is_bought_in
from source_precedence import apply_field


# Which reader actually saw a merged BOM row. merge_boms.reconcile_page stamps every row it
# emits, and those four values are the whole answer.
_BOM_ROW_READER = {
    "BOTH":        "bom_tree",      # the deterministic reader and vision agreed
    "A_ONLY":      "bom_tree",      # the deterministic reader alone — what bom_tree means
    "B_RECOVERED": "llm_extract",   # vision found a row the deterministic reader did not
    "B_OVERRIDE":  "llm_extract",   # vision disagreed and won
}


def _bom_row_source(row: Dict[str, Any]) -> str:
    """A BOM ROW READ BY THE VISION MODEL IS NOT A MEASURED BOM ROW.

    Every quantity off a BOM was stamped `bom_tree` — rank 60, and a member of
    MEASURED_SOURCES, so reports print it with no reasoned-value mark and arbitration treats it
    as something read off a table rather than off a picture of one.

    ON AN LLM-ONLY RUN THAT IS FALSE FOR EVERY ROW ON THE JOB. --llm-only switches off Path A,
    so `document_analysis.bom_rows` is the vision model's reading and nothing else; it then
    reached section 9 of the report as "the bill of materials" with no lightning bolt beside
    it, telling an estimator those quantities were measured. James was right to push on this,
    though the column he named — material and thickness, which really do come off the drawing's
    text layer via pdfplumber — was the one place the labels were already correct.

    IT IS ALSO WRONG ON A FULL RUN, more quietly: any row vision RECOVERED (the deterministic
    reader missed it) or OVERRODE carries the same false stamp. Those are exactly the rows
    where corroboration did not happen, so they are exactly the rows the mark exists for.

    THE ANSWER WAS ALREADY ON THE ROW. reconcile_page records BOTH / A_ONLY / B_RECOVERED /
    B_OVERRIDE on every row it emits, and this was throwing it away. Nothing new is derived
    here — a recorded fact is read instead of being replaced by a constant.

    A NOTE ON RANK, because this is not purely cosmetic. bom_tree is 60 and llm_extract is 40,
    so a vision-only quantity can now be displaced by an override rule at 50 where before it
    could not. The exposure is narrow: a B_RECOVERED row is by definition one the deterministic
    reader never saw, so no competing BOM value exists, and a title-block quantity already
    outranked it at 70. Worth a look at the next full run's total against the 23:09 run's
    £574.94 before this is shown to anybody.
    """
    return _BOM_ROW_READER.get(str(row.get("source") or "").strip().upper(), "bom_tree")


def _clean_bom_description(desc: Any) -> Any:
    """Truncate BOM text blobs to the first meaningful phrase (max 80 chars)."""
    if not desc:
        return desc
    text = str(desc).strip()
    if len(text) <= 80 and not any(c.isdigit() for c in text[:3]):
        return text
    cleaned = re.sub(r"^QTY\s*\d+\s+[A-Z0-9\-]+\s+", "", text, flags=re.IGNORECASE).strip()
    match = re.search(r"\s+\d+\s+[A-Z0-9]{4,}-[A-Z0-9\-]+", cleaned)
    if match:
        cleaned = cleaned[: match.start()].strip()
    if len(cleaned) > 80:
        cleaned = cleaned[:77].rstrip() + "…"
    return cleaned if cleaned else text[:80]


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
    document_bom_lookup = {  # noqa: E501 — see _bom_row_source below for how these are attributed
        row["part_number"]: row
        for row in summary.get("document_analysis", {}).get("bom_rows", [])
        if is_valid_part_identifier(row.get("part_number"))
    }
    document_primary_thickness = summary.get("document_analysis", {}).get("primary_fields", {}).get("thickness_mm")

    for row in summary.get("document_analysis", {}).get("bom_rows", []):
        pn = row["part_number"]
        if not is_valid_part_identifier(pn):
            continue
        # BORN WITH A SOURCE. Constructing the record with quantity=<BOM value> and no
        # quantity_source left most BOM quantities unattributed, so arbitration had nothing
        # to weigh them against and any later pass could replace them silently. Worse, the
        # apply path further down only ran for quantities of None or 1 — so every quantity
        # ABOVE one, which is most of them, skipped attribution entirely. Construct without
        # it, then submit it as the observation it is.
        parts[pn] = empty_part_record(
            part_number=pn,
            item_number=row.get("item_number"),
            description=_clean_bom_description(row.get("description")),
            quantity=None,
        )
        apply_field(parts[pn], "quantity", row.get("quantity"), _bom_row_source(row))

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
            part["weights"].extend(prefer_local_title_block_values(effective_page_role, title_block.get("weights", []), allow_on_assembly=allow_local_component_data))
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
            # Title-block readings: rank 70. `x = x or y` fills a gap, which is the right
            # direction, but records no source — and an unattributed datum is invisible to
            # arbitration, so the next pass has nothing to weigh itself against.
            _norm_tb = title_block.get("normalized", {})
            for _fld, _tb_key in (("normalized_material", "primary_material"),
                                  ("normalized_finish", "primary_finish"),
                                  ("normalized_thickness_mm", "primary_thickness_mm")):
                _v = prefer_local_scalar(effective_page_role, _norm_tb.get(_tb_key),
                                         allow_on_assembly=allow_local_component_data)
                if _v not in (None, ""):
                    apply_field(part, _fld, _v, "drawing_deterministic")

            if part["description"] is None and pn in document_bom_lookup:
                part["description"] = _clean_bom_description(document_bom_lookup[pn].get("description"))
            if part["description"] is None:
                for description in title_block.get("descriptions", []):
                    if is_good_description(description):
                        part["description"] = _clean_bom_description(description)
                        break

            # No "is it None or 1" test. That treated a quantity of ONE as an empty slot, so
            # a part the model says there is one of was open to replacement by whatever a
            # table happened to say — and it skipped attribution for everything above one.
            # Every observation is submitted; the resolver decides which survives.
            quantities = title_block.get("quantities", [])
            if pn in document_bom_lookup and document_bom_lookup[pn].get("quantity"):
                # SAME ROW, SAME ATTRIBUTION. The second of the two places a BOM quantity is
                # submitted; stamping it differently from the first would put one part's
                # quantity at rank 60 and another's at 40 for no reason a reader could find.
                apply_field(part, "quantity", document_bom_lookup[pn].get("quantity"),
                            _bom_row_source(document_bom_lookup[pn]))
            elif quantities:
                try:
                    apply_field(part, "quantity", int(quantities[0]), "drawing_deterministic")
                except (TypeError, ValueError):
                    pass

            if should_assign_dimensions(effective_page_role, component_sheet):
                page_dims = pick_part_dimensions(part, dimensions)
                if part["overall_length_mm"] is None and page_dims.get("overall_length_mm") is not None:
                    part["overall_length_mm"] = page_dims["overall_length_mm"]
                if part["overall_width_mm"] is None and page_dims.get("overall_width_mm") is not None:
                    part["overall_width_mm"] = page_dims["overall_width_mm"]

            if part["normalized_thickness_mm"] is None:
                apply_field(part, "normalized_thickness_mm",
                            first_numeric_thickness(part.get("thicknesses_mm", [])),
                            "drawing_deterministic")
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
            part[key] = dedupe(part[key])   # precedence: direct-write ok — dedupes a list in place, introduces no new evidence
        if part.get("normalized_material"):
            part["materials"] = [part["normalized_material"]]
        if part.get("normalized_finish"):
            part["surface_finishes"] = [part["normalized_finish"]]
        else:
            part["surface_finishes"] = clean_finish_values(part.get("surface_finishes", []))
        part["review_flags"] = dedupe(part["review_flags"])
        if not part.get("drawing_numbers") and not is_assembly_identifier(part.get("part_number")):
            part["drawing_numbers"] = [part["part_number"]]
        # THE PACK'S GAUGE BELONGS TO THE PARTS WE CUT FROM IT.
        #
        # This fallback exists because a detail sheet that does not repeat the gauge should
        # inherit the document's, and for a fabricated part that is right. It was applied to
        # every part with no thickness of its own, which put a sheet gauge on things that are
        # not cut from sheet at all:
        #
        #   12552-01-01X  62012RS Ball Bearing 12x32x10mm   ->  1.5mm
        #   12552-01-02X  CONCRETE SLAB (drawing says 20mm) ->  1.5mm
        #
        # A gauge is not decoration. It makes a part look like sheet metal to the estimator —
        # _has_blank accepts a bare thickness — and it sets the rate and steps the cut time.
        # The bearing carried 1.5mm through three runs while everything else about it was
        # being corrected, and it is the last thing holding it in the 1.5mm MILD STEEL laser
        # group.
        #
        # NOT FLAGGED, deliberately, unlike the other bought-in refusals. Those all suppress
        # something that would otherwise appear — a blank, a route — where silence would look
        # like the rule never ran. Here the correct end state IS the absence, and it is
        # already visible: the Gauge column on the sheet is simply empty, which is the honest
        # answer for a part whose thickness we do not know and do not need. Flagging every
        # FIXING on every job would be noise, not evidence.
        if (part.get("normalized_thickness_mm") is None
                and document_primary_thickness is not None
                and not _is_bought_in(part)):
            apply_field(part, "normalized_thickness_mm", document_primary_thickness,
                        "drawing_deterministic")
            if not part.get("thicknesses_mm"):
                part["thicknesses_mm"] = [str(document_primary_thickness)]
        part["confidence"] = {
            key: round(sum(values) / len(values), 2) if values else 0.0
            for key, values in part.get("confidence", {}).items()
        }
        interpret_part(part)
        result.append(part)

    return sorted(result, key=lambda item: item.get("part_number") or "")
