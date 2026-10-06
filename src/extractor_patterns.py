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


# ── THE SPECIFICATION LEGEND IS NOT WORK — ONE READER FOR EVERY DOOR ─────────────────────
# document_builder learned this on 10975-02 (EPDM tape welded and powder coated from the border
# text) and stripped the legend before ITS operation scan. The page-level scan below never did,
# and every part takes its sheet's operations from it (part_index), so on 12173-02 (17:34 book)
# the border's "WELD SPECIFICATION: ALL WELDS TO BE TIG UNLESS STATED" — read cleanly by OCR
# where pdfplumber interleaves it — put Weld (CO2) and dressing on 29 parts: tab-and-slot
# pocket sides and shelves, the rack and trough, meshes, risers, hook saddles and an MFC back.
# The legend says HOW a weld the drawing calls up is made; it never says THAT a part is welded.
# Vocabulary in config (SPECIFICATION_LEGEND_HEADINGS / _STOPS / SPECIFICATION_DEFAULT_SENTENCES).
_LEGEND_DEFAULT_HEADINGS = [
    r"(?:FINISH|WELD(?:ING)?|CHINA MATERIAL)\s+SPECIFICATIONS?\s*:", r"GENERAL TOLERANCES\s*:",
    r"TIMBER PRODUCTS\s*:", r"GLASS:\s*NO GLASS", r"WIRING:\s*ALL ELECTRICAL"]
_LEGEND_DEFAULT_STOPS = [
    r"(?:FINISH|WELD(?:ING)?|CHINA MATERIAL)\s+SPECIFICATIONS?\s*:", r"GENERAL TOLERANCES\s*:",
    r"TIMBER PRODUCTS\s*:", r"GLASS\s*:", r"WIRING\s*:", r"DRAWING\s+No", r"DRAWN\b",
    r"CHECKED\b", r"REVISION TABLE", r"ITEM\s+DWG", r"WEIGHT\s*:", r"MATERIAL\s*:",
    r"FINISH\s*:", r"SCALE\b", r"MAX LOADING"]
_LEGEND_DEFAULT_SENTENCES = [
    r"\bALL\s+WELDS?\b[^.;\n•]{0,60}?\bUNLESS\s+(?:OTHERWISE\s+)?(?:STATED|SPECIFIED|NOTED|SHOWN|INDICATED)\b",
    r"\bRESISTANCE\s+WELDING\s+WIRE\s+TO\s+WIRE\b[^•\n]{0,80}"]
_LEGEND_RES: Dict[str, Any] = {}


def _legend_res():
    if not _LEGEND_RES:
        try:
            import config as _cfg
            heads = list(getattr(_cfg, "SPECIFICATION_LEGEND_HEADINGS", None) or _LEGEND_DEFAULT_HEADINGS)
            stops = list(getattr(_cfg, "SPECIFICATION_LEGEND_STOPS", None) or _LEGEND_DEFAULT_STOPS)
            sents = list(getattr(_cfg, "SPECIFICATION_DEFAULT_SENTENCES", None) or _LEGEND_DEFAULT_SENTENCES)
        except Exception:                                            # noqa: BLE001
            heads, stops, sents = _LEGEND_DEFAULT_HEADINGS, _LEGEND_DEFAULT_STOPS, _LEGEND_DEFAULT_SENTENCES
        _LEGEND_RES["start"] = re.compile("|".join(heads), re.IGNORECASE)
        _LEGEND_RES["stop"] = re.compile("|".join(stops), re.IGNORECASE)
        _LEGEND_RES["sentences"] = [re.compile(x, re.IGNORECASE) for x in sents]
    return _LEGEND_RES


def strip_specification_legend(text: Any) -> str:
    """The text with the specification legend removed, for OPERATION-CUE scanning only.

    Two forms are removed. A legend BLOCK runs from a heading ("WELD SPECIFICATION:") to the
    next title-block field or heading; a heading used as a stop is consumed by the next pass.
    A DEFAULT SENTENCE ("ALL WELDS TO BE TIG UNLESS STATED") is removed wherever it stands,
    because a read that lost the heading still reads the legend. Everything else — a view's
    "CORNERS TO BE WELDED", a title block's "FINISH: WELDED" — is kept."""
    s = str(text or "")
    res = _legend_res()
    out: List[str] = []
    pos = 0
    while pos < len(s):
        m = res["start"].search(s, pos)
        if not m:
            out.append(s[pos:])
            break
        out.append(s[pos:m.start()])
        stop = res["stop"].search(s, m.end())
        pos = stop.start() if stop else len(s)
    kept = " ".join(part for part in out if part)
    for rx in res["sentences"]:
        kept = rx.sub(" ", kept)
    return kept


def cites_only_specification_legend(evidence: Any) -> bool:
    """A quoted reason for a weld that is the pack's weld specification and nothing else
    ("ALL WELDS TO BE TIG UNLESS STATED"): a statement of how, not that."""
    return bool(str(evidence or "").strip()) and bool(legend_cues_set_aside(evidence))


def weld_process_stated(text: Any) -> Optional[Dict[str, Any]]:
    """The weld PROCESS a sheet's specification states, or None (D-393).

    "ALL WELDS TO BE TIG UNLESS STATED" says how a weld is made, never that a part is welded —
    strip_specification_legend removes it before any cue is read. But on a part whose own
    sheet DOES state a weld (a fillet symbol, FINISH: WELDED) the same sentence is the one
    statement of process the pack makes, and the rate card has one arc-weld row (Weld (CO2)),
    so a TIG weld is charged there. This reads the process so the row can say so.

    Matched on the text with its whitespace removed — a letter-spaced border and the squashed
    sheet text weld_symbols keeps both read the same — against config's patterns and words.
    Returns {"process", "word", "statement", "default"}; `default` is True when the sentence
    carries an "UNLESS ... STATED" clause (a pack default, not a note on this joint)."""
    squashed = re.sub(r"\s+", "", str(text or "")).upper()
    if not squashed:
        return None
    try:
        import config as _cfg
        vocab = dict(getattr(_cfg, "WELD_PROCESS_VOCAB", None) or {})
        patterns = list(getattr(_cfg, "WELD_PROCESS_STATEMENT_PATTERNS", None) or [])
    except Exception:                                                # noqa: BLE001
        vocab, patterns = {}, []
    if not vocab or not patterns:
        return None
    words = "|".join(sorted((re.escape(str(w).upper()) for w in vocab), key=len, reverse=True))
    for pat in patterns:
        try:
            m = re.search(str(pat).replace("{proc}", words), squashed)
        except re.error:
            continue
        if not m:
            continue
        word = m.group(1).upper()
        tail = squashed[m.end():m.end() + 40]
        return {"process": str(vocab.get(word) or word),
                "word": word,
                "statement": m.group(0),
                "default": bool(re.match(r"UNLESS(?:OTHERWISE)?(?:STATED|SPECIFIED|NOTED|SHOWN)",
                                         tail))}
    return None


def legend_cues_set_aside(text: Any) -> List[str]:
    """The operations a page's legend alone would have cued (weld and dressing), for the record:
    what the full text cues and the legend-stripped text does not."""
    full = normalize_text(str(text or "")).upper()
    kept = normalize_text(strip_specification_legend(text)).upper()

    def _weld(t: str) -> bool:
        return bool("WELD" in t or re.search(r"\b(?:TIG|MIG)\b", t))
    return ["welding"] if _weld(full) and not _weld(kept) else []


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


# The band a drawing prints as its GENERAL tolerance table (±0.5/1.0/1.5/2.0 by length). It
# reads as a run of thicknesses and is not a gauge. Matches document_builder._TOLERANCE_TABLE_VALUES.
_TOLERANCE_TABLE_VALUES = frozenset({0.5, 1.0, 1.5, 2.0})
_MIN_SHEET_THICKNESS_MM = 0.8


def _primary_thickness_mm(thicknesses) -> Optional[float]:
    """The title block's own stated thickness, with a tolerance table filtered out.

    8352's drawing carries a general tolerance table (0.5/1.0/1.5/2.0 by length band). Taking the
    FIRST thickness put 0.5mm on six mild-steel parts as the title block's gauge; the model then
    had to overrule each one, flagging a gauge disagreement that was pure noise. A LONE 2.0 is a
    real gauge and must survive, but 2.0 sitting inside the whole band is a tolerance value — so
    the band is only stripped when the WHOLE of it is present, exactly as the costing picker
    decides. What survives, at or above the sheet floor, is the stated gauge; nothing surviving
    means the title block named no thickness of its own, and None is the honest answer.
    """
    floats = []
    for v in thicknesses or ():
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f > 0:
            floats.append(f)
    if not floats:
        return None
    if _TOLERANCE_TABLE_VALUES <= {round(f, 1) for f in floats}:
        floats = [f for f in floats if round(f, 1) not in _TOLERANCE_TABLE_VALUES]
    for f in floats:
        if f >= _MIN_SHEET_THICKNESS_MM:
            return f
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
    # Dates are blanked before the scan. A title block puts a date immediately after a name —
    # "DRAWN BY: P.Andrew - 14/11/2023" — and the day of the month then completes a part number
    # that the name started. Masking the date leaves "P.Andrew - " with nothing to pair with.
    #
    # This is the second of two defences; config's PART_NUMBER_PATTERN also requires a digit in
    # the head. Either would have stopped ANDREW-14 on its own, and the title block is the one
    # place on a drawing where prose and part numbers sit this close together.
    masked = re.sub(DATE_PATTERN, lambda m: " " * len(m.group(0)), text or "", flags=re.IGNORECASE)
    candidates: List[str] = []
    for pattern in PART_NUMBER_PATTERNS:
        candidates.extend(_findall_unique(pattern, masked, flags=re.IGNORECASE))
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
    # The head has to carry a digit. A pure-alpha head is prose: ANDREW-14 was a draughtsman and
    # a date, PANEL-02 is a note. Real codes are 10575-02, BE2030-10, 12173-02-GA. The rule lives
    # here as well as in the pattern so it holds for every route into this filter, not only the
    # one regex that happened to produce the fault.
    if parts and not any(ch.isdigit() for ch in parts[0]):
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


def _table_column_words() -> set:
    """The parts-table column headers (config PARTS_TABLE_COLUMN_WORDS; the parts-list
    reader's own header words when config does not say)."""
    words = None
    try:
        import config as _cfg
        words = getattr(_cfg, "PARTS_TABLE_COLUMN_WORDS", None)
    except Exception:                                            # noqa: BLE001
        words = None
    if not words:
        # The parts-list reader's header words (_bom_words_reader.HEADER_TOKENS), written
        # out rather than imported: this module ships to the scan service, and importing the
        # reader there would pull the whole table extractor after it for a default.
        words = ("ITEM", "DWG", "NO", "NO.", "DESCRIPTION", "QTY", "QTY.")
    return {str(w).strip().upper() for w in words if str(w).strip()}


def starts_with_a_table_column(value: Any) -> bool:
    """True when a value begins with a parts-table column header — the head of a table read
    as if it were a title field ("QTY 1 <code> FRONT FRAME ASSEMBLY 1 …")."""
    tokens = str(value or "").strip().split()
    if not tokens:
        return False
    return tokens[0].upper().rstrip(":") in _table_column_words()


def _extract_description_candidates(text: str, refused: Optional[List[str]] = None) -> List[str]:
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
        # A DESCRIPTION LABEL FOLLOWED BY ANOTHER COLUMN HEADER IS A TABLE HEAD, NOT A TITLE.
        # 12173-02: on SDI's template "DESCRIPTION" is only the parts list's column, so the
        # value after it began "QTY 1 12173-03-202 FRONT FRAME ASSEMBLY 1 …" and frame weld
        # 201 was titled with row 1 of its own parts list. Every DESCRIPTION candidate on the
        # four sheets read was parts-table text. Refused here; nothing invented in its place —
        # the refused text is kept (title block `descriptions_refused`) so the graph can say
        # that no reader titled the part.
        if starts_with_a_table_column(value):
            if refused is not None:
                refused.append(value)
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


# Cross-reference / placeholder phrases a MATERIAL field may carry on GA / parent sheets
# ("MATERIAL: SEE INDIVIDUAL DRAWINGS") — these are NOT materials and must not be accepted
# as one when the keyword list doesn't recognise the labelled value.
def is_cross_reference_note(value: Any) -> bool:
    """True when a MATERIAL or FINISH value is an instruction, not an answer.

    "REFER TO INDIVIDUAL COMPONENT DRAWINGS" is what a GA puts in those fields when the real
    values live on the component sheets. It is not a material and it is not a finish, and on
    10575-02 the engine stored it as both: the material could not be priced (£0.00) and no finish
    was ever routed, so a powder-coated job carried £0.00 of powder and £0.00 of P.Coat labour.
    Nothing failed. The job was simply costed as though the parts were made of nothing and
    finished with nothing.

    The guard already existed — `_MATERIAL_REF_NOTE_RE`, below — but only on the title-block
    reader. This value arrived from `llm_full_extract`, a different path with no such check, and
    that is the hole. Exported so every path that accepts a material or a finish can use the ONE
    definition rather than growing its own.
    """
    return bool(_MATERIAL_REF_NOTE_RE.search(normalize_text(value).upper())) if value else False


_MATERIAL_REF_NOTE_RE = re.compile(
    r"\b(SEE|REFER|INDIVIDUAL|ASSEMBLY|DRAWING|DRAWINGS|SHOWN|ABOVE|BELOW|VARIOUS|"
    r"AS\s+PER|TBC|TBA|N/?A|NONE)\b",
    re.IGNORECASE,
)


def _extract_material_candidates(text: str) -> List[str]:
    """Labelled 'MATERIAL:' extraction — the authoritative part callout, read the same
    way FINISH and COLOUR are (rather than a whole-page keyword scan). Excludes the
    'MATERIAL SPECIFICATION(S)' legend heading via negative lookahead so the generic
    grade table (Q195/Q235/SPCC/TIMBER PRODUCTS) can never masquerade as the part's
    material. Returns cleaned material tokens: a known keyword if one sits inside the
    labelled value, else the short labelled callout itself (e.g. 'MARINE PLY', 'TILES')
    so downstream family mapping can resolve materials the keyword list doesn't list."""
    values = _extract_labeled_values(
        text,
        r"MATERIAL(?!\s*SPEC)\s*[:\-]",
        TITLE_BLOCK_STOP_LABELS,
    )
    out: List[str] = []
    for value in values:
        # a cramped title block can run the labelled field straight into the legend text,
        # and straight into the sheet's standing notes — "16mm MFC DO NOT SCALE" is one
        # value to the reader and two facts to a person. Truncate at the note, then blank
        # the legend phrases; what is left is the callout.
        v = _strip_material_boilerplate(
            _truncate_at_drawing_note(normalize_text(value))).strip(" :;-,.")
        if not v:
            continue
        keyword_hits = _findall_unique(MATERIAL_PATTERN, v, flags=re.IGNORECASE)
        if keyword_hits:
            out.extend(keyword_hits)
        elif (len(v) <= 25 and re.fullmatch(r"[A-Za-z][A-Za-z /+.\-]*", v)
              and not _MATERIAL_REF_NOTE_RE.search(v)):
            # a short alpha callout the keyword list does not yet know (e.g. MARINE PLY,
            # TILES) — but NOT a cross-reference note like "SEE INDIVIDUAL DRAWINGS" that
            # a GA/parent sheet puts in its MATERIAL field. Those fall through to the
            # keyword fallback / engine default instead of becoming a bogus material.
            out.append(v)
        elif len(v) <= 40 and _print_stock_weight_re().search(v.upper()):
            # A STOCK NAMED BY ITS WEIGHT (D-402): "400 MIC", "300 GSM SILK". The alpha arm
            # refused it for its digits, the page scan ran instead, and the legend's words
            # became the part's material. The callout is the sheet's answer; kept as printed.
            out.append(v)
    seen: set = set()
    unique: List[str] = []
    for token in out:
        key = token.upper()
        if key not in seen:
            seen.add(key)
            unique.append(token)
    return unique


# A TOLERANCE IS NOT A GAUGE (D-392). The M&S border prints "OVER 120mm UP TO 1000mm +/-1.0mm"
# beside the coating paragraph's "THICKNESS COVERAGE", and the text layer runs them together:
# "+/-1.0mm THICKNESS" read as a 1 mm gauge on every sheet of 12696-01 and 12173-02, and the
# fallback scan took every "+/-0.5mm ... +/-2.0mm" as a candidate too. A figure that follows a
# tolerance sign is a tolerance, whatever word follows it.
_TOLERANCE_FIGURE_RE = re.compile(r"(?:\+/-|±|\+-|-/\+|\+\s*/\s*-)\s*\d+(?:\.\d+)?\s*(?:MM|mm)?",
                                  re.IGNORECASE)


def _text_for_gauges(text: str) -> str:
    """The page text a gauge may be read from: tolerances and the specification legend removed."""
    return _TOLERANCE_FIGURE_RE.sub(" ", strip_specification_legend(normalize_text(text)))


def _extract_thickness_fallbacks(text: str) -> List[str]:
    normalized = _text_for_gauges(text)
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


# ── Spec-legend boilerplate that carries material words in a NON-part context ──
# Retail-display drawings (M&S and others) print a standard MATERIAL SPECIFICATIONS
# legend that lists generic material categories and grade rules for the WHOLE product
# range, e.g. "... UP TO 3mm THICK FOR POWDER COATED STEEL ... TIMBER PRODUCTS:
# • Q235 OVER 3mm THICK ...". The word TIMBER in "TIMBER PRODUCTS:" is a SECTION
# HEADER in that legend, not a statement that this part is made of timber. Because
# the material scan reads the whole page, that header (and "WOOD PRODUCTS") gets
# stamped onto steel parts whose own material callout is absent on the page — the
# part is then routed through the timber/joinery path (saw/glue/CNC) in error.
# Strip these boilerplate phrases before scanning so ONLY genuine callouts remain.
# This never removes a real material: no drawing writes "TIMBER PRODUCTS" to mean
# the part IS timber, and a genuine timber part keeps its own standalone TIMBER/
# MDF/PLYWOOD callout (not followed by "PRODUCTS"). General across every drawing
# that carries the legend, not a per-job patch.
_MATERIAL_BOILERPLATE_RE = re.compile(
    r"\bTIMBER\s+PRODUCTS\b"
    r"|\bWOOD\s+PRODUCTS\b"
    r"|\bMATERIAL\s+SPECIFICATIONS?\b"
    r"|\bFOR\s+POWDER\s+COATED\s+STEEL\b"
    r"|\bFOR\s+CHROME[,\s]+ZINC\s+PLATE\b"
    # ── A RAL COLOUR NAME IS NOT A MATERIAL ─────────────────────────────────────────
    #
    # 12552's 02-09M is MILD STEEL powder coated RAL9006, whose registered name is WHITE
    # ALUMINIUM. Its title block extracts as labels-then-values, so "MATERIAL:" is followed
    # immediately by "COLOUR:" and the labelled read returns nothing; the whole-page keyword
    # fallback then scans the page and finds ALUMINIUM — inside the colour name — BEFORE it
    # reaches MILD STEEL, and _first_or_none takes the first. A 1.5 mm steel cover is costed
    # as aluminium: a third of the density, a different rate, a different supplier.
    #
    # RAL's own palette is full of these. 9006 White Aluminium, 9007 Grey Aluminium, 8004
    # Copper Brown, 9022 Pearl Light Grey. Any of them lands a metal word on a page whose
    # part is made of something else, and the more carefully a drawing office names its
    # colour the worse the misread gets.
    #
    # Blanked as a phrase, not as a word: "ALUMINIUM" on its own is still a perfectly good
    # material callout, and a part genuinely made of aluminium and coated RAL9006 still reads
    # correctly from its MATERIAL field or from any other mention on the sheet.
    # The words between the RAL code and the metal word must not themselves be material
    # words. Without that guard the filler is greedy: on "RAL9006 WHITE ALUMINIUM MILD STEEL"
    # it swallows "WHITE ALUMINIUM MILD " to reach STEEL, and blanks the part's real material
    # along with the colour name — turning a misread into a blank, which is worse.
    r"|\bRAL\s*\d{3,4}[\s\-–—:]*"
    r"(?:(?!ALUMINIUM|ALUMINUM|COPPER|SILVER|BRASS|BRONZE|STEEL|MILD|GOLD)[A-Z]+[\s\-]+){0,2}"
    r"(?:ALUMINIUM|ALUMINUM|COPPER|SILVER|BRASS|BRONZE|GOLD)\b",
    re.IGNORECASE,
)

# WHERE THE MATERIAL FIELD ENDS AND THE DRAWING'S STANDING NOTES BEGIN.
#
# A cramped title block runs the labelled value straight into the sheet's boilerplate, and
# the labelled-value reader has no other signal for where to stop. On 12422-24 the end cap's
# "MATERIAL: 16mm MFC" ran into "DO NOT SCALE" and, because the keyword list did not know
# MFC, the whole run reached the sheet as the material "MFC DO NOT" — in the BOM
# description, in the labour block, and in the group key that decides which parts share a
# setup.
#
# These are the phrases every engineering drawing carries and no material ever contains, so
# the value is TRUNCATED at the first one rather than blanked: what precedes it is the
# genuine callout and must survive. config.JUNK_PART_TOKENS is the same idea applied to part
# numbers; a phrase that disqualifies a part number cannot be part of a material either.
_MATERIAL_NOTE_START_RE = re.compile(
    r"\b(?:DO\s+NOT(?:\s+SCALE)?"
    r"|ALL\s+DIMENSIONS?"
    r"|UNLESS\s+(?:OTHERWISE\s+)?(?:STATED|SPECIFIED)"
    r"|REMOVE\s+(?:ALL\s+)?BURRS?"
    r"|TOLERANCES?\b"
    r"|THIS\s+DRAWING"
    r"|PROPERTY\s+OF"
    r"|CONFIDENTIAL"
    r"|REF(?:ERENCE)?\s+ONLY"
    r"|THIRD\s+ANGLE"
    r"|SCALE\s*[:=]"
    r"|BREAK\s+SHARP\s+EDGES?)\b",
    re.IGNORECASE,
)


def _truncate_at_drawing_note(text: str) -> str:
    """The part of a labelled value that precedes the sheet's standing notes."""
    match = _MATERIAL_NOTE_START_RE.search(text or "")
    return (text or "")[:match.start()] if match else (text or "")


# A REVISION NOTE THAT REMOVES SOMETHING IS NOT A MATERIAL CALLOUT.
#
# On 10575-02 the note "MDF PANEL REMOVED" set the part's material to MDF and it was priced as
# board. The note records what came OFF the drawing; the keyword scan saw only the letters.
#
# Same shape as the spec-legend leak above — a material word in a non-part context — so it is
# handled the same way, by blanking before the scan rather than by second-guessing afterwards.
_MATERIAL_NEGATION_RE = re.compile(
    r"\b(?:REMOVED|DELETED|OMITTED|SUPERSEDED|CANCELLED|CANCELED"
    r"|NOT\s+(?:USED|REQUIRED|APPLICABLE)"
    r"|NO\s+LONGER\s+(?:USED|REQUIRED|APPLIES))\b",
    re.IGNORECASE,
)
# How far a removal verb may sit from the material word and still be about it. Short on purpose:
# a verb at the other end of the sheet is describing something else, and letting it reach back
# would lose genuine callouts.
_NEGATION_WINDOW_CHARS = 30


def _strip_negated_materials(text: str) -> str:
    """Blank material words that a nearby removal verb says are not there.

    Only the material token is blanked, never the clause around it. A drawing carrying
    "MATERIAL: MDF" and, separately, "REV C ALUMINIUM PANEL REMOVED" must keep MDF and drop
    ALUMINIUM — blanking the clause would have taken both.

    Proximity to a revision marker is deliberately NOT the signal. Revision blocks are where
    material changes are recorded, and "REV D MATERIAL NOW 18MM MDF" is the most authoritative
    statement of material on the sheet. Negation is the signal.
    """
    src = text or ""
    out = list(src)
    for match in re.finditer(MATERIAL_PATTERN, src, flags=re.IGNORECASE):
        window = src[match.end():match.end() + _NEGATION_WINDOW_CHARS]
        verb = _MATERIAL_NEGATION_RE.search(window)
        if not verb:
            continue
        # Another material word between this one and the verb means the verb belongs to that
        # one, not to this. Without the check a labelled callout loses to a later note.
        if re.search(MATERIAL_PATTERN, window[:verb.start()], flags=re.IGNORECASE):
            continue
        for i in range(match.start(), match.end()):
            out[i] = " "
    return "".join(out)


_VOCAB_RES: Dict[str, Any] = {}


def _print_stock_weight_re():
    if "print_stock" not in _VOCAB_RES:
        try:
            import config as _cfg
            _pat = getattr(_cfg, "PRINT_STOCK_WEIGHT_PATTERN", None)
        except Exception:                                            # noqa: BLE001
            _pat = None
        _VOCAB_RES["print_stock"] = re.compile(
            _pat or r"^\s*\d+(?:\.\d+)?\s*(?:MIC|MICRONS?|MU|GSM|G/?M2)\b", re.IGNORECASE)
    return _VOCAB_RES["print_stock"]


def _material_legend_re():
    if "legend" not in _VOCAB_RES:
        try:
            import config as _cfg
            _phr = list(getattr(_cfg, "MATERIAL_LEGEND_PHRASES", None) or [])
        except Exception:                                            # noqa: BLE001
            _phr = []
        _VOCAB_RES["legend"] = re.compile("|".join(_phr), re.IGNORECASE) if _phr else None
    return _VOCAB_RES["legend"]


def _strip_material_boilerplate(text: str) -> str:
    """Blank out standard spec-legend phrases that carry a material word in a
    non-part context (legend headers, grade-rule bullets) so they cannot set the
    part's material family. Genuine part callouts are untouched."""
    out = _MATERIAL_BOILERPLATE_RE.sub(" ", text or "")
    _legend = _material_legend_re()
    if _legend is not None:
        out = _legend.sub(" ", out)
    return _strip_negated_materials(out)


def material_field_states_something(text: str) -> bool:
    """Does a labelled MATERIAL field on this text name a material — resolved or not (D-402)?

    A field that names something is the sheet's answer, and the whole-page keyword scan must
    not run over it: 9598-02-02G's "MATERIAL: 400 MIC" was refused by the keyword list, the
    page was scanned instead, and the legend's TIMBER became the graphic's material. A
    pointer ("REFER TO INDIVIDUAL COMPONENT DRAWINGS") or a bare gauge ("2MM") names nothing."""
    for value in _extract_labeled_values(text or "", r"MATERIAL(?!\s*SPEC)\s*[:\-]",
                                         TITLE_BLOCK_STOP_LABELS):
        v = _strip_material_boilerplate(_truncate_at_drawing_note(normalize_text(value))).strip(" :;-,.")
        if not v or _MATERIAL_REF_NOTE_RE.search(v):
            continue
        if re.search(r"[A-Za-z]{3,}", v) and not re.fullmatch(r"[\d.\s]*MM\s*(?:THK|THICK)?", v, re.IGNORECASE):
            return True
    return False


def extract_title_block_fields(text: str) -> Dict[str, Any]:
    raw_text = text or ""
    normalized_text = normalize_text(raw_text)
    part_number_values = _extract_part_number_candidates(normalized_text)
    # Material is read PRIMARY from the labelled "MATERIAL:" field (authoritative, the
    # same way FINISH/COLOUR are extracted). Only when no labelled callout exists do we
    # fall back to a whole-page keyword scan — and that scan runs on de-boilerplated text
    # so the spec-legend "TIMBER PRODUCTS:" header and grade bullets can never be read as
    # the part's material. This asymmetry (labelled FINISH/COLOUR but keyword MATERIAL)
    # was the source of the family leak that put TIMBER on steel detail sheets.
    # NOT pre-stripped here: _extract_material_candidates already runs the labelled value
    # through _strip_material_boilerplate, which now carries the negation strip. Doing it twice
    # collapses the blanked run of spaces and brings the removal verb within reach of the
    # labelled callout itself — "MATERIAL: MDF ... ALUMINIUM PANEL REMOVED" then lost MDF too.
    labelled_materials = _extract_material_candidates(raw_text)
    if labelled_materials:
        materials = [canonical_material(value) for value in labelled_materials]
    elif material_field_states_something(raw_text):
        # THE FIELD NAMED SOMETHING THE READER COULD NOT RESOLVE (D-402). That is the sheet's
        # answer, recorded as unresolved by the readers downstream; the page is NOT scanned,
        # because the page's other material words are the legend's and another part's.
        materials = []
    else:
        # The page scan runs with the specification legend removed as well as the standing
        # phrases: "• 304 - STAINLESS STEEL" and "WHERE SPECIFIED ALL TIMBER-BASED PRODUCTS"
        # are the border's words on every sheet, never this part's (D-402).
        material_scan_text = _strip_material_boilerplate(strip_specification_legend(normalized_text))
        materials = [canonical_material(value) for value in _findall_unique(MATERIAL_PATTERN, material_scan_text, flags=re.IGNORECASE)]
    drawing_numbers = _extract_drawing_number_candidates(raw_text) or _findall_unique(DRAWING_NUMBER_PATTERN, normalized_text, flags=re.IGNORECASE)
    revisions = _extract_revision_candidates(raw_text)
    dates = _findall_unique(DATE_PATTERN, normalized_text, flags=re.IGNORECASE)
    material_values = [material for material in materials if material]
    finishes = _extract_finish_candidates(raw_text) or [_normalize_finish(value) for value in _findall_unique(FINISH_PATTERN, normalized_text, flags=re.IGNORECASE)]
    # A GAUGE IS A SHEET OR BOARD THICKNESS (D-392): "UP TO 1000mm" running into the coating
    # paragraph's "THICKNESS COVERAGE" is not one, whatever the words beside it.
    thicknesses = [value for value in _findall_unique(THICKNESS_PATTERN, _text_for_gauges(raw_text), flags=re.IGNORECASE)
                   if (_safe_float(value) is not None and 0.2 <= _safe_float(value) <= 50.0)] \
        or _extract_thickness_fallbacks(raw_text)
    revision_updates = _extract_revision_update_thicknesses(raw_text)
    if revision_updates:
        ordered_thicknesses = revision_updates + [value for value in thicknesses if value not in revision_updates]
        thicknesses = ordered_thicknesses
    descriptions_refused: List[str] = []
    descriptions = _extract_description_candidates(raw_text, descriptions_refused)
    colours =_extract_colour_candidates(raw_text) or _findall_unique(COLOUR_PATTERN, normalized_text, flags=re.IGNORECASE)
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
        "descriptions_refused": descriptions_refused,
        "clients": clients,
        "project_titles": project_titles,
        "quantities": _findall_unique(QUANTITY_PATTERN, normalized_text, flags=re.IGNORECASE),
        "thicknesses_mm": thicknesses,
        "normalized": {
            "primary_material": _first_or_none(material_values),
            "primary_finish": _first_or_none(finishes),
            "primary_thickness_mm": _primary_thickness_mm(thicknesses),
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
        "descriptions_refused": _pick_preferred(primary, fallback, "descriptions_refused"),
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


def extract_bom_rows(text: str, *, source: str = "bom_table",
                     source_page: Optional[int] = None) -> List[Dict[str, Any]]:
    """Parts-table rows from a page's text, EACH ONE STAMPED WITH WHO READ IT AND WHERE.

    WHY THE STAMP IS NOT A NICETY. Six readers can produce a BOM row — this table parser, the
    vision model, the SolidWorks API, the whole-document LLM pass, the assembly tree and the DXF
    filename — and until now not one row carried which. Every artefact that tried to show an
    estimator where a line came from printed a blank, and the quality of a reader could not be
    judged from its output because its output was anonymous.

    It also unlocks the material. The parts table on an SDI drawing frequently has no material
    column at all — the material is in the title block of the detail sheet — so the honest way
    to fill "material" against a row is to resolve it from the page the row was read from, which
    is impossible while the row does not know its page.
    """
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
                # WHO READ IT AND WHERE. Stamped at the point of creation, because anywhere
                # later is a guess: by the time rows from several pages and several readers have
                # been merged, nothing can say which of them produced a given line.
                "source": source,
                "source_page": source_page,
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
                # WHO READ IT AND WHERE. Stamped at the point of creation, because anywhere
                # later is a guess: by the time rows from several pages and several readers have
                # been merged, nothing can say which of them produced a given line.
                "source": source,
                "source_page": source_page,
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
        # The legend's "ALL WELDS TO BE TIG" is not a weld on this sheet (see
        # strip_specification_legend): the cue, and the "Weld text cue detected" flag it
        # raises, read the text without it.
        "weld_detected": bool(re.search(WELD_PATTERN, strip_specification_legend(text),
                                        flags=re.IGNORECASE)),
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
            "welding": _confidence(0.9 if re.search(WELD_PATTERN, strip_specification_legend(text),
                                                    flags=re.IGNORECASE) else 0.0),
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
        # A finish note naming ONE face ("PAINTED TOP FACE", 12173-03-02J) is kept so the
        # coated-area reader can see it; it adds no operation (config "finish_one_face").
        "FACE",
    ]

    _weld_text = strip_specification_legend(text)
    for operation, pattern in PROCESS_NOTE_PATTERNS.items():
        # A weld is read from the notes with the legend taken out: the border's weld
        # specification is not a weld note on this sheet.
        _t = _weld_text if operation == "welding" else text
        if re.search(pattern, _t, flags=re.IGNORECASE):
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
    # Metal holes are laser-cut (fold into the laser profile) — no separate op, matching
    # shop practice and Tim's sheets (metal has no hole op; only "Drill (Acrylic)" exists).
    # Only acrylic/plastic parts (not is_sheet_steel) get a genuine separate drilling op.
    if hole_cue and not is_sheet_steel:
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

    # A WELD IS READ OFF THE SHEET, NOT OFF ITS BORDER. "WELD SPECIFICATION: ALL WELDS TO BE
    # TIG UNLESS STATED" and "RESISTANCE WELDING WIRE TO WIRE" print on every sheet of the pack
    # and say how a weld is made, not that this part has one (12173-02: 29 parts welded and
    # dressed from it). Weld and dressing cues read the text with the legend removed; "FINISH:
    # WELDED", "WELD AND DRESS" and "CORNERS TO BE WELDED" are the sheet's own and are kept.
    weld_text = normalize_text(strip_specification_legend(text)).upper()
    weld_keywords = (
        "WELD" in weld_text
        or re.search(r"\bMIG\b", weld_text, flags=re.IGNORECASE)
        or re.search(r"\bTIG\b", weld_text, flags=re.IGNORECASE)
        or "WELD INT" in weld_text
        or "WELD FLUSH" in weld_text
        or "WELD CLOSED" in weld_text
        or "WELD CORNER" in weld_text
        or re.search(WELD_PATTERN, weld_text, flags=re.IGNORECASE)
    )
    if weld_keywords and not assembly_join_weld:
        operations.append("welding")

    if ("DRESS" in weld_text and "WELD" in weld_text) or "DRESS WELD" in weld_text \
            or "DRESS FLUSH" in weld_text:
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

    # diamond_polish only on a GENUINE polish cue. Bare "POLISH" was matching the standard
    # boilerplate "CHROME PLATING - POLISHING SPECIFICATION IS 400 GRIT FINAL POLISH", which
    # sits on every page, inventing a diamond-polish op on parts that are powder coated / raw.
    # Suppress bare "POLISH" when it only appears in that spec-legend context.
    _polish_boilerplate = ("POLISHING SPECIFICATION" in text
                           or "FINAL POLISH" in text
                           or "GRIT" in text)
    _genuine_polish_cue = ("DIAMOND POLISH" in text or "MATT POLISH" in text
                           or "MIRROR POLISH" in text or "FLAME POLISH" in text
                           or "EDGE POLISH" in text)
    if _genuine_polish_cue or ("POLISH" in text and not _polish_boilerplate):
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
    source_page: Optional[int] = None,
) -> Dict[str, Any]:
    full_text = normalize_text(text)
    title_text = normalize_text(title_block_text) or full_text
    bom_source = normalize_text(bom_text) or full_text
    notes_source = normalize_text(notes_text) or full_text

    title_block = merge_title_block_fields(extract_title_block_fields(title_text), extract_title_block_fields(full_text))
    bom_rows = extract_bom_rows(bom_source, source_page=source_page)
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
