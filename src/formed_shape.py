"""A formed shape is folded from sheet unless a section is named (D-589).

0351292's ROL2021-2408 BASE ANGLE: its own sheet states "3 mm", "MILD STEEL - RAW" — the same
title block as every flat part in the pack, where the tubes beside it state "30X20X2MM",
"MILD STEEL RECT TUBE - RAW". The word ANGLE in its description put it on the section road with
no section to cost ("section length not stated — taken as largest dimension 2mm"), its sheet
was never sized as a folded blank, and no fold was ever charged. A shape word is a section only
where a section is named: a section size (a x b x t) on the record, or the shape in its
MATERIAL. Otherwise, with a sheet gauge and a sheet metal, it is a shape folded from sheet, and
config.FORMED_SHEET_SHAPE_FOLDS says how many folds the shape has.

Shared by the estimator (the section road, the fold charge) and detail_page_geometry (the
provisional blank's flanges), so the two cannot disagree about one part.
"""
from __future__ import annotations

import re
from typing import Any, List, Mapping, Optional

_SECTION_SIZE_RE = re.compile(r"\d+(?:[.,]\d+)?\s*[X×]\s*\d+(?:[.,]\d+)?\s*[X×]\s*\d+")
_SHEET_METALS = {"MILD_STEEL", "STAINLESS_STEEL", "ALUMINIUM", "ALUMINUM", "ZINTEC",
                 "GALVANISED_STEEL", "GALVANIZED_STEEL"}


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def formed_sheet_shape(part: Mapping[str, Any], hits: Optional[List[str]] = None) -> Optional[str]:
    """The formed shape ("ANGLE", "CHANNEL"…) a sheet part's description names, or None.

    `hits`, where given, are the section keywords that matched the part: each must be one of
    the shape words found, or the part is a section for another reason."""
    import config
    shapes = getattr(config, "FORMED_SHEET_SHAPE_FOLDS", {}) or {}
    desc = str(part.get("description") or "").upper()
    found = sorted((s for s in shapes if re.search(rf"\b{re.escape(s)}\b", desc)),
                   key=len, reverse=True)
    if not found:
        return None
    if hits is not None and not all(any(h in s or s in h for s in found) for h in hits):
        return None
    if part.get("section_stock"):
        return None
    mat_text = " ".join([str(part.get("material") or "")]
                        + [str(m) for m in (part.get("materials") or [])]).upper()
    section_words = [str(t).upper() for t in
                     (getattr(config, "SECTION_STOCK_POLICY", {}) or {}).get("section_keywords", [])]
    if any(w in mat_text for w in section_words):
        return None
    if _SECTION_SIZE_RE.search(" ".join([desc, mat_text]
                                        + [str(t) for t in (part.get("thicknesses") or [])]).upper()):
        return None
    if not _num(part.get("normalized_thickness_mm") or part.get("thickness_mm")):
        return None
    if str(part.get("normalized_material") or "").upper().replace(" ", "_") not in _SHEET_METALS:
        return None
    return found[0]


def shape_folds(part: Mapping[str, Any]) -> int:
    """The folds the part's formed shape has (0 when it names none)."""
    shape = formed_sheet_shape(part)
    if not shape:
        return 0
    import config
    return int((getattr(config, "FORMED_SHEET_SHAPE_FOLDS", {}) or {}).get(shape) or 0)
