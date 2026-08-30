"""
source_connectors/drawing_facts_conn.py — fold the DETERMINISTIC drawing_facts extract into
the estimate's part records. Layer 2 of the source waterfall: printed-on-the-drawing facts,
read by pdfplumber+regex (no LLM, no hallucination). Non-destructive — it only FILLS a field
the engine left empty, and it SURFACES weights / tube sizes as review flags. It never
overwrites a value the engine already resolved, and it never touches a cost formula.

Applied via apply_drawing_facts_to_part_estimates(summary, facts). `facts` is the dict from
drawing_facts.extract_drawing_facts(pdf_path). Matching is by part number.

Effects (each guarded, each flagged for the estimator):
  - material : set normalized_material where the engine has none  -> fixes timber/MDF parts
               being routed as steel (e.g. a lacquered MDF rail lasered as metal).
  - finish   : set the finish where the engine has none           -> powder/lacquer resolved.
  - weight   : attach drawing_weight_g + a flag                   -> the mass the estimator can
               cost by, and a sanity check on the geometry-derived material.
  - tube     : attach tube_section + cut_length + a flag          -> the real stock for a tube
               part (30x30x1.5 @ length), so it is not mis-costed as a mystery sheet blank.

SOURCE_NAME/RELIABILITY tag the provenance. Wiring the CALL into main/file_scan is a small,
reviewed step; this mapping is isolated + unit-testable first.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

SOURCE_NAME = "drawing_pdf"
RELIABILITY = 0.9  # printed fact, deterministic read — below native/DXF (1.0), above LLM/guess


def _clean_pn(s: Any) -> str:
    return str(s or "").strip().upper()


def _facts_by_part(facts: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for pn, d in (facts.get("by_part") or {}).items():
        k = _clean_pn(pn)
        if k:
            out[k] = d
    return out


def apply_drawing_facts_to_part_estimates(summary: Dict[str, Any], facts: Dict[str, Any]) -> Dict[str, int]:
    """Non-destructively enrich estimate_summary.part_estimates from the deterministic drawing
    facts. Returns counts of what changed. Never overwrites a resolved value; never edits costs."""
    out = {"material_set": 0, "finish_set": 0, "weight_flagged": 0, "tube_flagged": 0}
    if not isinstance(summary, dict) or not isinstance(facts, dict):
        return out
    by_part = _facts_by_part(facts)
    if not by_part:
        return out
    es = summary.get("estimate_summary") or {}
    parts = es.get("part_estimates")
    if not isinstance(parts, list):
        return out

    for p in parts:
        if not isinstance(p, dict):
            continue
        pn = _clean_pn(p.get("part_number"))
        d = by_part.get(pn)
        if not d:
            continue

        # material — only where the engine has nothing solid (fixes timber/MDF routed as steel)
        mat = d.get("material")
        if mat and not str(p.get("normalized_material") or "").strip():
            p["normalized_material"] = mat
            p.setdefault("review_flags", []).append(f"Material '{mat}' from drawing (title block)")
            out["material_set"] += 1

        # finish — only where the engine has none (powder / lacquer resolved from the drawing)
        fin = d.get("finish")
        if fin and not str(p.get("finish") or p.get("normalized_finish") or "").strip():
            p["finish"] = fin
            p.setdefault("review_flags", []).append(f"Finish '{fin}' from drawing (title block)")
            out["finish_set"] += 1

        # weight — attach + flag (the mass the estimator can cost by; sanity vs geometry)
        wt = d.get("weight_g")
        if wt and not p.get("drawing_weight_g"):
            p["drawing_weight_g"] = wt
            p.setdefault("review_flags", []).append(
                f"Drawing weight {wt} g — material can be costed by mass if blank dims are missing")
            out["weight_flagged"] += 1

        # tube — attach the real stock section + cut length so a tube is not mis-costed as sheet
        tube, cutlen = d.get("tube_section"), d.get("cut_length_mm")
        if tube and not p.get("tube_section"):
            p["tube_section"] = tube
            if cutlen:
                p["tube_cut_length_mm"] = cutlen
            p.setdefault("review_flags", []).append(
                f"Tube stock {tube}" + (f" @ {cutlen}mm" if cutlen else "") + " (from drawing) — cost as tube, not sheet")
            out["tube_flagged"] += 1

    # Weld-process surfacing (honest, non-costing) — the drawing may specify TIG, but the
    # estimators' workbook has only a "Weld (CO2)" rate row (no TIG rate). We cannot invent a
    # TIG rate, so we do NOT silently re-route; instead we FLAG every welded part so the
    # estimator sees "drawing says TIG, sheet is costing CO2 — confirm the process/rate".
    out["weld_flagged"] = 0
    _weld = str(((facts.get("spec_block") or {}).get("weld_spec")) or "")
    if "TIG" in _weld.upper():
        for p in parts:
            if not isinstance(p, dict):
                continue
            _mi = p.get("manufacturing_interpretation") or {}
            _ops = _mi.get("textual_operations") or _mi.get("operations") or []
            if any("weld" in str(o).lower() for o in _ops) or p.get("is_sub_assembly"):
                p.setdefault("review_flags", []).append(
                    "Drawing weld spec: TIG — workbook costs at Weld (CO2) rate "
                    "(no TIG rate in WB); confirm weld process/rate")
                out["weld_flagged"] += 1

    return out
