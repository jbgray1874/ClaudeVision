from __future__ import annotations

import logging
import os
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from source_precedence import apply_field

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
    "MARINE PLY": "PLYWOOD",
    "TIMBER": "TIMBER",
    "WOOD": "TIMBER",
    # SPECIES, not families. A title block names the actual timber — "FSC PINE",
    # "SPRUCE", "BEECH" — and never the word TIMBER, so a species-blind vocabulary
    # returns nothing for a stated material and the part falls through unpriced or
    # takes a default. This is what left the Horti Crate's FSC PINE panels with no
    # material. Longest-key-first matching keeps "OAK VENEER MDF" resolving to the
    # veneered board rather than to solid oak.
    "FSC PINE": "TIMBER",
    "PINE": "TIMBER",
    "SPRUCE": "TIMBER",
    "REDWOOD": "TIMBER",
    "WHITEWOOD": "TIMBER",
    "SOFTWOOD": "TIMBER",
    "HARDWOOD": "TIMBER",
    "BEECH": "TIMBER",
    "ASH": "TIMBER",
    "OAK": "TIMBER",
    "MR MDF": "MDF",
    "MRMDF": "MDF",
    # FACED SHEET BOARD — melamine-faced chipboard and its spellings. The commonest
    # shop-fitting board there is, and this lexicon did not have it: on 12422-24 the end
    # cap panel's stated "16mm MFC" resolved to nothing here, so the title-block reader's
    # unknown-callout branch took the raw string and the drawing's boilerplate with it, and
    # the material reached the sheet as "MFC DO NOT".
    #
    # Longest-key-first matching is what keeps the faced spellings ahead of plain MDF, so
    # "MELAMINE FACED MDF" is faced board and not MDF. Deliberately NOT given a density or
    # a price-per-kg: config's per-kg lookup falls back to the MILD STEEL rate for anything
    # it does not know, so inventing an entry would cost a chipboard panel at steel's rate.
    # It stays in the board path and stays honestly unpriced until an estimator sets the
    # sheet rate — which is the same thing the sheet already asks for.
    # THE FACING IS NOT THE SUBSTRATE. MFC is melamine-faced CHIPBOARD; MFMDF is
    # melamine-faced MDF. They are bought as different sheets at different prices and they
    # machine differently — chipboard blows out on a routed edge where MDF does not — so
    # collapsing them onto one code would price one board at the other's rate the moment a
    # sheet rate exists for either. Same facing, two materials.
    # ONLY THE SPELLINGS THAT NAME THEIR SUBSTRATE. "MELAMINE FACED" and "PRE-LAM" on their
    # own say what was done to the sheet and not what the sheet IS, and the two candidates
    # are bought at different prices. Resolving them to MFC because it is the commoner of
    # the two is a guess wearing a fact's clothes — the same reasoning that keeps
    # "finishing" out of the department table. Unresolved, the part reaches the estimator
    # as a visible gap; resolved wrongly, it reaches them as somebody else's board.
    "MELAMINE FACED CHIPBOARD": "MFC",
    "MELAMINE FACED MDF": "MFMDF",
    "PRE LAMINATED CHIPBOARD": "MFC",
    "PRE LAM CHIPBOARD": "MFC",
    "PRE LAMINATED MDF": "MFMDF",
    "PRE LAM MDF": "MFMDF",
    "PRELAM MDF": "MFMDF",
    "MFMDF": "MFMDF",
    "MFC": "MFC",
    "CHIPBOARD": "CHIPBOARD",
    "HDPE": "HDPE_PLASTIC",
    "HIGH IMPACT ACRYLIC": "ACRYLIC",
    "ACRYLIC": "ACRYLIC",
    "PERSPEX": "ACRYLIC",
    "GREENCAST": "ACRYLIC",
    "POLYCARBONATE": "POLYCARBONATE",
    "VENEERED MDF": "VENEERED_MDF",
    "VENEER MDF": "VENEERED_MDF",
    "MDF VENEERED": "VENEERED_MDF",
    "OAK VENEER MDF": "OAK_VENEER_MDF",
    "OAK VENEER": "OAK_VENEER_MDF",
    "OAK MDF": "OAK_VENEER_MDF",
    "PAPER": "BOUGHT_IN",
    "PRINTED PAPER": "BOUGHT_IN",
    "DISPA BOARD": "BOUGHT_IN",
    "DISPABOARD": "BOUGHT_IN",
    "FOAMEX": "BOUGHT_IN",
    "CORREX": "BOUGHT_IN",
    "ERW TUBE": "MILD_STEEL",
    "STEEL TUBE": "MILD_STEEL",
    "MILD STEEL ERW": "MILD_STEEL",
    "CR4": "MILD_STEEL",
    "PETG": "ACRYLIC",
    "PET": "ACRYLIC",
    "POLYSTYRENE": "HIPS",      # HIPS = High Impact PolyStyrene — keep as HIPS
    "HIPS": "HIPS",             # keep HIPS distinct so it prices from live UDEF HIPS
                                # sheet rates (labour still routes acrylic-like via
                                # estimator._ACRYLIC_LIKE — cut/handle as plastic).
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

# Part-number suffix conventions used as WEAK material hints. '-M<digit>' is SDI's metal
# detail convention (12120-01-01M etc). There is deliberately no '-J' rule: J reads as
# JOINERY on real jobs, and treating it as a metal "joist" forced the Horti Crate's timber
# panels to steel. See normalise_material for why these can never override a stated material.
_METAL_PANEL_RE = re.compile(r"-\s*M\d", re.IGNORECASE)
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
    # Named species count as timber evidence. Without this a drawing stating "FSC PINE"
    # gives no timber cue at all, so the part-number and blob steel hints below win by
    # default on a wooden part. Suppressed where the blob also names steel, so a mixed
    # note ("PINE PACKER ON MILD STEEL FRAME") does not flip a steel part to timber.
    _SPECIES = ("FSC PINE", "PINE", "SPRUCE", "REDWOOD", "WHITEWOOD",
                "SOFTWOOD", "HARDWOOD", "BEECH", "OAK", "JOINERY")
    if any(s in blob_upper for s in _SPECIES) and "MILD STEEL" not in blob_upper:
        return True
    return False


def _hints_mild_steel_part_number(part_number: str) -> bool:
    u = str(part_number or "").upper()
    # '-J<digit>' removed: it reads as JOINERY on real jobs (Horti Crate -J01..-J08 are
    # timber panels), not the metal "joist" this was named for. See normalise_material.
    if _METAL_PANEL_RE.search(u):
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
    # Reject OCR artefacts misread as materials (Card, Led, Vinyl etc.)
    _REJECT_MAT = {"LED", "CARD", "VINYL", "TAPE"}
    if str(raw or "").strip().upper() in _REJECT_MAT:
        raw = ""
    pn = str(part.get("part_number") or "")
    blob = _part_text_blob(part).upper()
    pn_u = pn.upper()

    # Supplier / stock codes and finishes common on Boots & gondola packs.
    # Bought-in items — check raw material field AND description blob BEFORE
    # timber/steel heuristics so PAPER/DISPA BOARD parts aren't mis-classified.
    _raw_mat_upper = (raw or "").upper()
    if normalise_material(_raw_mat_upper) == "BOUGHT_IN":
        return "BOUGHT_IN"
    if any(k in blob for k in ("SUPPLIED BY M&S", "SUPPLIED BY MARKS", "FOR SIZE REFERENCE ONLY", "SUPPLIED BY CLIENT")):
        return "BOUGHT_IN"
    if "PAPER" in blob and "PRINTED" in blob:
        return "BOUGHT_IN"
    if "DISPA" in blob or "DISPABOARD" in blob:
        return "BOUGHT_IN"
    if any(k in _raw_mat_upper for k in ("PAPER", "DISPA", "FOAMEX", "CORREX")):
        return "BOUGHT_IN"
    # Check surface_finishes — PRINTED finish = customer-supplied printed item
    _finishes_upper = " ".join(str(f) for f in (part.get("surface_finishes") or [])).upper()
    if "PRINTED" in _finishes_upper:
        return "BOUGHT_IN"
    # Description-based: customer-supplied graphics only — not fabricated metal parts
    # like "GRAPHIC CHANNEL" (sheet MS with flat DXF). Require explicit supply wording.
    _desc_upper = str(part.get("description") or "").upper()
    _fabricated_metal = (
        part.get("flat_pattern_detected")
        or part.get("dxf_augmented")
        or "MILD STEEL" in blob
        or _METAL_PANEL_RE.search(pn_u)
    )
    if not _fabricated_metal:
        if any(k in _desc_upper or k in pn_u for k in ("GRAPHIC", "ARTWORK", "POSTER", "PRINT INSERT")):
            return "BOUGHT_IN"
    else:
        if any(k in _desc_upper for k in ("ARTWORK", "POSTER", "PRINT INSERT")):
            return "BOUGHT_IN"
        if "GRAPHIC" in _desc_upper and "SUPPLIED" in _desc_upper:
            return "BOUGHT_IN"
    if "TICKET" in _desc_upper and "PLATE" not in _desc_upper and "HOLDER" not in _desc_upper:
        return "BOUGHT_IN"

    if "PLAS518" in pn_u or "PLAS518" in blob or "GREENCAST" in blob or "CAST ACRYLIC" in blob:
        return "ACRYLIC"
    if "MDFS" in pn_u or ("MDF" in blob and "ACRYLIC" not in blob and "PERSPEX" not in blob and "GREENCAST" not in blob):
        if "MILD STEEL" not in blob and "STAINLESS" not in blob:
            # Preserve VENEERED qualifier so price lookup hits the correct catalog entry
            if any(v in blob for v in ("VENEERED", "VENEER MDF", "MDF VENEERED")):
                return "VENEERED_MDF"
            return "MDF"

    pn_steel = _hints_mild_steel_part_number(pn)
    timber = _hints_timber(blob)
    blob_steel = _hints_mild_steel_blob(blob)

    # PART-NUMBER SUFFIX AS A MATERIAL HINT — weak, and never an override.
    #
    # This used to return MILD_STEEL unconditionally for any '-M<digit>' or '-J<digit>'
    # part number, ahead of every material check, to defeat the M&S title-block legend
    # bleeding WOOD onto steel details. That legend problem is now fixed at source (the
    # boilerplate material scan in extractor_patterns), so the override is no longer
    # needed — and it was doing real harm: the Horti Crate's -J01..-J08 are the TIMBER
    # panels, priced by weight as timber/MDF in the BOM, yet were forced to MILD_STEEL
    # and routed to laser/weld/powder. A suffix is a NAMING CONVENTION, not a material.
    #
    # '-J' is dropped as a steel signal entirely: on this evidence J means JOINERY, and
    # the "joist" reading it was named for is not supported by any job we have. '-M' is a
    # genuine SDI convention for metal detail parts, so it is kept — but demoted to a hint
    # that yields to positive timber evidence, exactly as the '-SA' rule below already
    # does. Where the drawing states a material, that material wins.
    if _METAL_PANEL_RE.search(pn.upper()) and not timber:
        return "MILD_STEEL"

    # HIPS declared explicitly on the drawing (MATERIAL: HIPS) is a distinct plastic
    # with its own sheet price — keep it HIPS rather than collapsing to ACRYLIC via the
    # "LENS" heuristic below. (Labour still routes acrylic-like in the estimator.)
    if "HIPS" in _raw_mat_upper or "HIPS" in _desc_upper:
        return "HIPS"

    # Acrylic / perspex detection — MUST come before timber check because some
    # acrylic parts (e.g. "LENS") have "CLEAR" finish or "SCRAPED EDGES" that
    # otherwise look timber-like and get mis-priced as TIMBER.
    _is_acrylic = (
        any(k in _raw_mat_upper for k in ("ACRYLIC", "PERSPEX", "PMMA", "POLYCARBONATE"))
        or any(k in _desc_upper for k in ("LENS", "ACRYLIC", "PERSPEX"))
        or ("CLEAR" in _finishes_upper and "SCRAPED" in _finishes_upper)
        or ("CLEAR" in _finishes_upper and "LENS" in _desc_upper)
    )
    if _is_acrylic:
        return "ACRYLIC"

    # Wire/tube geometry -> MILD_STEEL override
    # Catches parts where PDF omits explicit material but ops/description
    # reveal fabricated steel (wire basket frames, tube sections, weldments).
    _ops_upper = " ".join(str(o) for o in (part.get("textual_operations") or [])).upper()
    _sizes_upper = " ".join(str(x) for x in (part.get("overall_sizes_mm") or [])).upper()
    _is_wire_tube = (
        "WIRE_FORMING" in _ops_upper
        or "WIRE FORMING" in _ops_upper
        or bool(re.search(r"\d+\s*[Xx]\s*\d+.*TUBE", _desc_upper + " " + _sizes_upper))
        or "WELDMENT" in _desc_upper
        or "WELDMENT" in pn_u
    )
    if _is_wire_tube and str(raw or "").upper() in ("", "UNKNOWN", "TIMBER", "WOOD", "NONE"):
        return "MILD_STEEL"

    # Timber joinery / boards when description clearly says so (before generic SA rule).
    if timber:
        return "TIMBER"

    # Shelf-assembly lines: SAxx can be wood — only force steel if no timber cues.
    if _METAL_SA_RE.search(pn.upper()) and not timber:
        return "MILD_STEEL"

    if pn_steel or blob_steel:
        return "MILD_STEEL"

    # PN suffix inference: -xxM=MILD_STEEL, -xxA=ACRYLIC, -xxT=MDF
    _raw_u = str(raw or "").strip().upper()
    if not _raw_u or _raw_u in ("UNKNOWN","NONE",""):
        _sfx_m = re.search(r"-\d+([TMAatma])$", pn_u.strip())
        if _sfx_m:
            _s = _sfx_m.group(1).upper()
            if _s == "M":
                return "MILD_STEEL"
            elif _s == "A":
                return "ACRYLIC"
            elif _s == "T":
                return "MDF"
    return normalise_material(raw)


def infer_operations(text: str) -> List[str]:
    ops: List[str] = []
    upper = text.upper()
    for keyword in _OPERATION_KEYS_SORTED:
        code = OPERATION_INFERENCE_MAP[keyword]
        if keyword in upper and code not in ops:
            ops.append(code)
    return ops


# Boilerplate blocks that appear on every M&S/SDI drawing page border.
# These must be stripped before operation inference so spec text doesn't
# bleed into per-part operations (e.g. "WELD SPECIFICATION" → welding).
_BOILERPLATE_RE = re.compile(
    r"WELD\s+SPECIFICATION[:\s].*"
    r"|FINISH\s+SPECIFICATIONS?[:\s].*"
    r"|CHINA\s+MATERIAL\s+SPECIFICATIONS?[:\s].*"
    r"|GENERAL\s+TOLERANCES?[:\s].*"
    r"|COPYRIGHT\s+M&S.*"
    r"|THIS\s+DRAWING\s+IS\s+THE\s+PROPERTY.*"
    r"|DO\s+NOT\s+SCALE\s+FROM\s+DRAWING.*"
    r"|ALL\s+DIMENSIONS\s+ARE\s+IN\s+MM.*"
    r"|UNLESS\s+OTHERWISE\s+STATED.*"
    r"|MAY\s+NOT\s+BE\s+COPIED.*"
    r"|SPECIFICATION\s+IS\s+\d+\s+GRIT.*"
    r"|RESISTANCE\s+WELDING\s+WIRE\s+TO\s+WIRE.*"
    r"|POWDERCOATING[:\s]+BETWEEN.*"
    r"|CHROME\s+PLATING[:\s].*"
    r"|BRIGHT\s+ZINC\s+PLATING[:\s].*"
    r"|TIMBER\s+PRODUCTS?[:\s].*"
    r"|FSC\s+CERTIFIED.*",
    re.IGNORECASE,
)


def _strip_spec_boilerplate(text: str) -> str:
    """Remove drawing-border spec blocks before operation inference."""
    return _BOILERPLATE_RE.sub(" ", text)


def apply_material_context_normalisation(parts: List[Dict[str, Any]]) -> None:
    """Apply context-aware material codes before costing so estimator sees corrected metals."""
    for part in parts:
        inferred = normalise_material_for_part(part)
        if inferred:
            # INFERENCE, rank 20. This reads the part number, the description and any stated
            # material and picks a family — a reading of text, not an observation of the part.
            # It ran unattributed and unconditionally, so it could overwrite a material the
            # MODEL had supplied simply by running later.
            apply_field(part, "normalized_material", inferred, "inference")


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
            apply_field(part, "normalized_material", inferred_material, "inference")

        if debug_mat and inferred_material and inferred_material != previous:
            logger.info(
                "Material normalised: part=%s | %s → %s | desc=%s",
                part.get("part_number"),
                previous,
                inferred_material,
                str(part.get("description") or "")[:80],
            )

        process_notes_text = _strip_spec_boilerplate(" ".join(
            str(n) for n in (part.get("process_notes") or []) + (part.get("textual_operations") or [])
        ))
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
