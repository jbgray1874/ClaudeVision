from __future__ import annotations

import logging
import os
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

V4_SCHEMA = "professional_manufacturing_json.v4"

MATERIAL_NORMALISATION = {
    "MILD STEEL": "MILD_STEEL",
    "MILDSTEEL": "MILD_STEEL",
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
    "MDF": "MDF",
    "MDF BOARD": "MDF",
    "BIRCH PLY": "BIRCH_PLYWOOD",
    "TIMBER": "TIMBER",
    "WOOD": "TIMBER",
    "HDPE": "HDPE_PLASTIC",
    "HIGH IMPACT ACRYLIC": "ACRYLIC",
    "ACRYLIC": "ACRYLIC",
    "PERSPEX": "ACRYLIC",
    "GREENCAST": "ACRYLIC",
    "POLYCARBONATE": "POLYCARBONATE",
    "OAK VENEER": "OAK_VENEER_MDF",
    "OAK MDF": "OAK_VENEER_MDF",
    "ERW TUBE": "MILD_STEEL",
    "STEEL TUBE": "MILD_STEEL",
    "MILD STEEL ERW": "MILD_STEEL",
    "CR4": "MILD_STEEL",
}

OPERATION_INFERENCE_MAP = {
    "SPOT WELD": "spot_welding",
    "WELD": "welding",
    "LASER": "laser_cutting",
    "CUT": "laser_cutting",
    "FOLD": "folding",
    "BEND": "folding",
    "WET SPRAYED": "wet_spray",
    "WET SPRAY": "wet_spray",
    "WET-SPRAY": "wet_spray",
    "WET PAINT": "wet_spray",
    "SPRAY SHOP": "wet_spray",
    "CNC ROUT": "cnc",
    "CNC ": "cnc",
    "CNC.": "cnc",
    "BENCH": "bench_work",
    "BENCHWORK": "bench_work",
    "POWDER": "powder_coating",
    "COAT": "powder_coating",
    "ASSEMBLE": "assembly",
    "PACK": "packing",
    "DRILL": "hole_machining",
    "TAP": "tapping",
    "DIAMOND POLISH": "diamond_polish",
    "POLISH": "diamond_polish",
    "DRESS WELD": "dress_welds",
    "GLUE": "glue",
    "GUILLOTINE": "guillotine",
    "PUNCH": "punch",
    "ROLL": "roll",
    "SAW": "saw",
    "LINISH": "linisher",
}

_MATERIAL_KEYS_SORTED = sorted(MATERIAL_NORMALISATION.keys(), key=len, reverse=True)
_OPERATION_KEYS_SORTED = sorted(OPERATION_INFERENCE_MAP.keys(), key=len, reverse=True)

# HORTI-style metal panels / joists in part number (override bogus WOOD bleed from title block).
_METAL_PANEL_RE = re.compile(r"-\s*M\d", re.IGNORECASE)
_METAL_JOIST_RE = re.compile(r"-\s*J\d", re.IGNORECASE)
_METAL_SA_RE = re.compile(r"-\s*SA\d", re.IGNORECASE)


def _first_material_text(part: Dict[str, Any]) -> str:
    materials = part.get("materials") or []
    if not materials:
        return ""
    first = materials[0]
    if isinstance(first, dict):
        return str(first.get("raw") or first.get("text") or first.get("value") or "")
    return str(first)


def _part_text_blob(part: Dict[str, Any]) -> str:
    desc = str(part.get("description") or "")
    notes = " ".join(str(n) for n in (part.get("process_notes") or []))
    return f"{desc} {notes}".strip()


def _hints_timber(blob_upper: str) -> bool:
    if any(k in blob_upper for k in ["PLYWOOD", "BIRCH PLY", "OAK VENEER", "OAK MDF"]):
        return True
    if "MDF" in blob_upper and "ACRYLIC" not in blob_upper and "PERSPEX" not in blob_upper and "GREENCAST" not in blob_upper:
        if any(k in blob_upper for k in ["PLY", "TIMBER", "WOOD", "OAK", "SHELF BOARD", "JOINERY"]):
            return True
    if ("PLANK" in blob_upper or "SHELF" in blob_upper) and any(
        w in blob_upper for w in ["TIMBER", "WOOD", "PLY", "OAK", "PLYWOOD"]
    ):
        return True
    if "TIMBER" in blob_upper and "MILD STEEL" not in blob_upper:
        return True
    return False


def _hints_mild_steel_part_number(part_number: str) -> bool:
    u = str(part_number or "").upper()
    if _METAL_PANEL_RE.search(u) or _METAL_JOIST_RE.search(u):
        return True
    if any(k in u for k in ["FRAME", "WELDMENT", "CHANNEL", "TUBE", "SECTION", "STIFFENER", "BRACKET", "BASE"]):
        return True
    return False


def _hints_mild_steel_blob(blob_upper: str) -> bool:
    if any(k in blob_upper for k in ["MILD STEEL", "ZINTEC", "GALVANISE", "GALVANIZE", "S355", "CR4", "LASER CUT"]):
        return True
    return False


def normalise_material(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    cleaned = re.sub(r"[^A-Z0-9 ]", " ", str(text).upper()).strip()
    cleaned = re.sub(r" {2,}", " ", cleaned)
    for key in _MATERIAL_KEYS_SORTED:
        code = MATERIAL_NORMALISATION[key]
        if key in cleaned:
            return code
    return None


def normalise_material_for_part(part: Dict[str, Any]) -> Optional[str]:
    """
    Context-aware normalisation to reduce WOOD/TIMBER leakage onto fabricated steel lines.
    Order: explicit metal line tags (-Mxx / -Jxx) -> acrylic/MDF sheet stock cues -> timber joinery text ->
    other steel hints -> lexicon on declared material string.
    """
    raw = _first_material_text(part)
    pn = str(part.get("part_number") or "")
    blob = _part_text_blob(part).upper()
    pn_u = pn.upper()

    # Supplier / stock codes and finishes common on Boots & gondola packs.
    if "PLAS518" in pn_u or "PLAS518" in blob or "GREENCAST" in blob or "CAST ACRYLIC" in blob:
        return "ACRYLIC"
    if "MDFS" in pn_u or ("MDF" in blob and "ACRYLIC" not in blob and "PERSPEX" not in blob and "GREENCAST" not in blob):
        if "MILD STEEL" not in blob and "STAINLESS" not in blob:
            return "MDF"

    pn_steel = _hints_mild_steel_part_number(pn)
    timber = _hints_timber(blob)
    blob_steel = _hints_mild_steel_blob(blob)

    # Strongest: HORTI metal BOM line tags (even if OCR material field says WOOD).
    if _METAL_PANEL_RE.search(pn.upper()) or _METAL_JOIST_RE.search(pn.upper()):
        return "MILD_STEEL"

    # Timber joinery / boards when description clearly says so (before generic SA rule).
    if timber:
        return "TIMBER"

    # Shelf-assembly lines: SAxx can be wood — only force steel if no timber cues.
    if _METAL_SA_RE.search(pn.upper()) and not timber:
        return "MILD_STEEL"

    if pn_steel or blob_steel:
        return "MILD_STEEL"

    return normalise_material(raw)


def infer_operations(text: str) -> List[str]:
    ops: List[str] = []
    upper = text.upper()
    for keyword in _OPERATION_KEYS_SORTED:
        code = OPERATION_INFERENCE_MAP[keyword]
        if keyword in upper and code not in ops:
            ops.append(code)
    return ops


def apply_material_context_normalisation(parts: List[Dict[str, Any]]) -> None:
    """Apply context-aware material codes before costing so estimator sees corrected metals."""
    for part in parts:
        inferred = normalise_material_for_part(part)
        if inferred:
            part["normalized_material"] = inferred


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

    debug_mat = os.getenv("MATERIAL_NORMALISATION_DEBUG", "").lower() in {"1", "true", "yes"}

    parts = _resolve_parts(normalised)
    for part in parts:
        previous = part.get("normalized_material")
        inferred_material = normalise_material_for_part(part)
        if inferred_material:
            part["normalized_material"] = inferred_material

        if debug_mat and inferred_material and inferred_material != previous:
            logger.info(
                "Material normalised: part=%s | %s → %s | desc=%s",
                part.get("part_number"),
                previous,
                inferred_material,
                str(part.get("description") or "")[:80],
            )

        process_notes_text = " ".join(
            str(n) for n in (part.get("process_notes") or []) + (part.get("textual_operations") or [])
        )
        inferred_ops = infer_operations(process_notes_text)
        existing_ops = part.get("textual_operations", []) or []
        combined_ops: List[str] = []
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

    if parts:
        codes = [p.get("normalized_material") for p in parts if p.get("normalized_material")]
        if codes:
            majority = Counter(codes).most_common(1)[0][0]
            da = normalised.setdefault("document_analysis", {})
            if isinstance(da, dict):
                pf = da.setdefault("primary_fields", {})
                if isinstance(pf, dict):
                    pf.setdefault("normalized_material_majority", majority)

    normalised["normalisation_meta"] = {
        "parts_normalised": len(parts),
        "normalised_at": datetime.now(timezone.utc).isoformat(),
        "schema": V4_SCHEMA,
        "material_context_rules": "horti_v1",
    }

    return normalised
