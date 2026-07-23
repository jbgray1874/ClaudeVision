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


def overlay_drawing_facts(job: Dict[str, Any], facts: Dict[str, Any]) -> Dict[str, Any]:
    """Overlay the DETERMINISTIC drawing_facts onto the LLM job so each source covers the other's
    gaps — the responsibility for a PDF-only job. The LLM owns the hierarchy + structure; the
    deterministic reader owns the PRINTED title-block facts (per-part finish, thickness) and the
    letter-scrambled spec block the LLM misreads. Concretely: fill the LLM's null part fields with
    drawing_facts' printed values, and COMBINE the weld spec (the LLM caught 'set-down 20%',
    drawing_facts caught 'ALL WELDS TO BE TIG'). Mutates and returns job; records provenance."""
    if not (isinstance(job, dict) and job.get("found") and isinstance(facts, dict)):
        return job
    by_part = {_clean_pn(pn): d for pn, d in (facts.get("by_part") or {}).items() if isinstance(d, dict)}
    _EMPTY = (None, "", [])
    for p in (job.get("parts") or []):
        if not isinstance(p, dict):
            continue
        d = by_part.get(_clean_pn(p.get("part_number")))
        if not d:
            continue
        # HARD PRINTED FACTS: deterministic is AUTHORITATIVE where it has a value (it read the
        # exact printed value and cannot hallucinate). The LLM only fills where deterministic is
        # null. If both have a value and they DISAGREE, deterministic wins and it is flagged.
        for k in ("material", "thickness_mm", "tube_section", "cut_length_mm", "weight_g", "finish"):
            dv, lv = d.get(k), p.get(k)
            if dv in (None, ""):
                continue  # deterministic has nothing here -> keep the LLM value (gap fill)
            if lv not in _EMPTY and str(lv).strip().upper() != str(dv).strip().upper():
                p.setdefault("_merge_flags", []).append(
                    f"{k}: LLM='{lv}' vs deterministic='{dv}' — used deterministic (printed)")
            p[k] = dv
            p.setdefault("_deterministic", []).append(k)
    # Spec: COMBINE the weld line (each source has half), fill the rest from the deterministic block.
    sb = facts.get("spec_block") or {}
    spec = job.setdefault("spec", {})
    _det_weld, _llm_weld = sb.get("weld_spec"), spec.get("weld")
    if _det_weld and _llm_weld and _det_weld.strip().lower() not in _llm_weld.strip().lower():
        spec["weld"] = f"{_det_weld}; {_llm_weld}"
    elif _det_weld and not _llm_weld:
        spec["weld"] = _det_weld
    for k in ("powder_micron", "tolerances", "timber_note"):
        if not spec.get(k) and sb.get(k):
            spec[k] = sb[k]
    job["_overlay"] = "drawing_facts merged (deterministic fills LLM nulls; weld combined)"
    return job


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
        # SOURCE WATERFALL: a DXF flat pattern (or SolidWorks native) is MEASURED truth and wins
        # on GEOMETRY. Where it exists (e.g. 12120), the LLM must NOT override the blank/section —
        # it only fills material/finish the engine lacks. The LLM drives geometry ONLY for the
        # no-DXF PDF-only parts (e.g. the M&S tender). So LLM vars can be live on every job safely.
        # Match the engine's OWN definition of DXF-backed (estimator.py:109 uses
        # geometry_source=='dxf_flat_pattern' OR dxf_augmented) plus the other DXF markers it
        # sets, so NO measured part slips through and gets overridden by the LLM.
        _dxf_backed = (
            str(part.get("geometry_source") or "").lower() in ("dxf_flat_pattern", "dxf", "dxf_flat")
            or bool(part.get("dxf_augmented"))
            or bool(part.get("flat_pattern_detected"))
            or bool(part.get("dxf_source_file"))
        )

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

        # Tube: real section + cut length -> section_stock so the tube path costs by the REAL
        # length. OVERRIDE any existing section_stock the engine stamped (its length is the
        # generic @1100 / garbled one); the LLM cut length is the printed truth.
        a, b, t = _parse_section(jp.get("tube_section"))
        cut = _num(jp.get("cut_length_mm"))
        if a and b and t and cut and cut > 0 and not _dxf_backed:  # DXF geometry wins; LLM drives no-DXF
            ss = part.get("section_stock")
            ss = dict(ss) if isinstance(ss, dict) else {}
            _before_len = _num(ss.get("length_mm"))
            ss.update({"a": a, "b": b, "t": t, "length_mm": cut})
            part["section_stock"] = ss
            if _before_len != cut:
                _flagged = True
                out["tube"] += 1

        if _flagged:
            part.setdefault("review_flags", []).append(
                "enriched from whole-document LLM extract (transcribed from drawing — verify)")

    return out
