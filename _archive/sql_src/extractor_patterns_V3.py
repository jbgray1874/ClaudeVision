import re
from typing import Any, Dict, List, Optional

from config import (
    ANGLE_PATTERN,
    BREAK_EDGE_PATTERN,
    CLIENT_PATTERN,
    COLOUR_PATTERN,
    CSK_PATTERN,
    DATE_PATTERN,
    DEBURR_PATTERN,
    DESCRIPTION_PATTERN,
    DIMENSION_PATTERN,
    DRAWING_NUMBER_PATTERN,
    DRAWN_BY_PATTERN,
    DRILL_PATTERN,
    EDGE_DISTANCE_PATTERN,
    FINISH_PATTERN,
    FLAT_PATTERN_PATTERN,
    FOLD_PATTERN,
    FOLD_VALUE_PATTERN,
    HOLE_PATTERN,
    LASER_PATTERN,
    LENGTH_BY_WIDTH_PATTERN,
    MATERIAL_PATTERN,
    MODIFIED_BY_PATTERN,
    PART_NUMBER_PATTERNS,
    PITCH_PATTERN,
    PROCESS_NOTE_PATTERNS,
    PROJECT_TITLE_PATTERN,
    PUNCH_PATTERN,
    QTY_TABLE_ROW_PATTERN,
    QUANTITY_PATTERN,
    RADIUS_PATTERN,
    REVISION_PATTERN,
    SCALE_PATTERN,
    SHEET_PATTERN,
    SHEET_SIZE_PATTERN,
    SLOT_PATTERN,
    SLOT_SIZE_PATTERN,
    TAP_PATTERN,
    THICKNESS_PATTERN,
    WEIGHT_PATTERN,
    WELD_PATTERN,
)


def normalize_text(text: str) -> str:
    return " ".join((text or "").replace("\x00", " ").replace("\n", " ").replace("\r", " ").split())


def _findall_unique(pattern: str, text: str, flags: int = 0) -> List[str]:
    matches = re.findall(pattern, text, flags=flags)
    flattened: List[str] = []
    for match in matches:
        if isinstance(match, tuple):
            values = [str(item).strip() for item in match if str(item).strip()]
            flattened.append(" ".join(values).strip())
        else:
            flattened.append(str(match).strip())

    seen: List[str] = []
    for item in flattened:
        if item and item not in seen:
            seen.append(item)
    return seen


def _first_or_none(values: List[str]) -> Optional[str]:
    return values[0] if values else None


def _safe_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def canonical_material(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    cleaned = normalize_text(value).upper()
    aliases = {
        "ALUMINUM": "ALUMINIUM",
        "ALU": "ALUMINIUM",
    }
    return aliases.get(cleaned, cleaned)


def _safe_int(value: Optional[str]) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _confidence(score: float) -> float:
    return round(max(0.0, min(1.0, score)), 2)


def _clean_dimension_candidates(values: List[str]) -> List[str]:
    cleaned: List[str] = []
    for value in values:
        number = _safe_float(value)
        if number is None:
            continue
        if number < 1.0:
            continue
        if number > 5000.0:
            continue
        if 1900 <= number <= 2100:
            continue
        if value not in cleaned:
            cleaned.append(value)
    return cleaned


def _field_with_confidence(values: List[str], base_confidence: float) -> Dict[str, Any]:
    return {
        "values": values,
        "confidence": _confidence(base_confidence if values else 0.0),
    }


def _normalize_thicknesses(values: List[str]) -> List[float]:
    normalized: List[float] = []
    for value in values:
        number = _safe_float(value)
        if number is None:
            continue
        if 0.1 <= number <= 50.0 and number not in normalized:
            normalized.append(number)
    return normalized


def _normalize_finish(value: str) -> str:
    normalized = normalize_text(value).upper()
    aliases = {
        "POWDER COAT": "POWDER COATING",
        "POWDER COATED": "POWDER COATING",
    }
    return aliases.get(normalized, normalized)


def extract_title_block_fields(text: str) -> Dict[str, Any]:
    text = normalize_text(text)
    part_numbers: List[str] = []
    for pattern in PART_NUMBER_PATTERNS:
        part_numbers.extend(_findall_unique(pattern, text, flags=re.IGNORECASE))

    materials = [canonical_material(value) for value in _findall_unique(MATERIAL_PATTERN, text, flags=re.IGNORECASE)]
    drawing_numbers = _findall_unique(DRAWING_NUMBER_PATTERN, text, flags=re.IGNORECASE)
    part_number_values = _findall_unique(r"|".join(PART_NUMBER_PATTERNS), text, flags=re.IGNORECASE) if len(PART_NUMBER_PATTERNS) == 1 else list(dict.fromkeys(part_numbers))
    revisions = _findall_unique(REVISION_PATTERN, text, flags=re.IGNORECASE)
    dates = _findall_unique(DATE_PATTERN, text, flags=re.IGNORECASE)
    material_values = [material for material in materials if material]
    finishes = [_normalize_finish(value) for value in _findall_unique(FINISH_PATTERN, text, flags=re.IGNORECASE)]
    thicknesses = _findall_unique(THICKNESS_PATTERN, text, flags=re.IGNORECASE)

    return {
        "drawing_numbers": drawing_numbers,
        "part_numbers": part_number_values,
        "revisions": revisions,
        "dates": dates,
        "materials": material_values,
        "surface_finishes": finishes,
        "colours": _findall_unique(COLOUR_PATTERN, text, flags=re.IGNORECASE),
        "weights": _findall_unique(WEIGHT_PATTERN, text, flags=re.IGNORECASE),
        "drawn_by": _findall_unique(DRAWN_BY_PATTERN, text, flags=re.IGNORECASE),
        "modified_by": _findall_unique(MODIFIED_BY_PATTERN, text, flags=re.IGNORECASE),
        "sheet_refs": _findall_unique(SHEET_PATTERN, text, flags=re.IGNORECASE),
        "sheet_sizes": _findall_unique(SHEET_SIZE_PATTERN, text, flags=re.IGNORECASE),
        "scale": _findall_unique(SCALE_PATTERN, text, flags=re.IGNORECASE),
        "descriptions": _findall_unique(DESCRIPTION_PATTERN, text, flags=re.IGNORECASE),
        "clients": _findall_unique(CLIENT_PATTERN, text, flags=re.IGNORECASE),
        "project_titles": _findall_unique(PROJECT_TITLE_PATTERN, text, flags=re.IGNORECASE),
        "quantities": _findall_unique(QUANTITY_PATTERN, text, flags=re.IGNORECASE),
        "thicknesses_mm": thicknesses,
        "normalized": {
            "primary_material": _first_or_none(material_values),
            "primary_finish": _first_or_none(finishes),
            "primary_thickness_mm": _first_or_none(thicknesses),
        },
        "confidence": {
            "drawing_numbers": _confidence(0.95 if drawing_numbers else 0.0),
            "part_numbers": _confidence(0.95 if part_number_values else 0.0),
            "revisions": _confidence(0.9 if revisions else 0.0),
            "dates": _confidence(0.9 if dates else 0.0),
            "materials": _confidence(0.92 if material_values else 0.0),
            "surface_finishes": _confidence(0.88 if finishes else 0.0),
            "thicknesses_mm": _confidence(0.9 if thicknesses else 0.0),
        },
    }


def extract_bom_rows(text: str) -> List[Dict[str, Any]]:
    text = normalize_text(text)
    rows: List[Dict[str, Any]] = []
    matches = re.findall(QTY_TABLE_ROW_PATTERN, text, flags=re.IGNORECASE)
    for item_no, part_no, description, qty in matches:
        rows.append(
            {
                "item_number": item_no.strip(),
                "part_number": normalize_text(part_no),
                "description": normalize_text(description),
                "quantity": _safe_int(qty),
            }
        )
    return rows


def classify_dimensions(text: str) -> Dict[str, Any]:
    text = normalize_text(text)
    overall_sizes_raw = re.findall(LENGTH_BY_WIDTH_PATTERN, text, flags=re.IGNORECASE)
    overall_sizes = [f"{left} x {right}" for left, right in overall_sizes_raw]
    slot_sizes = [f"{left} x {right}" for left, right in re.findall(SLOT_SIZE_PATTERN, text, flags=re.IGNORECASE)]

    all_dimensions_mm = _clean_dimension_candidates(_findall_unique(DIMENSION_PATTERN, text, flags=re.IGNORECASE))
    edge_distances = _findall_unique(EDGE_DISTANCE_PATTERN, text, flags=re.IGNORECASE)
    angles = _findall_unique(ANGLE_PATTERN, text, flags=re.IGNORECASE)
    hole_sizes = _findall_unique(HOLE_PATTERN, text, flags=re.IGNORECASE)
    pitch_values = _findall_unique(PITCH_PATTERN, text, flags=re.IGNORECASE)
    radii = _findall_unique(RADIUS_PATTERN, text, flags=re.IGNORECASE)
    fold_values = _findall_unique(FOLD_VALUE_PATTERN, text, flags=re.IGNORECASE)

    dims_float = sorted(
        [_safe_float(value) for value in all_dimensions_mm if _safe_float(value) is not None],
        reverse=True,
    )

    return {
        "overall_sizes_mm": overall_sizes,
        "overall_length_mm": dims_float[0] if len(dims_float) > 0 else None,
        "overall_width_mm": dims_float[1] if len(dims_float) > 1 else None,
        "all_dimensions_mm": all_dimensions_mm[:500],
        "angles_deg": angles,
        "hole_sizes_mm": hole_sizes,
        "pitch_values_mm": pitch_values,
        "radii_mm": radii,
        "fold_values_mm": fold_values,
        "slot_sizes_mm": slot_sizes,
        "edge_distances_mm": edge_distances,
        "confidence": {
            "overall_length_mm": _confidence(0.65 if len(dims_float) > 0 else 0.0),
            "overall_width_mm": _confidence(0.6 if len(dims_float) > 1 else 0.0),
            "hole_sizes_mm": _confidence(0.85 if hole_sizes else 0.0),
            "angles_deg": _confidence(0.88 if angles else 0.0),
            "slot_sizes_mm": _confidence(0.85 if slot_sizes else 0.0),
        },
    }


def extract_feature_cues(text: str) -> Dict[str, Any]:
    text = normalize_text(text)
    dimensions = classify_dimensions(text)

    return {
        "angles_deg": dimensions["angles_deg"],
        "hole_sizes_mm": dimensions["hole_sizes_mm"],
        "pitch_values_mm": dimensions["pitch_values_mm"],
        "radii_mm": dimensions["radii_mm"],
        "fold_values_mm": dimensions["fold_values_mm"],
        "all_dimensions_mm": dimensions["all_dimensions_mm"],
        "slot_sizes_mm": dimensions["slot_sizes_mm"],
        "edge_distances_mm": dimensions["edge_distances_mm"],
        "fold_count_textual": len(re.findall(FOLD_PATTERN, text, flags=re.IGNORECASE)),
        "flat_pattern_detected": bool(re.search(FLAT_PATTERN_PATTERN, text, flags=re.IGNORECASE)),
        "slot_detected": bool(re.search(SLOT_PATTERN, text, flags=re.IGNORECASE)),
        "laser_text_detected": bool(re.search(LASER_PATTERN, text, flags=re.IGNORECASE)),
        "weld_detected": bool(re.search(WELD_PATTERN, text, flags=re.IGNORECASE)),
        "tapped_detected": bool(re.search(TAP_PATTERN, text, flags=re.IGNORECASE)),
        "countersink_detected": bool(re.search(CSK_PATTERN, text, flags=re.IGNORECASE)),
        "deburr_detected": bool(re.search(DEBURR_PATTERN, text, flags=re.IGNORECASE)),
        "break_edges_detected": bool(re.search(BREAK_EDGE_PATTERN, text, flags=re.IGNORECASE)),
        "drill_detected": bool(re.search(DRILL_PATTERN, text, flags=re.IGNORECASE)),
        "punch_detected": bool(re.search(PUNCH_PATTERN, text, flags=re.IGNORECASE)),
        "mirrored_detected": "MIRRORED" in text.upper(),
        "hanging_hole_detected": "HANGING HOLE" in text.upper(),
    }


def extract_process_notes(text: str) -> Dict[str, Any]:
    text = normalize_text(text)
    note_hits: List[str] = []
    operations: List[str] = []

    for operation, pattern in PROCESS_NOTE_PATTERNS.items():
        if re.search(pattern, text, flags=re.IGNORECASE):
            note_hits.append(operation)
            operations.append(operation)

    raw_note_snippets: List[str] = []
    for fragment in re.split(r"(?<=[.;])\s+|\s{2,}", text):
        cleaned = normalize_text(fragment)
        if not cleaned:
            continue
        if any(re.search(pattern, cleaned, flags=re.IGNORECASE) for pattern in PROCESS_NOTE_PATTERNS.values()):
            raw_note_snippets.append(cleaned)

    return {
        "detected_note_types": note_hits,
        "note_snippets": raw_note_snippets[:20],
        "operations_from_notes": list(dict.fromkeys(operations)),
        "confidence": _confidence(0.9 if note_hits else 0.0),
    }


def infer_operations_from_text(text: str) -> List[str]:
    text = normalize_text(text).upper()
    operations: List[str] = []

    if "FLAT PATTERN" in text or "LASER" in text:
        operations.append("laser_cutting")
    if "HOLE" in text or "DRILL" in text or "PUNCH" in text:
        operations.append("hole_machining")
    if "FOLD" in text or "BEND" in text or re.search(ANGLE_PATTERN, text, flags=re.IGNORECASE):
        operations.append("folding")
    if "POWDER COAT" in text:
        operations.append("powder_coating")
    if re.search(WELD_PATTERN, text, flags=re.IGNORECASE):
        operations.append("welding")
    if re.search(TAP_PATTERN, text, flags=re.IGNORECASE):
        operations.append("tapping")
    if re.search(CSK_PATTERN, text, flags=re.IGNORECASE):
        operations.append("countersinking")
    operations.append("handling")

    return list(dict.fromkeys(operations))


def build_review_flags(
    title_block: Dict[str, Any],
    dimensions: Dict[str, Any],
    feature_cues: Dict[str, Any],
    process_notes: Dict[str, Any],
    page_role_hint: Optional[str],
) -> List[Dict[str, Any]]:
    review_flags: List[Dict[str, Any]] = []

    if not title_block.get("drawing_numbers"):
        review_flags.append({"severity": "warning", "field": "drawing_number", "reason": "No drawing number extracted."})
    if not title_block.get("materials"):
        review_flags.append({"severity": "warning", "field": "material", "reason": "No material extracted from title block."})
    if not title_block.get("thicknesses_mm"):
        review_flags.append({"severity": "warning", "field": "thickness", "reason": "No thickness extracted from title block."})
    if dimensions.get("overall_length_mm") is None or dimensions.get("overall_width_mm") is None:
        review_flags.append({"severity": "warning", "field": "overall_size", "reason": "Overall dimensions inferred with low confidence or missing."})
    if page_role_hint == "detail" and not feature_cues.get("flat_pattern_detected") and not feature_cues.get("hole_sizes_mm") and not feature_cues.get("angles_deg"):
        review_flags.append({"severity": "info", "field": "detail_features", "reason": "Detail page has few manufacturing cues; verify extraction."})
    if process_notes.get("detected_note_types") and len(process_notes.get("note_snippets", [])) == 0:
        review_flags.append({"severity": "info", "field": "process_notes", "reason": "Process note types detected without clear snippets."})

    return review_flags


def build_textual_manufacturing_summary(
    text: str,
    title_block_text: str = "",
    bom_text: str = "",
    notes_text: str = "",
    page_role_hint: Optional[str] = None,
) -> Dict[str, Any]:
    full_text = normalize_text(text)
    title_text = normalize_text(title_block_text) or full_text
    bom_source = normalize_text(bom_text) or full_text
    notes_source = normalize_text(notes_text) or full_text

    title_block = extract_title_block_fields(title_text)
    bom_rows = extract_bom_rows(bom_source)
    dimensions = classify_dimensions(full_text)
    feature_cues = extract_feature_cues(full_text)
    process_notes = extract_process_notes(notes_source)
    inferred_operations = infer_operations_from_text(full_text + " " + notes_source)
    review_flags = build_review_flags(title_block, dimensions, feature_cues, process_notes, page_role_hint)
    confidence = {
        "title_block": _confidence(sum(title_block.get("confidence", {}).values()) / max(1, len(title_block.get("confidence", {}))) if title_block.get("confidence") else 0.0),
        "dimensions": _confidence(sum(dimensions.get("confidence", {}).values()) / max(1, len(dimensions.get("confidence", {}))) if dimensions.get("confidence") else 0.0),
        "process_notes": process_notes.get("confidence", 0.0),
        "overall": _confidence(
            (
                (sum(title_block.get("confidence", {}).values()) / max(1, len(title_block.get("confidence", {})))) +
                (sum(dimensions.get("confidence", {}).values()) / max(1, len(dimensions.get("confidence", {})))) +
                process_notes.get("confidence", 0.0)
            ) / 3
        ),
    }

    primary_material = _first_or_none(title_block["materials"])
    primary_finish = _first_or_none(title_block["surface_finishes"])
    primary_colour = _first_or_none(title_block["colours"])
    primary_revision = _first_or_none(title_block["revisions"])
    primary_drawing_number = _first_or_none(title_block["drawing_numbers"])
    primary_quantity = _first_or_none(title_block["quantities"])
    primary_thickness = _first_or_none(title_block["thicknesses_mm"])

    return {
        "title_block": title_block,
        "bom_rows": bom_rows,
        "dimensions": dimensions,
        "feature_cues": feature_cues,
        "process_notes": process_notes,
        "inferred_operations": list(dict.fromkeys(inferred_operations + process_notes["operations_from_notes"])),
        "page_role_hint": page_role_hint,
        "review_flags": review_flags,
        "confidence": confidence,
        "primary_fields": {
            "drawing_number": primary_drawing_number,
            "revision": primary_revision,
            "material": primary_material,
            "normalized_material": canonical_material(primary_material),
            "finish": primary_finish,
            "normalized_finish": _normalize_finish(primary_finish) if primary_finish else None,
            "colour": primary_colour,
            "quantity": _safe_int(primary_quantity),
            "thickness_mm": _safe_float(primary_thickness),
            "normalized_thickness_mm": _safe_float(primary_thickness),
            "overall_length_mm": dimensions["overall_length_mm"],
            "overall_width_mm": dimensions["overall_width_mm"],
        },
    }
