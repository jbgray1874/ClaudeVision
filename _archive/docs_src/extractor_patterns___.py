import re
from typing import Any, Dict, List, Optional

from config import (
    ANGLE_PATTERN,
    BREAK_EDGE_PATTERN,
    CLIENT_PATTERN,
    COLOUR_PATTERN,
    CSK_PATTERN,
    DATE_PATTERN,
    DIAMETER_HOLE_PATTERN,
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
        if number in {3.0, 4.0, 5.0} and value.isdigit():
            # Grid references and sheet markers are common noise on drawings.
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


# Standard SDI sheet metal gauges — validate thickness extraction.
# Values outside this set on steel are often hole diameters, radii, or grid refs.
_STEEL_STANDARD_GAUGES_MM = {
    0.5, 0.7, 0.8, 0.9, 1.0, 1.2, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0
}
_ACRYLIC_STANDARD_GAUGES_MM = {
    1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 15.0, 20.0
}


def _validate_thickness_for_material(thickness_mm: Optional[float], material: str) -> Optional[float]:
    """
    Return thickness if plausible for material; None if likely a parsing artefact
    (e.g. 8.0 mm on mild steel is usually a dimension, not gauge stock).
    """
    if thickness_mm is None:
        return None
    mat = (material or "").upper()
    is_steel = any(m in mat for m in ("MILD STEEL", "STAINLESS", "GALVAN", "ZINTEC", "CRS"))
    is_acrylic = any(m in mat for m in ("ACRYLIC", "PERSPEX", "PETG", "POLYCARBONATE"))
    if is_steel and thickness_mm not in _STEEL_STANDARD_GAUGES_MM:
        return None
    if is_acrylic and thickness_mm not in _ACRYLIC_STANDARD_GAUGES_MM:
        return None
    return thickness_mm


def _normalize_finish(value: str) -> str:
    normalized = normalize_text(value).upper()
    aliases = {
        "POWDER COAT": "POWDER COATING",
        "POWDER COATED": "POWDER COATING",
    }
    return aliases.get(normalized, normalized)


def _count_numeric_occurrences(values: List[str]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for value in values:
        normalized = str(value).strip()
        if not normalized:
            continue
        counts[normalized] = counts.get(normalized, 0) + 1
    return counts


def _coalesce_unique(*lists: List[str]) -> List[str]:
    merged: List[str] = []
    for values in lists:
        for value in values:
            if value not in merged:
                merged.append(value)
    return merged


def _pick_preferred(primary: Dict[str, Any], fallback: Dict[str, Any], key: str) -> List[str]:
    primary_values = primary.get(key, []) or []
    fallback_values = fallback.get(key, []) or []
    return primary_values if primary_values else fallback_values


def _prefer_best_scalar(*values: Optional[str]) -> Optional[str]:
    candidates = [value for value in values if value not in (None, "")]
    if not candidates:
        return None
    return max(candidates, key=lambda value: len(str(value)))


TITLE_BLOCK_STOP_LABELS = [
    "DESCRIPTION",
    "CLIENT",
    "PROJECT TITLE",
    "DWG NO",
    "DRAWING NO",
    "REVISION",
    "DATE",
    "DRAWN BY",
    "MODIFIED BY",
    "MATERIAL",
    "SURFACE FINISH",
    "FINISH",
    "COLOUR",
    "COLOR",
    "CLIENT REF",
    "SCALE",
    "SHEET SIZE",
    "SHEET",
    "WEIGHT",
    "UNLESS OTHERWISE STATED",
]


def _extract_labeled_value(text: str, label_pattern: str, stop_labels: List[str]) -> List[str]:
    normalized = normalize_text(text)
    match = re.search(label_pattern, normalized, flags=re.IGNORECASE)
    if not match:
        return []

    start = match.end()
    remainder = normalized[start:].strip()
    if not remainder:
        return []

    stop_pattern = r"\b(?:" + "|".join(stop_labels) + r")\b\s*[:\-]?"
    stop_match = re.search(stop_pattern, remainder, flags=re.IGNORECASE)
    value = remainder[:stop_match.start()].strip() if stop_match else remainder.strip()
    value = normalize_text(value.rstrip(":;- ,"))
    return [value] if value else []


def _extract_labeled_values(text: str, label_pattern: str, stop_labels: List[str]) -> List[str]:
    normalized = normalize_text(text)
    matches: List[str] = []
    for match in re.finditer(label_pattern, normalized, flags=re.IGNORECASE):
        remainder = normalized[match.end():].strip()
        if not remainder:
            continue
        stop_pattern = r"\b(?:" + "|".join(stop_labels) + r")\b\s*[:\-]?"
        stop_match = re.search(stop_pattern, remainder, flags=re.IGNORECASE)
        value = remainder[:stop_match.start()].strip() if stop_match else remainder.strip()
        value = normalize_text(value.rstrip(":;- ,"))
        if value and value not in matches:
            matches.append(value)
    return matches


def _raw_lines(text: str) -> List[str]:
    return [line.strip() for line in (text or "").replace("\r", "\n").split("\n") if line.strip()]


def _looks_like_label_heavy(value: str) -> bool:
    upper = normalize_text(value).upper()
    if not upper:
        return True
    label_hits = sum(1 for label in TITLE_BLOCK_STOP_LABELS if label in upper)
    return label_hits >= 2


def _extract_following_line_values(text: str, label_pattern: str, max_lines: int = 3) -> List[str]:
    lines = _raw_lines(text)
    values: List[str] = []
    compiled = re.compile(label_pattern, flags=re.IGNORECASE)

    for index, line in enumerate(lines):
        match = compiled.search(line)
        if not match:
            continue

        inline = normalize_text(line[match.end():].strip(" :-"))
        if inline and not _looks_like_label_heavy(inline):
            values.append(inline)
            continue

        for look_ahead in range(index + 1, min(len(lines), index + 1 + max_lines)):
            candidate = normalize_text(lines[look_ahead].strip(" :-"))
            if not candidate:
                continue
            if _looks_like_label_heavy(candidate):
                continue
            values.append(candidate)
            break

    return _dedupe_strings(values)


def _extract_part_number_candidates(text: str) -> List[str]:
    candidates: List[str] = []
    for pattern in PART_NUMBER_PATTERNS:
        candidates.extend(_findall_unique(pattern, text, flags=re.IGNORECASE))
    return _dedupe_strings(candidates)


def _looks_like_part_number(value: str) -> bool:
    normalized = normalize_text(value).upper()
    if not normalized:
        return False
    if normalized.startswith(("ITEM", "QTY", "DESCRIPTION", "SHEET", "SCALE")):
        return False
    if normalized in {"A-A", "B-B", "C-C", "D-D", "E-E", "F-F"}:
        return False
    if normalized.endswith(("-FLAT", "-ASSEMBLY", "-WELD", "-REV", "-DRAWING")):
        return False
    if re.search(r"\b(?:BLACK|WHITE|RAW|RAL|SEMI|GLOSS|MATT|TEXTURED)\b", normalized):
        return False
    parts = [item.strip() for item in normalized.split("-")]
    if len(parts) == 2 and len(parts[0]) == 1 and len(parts[1]) == 1:
        return False
    if len(parts) == 2 and len(parts[0]) <= 2 and len(parts[1]) <= 2:
        return False
    return bool(re.fullmatch(r"[A-Z0-9_]+(?:\s*-\s*[A-Z0-9_]+){1,4}", normalized))


def _looks_like_noise_description(value: str) -> bool:
    normalized = normalize_text(value).upper()
    if not normalized:
        return True
    if normalized.startswith(("DWG NO", "DESCRIPTION", "QTY", "ITEM")):
        return True
    if "APPROPRIATE CERTIFICATION" in normalized:
        return True
    if "RIDGEFIELD" in normalized:
        return True
    if "COPT OAK BARN" in normalized:
        return True
    if "GENERAL TOLERANCES" in normalized:
        return True
    if "THIS DRAWING IS THE PROPERTY" in normalized:
        return True
    alpha_count = sum(1 for char in normalized if char.isalpha())
    digit_count = sum(1 for char in normalized if char.isdigit())
    if digit_count > alpha_count and digit_count > 4:
        return True
    return False


def _is_reasonable_hole_size(value: str) -> bool:
    number = _safe_float(value)
    if number is None:
        return False
    if number < 1.0:
        return False
    if number > 50.0:
        return False
    return True


def _dedupe_strings(values: List[str]) -> List[str]:
    deduped: List[str] = []
    for value in values:
        if value and value not in deduped:
            deduped.append(value)
    return deduped


def _filter_revision_candidates(values: List[str]) -> List[str]:
    filtered: List[str] = []
    for value in values:
        normalized = normalize_text(value).upper()
        if normalized in {"TABLE", "PROJECT", "DATE", "BY"}:
            continue
        if len(normalized) > 8:
            continue
        if normalized not in filtered:
            filtered.append(normalized)
    return filtered


def _extract_revision_from_context(text: str, part_numbers: List[str]) -> List[str]:
    revisions: List[str] = []
    normalized = normalize_text(text)
    for part_number in part_numbers:
        pattern = re.escape(normalize_text(part_number)) + r"\s+([A-Z0-9]{1,4})\b"
        for value in _findall_unique(pattern, normalized, flags=re.IGNORECASE):
            cleaned = normalize_text(value).upper()
            if cleaned in {"TTI", "A3"}:
                continue
            if re.fullmatch(r"\d{1,3}|[A-Z]\d{0,2}", cleaned):
                revisions.append(cleaned)
    return _filter_revision_candidates(_dedupe_strings(revisions))


def _extract_person_name_candidates(text: str, label_pattern: str) -> List[str]:
    values = _extract_labeled_values(text, label_pattern, TITLE_BLOCK_STOP_LABELS)
    values.extend(_extract_following_line_values(text, label_pattern, max_lines=4))

    cleaned: List[str] = []
    for value in values:
        normalized = normalize_text(value).strip(" :-")
        upper = normalized.upper()
        if not normalized:
            continue
        if "@" in normalized:
            continue
        if upper in {"MODIFIED BY", "DRAWN BY", "DATE"}:
            continue
        if _looks_like_label_heavy(normalized):
            continue
        if re.search(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", normalized):
            continue
        if not re.fullmatch(r"[A-Z][A-Z0-9._\- ]{1,40}", upper):
            continue
        cleaned.append(normalized.upper())
    return _dedupe_strings(cleaned)


def _extract_drawing_number_candidates(text: str) -> List[str]:
    labeled = _extract_labeled_values(text, r"(?:DWG\s*NO|DRAWING\s*NO)\s*[:\-]?", TITLE_BLOCK_STOP_LABELS)
    part_like = []
    for value in labeled:
        part_like.extend(_extract_part_number_candidates(value))
    if part_like:
        return _dedupe_strings(part_like)

    context_matches: List[str] = []
    normalized = normalize_text(text)
    for match in re.finditer(r"(?:PROJECT\s*TITLE\s*:?\s*)?.{0,120}?(" + DRAWING_NUMBER_PATTERN + r")\s+[A-Z0-9]{1,4}\b", normalized, flags=re.IGNORECASE):
        groups = [item for item in match.groups() if item]
        for group in groups:
            context_matches.extend(_extract_part_number_candidates(group))
    if context_matches:
        return _dedupe_strings(context_matches)

    all_part_numbers = _extract_part_number_candidates(normalized)
    assembly_like = [value for value in all_part_numbers if str(value).upper().replace(" ", "").endswith("-GA")]
    return _dedupe_strings(assembly_like or all_part_numbers[:1])


def _extract_revision_candidates(text: str) -> List[str]:
    labeled = _extract_labeled_values(text, r"REV(?:ISION)?\s*[:.\-]?", TITLE_BLOCK_STOP_LABELS)
    filtered = _filter_revision_candidates(labeled)
    if filtered:
        return filtered
    contextual = _extract_revision_from_context(text, _extract_part_number_candidates(text))
    if contextual:
        return contextual
    return _filter_revision_candidates(_findall_unique(REVISION_PATTERN, text, flags=re.IGNORECASE))


def _extract_drawn_by_candidates(text: str) -> List[str]:
    return _extract_person_name_candidates(text, r"DRAWN\s*BY\s*[:\-]?")


def _extract_modified_by_candidates(text: str) -> List[str]:
    values = _extract_person_name_candidates(text, r"MODIFIED\s*BY\s*[:\-]?")
    return [value for value in values if value.upper() not in {"DRAWN BY", "DATE"}]


def _extract_client_candidates(text: str) -> List[str]:
    values = _extract_labeled_values(text, r"CLIENT\s*[:\-]?", TITLE_BLOCK_STOP_LABELS)
    values.extend(_extract_following_line_values(text, r"CLIENT\s*[:\-]?", max_lines=2))
    cleaned: List[str] = []
    for value in values:
        upper = value.upper()
        if upper in {"REF", "CLIENT REF"}:
            continue
        if _looks_like_label_heavy(value):
            continue
        if value not in cleaned:
            cleaned.append(value)
    return cleaned


def _extract_scale_candidates(text: str) -> List[str]:
    values = _extract_labeled_values(text, r"SCALE\s*[:\-]?", TITLE_BLOCK_STOP_LABELS)
    values.extend(_extract_following_line_values(text, r"SCALE\s*[:\-]?", max_lines=2))
    cleaned: List[str] = []
    for value in values:
        normalized = normalize_text(value)
        if re.fullmatch(r"\d+\s*:\s*\d+", normalized):
            cleaned.append(normalized)
    return cleaned


def _extract_sheet_ref_candidates(text: str) -> List[str]:
    values = _extract_labeled_values(text, r"SHEET\s*[:\-]?", TITLE_BLOCK_STOP_LABELS)
    values.extend(_extract_following_line_values(text, r"SHEET\s*[:\-]?", max_lines=2))
    cleaned: List[str] = []
    for value in values:
        match = re.search(r"\b\d+\s*/\s*\d+\b", value)
        if match:
            ref = match.group(0).replace(" ", "")
            left, right = ref.split("/")
            try:
                left_num = int(left)
                right_num = int(right)
            except ValueError:
                continue
            if right_num <= 0 or right_num > 100:
                continue
            if left_num <= 0 or left_num > right_num:
                continue
            cleaned.append(ref)
    return _dedupe_strings(cleaned)


def _extract_sheet_size_candidates(text: str) -> List[str]:
    values = _extract_labeled_values(text, r"SHEET\s+SIZE\s*[:\-]?", TITLE_BLOCK_STOP_LABELS)
    cleaned: List[str] = []
    for value in values:
        match = re.search(r"\bA[0-4]\b", value, flags=re.IGNORECASE)
        if match:
            cleaned.append(match.group(0).upper())
    return _dedupe_strings(cleaned)


def _extract_description_candidates(text: str) -> List[str]:
    values = _extract_labeled_value(
        text,
        r"DESCRIPTION\s*[:\-]?",
        TITLE_BLOCK_STOP_LABELS,
    )
    cleaned: List[str] = []
    for value in values:
        if len(value) < 3:
            continue
        if "PROJECT TITLE" in value.upper():
            continue
        cleaned.append(value)
    return cleaned


def _extract_project_title_candidates(text: str) -> List[str]:
    values = _extract_labeled_value(
        text,
        r"PROJECT\s*TITLE\s*[:\-]?",
        TITLE_BLOCK_STOP_LABELS,
    )
    cleaned: List[str] = []
    for value in values:
        normalized = normalize_text(value)
        if len(normalized) < 3:
            continue
        if _looks_like_label_heavy(normalized):
            continue
        cleaned.append(normalized)
    return cleaned


def _extract_finish_candidates(text: str) -> List[str]:
    values = _extract_labeled_value(
        text,
        r"(?:SURFACE\s+FINISH|FINISH)\s*[:\-]?",
        TITLE_BLOCK_STOP_LABELS,
    )
    cleaned: List[str] = []
    for value in values:
        normalized = _normalize_finish(value)
        normalized = re.split(r"\bPROPERTY OF\b|\bTHIS DRAWING\b", normalized, maxsplit=1, flags=re.IGNORECASE)[0].strip()
        normalized = normalize_text(normalized.rstrip(". "))
        if normalized:
            cleaned.append(normalized)
    return cleaned


def _extract_colour_candidates(text: str) -> List[str]:
    return _extract_labeled_value(
        text,
        r"(?:COLOUR|COLOR)\s*[:\-]?",
        TITLE_BLOCK_STOP_LABELS,
    )


def _extract_thickness_fallbacks(text: str) -> List[str]:
    normalized = normalize_text(text)
    values = _findall_unique(r"\b(\d+(?:\.\d+)?)\s*mm\b", normalized, flags=re.IGNORECASE)
    filtered: List[str] = []
    for value in values:
        number = _safe_float(value)
        if number is None:
            continue
        if 0.2 <= number <= 20.0 and value not in filtered:
            filtered.append(value)
    return filtered


def _extract_revision_update_thicknesses(text: str) -> List[str]:
    normalized = normalize_text(text)
    updates: List[str] = []
    for match in re.finditer(r"UPDATE\s+TO\b", normalized, flags=re.IGNORECASE):
        remainder = normalized[match.end(): match.end() + 120]
        thickness_matches = re.findall(r"(\d+(?:\.\d+)?)\s*mm\b", remainder, flags=re.IGNORECASE)
        for value in reversed(thickness_matches):
            number = _safe_float(value)
            if number is None:
                continue
            if 0.2 <= number <= 20.0 and value not in updates:
                updates.append(value)
                break
    return updates


def _infer_flat_pattern_dimensions(text: str) -> List[float]:
    upper = normalize_text(text).upper()
    if "FLAT PATTERN" not in upper:
        return []
    if upper.count("FLAT PATTERN") != 1:
        # Multi-page/document-level text often contains several flat-pattern callouts.
        # In that case, a single pair of dimensions is too ambiguous to trust here.
        return []

    focus = upper.split("DESCRIPTION:")[0]
    candidates: List[float] = []
    for match in re.finditer(r"\b(\d+(?:\.\d+)?)\b", focus):
        value = match.group(1)
        number = _safe_float(value)
        if number is None:
            continue
        if number < 20.0 or number > 5000.0:
            continue
        window = focus[max(0, match.start() - 16): min(len(focus), match.end() + 16)]
        excluded_tokens = [" EXT", " INT", "PITCH", "HOLE", "SCALE", "ANGLE", "TOLERANCE", "DETAIL", "WEIGHT"]
        if any(token in window for token in excluded_tokens):
            continue
        if re.search(r"\bR\s*\d", window):
            continue
        if number not in candidates:
            candidates.append(number)

    if len(candidates) < 2:
        return []

    ordered = sorted(candidates, reverse=True)
    chosen: List[float] = [ordered[0]]
    for value in ordered[1:]:
        if abs(value - chosen[0]) <= 15.0:
            continue
        chosen.append(value)
        if len(chosen) == 2:
            break
    return chosen if len(chosen) == 2 else []


def extract_title_block_fields(text: str) -> Dict[str, Any]:
    raw_text = text or ""
    normalized_text = normalize_text(raw_text)
    part_number_values = _extract_part_number_candidates(normalized_text)
    materials = [canonical_material(value) for value in _findall_unique(MATERIAL_PATTERN, normalized_text, flags=re.IGNORECASE)]
    drawing_numbers = _extract_drawing_number_candidates(raw_text) or _findall_unique(DRAWING_NUMBER_PATTERN, normalized_text, flags=re.IGNORECASE)
    revisions = _extract_revision_candidates(raw_text)
    dates = _findall_unique(DATE_PATTERN, normalized_text, flags=re.IGNORECASE)
    material_values = [material for material in materials if material]
    finishes = _extract_finish_candidates(raw_text) or [_normalize_finish(value) for value in _findall_unique(FINISH_PATTERN, normalized_text, flags=re.IGNORECASE)]
    thicknesses = _findall_unique(THICKNESS_PATTERN, normalized_text, flags=re.IGNORECASE) or _extract_thickness_fallbacks(raw_text)
    revision_updates = _extract_revision_update_thicknesses(raw_text)
    if revision_updates:
        ordered_thicknesses = revision_updates + [value for value in thicknesses if value not in revision_updates]
        thicknesses = ordered_thicknesses
    descriptions = _extract_description_candidates(raw_text)
    colours = _extract_colour_candidates(raw_text) or _findall_unique(COLOUR_PATTERN, normalized_text, flags=re.IGNORECASE)
    drawn_by = _extract_drawn_by_candidates(raw_text)
    modified_by = _extract_modified_by_candidates(raw_text)
    clients = _extract_client_candidates(raw_text)
    scale = _extract_scale_candidates(raw_text)
    sheet_refs = _extract_sheet_ref_candidates(raw_text)
    sheet_sizes = _extract_sheet_size_candidates(raw_text) or _findall_unique(SHEET_SIZE_PATTERN, normalized_text, flags=re.IGNORECASE)
    project_titles = _extract_project_title_candidates(raw_text)

    return {
        "drawing_numbers": drawing_numbers,
        "part_numbers": part_number_values,
        "revisions": revisions,
        "dates": dates,
        "materials": material_values,
        "surface_finishes": finishes,
        "colours": colours,
        "weights": _findall_unique(WEIGHT_PATTERN, text, flags=re.IGNORECASE),
        "drawn_by": drawn_by,
        "modified_by": modified_by,
        "sheet_refs": sheet_refs,
        "sheet_sizes": sheet_sizes,
        "scale": scale,
        "descriptions": descriptions,
        "clients": clients,
        "project_titles": project_titles,
        "quantities": _findall_unique(QUANTITY_PATTERN, normalized_text, flags=re.IGNORECASE),
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


def merge_title_block_fields(primary: Dict[str, Any], fallback: Dict[str, Any]) -> Dict[str, Any]:
    drawing_numbers = _pick_preferred(primary, fallback, "drawing_numbers")
    part_numbers = _pick_preferred(primary, fallback, "part_numbers")
    revisions = _pick_preferred(primary, fallback, "revisions")
    dates = _pick_preferred(primary, fallback, "dates")
    materials = _pick_preferred(primary, fallback, "materials")
    finishes = _pick_preferred(primary, fallback, "surface_finishes")
    thicknesses = _pick_preferred(primary, fallback, "thicknesses_mm")

    merged = {
        "drawing_numbers": drawing_numbers,
        "part_numbers": part_numbers,
        "revisions": revisions,
        "dates": dates,
        "materials": materials,
        "surface_finishes": finishes,
        "colours": _pick_preferred(primary, fallback, "colours"),
        "weights": _pick_preferred(primary, fallback, "weights"),
        "drawn_by": _pick_preferred(primary, fallback, "drawn_by"),
        "modified_by": _pick_preferred(primary, fallback, "modified_by"),
        "sheet_refs": _pick_preferred(primary, fallback, "sheet_refs"),
        "sheet_sizes": _pick_preferred(primary, fallback, "sheet_sizes"),
        "scale": _pick_preferred(primary, fallback, "scale"),
        "descriptions": _pick_preferred(primary, fallback, "descriptions"),
        "clients": _pick_preferred(primary, fallback, "clients"),
        "project_titles": _pick_preferred(primary, fallback, "project_titles"),
        "quantities": _pick_preferred(primary, fallback, "quantities"),
        "thicknesses_mm": thicknesses,
    }
    merged["normalized"] = {
        "primary_material": _prefer_best_scalar(primary.get("normalized", {}).get("primary_material"), fallback.get("normalized", {}).get("primary_material")),
        "primary_finish": _prefer_best_scalar(primary.get("normalized", {}).get("primary_finish"), fallback.get("normalized", {}).get("primary_finish")),
        "primary_thickness_mm": _prefer_best_scalar(primary.get("normalized", {}).get("primary_thickness_mm"), fallback.get("normalized", {}).get("primary_thickness_mm")),
    }
    merged["confidence"] = {
        "drawing_numbers": max(primary.get("confidence", {}).get("drawing_numbers", 0.0), fallback.get("confidence", {}).get("drawing_numbers", 0.0)),
        "part_numbers": max(primary.get("confidence", {}).get("part_numbers", 0.0), fallback.get("confidence", {}).get("part_numbers", 0.0)),
        "revisions": max(primary.get("confidence", {}).get("revisions", 0.0), fallback.get("confidence", {}).get("revisions", 0.0)),
        "dates": max(primary.get("confidence", {}).get("dates", 0.0), fallback.get("confidence", {}).get("dates", 0.0)),
        "materials": max(primary.get("confidence", {}).get("materials", 0.0), fallback.get("confidence", {}).get("materials", 0.0)),
        "surface_finishes": max(primary.get("confidence", {}).get("surface_finishes", 0.0), fallback.get("confidence", {}).get("surface_finishes", 0.0)),
        "thicknesses_mm": max(primary.get("confidence", {}).get("thicknesses_mm", 0.0), fallback.get("confidence", {}).get("thicknesses_mm", 0.0)),
    }
    return merged


def extract_bom_rows(text: str) -> List[Dict[str, Any]]:
    try:
        from part_identity import normalize_bom_row, preprocess_bom_text

        text = preprocess_bom_text(normalize_text(text))
    except Exception:
        text = normalize_text(text)
    rows: List[Dict[str, Any]] = []
    matches = re.findall(QTY_TABLE_ROW_PATTERN, text, flags=re.IGNORECASE)
    for item_no, part_no, description, qty in matches:
        normalized_part = normalize_text(part_no)
        normalized_description = normalize_text(description)
        if not _looks_like_part_number(normalized_part):
            continue
        if _looks_like_noise_description(normalized_description):
            continue
        if _safe_int(qty) is None or _safe_int(qty) <= 0 or _safe_int(qty) > 250:
            continue
        rows.append(
            {
                "item_number": item_no.strip(),
                "part_number": normalized_part,
                "description": normalized_description,
                "quantity": _safe_int(qty),
            }
        )
    if rows:
        try:
            from part_identity import normalize_bom_row

            return [normalize_bom_row(r) for r in rows]
        except Exception:
            return rows

    token_matches = re.finditer(
        r"\b(\d+)\b\s+([A-Z0-9_]+(?:\s*-\s*[A-Z0-9_]+){1,4})\s+(.+?)\s+\b(\d+)\b",
        text,
        flags=re.IGNORECASE,
    )
    for match in token_matches:
        item_no, part_no, description, qty = match.groups()
        normalized_part = normalize_text(part_no)
        normalized_description = normalize_text(description)
        if not _looks_like_part_number(normalized_part):
            continue
        if len(normalized_description) < 2:
            continue
        if _looks_like_noise_description(normalized_description):
            continue
        if _safe_int(qty) is None or _safe_int(qty) <= 0 or _safe_int(qty) > 250:
            continue
        rows.append(
            {
                "item_number": item_no.strip(),
                "part_number": normalized_part,
                "description": normalized_description,
                "quantity": _safe_int(qty),
            }
        )
    deduped_rows: List[Dict[str, Any]] = []
    seen_keys = set()
    for row in rows:
        key = (row["item_number"], row["part_number"], row["quantity"])
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped_rows.append(row)
    try:
        from part_identity import normalize_bom_row

        return [normalize_bom_row(r) for r in deduped_rows]
    except Exception:
        return deduped_rows


def classify_dimensions(text: str) -> Dict[str, Any]:
    text = normalize_text(text)
    if "GENERAL TOLERANCES" in text.upper():
        tolerance_noise_values = {"0.5", "1.0", "1.5", "2.0", "120", "1000", "2000", "4000"}
    else:
        tolerance_noise_values = set()
    overall_sizes_raw = re.findall(LENGTH_BY_WIDTH_PATTERN, text, flags=re.IGNORECASE)
    overall_sizes = [f"{left} x {right}" for left, right in overall_sizes_raw]
    slot_sizes = [f"{left} x {right}" for left, right in re.findall(SLOT_SIZE_PATTERN, text, flags=re.IGNORECASE)]

    all_dimensions_mm = _clean_dimension_candidates(_findall_unique(DIMENSION_PATTERN, text, flags=re.IGNORECASE))
    if tolerance_noise_values:
        all_dimensions_mm = [value for value in all_dimensions_mm if value not in tolerance_noise_values]
    edge_distances = _findall_unique(EDGE_DISTANCE_PATTERN, text, flags=re.IGNORECASE)
    angles = []
    for value in _findall_unique(ANGLE_PATTERN, text, flags=re.IGNORECASE):
        number = _safe_float(value)
        if number is None:
            continue
        if number < 5.0 or number > 180.0:
            continue
        angles.append(value)
    hole_candidates = _findall_unique(HOLE_PATTERN, text, flags=re.IGNORECASE) + _findall_unique(DIAMETER_HOLE_PATTERN, text, flags=re.IGNORECASE)
    hole_sizes = _dedupe_strings([value for value in hole_candidates if _is_reasonable_hole_size(value)])
    pitch_values = [value for value in _findall_unique(PITCH_PATTERN, text, flags=re.IGNORECASE) if value not in tolerance_noise_values]
    radii = _findall_unique(RADIUS_PATTERN, text, flags=re.IGNORECASE)
    fold_values = _findall_unique(FOLD_VALUE_PATTERN, text, flags=re.IGNORECASE)
    flat_pattern_dims = _infer_flat_pattern_dimensions(text)

    overall_pairs = []
    for left, right in overall_sizes_raw:
        left_num = _safe_float(left)
        right_num = _safe_float(right)
        if left_num is None or right_num is None:
            continue
        ordered = sorted([left_num, right_num], reverse=True)
        overall_pairs.append((ordered[0], ordered[1]))

    dims_float = sorted(
        [_safe_float(value) for value in all_dimensions_mm if _safe_float(value) is not None and _safe_float(value) >= 10.0],
        reverse=True,
    )
    if flat_pattern_dims:
        overall_length = flat_pattern_dims[0]
        overall_width = flat_pattern_dims[1]
        if f"{overall_length} x {overall_width}" not in overall_sizes:
            overall_sizes = [f"{overall_length} x {overall_width}"] + overall_sizes
    else:
        overall_length = overall_pairs[0][0] if overall_pairs else (dims_float[0] if len(dims_float) > 0 else None)
        overall_width = overall_pairs[0][1] if overall_pairs else (dims_float[1] if len(dims_float) > 1 else None)

    return {
        "overall_sizes_mm": overall_sizes,
        "overall_length_mm": overall_length,
        "overall_width_mm": overall_width,
        "flat_pattern_dimensions_mm": flat_pattern_dims,
        "all_dimensions_mm": all_dimensions_mm[:500],
        "angles_deg": angles,
        "hole_sizes_mm": hole_sizes,
        "pitch_values_mm": pitch_values,
        "radii_mm": radii,
        "fold_values_mm": fold_values,
        "slot_sizes_mm": slot_sizes,
        "edge_distances_mm": edge_distances,
        "counts": {
            "overall_sizes": len(overall_sizes),
            "all_dimensions_mm": len(all_dimensions_mm),
            "hole_sizes_mm": len(hole_sizes),
            "angles_deg": len(angles),
            "pitch_values_mm": len(pitch_values),
            "radii_mm": len(radii),
            "fold_values_mm": len(fold_values),
            "slot_sizes_mm": len(slot_sizes),
            "edge_distances_mm": len(edge_distances),
        },
        "confidence": {
            "overall_length_mm": _confidence(0.92 if overall_pairs else (0.65 if len(dims_float) > 0 else 0.0)),
            "overall_width_mm": _confidence(0.9 if overall_pairs else (0.6 if len(dims_float) > 1 else 0.0)),
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
        "feature_counts": {
            "hole_size_mentions": len(dimensions["hole_sizes_mm"]),
            "angle_mentions": len(dimensions["angles_deg"]),
            "fold_value_mentions": len(dimensions["fold_values_mm"]),
            "slot_size_mentions": len(dimensions["slot_sizes_mm"]),
            "radius_mentions": len(dimensions["radii_mm"]),
            "pitch_mentions": len(dimensions["pitch_values_mm"]),
        },
        "confidence": {
            "holes": _confidence(0.88 if dimensions["hole_sizes_mm"] or "HOLE" in text.upper() else 0.0),
            "folds": _confidence(0.88 if dimensions["fold_values_mm"] or dimensions["angles_deg"] or re.search(FOLD_PATTERN, text, flags=re.IGNORECASE) else 0.0),
            "slots": _confidence(0.88 if dimensions["slot_sizes_mm"] or re.search(SLOT_PATTERN, text, flags=re.IGNORECASE) else 0.0),
            "welding": _confidence(0.9 if re.search(WELD_PATTERN, text, flags=re.IGNORECASE) else 0.0),
            "tapping": _confidence(0.9 if re.search(TAP_PATTERN, text, flags=re.IGNORECASE) else 0.0),
            "countersinking": _confidence(0.9 if re.search(CSK_PATTERN, text, flags=re.IGNORECASE) else 0.0),
        },
    }


def extract_process_notes(text: str) -> Dict[str, Any]:
    text = normalize_text(text)
    note_hits: List[str] = []
    operations: List[str] = []
    operation_note_types = {
        "deburr",
        "break_sharp_edges",
        "powder_coating",
        "welding",
        "tapping",
        "countersinking",
        "laser_cutting",
        "drilling",
        "punching",
    }
    note_keywords = [
        "DEBURR",
        "BREAK",
        "POWDER",
        "WELD",
        "TAP",
        "CSK",
        "COUNTERSINK",
        "LASER",
        "DRILL",
        "PUNCH",
    ]

    for operation, pattern in PROCESS_NOTE_PATTERNS.items():
        if re.search(pattern, text, flags=re.IGNORECASE):
            note_hits.append(operation)
            if operation in operation_note_types:
                operations.append(operation)

    raw_note_snippets: List[str] = []
    for fragment in re.split(r"(?<=[.;])\s+|\s{2,}", text):
        cleaned = normalize_text(fragment)
        if not cleaned:
            continue
        alpha_count = sum(1 for char in cleaned if char.isalpha())
        digit_count = sum(1 for char in cleaned if char.isdigit())
        if alpha_count < 4:
            continue
        if digit_count > alpha_count * 1.2:
            continue
        if not any(keyword in cleaned.upper() for keyword in note_keywords):
            continue
        if any(re.search(pattern, cleaned, flags=re.IGNORECASE) for pattern in PROCESS_NOTE_PATTERNS.values()):
            raw_note_snippets.append(cleaned)

    return {
        "detected_note_types": note_hits,
        "note_snippets": raw_note_snippets[:20],
        "operations_from_notes": list(dict.fromkeys(operations)),
        "note_type_counts": _count_numeric_occurrences(note_hits),
        "confidence": _confidence(0.9 if note_hits else 0.0),
    }


def infer_operations_from_text(
    text: str,
    material: str = "",
    finishes: Optional[List[str]] = None,
    has_fold_geometry: bool = False,
    has_cut_length: bool = False,
    page_role: Optional[str] = None,
) -> List[str]:
    """
    Infer manufacturing operations from drawing text and geometry signals.

    Evidence-based: each operation needs a positive signal from text, material,
    finish list, or geometry — not blanket rules per page type.
    """
    del page_role  # reserved for future assembly-only rules
    text = normalize_text(text).upper()
    mat = material.upper() if material else ""
    fin_text = " ".join(finishes or []).upper()
    operations: List[str] = []

    is_sheet_steel = any(
        m in mat
        for m in (
            "MILD STEEL",
            "MILD_STEEL",
            "GALVANISED",
            "GALVANIZED",
            "STAINLESS",
            "ZINTEC",
            "CRS",
            "MS",
        )
    )

    laser_text = "FLAT PATTERN" in text or "LASER" in text or "PROFILE CUT" in text
    laser_steel = is_sheet_steel and (
        has_fold_geometry
        or has_cut_length
        or "FOLD" in text
        or "BEND" in text
        or re.search(ANGLE_PATTERN, text, flags=re.IGNORECASE)
    )
    if laser_text or laser_steel:
        operations.append("laser_cutting")

    # Assembly-join weld instructions ("WELD THROUGH HOLES TO SECURE LEFT FOOTBASE
    # AND RIGHT FOOTBASE TOGETHER") describe joining separate parts at a downstream
    # assembly stage — not a fab operation on THIS flat detail. Costing them as
    # welding + hole_machining over-states the part by an order of magnitude; the
    # join belongs to the assembly/weldment, not the blank.
    assembly_join_weld = bool(
        re.search(r"WELD\b[^.]*\bTOGETHER\b", text, flags=re.IGNORECASE)
        or re.search(r"SECURE\b[^.]*\bTOGETHER\b", text, flags=re.IGNORECASE)
    )

    hole_cue = "HOLE" in text or "DRILL" in text or "PUNCH" in text
    # Do not read "WELD THROUGH HOLES" (weld-locating holes joined at assembly) as a
    # machining op unless there is an independent drill/punch callout.
    if hole_cue and assembly_join_weld and "DRILL" not in text and "PUNCH" not in text:
        hole_cue = False
    if hole_cue:
        operations.append("hole_machining")

    if (
        "FOLD" in text
        or "BEND" in text
        or has_fold_geometry
        or re.search(ANGLE_PATTERN, text, flags=re.IGNORECASE)
    ):
        operations.append("folding")

    powder_text = "POWDER COAT" in text or "POWDER COATED" in text or "P/C" in text
    powder_finish = any(
        kw in fin_text for kw in ("POWDER COAT", "POWDER COATED", "POLYESTER", "EPOXY COAT")
    )
    if powder_text or powder_finish:
        operations.append("powder_coating")

    weld_keywords = (
        "WELD" in text
        or "MIG" in text
        or "TIG" in text
        or "WELD INT" in text
        or "WELD FLUSH" in text
        or "WELD CLOSED" in text
        or "WELD CORNER" in text
        or re.search(WELD_PATTERN, text, flags=re.IGNORECASE)
    )
    if weld_keywords and not assembly_join_weld:
        operations.append("welding")

    if ("DRESS" in text and "WELD" in text) or "DRESS WELD" in text or "DRESS FLUSH" in text:
        operations.append("dress_welds")

    if "WET SPRAY" in text or "SPRAY PAINT" in text or "PAINT" in fin_text:
        operations.append("wet_spray")

    if re.search(TAP_PATTERN, text, flags=re.IGNORECASE):
        operations.append("tapping")

    if re.search(CSK_PATTERN, text, flags=re.IGNORECASE):
        operations.append("countersinking")

    is_acrylic = any(m in mat for m in ("ACRYLIC", "PERSPEX", "PETG", "POLYCARBONATE"))
    if is_acrylic and "laser_cutting" not in operations:
        operations.append("laser_cutting")

    if "DIAMOND POLISH" in text or "MATT POLISH" in text or "POLISH" in text:
        operations.append("diamond_polish")

    if "GLUE" in text or "BONDING" in text or "BONDED" in text:
        operations.append("glue")

    if "CNC" in text and is_sheet_steel:
        operations.append("cnc")

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
    if feature_cues.get("weld_detected") and "welding" not in process_notes.get("operations_from_notes", []):
        review_flags.append({"severity": "info", "field": "welding", "reason": "Weld text cue detected; verify weld type and length manually."})
    if feature_cues.get("tapped_detected") and not feature_cues.get("hole_sizes_mm"):
        review_flags.append({"severity": "info", "field": "tapping", "reason": "Tapped feature indicated without clear hole size callout."})
    if feature_cues.get("countersink_detected") and not feature_cues.get("hole_sizes_mm"):
        review_flags.append({"severity": "info", "field": "countersink", "reason": "Countersink indicated without clear hole size callout."})
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
    has_cut_length: bool = False,
) -> Dict[str, Any]:
    full_text = normalize_text(text)
    title_text = normalize_text(title_block_text) or full_text
    bom_source = normalize_text(bom_text) or full_text
    notes_source = normalize_text(notes_text) or full_text

    title_block = merge_title_block_fields(extract_title_block_fields(title_text), extract_title_block_fields(full_text))
    bom_rows = extract_bom_rows(bom_source)
    dimensions = classify_dimensions(full_text)
    feature_cues = extract_feature_cues(full_text)
    process_notes = extract_process_notes(notes_source)
    page_material = " ".join(title_block.get("materials", []))
    finishes = list(title_block.get("surface_finishes") or [])
    has_fold_geometry = bool(
        feature_cues.get("fold_values_mm")
        or feature_cues.get("angles_deg")
        or feature_cues.get("fold_count_textual")
    )
    inferred_operations = infer_operations_from_text(
        full_text + " " + notes_source,
        material=page_material,
        finishes=finishes,
        has_fold_geometry=has_fold_geometry,
        has_cut_length=has_cut_length,
        page_role=page_role_hint,
    )
    operations_with_features = list(dict.fromkeys(inferred_operations + process_notes["operations_from_notes"]))
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
    primary_thickness_raw = _first_or_none(title_block["thicknesses_mm"])
    primary_thickness = _validate_thickness_for_material(
        _safe_float(primary_thickness_raw),
        primary_material or page_material,
    )

    return {
        "title_block": title_block,
        "bom_rows": bom_rows,
        "dimensions": dimensions,
        "feature_cues": feature_cues,
        "process_notes": process_notes,
        "inferred_operations": operations_with_features,
        "manufacturing_signals": {
            "feature_counts": feature_cues.get("feature_counts", {}),
            "process_note_counts": process_notes.get("note_type_counts", {}),
            "operations": operations_with_features,
        },
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
            "thickness_mm": primary_thickness,
            "normalized_thickness_mm": primary_thickness,
            "overall_length_mm": dimensions["overall_length_mm"],
            "overall_width_mm": dimensions["overall_width_mm"],
        },
    }
