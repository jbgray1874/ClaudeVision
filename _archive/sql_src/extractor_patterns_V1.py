import re
from typing import Any, Dict, List, Optional

from config import (
    ANGLE_PATTERN,
    CLIENT_PATTERN,
    COLOUR_PATTERN,
    DATE_PATTERN,
    DESCRIPTION_PATTERN,
    DIMENSION_PATTERN,
    DRAWN_BY_PATTERN,
    DWG_NO_PATTERN,
    FINISH_PATTERN,
    FLAT_PATTERN_PATTERN,
    FOLD_PATTERN,
    FOLD_VALUE_PATTERN,
    HOLE_PATTERN,
    MATERIAL_PATTERN,
    MODIFIED_BY_PATTERN,
    PART_NUMBER_PATTERN,
    PITCH_PATTERN,
    PROJECT_TITLE_PATTERN,
    QTY_TABLE_ROW_PATTERN,
    QUANTITY_PATTERN,
    RADIUS_PATTERN,
    REVISION_PATTERN,
    SCALE_PATTERN,
    SHEET_PATTERN,
    SHEET_SIZE_PATTERN,
    SLOT_PATTERN,
    TAP_PATTERN,
    THICKNESS_PATTERN,
    WEIGHT_PATTERN,
    WELD_PATTERN,
    CSK_PATTERN,
    LASER_PATTERN,
)


def normalize_text(text: str) -> str:
    return " ".join((text or "").replace("\x00", " ").split())


def _findall_unique(pattern: str, text: str, flags: int = 0) -> List[str]:
    matches = re.findall(pattern, text, flags=flags)
    flattened = []
    for match in matches:
        if isinstance(match, tuple):
            values = [str(x).strip() for x in match if str(x).strip()]
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


def canonical_material(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    cleaned = normalize_text(value).upper()
    aliases = {
        "ALUMINUM": "ALUMINIUM",
        "ALU": "ALUMINIUM",
    }
    return aliases.get(cleaned, cleaned)



def extract_title_block_fields(text: str) -> Dict[str, Any]:
    text = normalize_text(text)
    materials = [canonical_material(v) for v in _findall_unique(MATERIAL_PATTERN, text, flags=re.IGNORECASE)]
    return {
        "drawing_numbers": _findall_unique(DWG_NO_PATTERN, text, flags=re.IGNORECASE),
        "part_numbers": _findall_unique(PART_NUMBER_PATTERN, text, flags=re.IGNORECASE),
        "revisions": _findall_unique(REVISION_PATTERN, text, flags=re.IGNORECASE),
        "dates": _findall_unique(DATE_PATTERN, text, flags=re.IGNORECASE),
        "materials": [m for m in materials if m],
        "surface_finishes": _findall_unique(FINISH_PATTERN, text, flags=re.IGNORECASE),
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
        "thicknesses_mm": _findall_unique(THICKNESS_PATTERN, text, flags=re.IGNORECASE),
    }



def extract_bom_rows(text: str) -> List[Dict[str, Any]]:
    text = normalize_text(text)
    rows = []
    matches = re.findall(QTY_TABLE_ROW_PATTERN, text, flags=re.IGNORECASE)
    for item_no, part_no, description, qty in matches:
        rows.append(
            {
                "item_number": item_no.strip(),
                "part_number": normalize_text(part_no),
                "description": normalize_text(description),
                "quantity": int(qty),
            }
        )
    return rows



def extract_feature_cues(text: str) -> Dict[str, Any]:
    text = normalize_text(text)

    hole_values = _findall_unique(HOLE_PATTERN, text, flags=re.IGNORECASE)
    angle_values = _findall_unique(ANGLE_PATTERN, text, flags=re.IGNORECASE)
    pitch_values = _findall_unique(PITCH_PATTERN, text, flags=re.IGNORECASE)
    radius_values = _findall_unique(RADIUS_PATTERN, text, flags=re.IGNORECASE)
    fold_values = _findall_unique(FOLD_VALUE_PATTERN, text, flags=re.IGNORECASE)
    dimensions = _findall_unique(DIMENSION_PATTERN, text, flags=re.IGNORECASE)

    return {
        "angles_deg": angle_values,
        "hole_sizes_mm": hole_values,
        "pitch_values_mm": pitch_values,
        "radii_mm": radius_values,
        "fold_values_mm": fold_values,
        "all_dimensions_mm": dimensions[:500],
        "fold_count_textual": len(re.findall(FOLD_PATTERN, text, flags=re.IGNORECASE)),
        "flat_pattern_detected": bool(re.search(FLAT_PATTERN_PATTERN, text, flags=re.IGNORECASE)),
        "slot_detected": bool(re.search(SLOT_PATTERN, text, flags=re.IGNORECASE)),
        "laser_text_detected": bool(re.search(LASER_PATTERN, text, flags=re.IGNORECASE)),
        "weld_detected": bool(re.search(WELD_PATTERN, text, flags=re.IGNORECASE)),
        "tapped_detected": bool(re.search(TAP_PATTERN, text, flags=re.IGNORECASE)),
        "countersink_detected": bool(re.search(CSK_PATTERN, text, flags=re.IGNORECASE)),
        "mirrored_detected": "MIRRORED" in text.upper(),
        "hanging_hole_detected": "HANGING HOLE" in text.upper(),
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

    deduped: List[str] = []
    for op in operations:
        if op not in deduped:
            deduped.append(op)
    return deduped



def build_textual_manufacturing_summary(text: str) -> Dict[str, Any]:
    title_block = extract_title_block_fields(text)
    bom_rows = extract_bom_rows(text)
    feature_cues = extract_feature_cues(text)
    inferred_operations = infer_operations_from_text(text)

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
        "feature_cues": feature_cues,
        "inferred_operations": inferred_operations,
        "primary_fields": {
            "drawing_number": primary_drawing_number,
            "revision": primary_revision,
            "material": primary_material,
            "finish": primary_finish,
            "colour": primary_colour,
            "quantity": int(primary_quantity) if primary_quantity and primary_quantity.isdigit() else None,
            "thickness_mm": float(primary_thickness) if primary_thickness else None,
        },
    }
