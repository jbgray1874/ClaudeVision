from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import re

V4_SCHEMA = "professional_manufacturing_json.v4"

MATERIAL_NORMALISATION = {
    "MILD STEEL": "MILD_STEEL",
    "MS": "MILD_STEEL",
    "SHEET STEEL": "MILD_STEEL",
    "STAINLESS": "STAINLESS_STEEL",
    "SS": "STAINLESS_STEEL",
    "ALUMINIUM": "ALUMINIUM",
    "ALUMINUM": "ALUMINIUM",
    "Q195": "MILD_STEEL",
    "Q235": "MILD_STEEL",
    "SPCC": "MILD_STEEL_SPCC",
    "304": "STAINLESS_STEEL_304",
    "316": "STAINLESS_STEEL_316",
    "PLYWOOD": "PLYWOOD",
    "BIRCH PLY": "BIRCH_PLYWOOD",
    "TIMBER": "TIMBER",
    "HDPE": "HDPE_PLASTIC",
    "ACRYLIC": "ACRYLIC",
    "OAK VENEER": "OAK_VENEER_MDF",
    "OAK MDF": "OAK_VENEER_MDF",
}

OPERATION_INFERENCE_MAP = {
    "SPOT WELD": "spot_welding",
    "WELD": "welding",
    "LASER": "laser_cutting",
    "CUT": "laser_cutting",
    "FOLD": "folding",
    "BEND": "folding",
    "POWDER": "powder_coating",
    "COAT": "powder_coating",
    "ASSEMBLE": "assembly",
    "PACK": "packing",
    "DRILL": "hole_machining",
    "TAP": "tapping",
}


_MATERIAL_KEYS_SORTED = sorted(MATERIAL_NORMALISATION.keys(), key=len, reverse=True)
_OPERATION_KEYS_SORTED = sorted(OPERATION_INFERENCE_MAP.keys(), key=len, reverse=True)


def normalise_material(text: Optional[str]) -> str | None:
    if not text:
        return None
    cleaned = re.sub(r"[^A-Z0-9 ]", " ", str(text).upper()).strip()
    cleaned = re.sub(r" {2,}", " ", cleaned)
    for key in _MATERIAL_KEYS_SORTED:
        code = MATERIAL_NORMALISATION[key]
        if key in cleaned:
            return code
    return None


def infer_operations(text: str) -> List[str]:
    ops: List[str] = []
    upper = text.upper()
    for keyword in _OPERATION_KEYS_SORTED:
        code = OPERATION_INFERENCE_MAP[keyword]
        if keyword in upper and code not in ops:
            ops.append(code)
    return ops


def _resolve_parts(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    writeup_parts = summary.get("manufacturing_writeup", {}).get("parts")
    if isinstance(writeup_parts, list) and writeup_parts:
        return writeup_parts
    top_parts = summary.get("parts")
    if isinstance(top_parts, list) and top_parts:
        return top_parts
    return []


def normalise_json(raw_json: Dict[str, Any]) -> Dict[str, Any]:
    """
    Post-process scan summary into a consistent v4-style view without
    destructively replacing richer upstream fields.
    """
    normalised = dict(raw_json)
    normalised["schema"] = V4_SCHEMA
    normalised["processed_at"] = datetime.now(timezone.utc).isoformat()

    parts = _resolve_parts(normalised)
    for part in parts:
        materials = part.get("materials", [])
        inferred_material = normalise_material(materials[0] if materials else "")
        if not part.get("normalized_material") and inferred_material:
            part["normalized_material"] = inferred_material

        process_notes_text = " ".join(
            str(n) for n in (part.get("process_notes") or []) + (part.get("textual_operations") or [])
        )
        inferred_ops = infer_operations(process_notes_text)
        existing_ops = part.get("textual_operations", []) or []
        combined_ops = []
        for op in list(existing_ops) + inferred_ops:
            if op not in combined_ops:
                combined_ops.append(op)
        if combined_ops:
            part["textual_operations"] = combined_ops

        if not isinstance(part.get("confidence"), dict) or not part.get("confidence"):
            part["confidence"] = {"overall": 0.0}

        part.setdefault(
            "provenance",
            {
                "source": "pdf_scan_v4",
                "extracted_at": datetime.now(timezone.utc).isoformat(),
                "geometry_reliability": part.get("geometry_rollup", {}).get("confidence", {}).get("geometry_reliability", 0.0),
            },
        )

    normalised["normalisation_meta"] = {
        "parts_normalised": len(parts),
        "normalised_at": datetime.now(timezone.utc).isoformat(),
        "schema": V4_SCHEMA,
    }

    return normalised
