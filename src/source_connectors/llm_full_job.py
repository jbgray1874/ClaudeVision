"""
source_connectors/llm_full_job.py — DRIVE the estimate from the whole-document LLM extract.

Takes the structured job from llm_full_extract.extract_full_job() and folds it into the
PRE-ESTIMATE part records (before costing), so the engine's EXISTING paths fire with the good
data instead of garbled vision geometry:
  - tube_section + cut_length  -> part["section_stock"] = {a,b,t,length_mm}  => the section/tube
    catalogue path costs by the REAL length (1342/529.8/1600/270), not a generic @1100.
  - material                   -> normalized_material  => timber/MDF no longer routed as steel.
  - weight_g                   -> stated_weight_g       => stated-weight material path (now
    trusted over garbled blanks when there is no DXF).
  - thickness_mm               -> normalized_thickness_mm.
  - is_assembly (from hierarchy) -> flagged as a sub-assembly (not a fabricated flat part).

Every touched field is tagged in review_flags as LLM-sourced (estimator to verify). This is
TRANSCRIBED data (printed on the drawing), cross-checked against the deterministic reads — not
an invented number.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

SOURCE_NAME = "llm_full_extract"
_RE_SECTION = re.compile(r"(\d+(?:\.\d+)?)\s*[xX]\s*(\d+(?:\.\d+)?)\s*[xX]\s*(\d+(?:\.\d+)?)")


def _clean_pn(s: Any) -> str:
    return str(s or "").strip().upper()


def _num(v: Any) -> Optional[float]:
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _parse_section(s: Optional[str]):
    """'30.00 x 30.00 x 1.50mm TUBE' -> (30.0, 30.0, 1.5)."""
    m = _RE_SECTION.search(str(s or ""))
    if not m:
        return None, None, None
    return _num(m.group(1)), _num(m.group(2)), _num(m.group(3))


def _norm_material(m: str) -> str:
    u = str(m or "").upper()
    if "STAINLESS" in u:
        return "STAINLESS_STEEL"
    if "MILD" in u or u.strip() == "STEEL":
        return "MILD_STEEL"
    if "MDF" in u or "VENEER" in u:
        return "MDF"
    if "TIMBER" in u or "WOOD" in u or "OAK" in u:
        return "TIMBER"
    if "ALUM" in u:
        return "ALUMINIUM"
    if "ACRYLIC" in u or "PERSPEX" in u:
        return "ACRYLIC"
    return str(m or "").strip()


def apply_full_job_to_pre_estimate(parts: List[Dict[str, Any]], job: Dict[str, Any]) -> Dict[str, int]:
    """Fold the LLM whole-document job into the pre-estimate part records. Non-destructive:
    fills a field only where the engine has nothing solid, EXCEPT it deliberately provides
    section_stock + stated_weight so the good paths win over garbled vision geometry.
    Returns counts of what changed."""
    out = {"material": 0, "weight": 0, "thickness": 0, "tube": 0, "assembly_flagged": 0}
    if not isinstance(job, dict) or not job.get("found") or not isinstance(parts, list):
        return out

    by_pn = {_clean_pn(p.get("part_number")): p for p in (job.get("parts") or []) if isinstance(p, dict)}
    assembly_pns = {_clean_pn(a.get("part_number")) for a in (job.get("assemblies") or []) if isinstance(a, dict)}

    for part in parts:
        if not isinstance(part, dict):
            continue
        pn = _clean_pn(part.get("part_number"))
        jp = by_pn.get(pn)

        # Sub-assembly: flag it (it is a weld/build step, not a fabricated flat part).
        if pn in assembly_pns:
            part["is_sub_assembly"] = True
            part.setdefault("review_flags", []).append(
                "LLM: sub-assembly (has its own parts page) — not a fabricated flat part")
            out["assembly_flagged"] += 1

        if not jp:
            continue
        _flagged = False

        mat = jp.get("material")
        if mat and not str(part.get("normalized_material") or "").strip():
            part["normalized_material"] = _norm_material(mat)
            _flagged = True
            out["material"] += 1

        wt = _num(jp.get("weight_g"))
        if wt and wt > 0 and not _num(part.get("stated_weight_g")):
            part["stated_weight_g"] = round(wt, 2)
            _flagged = True
            out["weight"] += 1

        thk = _num(jp.get("thickness_mm"))
        if thk and thk > 0 and not _num(part.get("normalized_thickness_mm")):
            part["normalized_thickness_mm"] = thk
            _flagged = True
            out["thickness"] += 1

        # Tube: real section + cut length -> section_stock so the tube catalogue path fires.
        a, b, t = _parse_section(jp.get("tube_section"))
        cut = _num(jp.get("cut_length_mm"))
        if a and b and t and cut and cut > 0 and not part.get("section_stock"):
            part["section_stock"] = {"a": a, "b": b, "t": t, "length_mm": cut}
            _flagged = True
            out["tube"] += 1

        if _flagged:
            part.setdefault("review_flags", []).append(
                "enriched from whole-document LLM extract (transcribed from drawing — verify)")

    return out
