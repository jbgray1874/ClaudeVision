"""
geometry_inference.py — SDI Intelligence

Infers blank dimensions for BOM parts that have NO flat DXF, so they get a
provisional cost instead of £0. Every inferred value is clearly flagged so the
estimate is honest about what is measured vs. estimated.

Inference priority (most reliable first):
  1. SDILive historical match — the part (or its number) was costed before.
  2. Sibling borrow — a DXF-backed part of the same material + description family
     in the SAME job (e.g. SIDE PANEL borrows from BACK PANEL).
  3. Category default — a conservative typical blank size by description keyword.

Parts touched are tagged:
  part["geometry_inferred"]      = True
  part["geometry_inference"]     = {"basis": ..., "source_part": ..., "note": ...}
  part["review_flags"]          += ["geometry_inferred_provisional"]
and given normalized_geometry.blank_length_mm / blank_width_mm so the normal
estimator material + labour path runs.

This module never raises — if inference is impossible it leaves the part as-is
(it will cost £0 and stay flagged "no geometry"), which is the safe outcome.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


# ── Description → family, for sibling matching and category defaults ──────────
# Each family: keywords that identify it, and a conservative default blank (mm).
_FAMILIES = {
    "panel":   {"kw": ("PANEL", "BACK", "FRONT", "SIDE", "DOOR", "FASCIA"),
                "default": (400.0, 300.0)},
    "tier":    {"kw": ("TIER", "SHELF", "BASE", "TRAY", "PLATE"),
                "default": (350.0, 250.0)},
    "divider": {"kw": ("DIVIDER", "FIN", "RIB", "BRACKET", "TAB", "CLIP"),
                "default": (120.0, 60.0)},
    "upright": {"kw": ("UPRIGHT", "POST", "LEG", "STILE", "RAIL", "BAR"),
                "default": (600.0, 80.0)},
    "foot":    {"kw": ("FEET", "FOOT", "LOWER LEG", "ADJUSTABLE FOOT"),
                "default": (150.0, 80.0)},
    "kick":    {"kw": ("KICK", "KICK PLATE", "TOE KICK"),
                "default": (500.0, 100.0)},
    "bracket": {"kw": ("SPIGOT", "SPIGGOT", "BRACKET", "LUG", "GUSSET", "TAB"),
                "default": (80.0, 40.0)},
    "body":    {"kw": ("BODY", "FRAME", "CARCASS", "ENCLOSURE"),
                "default": (500.0, 400.0)},
}


def provisional_blank_from_description(description: str) -> Optional[Dict[str, Any]]:
    """Typical blank size from a GA BOM description — for rollup when no detail exists."""
    fam = _family_of(description)
    if not fam:
        return None
    dl, dw = _FAMILIES[fam]["default"]
    return {
        "family": fam,
        "length_mm": dl,
        "width_mm": dw,
        "basis": "category_default",
    }


def _family_of(description: str) -> Optional[str]:
    """Pick the family whose MATCHED KEYWORD is most specific (longest).

    First-hit matching let generic families shadow specific ones because
    _FAMILIES is iterated in insertion order: e.g. 'KICK PLATE' hit tier's
    'PLATE' before kick's 'KICK PLATE', and 'LOWER LEG' hit upright's 'LEG'
    before foot's 'LOWER LEG'. Scoring by matched-keyword length fixes that —
    'KICK PLATE' (10) beats 'PLATE' (5); 'LOWER LEG' (9) beats 'LEG' (3).
    """
    d = (description or "").upper()
    best_fam: Optional[str] = None
    best_len = 0
    for fam, spec in _FAMILIES.items():
        for k in spec["kw"]:
            if k in d and len(k) > best_len:
                best_fam = fam
                best_len = len(k)
    return best_fam


def _has_geometry(part: Dict[str, Any]) -> bool:
    """True when the part already has measured geometry (DXF or explicit blank dims)."""
    ng = part.get("normalized_geometry") or {}
    if isinstance(ng, dict):
        l = ng.get("blank_length_mm")
        w = ng.get("blank_width_mm")
        if l and w and not ng.get("_inferred"):
            return True

    # DXF augmentation runs before inference and may populate rollup/extents
    # before blank_length_mm lands in normalized_geometry.
    if part.get("dxf_augmented"):
        return True
    gs = str(part.get("geometry_source") or "").lower()
    if "dxf" in gs:
        return True

    gr = part.get("geometry_rollup") or {}
    cut = float(gr.get("estimated_cut_length_mm") or 0)
    if cut > 0:
        conf = gr.get("confidence") or {}
        if float(conf.get("geometry_reliability") or part.get("dxf_geometry_reliability") or 0) >= 0.75:
            return True

    ol = part.get("overall_length_mm")
    ow = part.get("overall_width_mm")
    if ol and ow and part.get("flat_pattern_detected"):
        return True
    return False


def _clear_inference_tags(part: Dict[str, Any]) -> None:
    """Remove stale provisional-inference tags when real DXF geometry wins."""
    part.pop("geometry_inferred", None)
    part.pop("geometry_inference", None)
    flags = part.get("review_flags") or []
    if isinstance(flags, list):
        part["review_flags"] = [
            f for f in flags
            if str(f) != "geometry_inferred_provisional"
            and "geometry_inferred_provisional" not in str(f)
        ]
    ng = part.get("normalized_geometry")
    if isinstance(ng, dict):
        ng.pop("_inferred", None)


def _is_no_geometry_bom_part(part: Dict[str, Any]) -> bool:
    if part.get("source") == "sdi_bom_row_no_geometry":
        return True
    flags = part.get("review_flags") or []
    if any("no_geometry" in str(f) for f in flags):
        return True
    return not _has_geometry(part)


def _material_family(material: Optional[str]) -> str:
    m = (material or "").upper()
    if any(k in m for k in ("STEEL", "ALUMIN", "ZINTEC", "BRIGHT")):
        return "metal"
    if any(k in m for k in ("ACRYLIC", "PETG", "POLYCARB")):
        return "acrylic"
    if any(k in m for k in ("MDF", "TIMBER", "PLYWOOD", "VENEER", "BOARD")):
        return "board"
    return "other"


def _inject_dims(part: Dict[str, Any], length_mm: float, width_mm: float,
                 basis: str, source_part: Optional[str], note: str) -> None:
    """Write inferred blank dims into normalized_geometry and tag the part."""
    ng = part.get("normalized_geometry")
    if not isinstance(ng, dict):
        ng = {}
    ng["blank_length_mm"] = round(float(length_mm), 1)
    ng["blank_width_mm"] = round(float(width_mm), 1)
    # Mark reliability low so downstream confidence reflects the inference.
    conf = ng.get("confidence") if isinstance(ng.get("confidence"), dict) else {}
    conf["geometry_reliability"] = 0.4
    conf["blank_length_mm"] = 0.4
    ng["confidence"] = conf
    ng["_inferred"] = True
    part["normalized_geometry"] = ng

    part["geometry_inferred"] = True
    part["geometry_inference"] = {
        "basis": basis,
        "source_part": source_part,
        "note": note,
        "blank_length_mm": ng["blank_length_mm"],
        "blank_width_mm": ng["blank_width_mm"],
    }
    part.setdefault("review_flags", [])
    if "geometry_inferred_provisional" not in part["review_flags"]:
        part["review_flags"].append("geometry_inferred_provisional")


def _historical_dims(part: Dict[str, Any], db) -> Optional[Dict[str, Any]]:
    """Look up the part in SDILive history. Returns dims dict or None."""
    if db is None:
        return None
    pn = str(part.get("part_number") or "").strip()
    if not pn:
        return None
    try:
        hit = None
        if hasattr(db, "get_historical_cost"):
            hit = db.get_historical_cost(part_number=pn)
        if not hit and hasattr(db, "lookup_part"):
            hit = db.lookup_part(pn)
        if not hit:
            return None
        l = hit.get("blank_length_mm") or hit.get("BlankLengthMm")
        w = hit.get("blank_width_mm") or hit.get("BlankWidthMm")
        if l and w:
            return {"length": float(l), "width": float(w), "ref": pn}
    except Exception:
        return None
    return None


def _sibling_dims(part: Dict[str, Any],
                  geometried: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Borrow dims from a DXF-backed part of the same material + family."""
    fam = _family_of(part.get("description") or "")
    mat = _material_family(part.get("normalized_material"))
    best = None
    for g in geometried:
        if _material_family(g.get("normalized_material")) != mat:
            continue
        ng = g.get("normalized_geometry") or {}
        l, w = ng.get("blank_length_mm"), ng.get("blank_width_mm")
        if not (l and w):
            continue
        g_fam = _family_of(g.get("description") or "")
        # Same family is best; same material is acceptable fallback.
        score = 2 if (fam and g_fam == fam) else 1
        if best is None or score > best["score"]:
            best = {"length": float(l), "width": float(w),
                    "ref": g.get("part_number"), "score": score,
                    "same_family": bool(fam and g_fam == fam)}
    return best


def infer_missing_geometry(summary: Dict[str, Any], db=None) -> Dict[str, Any]:
    """
    Main entry. Mutates summary["manufacturing_writeup"]["parts"] in place,
    injecting provisional dimensions for no-geometry parts. Returns a small
    report dict: {"inferred": [...], "still_missing": [...]}.
    """
    try:
        parts = (summary.get("manufacturing_writeup") or {}).get("parts") or []
    except Exception:
        return {"inferred": [], "still_missing": []}

    geometried = [p for p in parts if _has_geometry(p)]
    inferred_log: List[Dict[str, Any]] = []
    still_missing: List[str] = []

    for part in parts:
        if _has_geometry(part):
            _clear_inference_tags(part)
            continue
        if not _is_no_geometry_bom_part(part):
            continue

        pn = part.get("part_number")

        # 1. Historical SDILive match
        hist = _historical_dims(part, db)
        if hist:
            _inject_dims(part, hist["length"], hist["width"],
                         basis="historical_sdilive", source_part=hist["ref"],
                         note=f"Dimensions from SDILive history for {hist['ref']}")
            inferred_log.append({"part": pn, "basis": "historical",
                                 "dims": (hist["length"], hist["width"])})
            continue

        # 2. Sibling borrow within the job
        sib = _sibling_dims(part, geometried)
        if sib:
            note = (f"Borrowed from sibling {sib['ref']} "
                    f"({'same type' if sib['same_family'] else 'same material'})")
            _inject_dims(part, sib["length"], sib["width"],
                         basis="sibling_borrow", source_part=sib["ref"], note=note)
            inferred_log.append({"part": pn, "basis": "sibling",
                                 "dims": (sib["length"], sib["width"]),
                                 "ref": sib["ref"]})
            continue

        # 3. Category default
        fam = _family_of(part.get("description") or "")
        if fam:
            dl, dw = _FAMILIES[fam]["default"]
            _inject_dims(part, dl, dw,
                         basis="category_default", source_part=None,
                         note=f"Typical '{fam}' size — rough provisional, verify")
            inferred_log.append({"part": pn, "basis": "category_default",
                                 "dims": (dl, dw)})
            continue

        # Nothing worked — leave as £0, keep flagged.
        still_missing.append(str(pn))

    return {"inferred": inferred_log, "still_missing": still_missing}
