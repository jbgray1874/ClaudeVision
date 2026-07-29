import csv
import hashlib
import json
import os
import re
import time
from datetime import date, datetime, timezone
from math import floor
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from source_precedence import apply_field as _apply_field

import config
from config import (
    CSV_HEADERS,
    HOURLY_RATES_GBP,
    LABOUR_RULES,
    MATERIAL_DENSITY_KG_PER_M3,
    MATERIAL_PRICE_GBP_PER_KG,
    NESTING_RULES,
    STANDARD_SHEET_SIZES_MM,
    WORKBOOK_EQUIVALENT_PRICING,
)
from estimate_source_extract import build_estimate_source_extract
from price_sources import PriceRequest, get_best_price
from unit_parsing import is_per_kg_unit, is_per_hour_unit

# Lazy PricingService singleton — the newer, token-scored pricing engine
# (UDEF + historical-quote RAG + supplier catalogue + LLM fallback). Used as a
# FALLBACK in _resolve_part_system_cost: the legacy price_sources connector
# (UDEF-only, no historical RAG) returns None for bought-in items like the loom,
# leaving them at the £0.42 handling floor. PricingService finds them
# (e.g. "50cm LOOM" -> £24.15 from historical_quote_material_line) so bought-in
# line items in the workbook are priced from the identified drawing items rather
# than the £0.42 floor or a static manual JSON.
_PRICING_SERVICE_SINGLETON = None
_PRICING_SERVICE_FAILED = False

def _get_pricing_service():
    """Return a shared PricingService, or None if it can't be constructed
    (e.g. DB unavailable). Cached; never raises into the estimate path."""
    global _PRICING_SERVICE_SINGLETON, _PRICING_SERVICE_FAILED
    if _PRICING_SERVICE_SINGLETON is not None:
        return _PRICING_SERVICE_SINGLETON
    if _PRICING_SERVICE_FAILED:
        return None
    try:
        from pricing_service import PricingService
        _PRICING_SERVICE_SINGLETON = PricingService()
        return _PRICING_SERVICE_SINGLETON
    except Exception:
        _PRICING_SERVICE_FAILED = True
        return None


def _first(values: List[Any]) -> Any:
    return values[0] if values else None


def _join(values: List[Any]) -> str:
    return "; ".join(str(value) for value in values if value not in (None, ""))


def _safe_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_stated_weight_kg(part: Dict[str, Any]) -> Optional[float]:
    """Extract a stated weight from the part's extracted 'weights' field (e.g. '885g', '1.2KG').
    Also checks stated_weight_g field written by file_scan weight extraction."""
    # Direct stated_weight_g field (written by improved weight regex in file_scan.py)
    _swg = _safe_float(part.get("stated_weight_g"))
    if _swg is not None and _swg > 0:
        _kg = _swg / 1000.0
        if 0.001 <= _kg <= 500.0:
            return round(_kg, 4)
    weights = part.get("weights") or part.get("title_block", {}).get("weights") or []
    if isinstance(weights, str):
        weights = [weights]
    for w in weights:
        text = str(w).strip().upper().replace(",", "")
        m = re.match(r"^([0-9]+(?:\.[0-9]+)?)\s*(KG|G)$", text)
        if not m:
            continue
        val = float(m.group(1))
        if m.group(2) == "G":
            val = val / 1000.0
        if 0.001 <= val <= 500.0:
            return round(val, 4)
    return None


def _stated_weight_kg_for_part(part: Dict[str, Any]) -> Optional[float]:
    """Prefer DXF flat-pattern mass; fall back to title-block WEIGHT (e.g. 138.85g)."""
    dxf_g = _safe_float(part.get("dxf_weight_g"))
    if dxf_g is not None and dxf_g > 0:
        return round(dxf_g / 1000.0, 4)
    dxf_kg = _safe_float(part.get("dxf_weight_kg"))
    if dxf_kg is not None and dxf_kg > 0:
        return round(dxf_kg, 4)
    return _parse_stated_weight_kg(part)


def _weight_source_label(part: Dict[str, Any]) -> str:
    if part.get("dxf_weight_g") or part.get("dxf_weight_kg"):
        return "dxf_flat_pattern"
    if part.get("geometry_source") == "dxf_flat_pattern" or part.get("dxf_augmented"):
        return "dxf_flat_pattern"
    if str(part.get("geometry_source") or "") == "solidworks_flat_pattern":
        return "solidworks_flat_pattern"
    return "pdf_stated"


def _safe_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_price_source_key(value: Any) -> str:
    return str(value or "").strip().lower()


def _rounding_mode() -> str:
    policy = getattr(config, "ROUNDING_POLICY", {}) or {}
    return str(policy.get("mode", "final_total_only")).strip().lower()


def _estimate_policy_snapshot_for_manifest() -> Dict[str, Any]:
    """Stable snapshot hashed into estimate_policy_manifest.policy_fingerprint_sha256."""
    wb = getattr(config, "WORKBOOK_INPUT_DEFAULTS", {}) or {}
    section = getattr(config, "SECTION_STOCK_POLICY", {}) or {}
    return {
        "estimate_policy_version": getattr(config, "ESTIMATE_POLICY_VERSION", "unknown"),
        "scrap_fraction": getattr(config, "SCRAP_PERCENTAGE", 0),
        "output_manufacturing_cost_only": bool(getattr(config, "OUTPUT_MANUFACTURING_COST_ONLY", False)),
        "assumed_job_quantity": wb.get("default_job_quantity"),
        "scrap_pct_workbook": wb.get("scrap_pct"),
        "powder_costing_policy": dict(getattr(config, "POWDER_COSTING_POLICY", {}) or {}),
        "labour_rule_powder_coating": dict((getattr(config, "LABOUR_RULES", {}) or {}).get("powder_coating", {}) or {}),
        "hourly_rate_powder_coating_gbp": float(HOURLY_RATES_GBP.get("powder_coating", 0.0) or 0.0),
        "rounding_policy": dict(getattr(config, "ROUNDING_POLICY", {}) or {}),
        "section_stock_waste_factor_pct": section.get("waste_factor_pct"),
    }


def _estimate_policy_fingerprint_sha256(snapshot: Dict[str, Any]) -> str:
    payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _build_estimate_policy_manifest() -> Dict[str, Any]:
    snap = _estimate_policy_snapshot_for_manifest()
    return {
        "schema": "estimate_policy_manifest.v1",
        "policy_fingerprint_sha256": _estimate_policy_fingerprint_sha256(snap),
        "policy_snapshot": snap,
        "calibration_notes": [
            "Powder throughput: divide actual booth hours into known coated area from one closed job "
            "to fit LABOUR_RULES['powder_coating']['throughput_m2_per_hour'].",
            "Powder £/kg: use POWDER_MATERIAL_GBP_PER_KG and POWDER_MATERIAL_SPECIAL_GBP_PER_KG for standard vs metallics/textures.",
        ],
    }


def _build_estimate_review_signals(part_estimates: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Rolls up heuristic risk_flags and quantitative gates so dashboards can queue human review early.
    """
    conf_thr = float(os.getenv("ESTIMATE_PART_CONFIDENCE_REVIEW_BELOW", "0.65") or "0.65")
    geom_thr = float(os.getenv("ESTIMATE_GEOMETRY_REVIEW_BELOW", "0.70") or "0.70")
    parts_out: List[Dict[str, Any]] = []
    for p in part_estimates:
        reasons: List[Dict[str, Any]] = []
        for rf in p.get("risk_flags") or []:
            reasons.append({"code": "risk_flag", "detail": str(rf)})
        assump = (p.get("cost_breakdown") or {}).get("assumptions") or {}
        pc_val = _safe_float(assump.get("part_confidence_overall"))
        if pc_val is not None and pc_val < conf_thr:
            reasons.append({"code": "low_part_confidence", "detail": pc_val})
        proc = p.get("process_estimate") or {}
        gr = _safe_float(proc.get("geometry_reliability"))
        times_min = proc.get("times_min") or {}
        if "powder_coating" in times_min and gr is not None and gr < geom_thr:
            reasons.append({"code": "low_geometry_reliability_with_powder", "detail": gr})
        if reasons:
            parts_out.append({"part_number": p.get("part_number"), "reasons": reasons})
    rec = "manual_review_recommended" if parts_out else "no_automatic_flags"
    return {
        "schema": "estimate_review_signals.v1",
        "thresholds": {"part_confidence_below": conf_thr, "geometry_with_powder_below": geom_thr},
        "parts_flagged": parts_out,
        "flagged_part_count": len(parts_out),
        "recommendation": rec,
    }


def _mfg_lookup(parts: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Map part_number (and description fallback) to manufacturing writeup part."""
    by_pn: Dict[str, Dict[str, Any]] = {}
    by_desc: Dict[str, Dict[str, Any]] = {}
    for p in parts:
        pn = str(p.get("part_number") or "").strip()
        if pn and pn.upper() not in ("NONE", "?"):
            by_pn[pn.upper()] = p
        dsc = str(p.get("description") or "").strip().upper()
        if dsc:
            by_desc[dsc] = p
    out = dict(by_pn)
    out.update({f"__DESC__{k}": v for k, v in by_desc.items()})
    return out


def _resolve_mfg_part(mfg_by_key: Dict[str, Dict[str, Any]], est_part: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    pn = str(est_part.get("part_number") or "").strip().upper()
    if pn and pn not in ("NONE", "?"):
        hit = mfg_by_key.get(pn)
        if hit:
            return hit
    dsc = str(est_part.get("description") or "").strip().upper()
    if dsc:
        return mfg_by_key.get(f"__DESC__{dsc}")
    return None


def _has_native_flat(part: Dict[str, Any]) -> bool:
    """True when the blank came from the SolidWorks sheet-metal CUT LIST — a modelled flat
    pattern, i.e. the same measured truth as a DXF flat (it is what generates the DXF), and
    sanity-gated against the solid before it is written. Kept as a separate predicate from
    the DXF ones so nothing anywhere claims a DXF exists when it does not; every gate that
    means "this part has measured geometry" ORs the two together."""
    if not isinstance(part, dict):
        return False
    return bool(part.get("native_flat_pattern")) or (
        str(part.get("geometry_source") or "").lower() == "solidworks_flat_pattern"
    )


def _part_has_part_dxf(mfg: Dict[str, Any]) -> bool:
    # A modelled flat pattern is measured geometry of the same class as a DXF flat, so the
    # credibility gate must accept it — otherwise a fully native job (better data than any
    # DXF job) would be stamped "insufficient data" for lacking a file it does not need.
    if _has_native_flat(mfg):
        return True
    if mfg.get("dxf_augmented"):
        return True
    gs = str(mfg.get("geometry_source") or "").lower()
    return "dxf" in gs


def _part_cost_credibility(mfg: Optional[Dict[str, Any]], est_part: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Return (credible, reasons) for whether this part's cost belongs in the headline total."""
    reasons: List[str] = []
    ext = float(est_part.get("extended_total_cost_gbp") or 0.0)
    if ext <= 0:
        return True, []

    mfg = mfg or {}

    # Bought-in parts structurally never have a DXF -- that's not a credibility
    # problem, it's the nature of the part. Exempt them from no_part_dxf so a
    # well-priced catalogue/historical line doesn't drag the cost-credibility
    # ratio down for lacking geometry it was never going to have. page_roles
    # is the signal confirmed 100%-reliable against real job data (1282,
    # all 15 bought-in parts) -- see credibility gate probe.
    if "bought_in" in [str(r).lower() for r in (mfg.get("page_roles") or [])]:
        return True, []

    rf_blob = " ".join(str(x) for x in (est_part.get("risk_flags") or []))

    if mfg.get("geometry_inferred"):
        reasons.append("geometry_inferred_provisional")
    if "implausible_system_cost_rejected" in rf_blob:
        reasons.append("rejected_catalogue_match")
    # SolidWorks named the material but the model yielded no blank/mass/section, so the
    # material cost is not derivable. Never let that line pass as a credible £0.
    if mfg.get("native_material_without_geometry"):
        reasons.append("native_material_no_geometry")

    has_dxf = _part_has_part_dxf(mfg)
    gr = _safe_float((est_part.get("process_estimate") or {}).get("geometry_reliability"))
    if gr is None:
        gr = _safe_float(((mfg.get("geometry_rollup") or {}).get("confidence") or {}).get("geometry_reliability"))

    if not has_dxf:
        reasons.append("no_part_dxf")
        cut = float((mfg.get("geometry_rollup") or {}).get("estimated_cut_length_mm") or 0)
        if cut > 3000 and (gr or 0) < 1.0:
            reasons.append("pdf_geometry_inflation_suspected")

    return (len(reasons) == 0), reasons


def _assess_estimate_data_sufficiency(
    source_parts: List[Dict[str, Any]],
    part_estimates: List[Dict[str, Any]],
    document_total: float,
) -> Dict[str, Any]:
    """
    Decide whether the document headline total is credible enough to report.
    GA-only jobs where most £ comes from PDF geometry / rejected catalogue hits
    are stamped INSUFFICIENT DATA and the reportable total is suppressed.
    """
    min_cost_ratio = float(getattr(config, "DATA_SUFFICIENCY_MIN_CREDIBLE_COST_RATIO", 0.50) or 0.50)
    min_dxf_ratio = float(getattr(config, "DATA_SUFFICIENCY_MIN_DXF_PART_RATIO", 0.25) or 0.25)

    mfg_by_key = _mfg_lookup(source_parts)
    credible_cost = 0.0
    unreliable_cost = 0.0
    unreliable_parts: List[Dict[str, Any]] = []

    for est in part_estimates:
        ext = float(est.get("extended_total_cost_gbp") or 0.0)
        mfg = _resolve_mfg_part(mfg_by_key, est)
        ok, reasons = _part_cost_credibility(mfg, est)
        if ext > 0 and not ok:
            unreliable_cost += ext
            unreliable_parts.append({
                "part_number": est.get("part_number"),
                "description": est.get("description"),
                "extended_cost_gbp": round(ext, 2),
                "reasons": reasons,
            })
        elif ext > 0:
            credible_cost += ext

    fabricated = [
        p for p in source_parts
        if str(p.get("normalized_material") or "").upper()
        not in {"BOUGHT_IN", "PAPER", "PRINTED_PAPER", "UNKNOWN", ""}
        and str(p.get("part_number") or "").upper() not in ("", "NONE", "?")
    ]
    with_dxf = [p for p in fabricated if _part_has_part_dxf(p)]
    dxf_part_ratio = len(with_dxf) / max(len(fabricated), 1)
    credible_cost_ratio = credible_cost / max(document_total, 0.01) if document_total > 0 else 1.0

    insufficient = False
    if document_total > 0 and credible_cost_ratio < min_cost_ratio:
        insufficient = True
    elif len(fabricated) >= 2 and dxf_part_ratio < min_dxf_ratio:
        insufficient = True

    status = "insufficient_data" if insufficient else "ok"
    msg = (
        "INSUFFICIENT DATA — part DXFs required for credible auto-estimate"
        if insufficient else "Data sufficiency OK"
    )

    if insufficient:
        print(
            f"   [data] {msg} — credible {credible_cost_ratio:.0%} of £{document_total:,.2f}; "
            f"DXF on {dxf_part_ratio:.0%} of {len(fabricated)} fabricated part(s); headline suppressed",
            flush=True,
        )

    return {
        "schema": "estimate_data_sufficiency.v1",
        "status": status,
        "message": msg,
        "suppress_headline_total": insufficient,
        "document_total_provisional_gbp": round(document_total, 2),
        "document_total_reportable_gbp": None if insufficient else round(document_total, 2),
        "credible_cost_gbp": round(credible_cost, 2),
        "unreliable_cost_gbp": round(unreliable_cost, 2),
        "credible_cost_ratio": round(credible_cost_ratio, 4),
        "fabricated_part_count": len(fabricated),
        "parts_with_dxf": len(with_dxf),
        "dxf_part_ratio": round(dxf_part_ratio, 4),
        "thresholds": {
            "min_credible_cost_ratio": min_cost_ratio,
            "min_dxf_part_ratio": min_dxf_ratio,
        },
        "unreliable_parts": unreliable_parts,
    }


def _money_decimals() -> int:
    policy = getattr(config, "ROUNDING_POLICY", {}) or {}
    return int(policy.get("money_decimals", 2))


def _round_money(value: Any) -> float:
    numeric = _safe_float(value) or 0.0
    return round(numeric, _money_decimals())


def _part_powder_material_extended_gbp(part_estimate: Dict[str, Any]) -> float:
    pc = (part_estimate.get("material_estimate") or {}).get("powder_consumable")
    if not isinstance(pc, dict):
        return 0.0
    return float(pc.get("extended_powder_material_cost_gbp") or 0.0)


def _part_powder_labour_gbp(part_estimate: Dict[str, Any]) -> float:
    costs = (part_estimate.get("labour_estimate") or {}).get("costs_gbp") or {}
    return float(costs.get("powder_coating") or 0.0)


def _extract_selected_price(result: Dict[str, Any]) -> Dict[str, Any]:
    selected = result.get("selected") or {}
    return selected if isinstance(selected, dict) else {}


def _selected_price_value(selected: Dict[str, Any]) -> Optional[float]:
    try:
        price = selected.get("price")
        return float(price) if price is not None else None
    except (TypeError, ValueError):
        return None


def _selected_price_unit(selected: Dict[str, Any]) -> str:
    return str(selected.get("unit") or "").strip().lower()


def _build_price_source_metadata(result: Dict[str, Any], fallback_source: str, applied: bool, applied_basis: str | None = None) -> Dict[str, Any]:
    selected = _extract_selected_price(result)
    evidence = selected.get("evidence", {}) if isinstance(selected.get("evidence"), dict) else {}
    metadata = selected.get("metadata", {}) if isinstance(selected.get("metadata"), dict) else {}
    evidence_row = evidence.get("row", {}) if isinstance(evidence.get("row"), dict) else {}
    supplier_source = (
        metadata.get("supplier_name")
        or metadata.get("supplier_source")
        or evidence.get("supplier_name")
        or evidence.get("supplier_source")
        or evidence_row.get("supplier_name")
        or evidence_row.get("supplier_source")
        or selected.get("source")
        or fallback_source
    )
    source_name = selected.get("source") or fallback_source
    source_rank = (config.PRICE_FRESHNESS_RULES or {}).get("source_priority", {}).get(str(source_name), 0)
    freshness_bucket = _price_freshness_bucket(metadata.get("price_date") or evidence.get("price_date") or evidence_row.get("price_date"))
    freshness_penalty = (config.PRICE_FRESHNESS_RULES or {}).get("freshness_penalty", {}).get(freshness_bucket, 20.0)

    src_type = "external" if selected.get("source") else "config"
    if evidence.get("pricing_mode") == "web_ai_llm_estimate" or metadata.get("pricing_mode") == "web_ai_llm_estimate":
        src_type = "web_ai_fallback"
    elif str(source_name).lower() == "web" and selected.get("source"):
        src_type = "web_catalog"

    return {
        "supplier_source": supplier_source,
        "supplier_code": metadata.get("supplier_code") or evidence.get("supplier_code") or evidence_row.get("supplier_code"),
        "price_date": metadata.get("price_date") or evidence.get("price_date") or str(date.today()),
        "source_type": src_type,
        "source_name": source_name,
        "source_rank": source_rank,
        "unit": selected.get("unit") or "unknown",
        "currency": selected.get("currency") or "GBP",
        "confidence": selected.get("confidence"),
        "applied": applied,
        "applied_basis": applied_basis,
        "freshness_bucket": freshness_bucket,
        "freshness_penalty": freshness_penalty,
        "source_note": evidence.get("source_note") or metadata.get("source_note"),
        "web_query": evidence.get("web_query"),
        "selected": selected,
        "audit_trail": result.get("audit_trail", []),
        "candidates": result.get("candidates", []),
    }


def _price_freshness_bucket(raw_date: Any) -> str:
    if not raw_date:
        return "unknown"
    text = str(raw_date).strip().replace("T", " ")
    parsed = None
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y"):
        try:
            parsed = date.fromisoformat(text[:10]) if fmt == "%Y-%m-%d" else None
            if parsed is None:
                from datetime import datetime as _dt

                parsed = _dt.strptime(text[:19], fmt).date()
            break
        except Exception:
            continue
    if parsed is None:
        return "unknown"
    age = max(0, (date.today() - parsed).days)
    fresh_days = int((config.PRICE_FRESHNESS_RULES or {}).get("default_days_fresh", 30))
    stale_days = int((config.PRICE_FRESHNESS_RULES or {}).get("default_days_stale", 120))
    if age <= fresh_days:
        return "fresh"
    if age <= stale_days:
        return "stale"
    return "unknown"


def _quantity_break_multiplier(quantity: int) -> float:
    cfg = WORKBOOK_EQUIVALENT_PRICING or {}
    breaks = cfg.get("quantity_breaks") or []
    for br in breaks:
        qmin = int(br.get("min_qty", 1))
        qmax = br.get("max_qty")
        qmax_i = int(qmax) if qmax is not None else None
        if quantity >= qmin and (qmax_i is None or quantity <= qmax_i):
            return float(br.get("multiplier", 1.0))
    return 1.0


def _part_ops(part: Dict[str, Any]) -> List[str]:
    ops: List[str] = []
    for op in (part.get("textual_operations") or []) + (part.get("inferred_operations") or []):
        s = str(op).strip()
        if s and s not in ops:
            ops.append(s)
    return ops


def _part_confidence_overall(part: Dict[str, Any]) -> Optional[float]:
    conf = part.get("confidence")
    if isinstance(conf, dict):
        v = _safe_float(conf.get("overall"))
        if v is not None:
            return v
        vals = [_safe_float(x) for x in conf.values() if _safe_float(x) is not None]
        if vals:
            return round(sum(vals) / len(vals), 4)
    return None


def _part_geometry_reliability(part: Dict[str, Any]) -> Optional[float]:
    return _safe_float(
        ((part.get("geometry_rollup") or {}).get("confidence") or {}).get("geometry_reliability")
    )


def _resolve_material_price(material: Optional[str], thickness_mm: Optional[float], quantity: Optional[int], part: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not material:
        return {"result": {}, "applied_price_per_kg": None, "applied_basis": None}

    result = get_best_price(
        PriceRequest(
            kind="material_price",
            material=material,
            thickness_mm=thickness_mm,
            quantity=quantity,
            description=str((part or {}).get("description") or ""),
            finish=_first((part or {}).get("surface_finishes", []) or []),
            colour=_first((part or {}).get("colours", []) or []),
            part_confidence_overall=_part_confidence_overall(part or {}),
            part_geometry_reliability=_part_geometry_reliability(part or {}),
        )
    )
    selected = _extract_selected_price(result)
    price = _selected_price_value(selected)
    unit = _selected_price_unit(selected)
    if price is None:
        return {"result": result, "applied_price_per_kg": None, "applied_basis": None}

    if is_per_kg_unit(unit):
        return {"result": result, "applied_price_per_kg": price, "applied_basis": "GBP_per_kg"}

    return {"result": result, "applied_price_per_kg": None, "applied_basis": None}


def _parse_section_profile(description: str) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """
    Parse common section profile from description, e.g.:
    '25.00 x 25.00 x 1.50mm TUBE' -> (25.0, 25.0, 1.5)
    """
    text = str(description or "").upper().replace("MM", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*[Xx]\s*(\d+(?:\.\d+)?)\s*[Xx]\s*(\d+(?:\.\d+)?)", text)
    if not m:
        return None, None, None
    return _safe_float(m.group(1)), _safe_float(m.group(2)), _safe_float(m.group(3))


def _lookup_catalogue_tube_price(
    side_a_mm: Optional[float],
    side_b_mm: Optional[float],
    wall_t_mm: Optional[float],
    length_mm: Optional[float],
) -> Optional[Dict[str, Any]]:
    """Find a genuine catalogued price for a detected hollow section by matching its
    PROFILE (and length, when available) against priced rows in UDEF
    (dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING). SDI stocks slotted/cut tube as bought-in
    parts (e.g. SLOTTEDTUBE01/02 = 'ERW RECT. 60 x 30 x 1.5mm @ 1125mm/1072mm',
    £3.57 EA, Preferred Tubes Ltd), so a detected 60x30x1.5 @ 1125mm tube should price
    from that real catalogue row, NOT a generic mass*£/kg estimate.

    Matching is genuine: the catalogue description carries the profile and length, so we
    match on the two cross-section dims + wall, then prefer the row whose stated length is
    closest to the detected length. Returns the priced row (price, supplier, code, desc) or
    None — never raises, never invents a price.
    """
    if not (side_a_mm and side_b_mm and wall_t_mm):
        return None
    try:
        import config as _cfg
        cn = _cfg.get_connection(timeout=20)
    except Exception:
        return None
    try:
        cur = cn.cursor()
        # Normalise the two cross-section dimensions (order-independent: 60x30 == 30x60).
        _lo, _hi = sorted([round(side_a_mm), round(side_b_mm)])
        # Pull candidate priced section rows; match dims in Python (descriptions vary in format).
        cur.execute(
            """SELECT [Part code],[Description],[System cost per],[Supplier name],[UOM]
               FROM dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING
               WHERE [System cost per] > 0
                 AND ([Description] LIKE '%TUBE%' OR [Part code] LIKE 'SLOTTEDTUBE%'
                      OR [Description] LIKE '%RECT%' OR [Description] LIKE '%RHS%' OR [Description] LIKE '%SHS%')"""
        )
        rows = cur.fetchall()
    except Exception:
        try:
            cn.close()
        except Exception:
            pass
        return None
    finally:
        try:
            cn.close()
        except Exception:
            pass

    best = None
    best_len_delta = None
    prof_re = re.compile(r"(\d+(?:\.\d+)?)\s*[xX]\s*(\d+(?:\.\d+)?)\s*[xX]\s*(\d+(?:\.\d+)?)")
    len_re = re.compile(r"(?:@|x|X)\s*(\d{2,5})\s*MM", re.IGNORECASE)
    for r in rows:
        code, desc, cost, supplier, uom = r[0], str(r[1] or ""), r[2], r[3], r[4]
        pm = prof_re.search(desc.upper())
        if not pm:
            continue
        d = sorted([round(float(pm.group(1))), round(float(pm.group(2))), float(pm.group(3))])
        # d = [wall, lo, hi] after sort (wall is smallest)
        cat_wall, cat_lo, cat_hi = d[0], round(d[1]), round(d[2])
        if not (cat_lo == _lo and cat_hi == _hi and abs(cat_wall - wall_t_mm) < 0.3):
            continue  # profile must match
        # Length proximity (if the catalogue row and the part both state a length).
        lm = len_re.search(desc.upper())
        cat_len = float(lm.group(1)) if lm else None
        if length_mm and cat_len:
            delta = abs(cat_len - length_mm)
        else:
            delta = 1e9  # no length to compare — weak match, keep only if nothing better
        # Prefer Preferred Tubes Ltd when multiple suppliers carry the same code/price.
        _pref = 0 if (supplier and "PREFER" in str(supplier).upper()) else 1
        key = (delta, _pref)
        if best is None or key < best_len_delta:
            best = {
                "part_code": code,
                "description": desc.strip(),
                "unit_price_gbp": float(cost),
                "supplier": str(supplier or "").strip(),
                "uom": str(uom or "").strip(),
                "catalogue_length_mm": cat_len,
            }
            best_len_delta = key

    # LENGTH GATE — a catalogue tube row is a specific bought-in cut piece at a stated stock
    # length (e.g. SLOTTEDTUBE 60x30x1.5 @1125mm). It is only a genuine price for a part of
    # THAT length. Without this gate a 1342mm cut and a 529.8mm cut of the same profile both
    # match the same row and take the same fixed price — which is exactly wrong (they should
    # differ by length). So when the PART length is known, only accept the catalogue price if
    # the catalogue length is within tolerance; otherwise return None so the caller costs by
    # the length-sensitive mass path (kg/m x length x £/kg) — honest, repeatable, per-length.
    if best is not None and length_mm:
        _cat_len = best.get("catalogue_length_mm")
        _tol = max(0.10 * length_mm, 75.0)
        if not (_cat_len and abs(float(_cat_len) - length_mm) <= _tol):
            return None
    return best


# Cache the HIPS rate table per-thickness for the duration of one run so we don't
# re-query UDEF for every HIPS part. Keyed by rounded thickness; value is £/m².
_HIPS_RATE_CACHE: Dict[float, Optional[float]] = {}


def _resolve_board_sheet_rate_gbp_per_m2(material: str, thickness_mm: Optional[float]) -> Optional[Dict[str, Any]]:
    """Live £/m² rate for a plastic sheet material (HIPS etc.) derived from the CURRENT
    UDEF catalogue, so it tracks price changes rather than a stale config table.

    Queries dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING for PLAIN stock HIPS sheets at the given
    thickness, parses 'L x W x Tmm' from the description, computes £/m² = System cost per
    ÷ sheet area for each, and returns the MEDIAN of the plain-stock rates. Premium items
    (printed / mirrored / flocked / vac-formed / gold / silver) and tiny offcuts are
    excluded so the rate reflects plain sheet stock, not finished graphics.

    Returns {rate_gbp_per_m2, sample_count, thickness_mm, basis} or None (never raises,
    never invents a price). Consistent with the tube resolver: real catalogue rows only.
    """
    _mat_u = str(material or "").upper()
    # Only HIPS is sourced this way for now; other boards keep their existing path.
    if "HIPS" not in _mat_u:
        return None
    if thickness_mm is None:
        return None
    try:
        _t_key = round(float(thickness_mm), 1)
    except (TypeError, ValueError):
        return None
    if _t_key in _HIPS_RATE_CACHE:
        _cached = _HIPS_RATE_CACHE[_t_key]
        return None if _cached is None else {
            "rate_gbp_per_m2": _cached, "thickness_mm": _t_key,
            "sample_count": None, "basis": "udef_hips_median_cached",
        }

    try:
        import config as _cfg
        cn = _cfg.get_connection(timeout=20)
    except Exception:
        _HIPS_RATE_CACHE[_t_key] = None
        return None
    try:
        cur = cn.cursor()
        cur.execute(
            """SELECT [Part code],[Description],[System cost per]
               FROM dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING
               WHERE [System cost per] > 0 AND [Description] LIKE '%HIPS%'"""
        )
        rows = cur.fetchall()
    except Exception:
        rows = []
    finally:
        try:
            cn.close()
        except Exception:
            pass

    # Exclude premium / finished items — we want plain sheet stock rate only.
    _EXCLUDE = ("PRINT", "MIRROR", "FLOCK", "VAC", "GOLD", "SILVER", "FOIL",
                "GRAPHIC", "DIGITALLY", "SCREEN")
    _dim_re = re.compile(
        r"(\d{2,4}(?:\.\d+)?)\s*[xX]\s*(\d{2,4}(?:\.\d+)?)\s*[xX]\s*(\d(?:\.\d+)?)\s*mm",
        re.IGNORECASE)
    rates: List[float] = []
    for r in rows:
        desc = str(r[1] or "")
        du = desc.upper()
        if any(bad in du for bad in _EXCLUDE):
            continue
        m = _dim_re.search(desc)
        if not m:
            continue
        try:
            L, W, T = float(m.group(1)), float(m.group(2)), float(m.group(3))
            cost = float(r[2])
        except (TypeError, ValueError):
            continue
        if round(T, 1) != _t_key:
            continue
        area_m2 = (L * W) / 1_000_000.0
        if area_m2 < 0.05:          # skip tiny offcuts (inflated £/m²)
            continue
        rate = cost / area_m2
        if rate <= 0 or rate > 60:  # skip zero/anomalies and premium outliers
            continue
        rates.append(rate)

    if not rates:
        _HIPS_RATE_CACHE[_t_key] = None
        return None
    import statistics as _stats
    _median = round(_stats.median(rates), 2)
    _HIPS_RATE_CACHE[_t_key] = _median
    return {
        "rate_gbp_per_m2": _median,
        "thickness_mm": _t_key,
        "sample_count": len(rates),
        "basis": "udef_hips_median_live",
    }


def _infer_section_length_mm(part: Dict[str, Any]) -> Optional[float]:
    _ss_len = _safe_float((part.get("section_stock") or {}).get("length_mm"))
    if _ss_len is not None and _ss_len > 0:
        return _ss_len
    direct = _safe_float(part.get("length_mm"))
    if direct is not None and direct > 0:
        return direct
    geom = part.get("normalized_geometry", {}) or {}
    developed = _safe_float(geom.get("developed_length_mm"))
    if developed is not None and developed > 0:
        return developed
    overall = _safe_float(part.get("overall_length_mm"))
    if overall is not None and overall > 0:
        return overall
    dims = [_safe_float(v) for v in part.get("all_dimensions_mm", [])]
    dims = [v for v in dims if v is not None and v > 0]
    return max(dims) if dims else None


def _is_section_or_wire_candidate(part: Dict[str, Any], material: Optional[str]) -> bool:
    policy = getattr(config, "SECTION_STOCK_POLICY", {}) or {}
    if not bool(policy.get("enabled", True)):
        return False
    if part.get("section_stock"):
        return True
    tokens = [str(t).upper() for t in policy.get("section_keywords", [])]
    blob = " ".join(
        [
            str(part.get("description") or ""),
            str(part.get("normalized_material") or ""),
            str(material or ""),
        ]
    ).upper()
    return any(token in blob for token in tokens)


def _resolve_labour_rate(operation: str) -> Dict[str, Any]:
    result = get_best_price(PriceRequest(kind="labour_rate", operation=operation))
    selected = _extract_selected_price(result)
    price = _selected_price_value(selected)
    unit = _selected_price_unit(selected)
    if price is None:
        return {"result": result, "applied_hourly_rate": None, "applied_basis": None}

    if is_per_hour_unit(unit):
        return {"result": result, "applied_hourly_rate": price, "applied_basis": "GBP_per_hour"}

    return {"result": result, "applied_hourly_rate": None, "applied_basis": None}


def _resolve_part_system_cost(part: Dict[str, Any]) -> Dict[str, Any]:
    part_number = str(part.get("part_number") or "").strip()
    item_number = str(part.get("item_number") or "").strip()
    part_code = part_number or item_number
    description = str(part.get("description") or "").strip()
    if not part_code and not description:
        return {"result": {}, "applied_unit_cost": None, "matched_part_code": None}

    candidate_codes: List[str] = []
    for code in [part_code, part_number, item_number]:
        code = str(code or "").strip()
        if not code:
            continue
        candidate_codes.extend(
            [
                code,
                code.replace(" - ", "-"),
                code.replace(" ", ""),
                code.upper(),
                code.replace(" - ", "-").upper(),
                code.replace(" ", "").upper(),
            ]
        )

    dedup_codes: List[str] = []
    seen_codes = set()
    for code in candidate_codes:
        key = code.upper()
        if key not in seen_codes:
            seen_codes.add(key)
            dedup_codes.append(code)

    best_result: Dict[str, Any] = {}
    best_price: Optional[float] = None
    matched_part_code: Optional[str] = None

    for code in dedup_codes or [""]:
        result = get_best_price(
            PriceRequest(
                kind="part_system_cost",
                part_code=code,
                description=description,
            )
        )
        selected = _extract_selected_price(result)
        price = _selected_price_value(selected)
        if price is not None:
            return {"result": result, "applied_unit_cost": price, "matched_part_code": code}
        if not best_result:
            best_result = result
            best_price = price
            matched_part_code = code

    # FALLBACK: the legacy connector found no price. Try the newer PricingService
    # chain (UDEF + historical-quote RAG + supplier catalogue + LLM), which finds
    # bought-in items the legacy UDEF-only connector misses (e.g. the loom at
    # £24.15 from historical_quote_material_line). This is what stops identified
    # bought-in items landing at the £0.42 handling floor. Additive and guarded:
    # if PricingService is unavailable or returns nothing usable, behaviour is
    # unchanged from before.
    ps = _get_pricing_service()
    if ps is not None:
        try:
            anchor = ps._select_anchor_price_source(
                {
                    "part_number": part_code,
                    "description": description,
                    "normalized_material": part.get("normalized_material"),
                }
            )
            ps_price = _safe_float(anchor.get("unit_price_gbp")) if anchor else None
            if ps_price is not None and ps_price > 0:
                return {
                    "result": {
                        "selected": {
                            "source": anchor.get("source"),
                            "price": ps_price,
                            "confidence": anchor.get("confidence"),
                            "provenance": anchor.get("provenance"),
                            "review_required": anchor.get("review_required", False),
                            "review_reason": anchor.get("review_reason"),
                        }
                    },
                    "applied_unit_cost": ps_price,
                    "matched_part_code": part_code,
                }
        except Exception:
            pass

    return {"result": best_result, "applied_unit_cost": best_price, "matched_part_code": matched_part_code}


def _dxf_geometry_trusted(part: Dict[str, Any], ng: Dict[str, Any]) -> bool:
    """True when blank/bbox extents came from flat DXF, not PDF page vectors."""
    if part.get("dxf_augmented") or part.get("flat_pattern_detected"):
        return True
    if part.get("geometry_source") == "dxf_flat_pattern":
        return True
    if _has_native_flat(part):
        return True
    if str(ng.get("geometry_source") or "").lower() in {
            "dxf_flat_pattern", "dxf", "solidworks_flat_pattern"}:
        return True
    prov = part.get("provenance") or {}
    if str(prov.get("source") or "").lower() == "dxf":
        return True
    return False


def _plausible_blank_dimension_mm(value: Optional[float]) -> bool:
    if value is None or value <= 0:
        return False
    # Reject calendar years misread as dimensions.
    # Dates like "07/04/2021" get parsed as 2021.0mm — filter them out.
    if 1900.0 <= value <= 2100.0:
        return False
    policy = getattr(config, "BLANK_DIMENSION_POLICY", {}) or {}
    max_mm = float(policy.get("max_single_dim_mm", 2500.0))
    min_mm = float(policy.get("min_single_dim_mm", 1.0))
    return min_mm <= value <= max_mm


# Tolerance table sequence that appears on EVERY drawing border — NOT a part thickness.
_TOLERANCE_TABLE_SEQUENCE = {0.5, 1.0, 1.5, 2.0, 3.0}


def _safe_thickness_mm(part: Dict[str, Any]) -> Optional[float]:
    """
    Pick the first plausible thickness from the part.

    Priority order (most reliable first):
      1. DXF filename thickness — "part_2mm_PETG.DXF" -> 2.0  (MOST RELIABLE
         for flat parts; the fabricator names the file by stock thickness)
      2. normalized_thickness_mm (already resolved upstream)
      3. thicknesses_mm list, stripping tolerance-table boilerplate

    Rejects: year-like values (1900-2100), values <= 0, values outside 0.3-50mm.
    Returns None if no reliable thickness found.
    """
    # MATERIAL-AWARE FLOOR. A sheet-metal gauge of 0.5mm is ordinary; a 0.5mm timber panel
    # is not a thing. Board and timber stock starts around 3mm (hardboard/thin ply) and is
    # usually 6-25mm, so anything below that on a joinery part is the tolerance table
    # bleeding in, not a thickness. It reached the sheet as "0.5mm TIMBER" on the Horti
    # Crate. Reject it and return nothing: an absent thickness is visibly missing, whereas
    # a wrong one silently drives grouping, gauge pricing and any thickness-based timing.
    _mat_thk_u = " ".join([
        str(part.get("normalized_material") or ""),
        str(part.get("material") or ""),
    ]).upper()
    # Two floors, because the stock differs. Sheet board is made thin — 3mm MDF and 3mm ply
    # are stocked items — but solid timber is not: nobody machines a 3mm pine panel, and the
    # thinnest practical section is around 6mm. One floor would either let solid-timber noise
    # through or reject real thin board. Sheet goods are checked first so a veneered or
    # ply-faced product ("OAK VENEER MDF", "BIRCH PLY") takes the board floor, not the
    # timber one — it is a board, whatever species is on its face.
    _SHEET_BOARD_TOKENS = ("MDF", "PLYWOOD", "PLY", "CHIPBOARD", "OSB", "HARDBOARD")
    _SOLID_TIMBER_TOKENS = ("TIMBER", "WOOD", "PINE", "SOFTWOOD", "HARDWOOD", "OAK",
                            "SPRUCE", "BEECH", "BIRCH", "REDWOOD", "WHITEWOOD", "ASH")
    if any(t in _mat_thk_u for t in _SHEET_BOARD_TOKENS):
        _min_t = float(getattr(config, "MIN_BOARD_THICKNESS_MM", 3.0))
    elif any(t in _mat_thk_u for t in _SOLID_TIMBER_TOKENS):
        _min_t = float(getattr(config, "MIN_SOLID_TIMBER_THICKNESS_MM", 6.0))
    else:
        _min_t = 0.0

    def _ok(v: Optional[float]) -> bool:
        if v is None or v <= 0:
            return False
        if _min_t and v < _min_t:
            part.setdefault("review_flags", []).append(
                f"thickness {v:g}mm rejected: below the {_min_t:g}mm minimum for a "
                f"board/timber part — that is tolerance-table text, not a stock thickness. "
                f"Thickness left unset; confirm the board gauge from the drawing")
            return False
        return True

    _dfn = str(part.get("dxf_source_file") or part.get("geometry_source_path") or "")
    if _dfn:
        _tm = re.search(r"[_\-\s](\d+\.?\d*)\s*mm", _dfn, re.IGNORECASE)
        if _tm:
            _tv = _safe_float(_tm.group(1))
            if _tv and 0.3 <= _tv <= 25.0 and _ok(_tv):
                return _tv

    # Already-normalised thickness — skip tolerance-table noise when DXF exists
    raw = part.get("normalized_thickness_mm")
    if raw:
        v = _safe_float(raw)
        _max_t = float(getattr(config, "MAX_SHEET_THICKNESS_MM", 25.0))
        if v and 0.4 <= v <= _max_t and not (1900 <= v <= 2100) and _ok(v):
            if round(v, 1) not in _TOLERANCE_TABLE_SEQUENCE or not _dfn:
                return v

    # thicknesses_mm list with tolerance-table stripping
    _max_t = float(getattr(config, "MAX_SHEET_THICKNESS_MM", 25.0))
    candidates = [_safe_float(x) for x in part.get("thicknesses_mm", [])]
    # A6: reject implausible sheet thickness (e.g. a 500mm dimension misparsed as gauge)
    candidates = [v for v in candidates
                  if v and 0.3 <= v <= _max_t and not (1900 <= v <= 2100)]
    if not candidates:
        return None

    # Tolerance-table strip runs FIRST, on the unfiltered set. The board floor below would
    # otherwise remove 0.5/1.0/1.5/2.0 itself, break this subset test, and leave the 3.0
    # that is also part of the table looking like a real 3mm board.
    cand_set = set(round(v, 1) for v in candidates)
    if _TOLERANCE_TABLE_SEQUENCE.issubset(cand_set):
        stripped = [v for v in candidates if round(v, 1) not in _TOLERANCE_TABLE_SEQUENCE]
        # Only use the stripped list if something survives; otherwise the
        # original values ARE the real thickness (e.g. a 2mm-only acrylic part).
        if stripped:
            candidates = stripped
        elif _min_t:
            # Board/timber part whose ONLY thickness candidates are the tolerance table.
            # For metal the fall-back above is sound (0.5-3mm are real gauges), but no
            # board is made in those sizes, so there is nothing here to keep. Return
            # nothing rather than the 3.0 that happens to sit at the top of the table.
            part.setdefault("review_flags", []).append(
                "no board thickness on the drawing - the only values found were the "
                "tolerance table. Thickness left unset; confirm the board gauge")
            return None
    if not candidates:
        return None

    # Material-aware floor, applied after the table strip.
    candidates = [v for v in candidates if _ok(v)]
    if not candidates:
        return None

    from collections import Counter
    rounded = [round(v, 2) for v in candidates]
    _best = Counter(rounded).most_common(1)[0][0]
    return _best or None


def _title_block_blank_mm(part: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    """Drawing flat-pattern or L×W callout — preferred over inflated DXF bbox."""
    fp = part.get("flat_pattern_dimensions_mm") or []
    if len(fp) >= 2:
        a, b = _safe_float(fp[0]), _safe_float(fp[1])
        if a and b and _plausible_blank_dimension_mm(a) and _plausible_blank_dimension_mm(b):
            return max(a, b), min(a, b)
    dims = sorted(
        {
            v
            for v in (_safe_float(x) for x in (part.get("all_dimensions_mm") or []))
            if v is not None and _plausible_blank_dimension_mm(v) and v <= 800.0
        },
        reverse=True,
    )
    best_area: Optional[float] = None
    best_pair: Tuple[Optional[float], Optional[float]] = (None, None)
    for i, a in enumerate(dims):
        for b in dims[i + 1 :]:
            area = a * b
            if area < 5_000.0:
                continue
            if best_area is None or area < best_area:
                best_area = area
                best_pair = (max(a, b), min(a, b))
    if best_pair[0] and best_pair[1]:
        return best_pair
    blob = " ".join(
        [
            str(part.get("description") or ""),
            " ".join(str(x) for x in (part.get("all_dimensions_mm") or [])),
            str(part.get("purchased_size") or ""),
        ]
    )
    m = re.search(
        r"(\d{2,4}(?:\.\d+)?)\s*[xX×]\s*(\d{2,4}(?:\.\d+)?)\s*(?:mm)?",
        blob,
        flags=re.IGNORECASE,
    )
    if m:
        a, b = _safe_float(m.group(1)), _safe_float(m.group(2))
        if a and b and _plausible_blank_dimension_mm(a) and _plausible_blank_dimension_mm(b):
            return max(a, b), min(a, b)
    g03_l = _safe_float(part.get("blank_length_mm"))
    g03_w = _safe_float(part.get("blank_width_mm"))
    if g03_l and g03_w and _plausible_blank_dimension_mm(g03_l) and _plausible_blank_dimension_mm(g03_w):
        return max(g03_l, g03_w), min(g03_l, g03_w)
    ol = _safe_float(part.get("overall_length_mm"))
    ow = _safe_float(part.get("overall_width_mm"))
    if ol and ow and _plausible_blank_dimension_mm(ol) and _plausible_blank_dimension_mm(ow):
        if ol <= 700.0 and ow <= 700.0:
            return max(ol, ow), min(ol, ow)
    return None, None


def infer_primary_dimensions(part: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """
    Infer blank dimensions in priority order:
      1. DXF flat-pattern exact geometry  (blank_length_mm / blank_width_mm)
      2. DXF bounding box  (normalized_geometry bbox — not PDF page vectors)
      3. part.overall_length_mm / overall_width_mm  (drawing_job_merge / OCR)
      4. part.all_dimensions_mm  (dimension text from drawing)
    PDF estimated_cut_length is never used for blank size — it sums all page vectors.
    """
    ng = part.get("normalized_geometry") or {}
    if not isinstance(ng, dict):
        ng = {}

    # ── Priority 1: DXF exact flat-pattern ────────────────────────────────────
    dxf_l = _safe_float(ng.get("blank_length_mm"))
    dxf_w = _safe_float(ng.get("blank_width_mm"))
    if dxf_l and dxf_w and _plausible_blank_dimension_mm(dxf_l) and _plausible_blank_dimension_mm(dxf_w):
        # Only second-guess DXF when a side is implausibly large (e.g. whole-page bbox).
        # Normal flats (500 mm base ~565×542) must keep DXF blank — £/tonne clamp fixes material.
        if max(dxf_l, dxf_w) > 900.0 or min(dxf_l, dxf_w) > 700.0:
            tb_l, tb_w = _title_block_blank_mm(part)
            if tb_l and tb_w:
                dxf_area = dxf_l * dxf_w
                tb_area = tb_l * tb_w
                if dxf_area > 2.5 * tb_area and tb_area >= 10_000.0:
                    return {
                        "overall_length_mm": tb_l,
                        "overall_width_mm": tb_w,
                        "all_dimensions_mm": sorted([tb_l, tb_w], reverse=True),
                        "source": "title_block_preferred_over_inflated_dxf_blank",
                    }
        return {
            "overall_length_mm": dxf_l,
            "overall_width_mm": dxf_w,
            "all_dimensions_mm": sorted([dxf_l, dxf_w], reverse=True),
            # Report the flat pattern's ACTUAL source. Both are measured blanks, but a
            # modelled cut-list flat must not be reported to an estimator as a DXF.
            "source": ("solidworks_flat_pattern" if _has_native_flat(part)
                       else "dxf_flat_pattern"),
        }

    # ── Priority 2: DXF normalised geometry bounding box only ─────────────────
    if _dxf_geometry_trusted(part, ng):
        flat_box = ng.get("bounding_box_flat_mm", {}) if isinstance(ng, dict) else {}
        flat_length = _safe_float(flat_box.get("length"))
        flat_width = _safe_float(flat_box.get("width"))
        if (
            flat_length and flat_width
            and _plausible_blank_dimension_mm(flat_length)
            and _plausible_blank_dimension_mm(flat_width)
        ):
            return {
                "overall_length_mm": flat_length,
                "overall_width_mm": flat_width,
                "all_dimensions_mm": sorted([flat_length, flat_width], reverse=True),
                "source": "normalized_geometry_bbox",
            }

    # ── Priority 2b: G03 page-text blanks from document_builder ─────────────
    g03_l = _safe_float(part.get("blank_length_mm"))
    g03_w = _safe_float(part.get("blank_width_mm"))
    if (
        g03_l
        and g03_w
        and _plausible_blank_dimension_mm(g03_l)
        and _plausible_blank_dimension_mm(g03_w)
    ):
        return {
            "overall_length_mm": g03_l,
            "overall_width_mm": g03_w,
            "all_dimensions_mm": sorted([g03_l, g03_w], reverse=True),
            "source": "document_builder_g03",
        }

    # ── Priority 3: overall dimensions (merge / title block / OCR pick) ───────
    overall_length = _safe_float(part.get("overall_length_mm"))
    overall_width = _safe_float(part.get("overall_width_mm"))
    if (
        overall_length and overall_width
        and _plausible_blank_dimension_mm(overall_length)
        and _plausible_blank_dimension_mm(overall_width)
    ):
        return {
            "overall_length_mm": overall_length,
            "overall_width_mm": overall_width,
            "all_dimensions_mm": sorted([overall_length, overall_width], reverse=True),
            "source": "part_overall_dims",
        }

    # ── Priority 4: OCR / extracted dimension list ────────────────────────────
    dims = sorted(
        [
            v for v in (
                _safe_float(x) for x in part.get("all_dimensions_mm", [])
            )
            if v is not None and _plausible_blank_dimension_mm(v)
        ],
        reverse=True,
    )
    overall_length = overall_length if _plausible_blank_dimension_mm(overall_length) else None
    overall_width = overall_width if _plausible_blank_dimension_mm(overall_width) else None
    overall_length = overall_length or (dims[0] if dims else None)
    overall_width = overall_width or (dims[1] if len(dims) > 1 else None)
    return {
        "overall_length_mm": overall_length,
        "overall_width_mm": overall_width,
        "all_dimensions_mm": dims,
        "source": "ocr_dimensions" if len(dims) >= 2 else "no_dims_available",
    }


def _part_powder_text_blob(part: Dict[str, Any]) -> str:
    bits = [
        str(part.get("description") or ""),
        ";".join(str(x) for x in (part.get("process_notes") or [])),
        ";".join(str(x) for x in (part.get("surface_finishes") or [])),
        ";".join(str(x) for x in (part.get("colours") or [])),
    ]
    return " ".join(bits).upper()


def _effective_coated_faces_multiplier(part: Dict[str, Any]) -> Tuple[float, str]:
    """2.0 = both blank faces; reduced when SINGLE FACE / EXTERNAL ONLY etc. match description or notes."""
    policy = getattr(config, "POWDER_COSTING_POLICY", {}) or {}
    blob = _part_powder_text_blob(part)
    default_m = float(policy.get("coated_faces_multiplier", 2.0))
    for kw in policy.get("single_face_keywords") or []:
        k = str(kw).upper().strip()
        if k and k in blob:
            return float(policy.get("coated_faces_multiplier_single_face", 1.0)), "single_face_keyword"
    for kw in policy.get("partial_exterior_keywords") or []:
        k = str(kw).upper().strip()
        if k and k in blob:
            return float(policy.get("coated_faces_multiplier_partial_exterior", 1.3)), "partial_exterior_keyword"
    return default_m, "default_both_faces"


def _resolve_powder_material_price_per_kg(part: Dict[str, Any]) -> Tuple[float, str]:
    policy = getattr(config, "POWDER_COSTING_POLICY", {}) or {}
    blob = _part_powder_text_blob(part)
    for kw in policy.get("special_finish_keywords") or []:
        k = str(kw).upper().strip()
        if k and k in blob:
            return float(policy.get("powder_material_gbp_per_kg_special") or 0.0), "special_finish"
    return float(policy.get("powder_material_gbp_per_kg") or 0.0), "standard"


def _powder_coated_area_m2(
    part: Dict[str, Any],
    blank_length: Optional[float],
    blank_width: Optional[float],
) -> Tuple[float, Dict[str, Any]]:
    """
    Total coated surface for powder (flat faces + bend-edge strips).
    Flat area uses coated_faces_multiplier (default 2 = both sides of blank).
    """
    policy = getattr(config, "POWDER_COSTING_POLICY", {}) or {}
    if blank_length is None or blank_width is None or blank_length <= 0 or blank_width <= 0:
        return 0.0, {}
    L, W = float(blank_length), float(blank_width)
    faces_m, faces_reason = _effective_coated_faces_multiplier(part)
    flat_m2 = (L * W) / 1_000_000.0 * faces_m
    strip_mm = float(policy.get("bend_coating_strip_mm", 40.0))
    def _nz_int(val: Any) -> int:
        n = _safe_int(val)
        return int(n) if n is not None else 0

    bends = max(
        _nz_int(part.get("manufacturing_features", {}).get("bend_count")),
        _nz_int((part.get("geometry_rollup") or {}).get("estimated_bend_line_count")),
        _nz_int(part.get("fold_count_textual")),
    )
    fold_vals = part.get("fold_values_mm") or []
    perimeter_fold_mm = sum(_safe_float(x) or 0.0 for x in fold_vals)
    if perimeter_fold_mm > 0:
        bend_extra_m2 = (perimeter_fold_mm / 1000.0) * (strip_mm / 1000.0) * 2.0
    else:
        bend_extra_m2 = float(bends) * (strip_mm / 1000.0) * (min(L, W) / 1000.0) * 2.0
    total = flat_m2 + bend_extra_m2
    detail = {
        "flat_coated_m2": round(flat_m2, 4),
        "bend_extra_coated_m2": round(bend_extra_m2, 4),
        "bend_lines_used": bends,
        "coated_faces_multiplier": faces_m,
        "coated_faces_reason": faces_reason,
    }
    return total, detail


def _powder_consumable_estimate(
    part: Dict[str, Any],
    blank_length: Optional[float],
    blank_width: Optional[float],
    quantity: int,
) -> Dict[str, Any]:
    """
    Powder material cost — matches workbook AB:AC:AD formula (cols AB-AD, rows 38-48):

        AB = (part_length_m × part_width_m) × 2        [both faces, m²]
        AC = 6 / AB                                     [parts per kg — coverage = 6 m²/kg]
        AD = (1 / AC) × qty_per_unit                    [kg per unit = area_m2 × 2 / 6]

    Simplified:  powder_kg_per_unit = blank_area_m2 × coated_faces_multiplier / coverage_m2_per_kg
    Workbook coverage constant = 6 m²/kg (hard-coded). Platform reads from POWDER_COSTING_POLICY.
    """
    policy = getattr(config, "POWDER_COSTING_POLICY", {}) or {}
    if not policy.get("enabled", True):
        return {}
    if "powder_coating" not in _part_ops(part):
        return {}
    if blank_length is None or blank_width is None or blank_length <= 0 or blank_width <= 0:
        return {}

    L_m = float(blank_length) / 1000.0
    W_m = float(blank_width) / 1000.0

    # Workbook AB: area = (L_m × W_m) × 2  (both faces, no bend strips in workbook formula)
    # Platform extends this with optional bend-edge strips for higher accuracy.
    faces_m, faces_reason = _effective_coated_faces_multiplier(part)
    flat_area_m2 = L_m * W_m * faces_m          # workbook: faces_m = 2.0 always
    bend_extra_m2 = 0.0
    strip_mm = float(policy.get("bend_coating_strip_mm", 40.0))
    bends = max(
        _safe_int((part.get("manufacturing_features") or {}).get("bend_count")) or 0,
        _safe_int((part.get("geometry_rollup") or {}).get("estimated_bend_line_count")) or 0,
        _safe_int(part.get("fold_count_textual")) or 0,
    )
    fold_vals = part.get("fold_values_mm") or []
    perimeter_fold_mm = sum(_safe_float(x) or 0.0 for x in fold_vals)
    if perimeter_fold_mm > 0:
        bend_extra_m2 = (perimeter_fold_mm / 1000.0) * (strip_mm / 1000.0) * 2.0
    elif bends > 0:
        bend_extra_m2 = bends * (strip_mm / 1000.0) * min(L_m, W_m) * 2.0
    total_area_m2 = flat_area_m2 + bend_extra_m2

    # Workbook AC/AD: kg_per_unit = total_area_m2 / coverage_m2_per_kg
    coverage = float(policy.get("coverage_m2_per_kg", 6.0))   # workbook = 6.0
    kg_raw = total_area_m2 / coverage if coverage > 0 else 0.0

    scrap_mult = 1.0
    if policy.get("apply_global_scrap_to_powder_kg", True):
        scrap_mult = 1.0 + float(getattr(config, "SCRAP_PERCENTAGE", 0.04))
    kg_per_unit = kg_raw * scrap_mult

    price_per_kg, price_tier = _resolve_powder_material_price_per_kg(part)
    unit_cost = kg_per_unit * price_per_kg if price_per_kg > 0 else 0.0
    extended = unit_cost * quantity

    return {
        "workbook_formula": "AD = (1/AC) × qty = area_m2×2/6 per unit",
        "coverage_m2_per_kg": coverage,
        "flat_area_m2": round(flat_area_m2, 6),
        "bend_extra_coated_m2": round(bend_extra_m2, 6),
        "coated_area_m2": round(total_area_m2, 6),
        "coated_faces_multiplier": faces_m,
        "coated_faces_reason": faces_reason,
        "bend_lines_used": bends,
        "kg_powder_per_unit": round(kg_per_unit, 6),
        "powder_material_gbp_per_kg": price_per_kg,
        "powder_price_tier": price_tier,
        "scrap_multiplier_on_kg": scrap_mult,
        "unit_powder_material_cost_gbp": round(unit_cost, 4) if price_per_kg > 0 else None,
        "extended_powder_material_cost_gbp": round(extended, 2) if price_per_kg > 0 else 0.0,
        "priced": price_per_kg > 0,
    }


def estimate_blank_size(dimensions: Dict[str, Optional[float]]) -> Tuple[Optional[float], Optional[float]]:
    length = dimensions.get("overall_length_mm")
    width = dimensions.get("overall_width_mm")
    if length is None or width is None:
        return None, None

    # Keep part blank equal to extracted flat pattern dimensions.
    # Sheet-level edge margin is applied in select_sheet_size().
    return round(length, 2), round(width, 2)


def select_sheet_size(material: Optional[str], blank_length: Optional[float], blank_width: Optional[float]) -> Dict[str, Any]:
    """
    EXACT template nesting formula — Estimate sheet, Sheet Steel section, cell K38:
        nx (length axis) = INT(  sheet_length        / (part_length + 20) )   <- no edge margin, +20 gap
        ny (width  axis) = INT( (sheet_width  - 80)  / (part_width  + 10) )   <- 80mm margin, +10 gap
        parts_per_sheet  = nx × ny
    Mapping to template columns: F=Part Length -> I=Sheet Length axis; G=Part Width -> J=Sheet Width axis.
    FIXED ORIENTATION — the template does not rotate parts (no best-of-two-orientations). Part length
    always nests along sheet length, part width along sheet width, exactly as K38 does.
    Template guards: a part dimension of 0, or larger than the sheet in that axis, yields "doesn't fit".

    NOTE: this is the STEEL rule (K38). The 'Other Sheet Material' section (plastic/acrylic, cell J51)
    uses a different rule (−5 margin, +20 both axes); that is handled separately for non-steel materials.
    """
    if blank_length is None or blank_width is None:
        return {"candidate_sheet_size_mm": None, "parts_per_sheet": None, "utilisation_pct": None}

    sizes = STANDARD_SHEET_SIZES_MM.get(material or "", STANDARD_SHEET_SIZES_MM["DEFAULT"])

    # Template K38 fixed margins/gaps (do NOT pull from NESTING_RULES symmetric values).
    LENGTH_MARGIN = 0.0    # template: I38 has no -80 on the length axis
    LENGTH_GAP    = 20.0   # template: (10*2) on the length axis
    WIDTH_MARGIN  = 80.0   # template: (J38-80) on the width axis
    WIDTH_GAP     = 10.0   # template: (5*2) on the width axis

    best: Optional[Dict[str, Any]] = None
    for sheet_length, sheet_width in sizes:
        part_l, part_w = blank_length, blank_width   # FIXED orientation — no rotation (matches K38)
        # Template guards: IF(part>sheet,"") -> doesn't fit in that axis
        if part_l <= 0 or part_w <= 0:
            continue
        if part_l > sheet_length or part_w > sheet_width:
            continue
        nx = int(sheet_length / (part_l + LENGTH_GAP)) if (part_l + LENGTH_GAP) > 0 else 0   # I/(F+20)
        ny = int((sheet_width - WIDTH_MARGIN) / (part_w + WIDTH_GAP)) if (part_w + WIDTH_GAP) > 0 else 0  # (J-80)/(G+10)
        qty = max(0, nx) * max(0, ny)
        if qty <= 0:
            continue
        utilisation = (qty * blank_length * blank_width) / (sheet_length * sheet_width) * 100.0
        candidate = {
            "candidate_sheet_size_mm": [sheet_length, sheet_width],
            "parts_per_sheet": qty,
            "utilisation_pct": round(utilisation, 2),
            "nx": nx,
            "ny": ny,
            "nesting_formula": f"INT({sheet_length}/({part_l}+{LENGTH_GAP:.0f})) × INT(({sheet_width}-{WIDTH_MARGIN:.0f})/({part_w}+{WIDTH_GAP:.0f}))  [template K38, fixed orientation]",
        }
        # Keep the first sheet size that yields parts (sizes are ordered); template uses one sheet size.
        if best is None or qty > best["parts_per_sheet"]:
            best = candidate

    return best or {"candidate_sheet_size_mm": None, "parts_per_sheet": None, "utilisation_pct": None}


def _canonical_material_family(raw: Any) -> Any:
    """Map a raw title-block material string to the canonical family the cost/density/routing
    tables key on. Timber drawings print species/grades (FSC PINE, MRMDF, SPRUCE, OAK VENEER)
    that never matched TIMBER/MDF, so those parts had no price and fell through to the sheet
    path as phantom mild steel. This normalises them. Metals/plastics pass through unchanged
    (only maps when a timber/board token is present)."""
    u = str(raw or "").upper()
    if not u:
        return raw
    if "MDF" in u:                                   # MRMDF, MR MDF, VENEERED MDF, OAK VENEER MDF
        return "MDF"
    if "PLYWOOD" in u or "PLYWD" in u or " PLY" in u or u.endswith("PLY"):
        return "PLYWOOD"
    if any(t in u for t in ("PINE", "SPRUCE", "SOFTWOOD", "HARDWOOD", "TIMBER", "WOOD",
                            "OAK", "BEECH", "BIRCH", "FSC")):
        return "TIMBER"
    if "BOARD" in u:                                 # generic board / soft-touch laminate board
        return "MDF"
    return raw


def estimate_material(part: Dict[str, Any]) -> Dict[str, Any]:
    material = part.get("normalized_material") or _first(part.get("materials", []))
    material = _canonical_material_family(material)
    if material:
        # Propagate the canonical family back onto the part so wb_populate's block routing
        # (which reads normalized_material) sends timber/board to the right block, not steel.
        # NORMALISATION, not new evidence: this is the part's OWN material rewritten to its
        # canonical family name ("MR MDF" -> "MDF"). It must not lose the source that
        # supplied it, so the recorded source is carried through unchanged rather than
        # re-stamped as if the estimator had observed something.
        part["normalized_material"] = material   # precedence: direct-write ok — canonicalises the part's own value, source unchanged
    thickness = _safe_thickness_mm(part)
    quantity = _safe_int(part.get("quantity")) or 1
    dims = infer_primary_dimensions(part)
    blank_length, blank_width = estimate_blank_size(dims)

    # FIX 2 (general): a weldment/assembly PARENT part is a roll-up of child parts that
    # are themselves in the BOM and individually material-costed. Giving the parent its
    # own blank double-counts material (e.g. 1455-C-101 HEADER WELDMENT carried £7.48 on
    # top of its already-costed children 1455-C-001..005). Convention matches Tim: the
    # parent line is LABOUR-only (weld/assemble). Config-driven token list, no per-job logic.
    _desc_wm = str(part.get("description") or "").upper()
    _wm_tokens = getattr(config, "WELDMENT_PARENT_DESC_TOKENS",
                         ["WELDMENT", "WELD ASSEMBLY", "WELDED ASSEMBLY", "WELD ASSY"])
    # Weld-assembly parent by PART NUMBER (e.g. ...-WA01 / ...-SA01) when it carries
    # no flat DXF of its own. This is spelling-independent, so a mislabelled title
    # block (material "MDF", a "SELDED" typo) cannot misroute the parent's material:
    # it is suppressed and carried by the costed child detail parts.
    _pn_wm = str(part.get("part_number") or "").upper()
    _wm_suffixes = getattr(config, "WELDMENT_PARENT_PN_SUFFIXES", [r"-WA\d*$", r"-SA\d*$"])
    _has_own_flat = ("dxf" in str(part.get("geometry_source") or "").lower()
                     or _has_native_flat(part))
    # is_assembly_parent is stamped upstream (drawing_job_merge) for a part with no
    # flat DXF whose PN is a strict prefix of >=2 others — a roll-up whose material
    # is carried by its costed children (TANK 04 over 04-01/04-02).
    _is_weldment_parent = (
        any(_t in _desc_wm for _t in _wm_tokens)
        or (not _has_own_flat and any(re.search(_sfx, _pn_wm) for _sfx in _wm_suffixes))
        or bool(part.get("is_assembly_parent"))
    )
    if _is_weldment_parent:
        return {
            "material": material,
            "thickness_mm": thickness,
            "blank_length_mm": None,
            "blank_width_mm": None,
            "blank_area_m2": None,
            "unit_material_mass_kg": None,
            "unit_material_cost_gbp": 0.0,
            "cost_per_part_gbp": 0.0,
            "extended_sheet_material_cost_gbp": 0.0,
            "powder_consumable": None,
            "extended_material_cost_gbp": 0.0,
            "stock_estimate": {"candidate_sheet_size_mm": None, "parts_per_sheet": None, "utilisation_pct": None},
            "cost_method": "weldment_parent_material_in_children",
            "part_confidence_overall": _part_confidence_overall(part),
            "part_geometry_reliability": _part_geometry_reliability(part),
            "reliability_flags": ["weldment_parent_material_suppressed"],
            "note": "Weldment/assembly parent \u2014 material carried by child BOM lines; parent costed for labour only.",
            "price_source": _build_price_source_metadata(
                {}, fallback_source="weldment_parent_material_in_children",
                applied=False, applied_basis=None,
            ),
        }

    # Acrylic / plastic sheet is bought and costed by the SHEET, not by mass — the £/kg
    # path under-prices it (a panel ~£1.98 by mass vs ~£3.20 sheet-nested). Price it
    # sheet-nested from config.ACRYLIC_SHEET_PRICE_GBP (PROVISIONAL, pending estimating),
    # using the existing nesting formula with the acrylic sheet size. Gated strictly to
    # acrylic-like materials, so steel / wire / MDF / 1282 are untouched.
    _mat_acr = str(material or "").upper().replace("_", " ")
    if _mat_acr in {"ACRYLIC", "HIGH IMPACT ACRYLIC", "HIPS", "PERSPEX", "PMMA", "POLYCARBONATE"} and blank_length and blank_width:
        _acr_area_m2 = (float(blank_length) * float(blank_width)) / 1_000_000.0
        _scrap = float(getattr(config, "SCRAP_PERCENTAGE", 0.04))

        # HIPS: price by area × a LIVE £/m² rate derived from the current UDEF catalogue
        # (plain stock sheets at this thickness). Tracks price changes automatically —
        # no stale config table. Falls through to the acrylic-config path if unavailable.
        _hips_rate = _resolve_board_sheet_rate_gbp_per_m2(material, thickness)
        if _hips_rate and _hips_rate.get("rate_gbp_per_m2"):
            _rate_m2 = float(_hips_rate["rate_gbp_per_m2"])
            _hips_cost_part = round(_acr_area_m2 * _rate_m2 * (1.0 + _scrap), 2)
            _hips_ext = round(_hips_cost_part * quantity, 2)
            return {
                "material": material,
                "thickness_mm": thickness,
                "blank_length_mm": blank_length,
                "blank_width_mm": blank_width,
                "blank_area_m2": round(_acr_area_m2, 4),
                "unit_material_mass_kg": None,
                "unit_material_cost_gbp": _hips_cost_part,
                "cost_per_part_gbp": _hips_cost_part,
                "extended_sheet_material_cost_gbp": _hips_ext,
                "powder_consumable": None,
                "extended_material_cost_gbp": _hips_ext,
                "stock_estimate": None,
                "cost_method": "hips_sheet_live_udef",
                "part_confidence_overall": _part_confidence_overall(part),
                "part_geometry_reliability": _part_geometry_reliability(part),
                "reliability_flags": [],
                "note": "HIPS sheet cost from LIVE UDEF rate £%.2f/m² (%s plain-stock sample(s) at %.1fmm) × %.4f m² area."
                        % (_rate_m2, _hips_rate.get("sample_count"), _hips_rate.get("thickness_mm") or 0.0, _acr_area_m2),
                "price_source": _build_price_source_metadata(
                    {}, fallback_source="hips_sheet_live_udef",
                    applied=True, applied_basis="udef_hips_rate_gbp_per_m2_live",
                ),
            }

        # Acrylic (and HIPS fallback): sheet-nested from config.ACRYLIC_SHEET_PRICE_GBP.
        # acrylic_area_pricing_v2 (2026-07-15): price the flat blank by AREA × £/m2 (UDEF-derived
        # Clear XT, PROVEN LINEAR full-sheet-to-blank), expressed through the workbook's own L/J so
        # estimators still read a real sheet price and parts-per-sheet. L = full-sheet price at the
        # £/m2 rate; J = geometric parts-per-sheet; the WB computes (L/J)×scrap = rate×part_area×scrap.
        # The full-sheet area cancels in L/J, so the cost is exactly area×rate regardless of sheet size.
        _acr_m2 = getattr(config, "ACRYLIC_PRICE_GBP_PER_M2", {}) or {}
        _acr_rate_m2 = None
        try:
            _acr_rate_m2 = _acr_m2.get(float(thickness)) if thickness is not None else None
        except (TypeError, ValueError):
            _acr_rate_m2 = None
        if _acr_rate_m2 is None:
            try:
                _mkeys = [k for k in _acr_m2 if isinstance(k, (int, float))]
                if thickness is not None and _mkeys:
                    _acr_rate_m2 = _acr_m2[min(_mkeys, key=lambda k: abs(k - float(thickness)))]
            except (TypeError, ValueError):
                _acr_rate_m2 = None
        if _acr_rate_m2 is None:
            _acr_rate_m2 = float(_acr_m2.get("default", 8.0))
        _acr_rate_m2 = float(_acr_rate_m2)

        _acr_sheet_est = select_sheet_size(material, blank_length, blank_width)
        # full-sheet area from the standard sheet the nester picked (falls back to 3050×2050)
        _acr_sheet_dims = _acr_sheet_est.get("candidate_sheet_size_mm") or [3050.0, 2050.0]
        try:
            _full_sheet_area_m2 = (float(_acr_sheet_dims[0]) * float(_acr_sheet_dims[1])) / 1_000_000.0
        except (TypeError, ValueError, IndexError):
            _full_sheet_area_m2 = (3050.0 * 2050.0) / 1_000_000.0
        # L = real full-sheet price at the UDEF £/m2 (verifiable against a supplier invoice)
        _sheet_price = round(_full_sheet_area_m2 * _acr_rate_m2, 2)
        # J = geometric parts-per-sheet (full area / part area); real nesting yields fewer and
        # the scrap % covers that waste. Cost is robust to J because full-sheet area cancels in L/J.
        _part_area_m2 = _acr_area_m2 if _acr_area_m2 and _acr_area_m2 > 0 else (_full_sheet_area_m2 or 1.0)
        _acr_pps = int(_full_sheet_area_m2 / _part_area_m2) if _part_area_m2 > 0 else 1
        if not _acr_pps or _acr_pps < 1:
            _acr_pps = 1
        # Python's own per-part figure (JSON summary) = the exact area price incl scrap.
        _acr_cost_part = _acr_area_m2 * _acr_rate_m2 * (1.0 + _scrap)
        _acr_ext = round(_acr_cost_part * quantity, 2)
        return {
            "material": material,
            "thickness_mm": thickness,
            "blank_length_mm": blank_length,
            "blank_width_mm": blank_width,
            "blank_area_m2": round(_acr_area_m2, 4),
            "unit_material_mass_kg": None,
            "unit_material_cost_gbp": round(_acr_cost_part, 2),
            "cost_per_part_gbp": round(_acr_cost_part, 2),
            "extended_sheet_material_cost_gbp": _acr_ext,
            "powder_consumable": None,
            "extended_material_cost_gbp": _acr_ext,
            "stock_estimate": _acr_sheet_est,
            # Raw PRE-scrap sheet price (£/sheet) so wb_populate can fill the WB Other Sheet
            # 'Cost per sheet' cell (col L). The WB formula M=(L/J)*(1+K)*D applies scrap (K)
            # and qty-per-sheet (J) itself, so we expose the sheet price, NOT the per-part cost.
            "sheet_price_gbp": round(float(_sheet_price), 2),
            "parts_per_sheet": int(_acr_pps),
            "cost_method": "acrylic_area_per_m2_provisional",
            "part_confidence_overall": _part_confidence_overall(part),
            "part_geometry_reliability": _part_geometry_reliability(part),
            "reliability_flags": [getattr(config, "ACRYLIC_PROVISIONAL_FLAG", "acrylic_provisional_pending_estimating")],
            "note": "Acrylic sheet-nested cost (PROVISIONAL) — £%.2f/sheet ÷ %s parts/sheet; swap for canonical on estimating confirmation." % (_sheet_price, _acr_pps),
            "price_source": _build_price_source_metadata(
                {}, fallback_source="acrylic_area_per_m2_provisional",
                applied=True, applied_basis="acrylic_area_per_m2_provisional",
            ),
        }
    external_price = _resolve_material_price(material, thickness, quantity, part=part)
    external_result = external_price.get("result", {})

    # ── ROUND BAR / STUD path (added 2026-07-13) ─────────────────────────────
    # Fires ONLY when document_builder recognised a bar schedule on the part's own page:
    #       ITEM  QTY  DESCRIPTION  LENGTH
    #         1    1    8mm DIA      65
    #
    # This has to be its own branch. The wire path below keys on the WORD "wire" in the
    # description (WIRE MESH / WELDED WIRE / WIRE FORM / ...) — the same spelling test we
    # just removed from document_builder, present here a second time. A solid bar whose
    # drawing says "STUD" can never satisfy it. And gauge_mm there falls back to 3.0 when
    # thickness is absent, which would price an 8mm bar as 3mm wire.
    #
    # Uses the SAME formula and rates as the workbook, so the engine's JSON total and the
    # WB's own Wire block agree:
    #     8mm -> 2534 m/tonne (WB gauge table; also = 1000 / (pi*(d/2000)^2 * 7850))
    #     price/m = £1600 / 2534 = £0.6313
    #     unit    = 0.6313/1000 x 65mm x 1.04 = £0.0427     (Tim's sheet: £0.04)
    if part.get("_bar_recognised"):
        _bar_gauge = _safe_float(part.get("wire_gauge_mm"))
        _bar_len = _safe_float(part.get("wire_length_mm"))
        if _bar_gauge and _bar_len:
            wb_defaults = getattr(config, "WORKBOOK_INPUT_DEFAULTS", {}) or {}
            _wire_per_tonne = float(wb_defaults.get("wire_cost_per_tonne_gbp") or 1600.0)
            _gauge_table = getattr(config, "WIRE_GAUGE_TABLE", {}) or {}
            _m_per_tonne = None
            if _gauge_table:
                _closest = min(_gauge_table.keys(), key=lambda g: abs(float(g) - _bar_gauge))
                # only trust the table if it actually has this gauge (within 0.25mm)
                if abs(float(_closest) - _bar_gauge) <= 0.25:
                    _m_per_tonne = float(_gauge_table[_closest])
            if not _m_per_tonne:
                # derive from the solid round section — matches the WB table exactly
                _area_m2 = 3.14159265 * ((_bar_gauge / 2000.0) ** 2)
                _kg_per_m = _area_m2 * 7850.0
                _m_per_tonne = (1000.0 / _kg_per_m) if _kg_per_m > 0 else None
            if _m_per_tonne and _m_per_tonne > 0:
                _price_per_m = _wire_per_tonne / _m_per_tonne
                _scrap = float(getattr(config, "SCRAP_PERCENTAGE", 0.04))
                _unit = (_price_per_m / 1000.0) * _bar_len * (1.0 + _scrap)
                _ext = _unit * quantity
                return {
                    "material": material,
                    "thickness_mm": None,          # a DIAMETER is not a thickness
                    "blank_length_mm": _bar_len,
                    "blank_width_mm": None,
                    "blank_area_m2": None,
                    "unit_material_mass_kg": round(_bar_len / 1000.0 / _m_per_tonne * 1000.0, 5),
                    "unit_material_cost_gbp": round(_unit, 4),
                    "cost_per_part_gbp": round(_unit, 4),
                    "extended_material_cost_gbp": round(_ext, 2),
                    "stock_estimate": {
                        "wire_length_mm": _bar_len,
                        "wire_gauge_mm": _bar_gauge,
                        "metres_per_tonne": round(_m_per_tonne, 1),
                        "price_per_metre_gbp": round(_price_per_m, 6),
                    },
                    "cost_method": "workbook_bar_formula",
                    "stock_form": "wire",
                    "wire_gauge_mm": _bar_gauge,
                    "wire_length_mm": _bar_len,
                    "requires_flat_blank": False,
                    "part_confidence_overall": _part_confidence_overall(part),
                    "part_geometry_reliability": _part_geometry_reliability(part),
                    "price_source": _build_price_source_metadata(
                        external_result, fallback_source="config_wire_cost_per_tonne",
                        applied=True, applied_basis="bar_diameter_x_length_gauge_lookup",
                    ),
                }

    # Section/tube/wire path: uses linear stock mass estimate when profile+length is available.
    if _is_section_or_wire_candidate(part, material):
        _ss = part.get("section_stock") or {}
        side_a_mm = _safe_float(_ss.get("a"))
        side_b_mm = _safe_float(_ss.get("b"))
        wall_t_mm = _safe_float(_ss.get("t"))
        if not (side_a_mm and side_b_mm and wall_t_mm):
            side_a_mm, side_b_mm, wall_t_mm = _parse_section_profile(str(part.get("description") or ""))
        length_mm = _infer_section_length_mm(part)

        # A hollow rolled section is METAL by definition — it cannot be timber/MDF/wood. On these
        # drawings the deterministic reader sometimes tags a tube 'TIMBER' off a nearby spec note,
        # which mis-costs it ~13x (timber density + rate vs steel). With a real a×b×t profile in
        # hand, coerce a non-metal material to mild steel so mass and £/kg are right.
        if side_a_mm and side_b_mm and wall_t_mm and str(material or "").upper().replace("_", " ") in (
                "TIMBER", "WOOD", "MDF", "PLYWOOD", "SOFTWOOD", "OAK", "MDF / OAK VENEER"):
            part.setdefault("review_flags", []).append(
                f"material '{material}' overridden to MILD STEEL — part is a "
                f"{side_a_mm:g}x{side_b_mm:g}x{wall_t_mm:g} hollow section (cannot be timber)")
            material = "MILD STEEL"

        # ── Wire path (workbook rows 28-35) ──────────────────────────────────
        # M = (wire_£_per_tonne / metres_per_tonne / 1000) × length_mm × qty × (1+scrap)
        desc_upper = str(part.get("description") or "").upper()
        is_wire = any(kw in desc_upper for kw in ("WIRE MESH", "WELDED WIRE", "WIRE FORM", "WIREWORK", "WIRE "))
        if is_wire and length_mm:
            wb_defaults = getattr(config, "WORKBOOK_INPUT_DEFAULTS", {}) or {}
            wire_per_tonne = float(wb_defaults.get("wire_cost_per_tonne_gbp") or 1600.0)
            wire_gauge_table = getattr(config, "WIRE_GAUGE_TABLE", {}) or {}
            gauge_mm = _safe_thickness_mm(part) or 3.0
            metres_per_tonne: Optional[float] = None
            if wire_gauge_table:
                closest_gauge = min(wire_gauge_table.keys(), key=lambda g: abs(float(g) - gauge_mm))
                metres_per_tonne = float(wire_gauge_table[closest_gauge])
            if not metres_per_tonne:
                wire_area_m2 = 3.14159 * ((gauge_mm / 2000.0) ** 2)
                kg_per_m = wire_area_m2 * 7850.0
                metres_per_tonne = 1000.0 / kg_per_m if kg_per_m > 0 else 1000.0
            price_per_metre = wire_per_tonne / metres_per_tonne if metres_per_tonne > 0 else 0.0
            scrap_frac = float(getattr(config, "SCRAP_PERCENTAGE", 0.04))
            unit_cost = (price_per_metre / 1000.0) * length_mm * (1.0 + scrap_frac)
            extended = unit_cost * quantity
            return {
                "material": material,
                "thickness_mm": thickness,
                "blank_length_mm": length_mm,
                "blank_width_mm": None,
                "blank_area_m2": None,
                "unit_material_mass_kg": round(length_mm / 1000.0 / metres_per_tonne * 1000.0, 4) if metres_per_tonne else None,
                "unit_material_cost_gbp": round(unit_cost, 4),
                "cost_per_part_gbp": round(unit_cost, 4),
                "extended_material_cost_gbp": round(extended, 2),
                "stock_estimate": {"wire_length_mm": length_mm, "metres_per_tonne": metres_per_tonne, "price_per_metre_gbp": round(price_per_metre, 6)},
                "cost_method": "workbook_wire_formula",
                "stock_form": "wire",
                "requires_flat_blank": False,
                "part_confidence_overall": _part_confidence_overall(part),
                "part_geometry_reliability": _part_geometry_reliability(part),
                "price_source": _build_price_source_metadata(
                    external_result, fallback_source="config_wire_cost_per_tonne",
                    applied=True, applied_basis="wire_£_per_tonne_gauge_lookup",
                ),
            }

        if side_a_mm and side_b_mm and wall_t_mm and length_mm:
            # GENUINE catalogue price first: SDI stocks cut/slotted tube as bought-in parts
            # (SLOTTEDTUBE01/02 etc. in UDEF). If the detected profile+length matches a priced
            # catalogue row, use that real per-piece price + supplier instead of a mass*£/kg
            # estimate. Falls through to the mass estimate (flagged) if no catalogue match.
            _cat = _lookup_catalogue_tube_price(side_a_mm, side_b_mm, wall_t_mm, length_mm)
            if _cat and _cat.get("unit_price_gbp"):
                _cat_unit = float(_cat["unit_price_gbp"])
                _cat_ext = round(_cat_unit * quantity, 2)
                return {
                    "material": material,
                    "thickness_mm": thickness,
                    "blank_length_mm": blank_length,
                    "blank_width_mm": blank_width,
                    "blank_area_m2": None,
                    "unit_material_mass_kg": None,
                    "unit_material_cost_gbp": round(_cat_unit, 2),
                    "cost_per_part_gbp": round(_cat_unit, 2),
                    "extended_material_cost_gbp": _cat_ext,
                    "stock_estimate": {
                        "section_length_mm": round(length_mm, 2),
                        "catalogue_part_code": _cat.get("part_code"),
                        "catalogue_description": _cat.get("description"),
                        "catalogue_length_mm": _cat.get("catalogue_length_mm"),
                    },
                    "stock_form": "tube",
                    "supplier": _cat.get("supplier"),
                    "requires_flat_blank": False,
                    "cost_method": "catalogue_section_price",
                    "part_confidence_overall": _part_confidence_overall(part),
                    "part_geometry_reliability": _part_geometry_reliability(part),
                    "price_source": _build_price_source_metadata(
                        {}, fallback_source="udef_catalogue_section",
                        applied=True, applied_basis=f"catalogue {_cat.get('part_code')} @ £{_cat_unit:.2f}/{_cat.get('uom') or 'EA'}",
                    ),
                }
            density = MATERIAL_DENSITY_KG_PER_M3.get(material or "", MATERIAL_DENSITY_KG_PER_M3.get("MILD STEEL"))
            # SHS/RHS approximation: A = outer - inner (mm^2)
            inner_a = max(0.0, side_a_mm - (2.0 * wall_t_mm))
            inner_b = max(0.0, side_b_mm - (2.0 * wall_t_mm))
            area_mm2 = max(0.0, (side_a_mm * side_b_mm) - (inner_a * inner_b))
            kg_per_m = (area_mm2 * (density or 7850.0)) / 1_000_000.0
            unit_length_m = length_mm / 1000.0
            unit_mass_kg = kg_per_m * unit_length_m
            applied_price_per_kg = external_price.get("applied_price_per_kg")
            fallback_price_per_kg = MATERIAL_PRICE_GBP_PER_KG.get(material or "")
            price_per_kg = applied_price_per_kg if applied_price_per_kg is not None else fallback_price_per_kg
            policy = getattr(config, "SECTION_STOCK_POLICY", {}) or {}
            waste_factor = 1.0 + (float(policy.get("waste_factor_pct", 4.0)) / 100.0)
            unit_cost = (unit_mass_kg * price_per_kg * waste_factor) if price_per_kg is not None else None
            extended = (unit_cost * quantity) if unit_cost is not None else None
            return {
                "material": material,
                "thickness_mm": thickness,
                "blank_length_mm": blank_length,
                "blank_width_mm": blank_width,
                "blank_area_m2": None,
                "unit_material_mass_kg": round(unit_mass_kg, 3),
                "unit_material_cost_gbp": round(unit_cost, 2) if unit_cost is not None else None,
                "cost_per_part_gbp": round(unit_cost, 2) if unit_cost is not None else None,
                "extended_material_cost_gbp": round(extended, 2) if extended is not None else None,
                "stock_estimate": {"section_length_mm": round(length_mm, 2), "kg_per_m": round(kg_per_m, 4)},
                # This branch has a full a×b×t hollow-section profile + a real cut length, so it IS a
                # tube — declare it as one (like the catalogue branch above) so the workbook routes it
                # to the tube/BOM block and prices it by length, NOT into the Sheet Steel block as a
                # flat blank (which mis-costs the 30×30 profile as a 30×30 plate).
                "stock_form": "tube",
                "requires_flat_blank": False,
                "part_confidence_overall": _part_confidence_overall(part),
                "part_geometry_reliability": _part_geometry_reliability(part),
                "price_source": _build_price_source_metadata(
                    external_result,
                    fallback_source="config_default_material_rates",
                    applied=applied_price_per_kg is not None,
                    applied_basis=external_price.get("applied_basis") if applied_price_per_kg is not None else "config_fallback_GBP_per_kg",
                )
                | {"section_profile_mm": {"a": side_a_mm, "b": side_b_mm, "t": wall_t_mm}},
            }

    # Stated-weight path: when the drawing declares a part weight (e.g. "WEIGHT: 885g"),
    # use it directly instead of computing mass from area x thickness x density.
    # Critical for timber/wood where the extracted thickness is often a tolerance artefact.
    _NON_SHEET_MATERIALS = {"TIMBER", "WOOD", "MDF", "PLYWOOD", "SOFTWOOD"}
    stated_weight_kg = _stated_weight_kg_for_part(part)
    # Plausibility gate: a DXF/PDF "stated weight" is trusted only when it agrees with the
    # blank-based mass (area x thickness x density). Bad unit conversions produce weights that
    # are wildly too small (e.g. 0.0007 kg for a ~2.3 kg peg) or too large (the 1450 title-block
    # case); in either direction we ignore the stated weight and fall through to the reliable
    # area formula below. Only gated when there is a blank to check against.
    if stated_weight_kg is not None and stated_weight_kg > 0 and blank_length and blank_width and thickness:
        _pol = getattr(config, "MATERIAL_PRICE_POLICY", {}) or {}
        _max_ratio = float(_pol.get("max_stated_weight_blank_ratio", 3.0))
        _min_ratio = float(_pol.get("min_stated_weight_blank_ratio", 0.5))
        _dens = (MATERIAL_DENSITY_KG_PER_M3.get(material)
                 or MATERIAL_DENSITY_KG_PER_M3.get((material or "").upper(), 7850.0) or 7850.0)
        _area_mass = (blank_length * blank_width / 1_000_000.0) * (thickness / 1000.0) * _dens
        if _area_mass > 0 and not (_min_ratio <= (stated_weight_kg / _area_mass) <= _max_ratio):
            # Stated weight and blank DISAGREE. Which source is reliable decides who wins:
            #  - DXF flat pattern present  -> the blank is measured truth; the odd stated weight
            #    is probably a bad unit conversion -> drop it, use the area formula (original).
            #  - NO DXF (blank is PDF-vision geometry, often garbled e.g. 4.5x4mm) -> the PRINTED
            #    weight is the reliable one -> KEEP it (costs by mass below) and flag the blank.
            # Lever: MATERIAL_PRICE_POLICY.trust_stated_weight_when_no_dxf (default True).
            _dxf_backed = (str(part.get("geometry_source") or "").lower() in (
                "dxf_flat_pattern", "dxf", "dxf_flat") or _has_native_flat(part))
            _trust_wt = bool(_pol.get("trust_stated_weight_when_no_dxf", True))
            if _dxf_backed or not _trust_wt:
                stated_weight_kg = None  # measured blank wins -> use area formula
            else:
                part.setdefault("review_flags", []).append(
                    f"blank {blank_length:g}x{blank_width:g}mm disagrees with stated weight "
                    f"{round(stated_weight_kg * 1000)}g by {stated_weight_kg / _area_mass:.0f}x — "
                    f"no DXF, costing by the printed weight (blank geometry unreliable)")
    if stated_weight_kg is not None and stated_weight_kg > 0:
        applied_price_per_kg = external_price.get("applied_price_per_kg")
        fallback_price_per_kg = MATERIAL_PRICE_GBP_PER_KG.get(material or "")
        price_per_kg = applied_price_per_kg if applied_price_per_kg is not None else fallback_price_per_kg
        if price_per_kg is not None:
            waste_factor = 1.0 + (NESTING_RULES["waste_factor_pct"] / 100.0)
            unit_cost = stated_weight_kg * price_per_kg * waste_factor
            extended = unit_cost * quantity
            return {
                "material": material,
                "thickness_mm": thickness,
                "blank_length_mm": blank_length,
                "blank_width_mm": blank_width,
                "blank_area_m2": None,
                "unit_material_mass_kg": round(stated_weight_kg, 3),
                "unit_material_cost_gbp": round(unit_cost, 2),
                "cost_per_part_gbp": round(unit_cost, 2),
                "extended_material_cost_gbp": round(extended, 2),
                "stock_estimate": None,
                "stock_form": "stated_weight",
                "requires_flat_blank": False,
                "part_confidence_overall": _part_confidence_overall(part),
                "part_geometry_reliability": _part_geometry_reliability(part),
                "price_source": _build_price_source_metadata(
                    external_result,
                    fallback_source="config_default_material_rates",
                    applied=applied_price_per_kg is not None,
                    applied_basis=(external_price.get("applied_basis") if applied_price_per_kg is not None
                                   else "config_fallback_GBP_per_kg"),
                )
                | {
                    "stated_weight_kg": stated_weight_kg,
                    "weight_source": _weight_source_label(part),
                },
            }

    if not material or thickness is None or blank_length is None or blank_width is None:
        return {
            "material": material,
            "thickness_mm": thickness,
            "blank_length_mm": blank_length,
            "blank_width_mm": blank_width,
            "blank_area_m2": None,
            "unit_material_mass_kg": None,
            "unit_material_cost_gbp": None,
            "extended_material_cost_gbp": None,
            "stock_estimate": select_sheet_size(material, blank_length, blank_width),
            "price_source": _build_price_source_metadata(
                external_result,
                fallback_source="config_default_material_rates",
                applied=False,
                applied_basis=None,
            ),
        }

    area_m2 = (blank_length * blank_width) / 1_000_000.0
    thickness_m = thickness / 1000.0
    density = MATERIAL_DENSITY_KG_PER_M3.get(material) or MATERIAL_DENSITY_KG_PER_M3.get((material or "").upper(), 7850.0)
    fallback_price_per_kg = MATERIAL_PRICE_GBP_PER_KG.get(material)
    applied_price_per_kg = external_price.get("applied_price_per_kg")
    price_per_kg = applied_price_per_kg if applied_price_per_kg is not None else fallback_price_per_kg

    sheet_estimate = select_sheet_size(material, blank_length, blank_width)

    # Sheet steel cost — workbook rows 37-48 formula:
    # cost_per_part = (sheet_steel_£_per_tonne / 1000 × kg_per_sheet) / parts_per_sheet × (1+scrap)
    wb_defaults = getattr(config, "WORKBOOK_INPUT_DEFAULTS", {}) or {}
    is_steel = (material or "").upper() in {
        "MILD STEEL", "MILD_STEEL", "ZINTEC", "GALVANISED STEEL",
        "GALVANIZED STEEL", "STAINLESS STEEL", "STAINLESS_STEEL",
        "MILD_STEEL_SPCC", "STAINLESS_STEEL_304", "STAINLESS_STEEL_316",
    }
    sheet_steel_per_tonne = float(wb_defaults.get("sheet_steel_cost_per_tonne_gbp") or 0.0)
    cfg_defaults = getattr(config, "WORKBOOK_INPUT_DEFAULTS", {}) or {}
    sane_default_tonne = float(cfg_defaults.get("sheet_steel_cost_per_tonne_gbp") or 800.0)
    if sheet_steel_per_tonne > 2500.0 or sheet_steel_per_tonne < 200.0:
        sheet_steel_per_tonne = sane_default_tonne
    scrap_frac = float(getattr(config, "SCRAP_PERCENTAGE", 0.04))
    parts_per_sheet = sheet_estimate.get("parts_per_sheet")
    if not parts_per_sheet or int(parts_per_sheet) < 1:
        parts_per_sheet = 1

    if density is None or price_per_kg is None:
        mass_kg = None
        material_cost = None
        cost_method = "no_price"
    elif is_steel and sheet_steel_per_tonne > 0 and parts_per_sheet > 0:
        # Exact workbook formula: cost/part = (£/tonne × kg/sheet) / (1000 × parts/sheet)
        sheet_dims = sheet_estimate.get("candidate_sheet_size_mm") or [2500.0, 1250.0]
        sheet_area_m2 = (float(sheet_dims[0]) * float(sheet_dims[1])) / 1_000_000.0
        kg_per_sheet = sheet_area_m2 * (thickness or 1.0) / 1000.0 * (density or 7850.0)
        cost_per_sheet = (sheet_steel_per_tonne / 1000.0) * kg_per_sheet
        cost_per_part = cost_per_sheet / parts_per_sheet
        mass_kg = area_m2 * thickness_m * density
        material_cost = cost_per_part * (1.0 + scrap_frac)
        cost_method = "workbook_sheet_steel_formula"
    else:
        mass_kg = area_m2 * thickness_m * density
        cap_kg = float((getattr(config, "MATERIAL_PRICE_POLICY", {}) or {}).get("max_sane_gbp_per_kg", 15.0))
        eff_price = price_per_kg
        if eff_price is not None and eff_price > cap_kg and is_steel:
            eff_price = float(
                MATERIAL_PRICE_GBP_PER_KG.get((material or "").upper())
                or MATERIAL_PRICE_GBP_PER_KG.get("MILD STEEL", 0.8)
            )
        material_cost = mass_kg * eff_price * (1.0 + scrap_frac) if eff_price is not None else None
        cost_method = "mass_times_price_per_kg"

    powder_block = _powder_consumable_estimate(part, blank_length, blank_width, quantity)
    # acrylic_powder_suppressed_v1 (2026-07-15): powder coat is a STEEL finish. Acrylic /
    # perspex / PMMA / polycarbonate are diamond polished, never powder coated. Suppress the
    # powder CONSUMABLE (BOM material line) at source for these materials, so no phantom POWDER
    # row reaches the workbook, rollups or totals. (The powder OPERATION is already gated out in
    # the acrylic routing block; this handles the material line.)
    _mat_pw = str(material or part.get("normalized_material") or "").upper().replace("_", " ")
    if _mat_pw in {"ACRYLIC", "HIGH IMPACT ACRYLIC", "PERSPEX", "PMMA", "POLYCARBONATE"} \
            or part.get("acrylic_no_powder"):
        powder_block = None
    powder_ext = float((powder_block or {}).get("extended_powder_material_cost_gbp") or 0.0)
    sheet_ext = round((material_cost or 0.0) * quantity, 2) if material_cost is not None else None
    if sheet_ext is not None:
        combined_ext = round(sheet_ext + powder_ext, 2)
    elif powder_ext:
        combined_ext = round(powder_ext, 2)
    else:
        combined_ext = None

    return {
        "material": material,
        "thickness_mm": thickness,
        "blank_length_mm": blank_length,
        "blank_width_mm": blank_width,
        "blank_area_m2": round(area_m2, 4),
        "unit_material_mass_kg": round(mass_kg, 3) if mass_kg is not None else None,
        "unit_material_cost_gbp": round(material_cost, 2) if material_cost is not None else None,
        "cost_per_part_gbp": round(material_cost, 2) if material_cost is not None else None,
        "extended_sheet_material_cost_gbp": sheet_ext,
        "powder_consumable": powder_block if powder_block else None,
        "extended_material_cost_gbp": combined_ext,
        "stock_estimate": sheet_estimate,
        "cost_method": cost_method,
        "stock_form": part.get("manufacturing_interpretation", {}).get("stock_form"),
        "requires_flat_blank": part.get("manufacturing_interpretation", {}).get("requires_flat_blank"),
        "part_confidence_overall": _part_confidence_overall(part),
        "part_geometry_reliability": _part_geometry_reliability(part),
        "price_source": _build_price_source_metadata(
            external_result,
            fallback_source=(
                "workbook_sheet_steel_formula" if cost_method == "workbook_sheet_steel_formula"
                else "config_default_material_rates"
            ),
            applied=(
                True if cost_method == "workbook_sheet_steel_formula"
                else applied_price_per_kg is not None
            ),
            applied_basis=(
                "workbook_sheet_steel_formula" if cost_method == "workbook_sheet_steel_formula"
                else (external_price.get("applied_basis") if applied_price_per_kg is not None
                      else "config_fallback_GBP_per_kg")
            ),
        ),
    }


def _peg_family_punch_cycle(part: Dict[str, Any]):
    """Machine-measured TruPunch cycle time for known peg-family panels.

    These parts are punched (cluster + tooth + perimeter tooling), but the DXF/PDF
    under-reads their perforation so the hole-count punch model collapses to ~0.
    Returns (minutes, basis_note) keyed on description/PN + panel size, or None.
    1m values are measured from TruPunch setup plans; 500mm is scaled x0.65.
    """
    table = getattr(config, "PUNCH_CYCLE_TIME_MIN", {}) or {}
    blob = (str(part.get("description") or "") + " " + str(part.get("part_number") or "")).upper()
    if "HALF PEG" in blob or "HALF HEIGHT PEG" in blob:
        family = "HALF_PEG"
    elif "PEG PANEL" in blob or "PEG METAL" in blob or "PEG" in blob:
        family = "PEG_PANEL"
    elif "BASE PLATE" in blob:
        family = "BASE_PLATE"
    else:
        return None
    sizes = table.get(family) or {}
    if "1000MM" in blob or "1000 MM" in blob or " 1M " in (" " + blob + " "):
        size = "1000mm"
    elif "500MM" in blob or "500 MM" in blob:
        size = "500mm"
    else:
        return None  # size not stated -- do not guess
    minutes = sizes.get(size)
    if not minutes:
        return None
    basis = (
        f"Punch {minutes} min/part: TruPunch 1000 machine cycle, {family} {size} "
        f"({'measured 1m plan' if size == '1000mm' else 'scaled x0.65 from 1m plan'}); "
        f"DXF/PDF under-reads perforation -- verify with CNC programmer."
    )
    return (float(minutes), basis)


def _is_punch_part(part: Dict[str, Any], holes: int, desc_blob: str) -> bool:
    """Decide whether a sheet-metal part is a PUNCH job rather than laser.

    Two corpus-validated signals (2023 manual estimates, 3,055 records):
      - geometric: a dense field of holes (uneconomic to laser-pierce one by one);
      - descriptive: peg / slotted / perforated / mesh parts (peg = 5.9x punch-lift).
    Caller gates this to sheet metals only.
    """
    cfg = getattr(config, "PUNCH_RECOGNITION", {}) or {}
    if not cfg.get("enabled", True):
        return False
    holes = int(holes or 0)
    if holes >= int(cfg.get("min_holes_for_punch", 24)):
        return True
    blob = (desc_blob or "").upper()
    kws = cfg.get("punch_keywords", []) or []
    if any(k in blob for k in kws) and holes >= int(cfg.get("min_holes_with_keyword", 8)):
        return True
    return False


# Special / bought-in FINISHING items — mirror mosaic tiles, ceramic/glass tiles,
# graphic panels, vinyl/decal graphics. These are NOT SDI-fabricated: they carry no
# saw/glue/CNC/laser/weld fab labour. Dual gate so it stays general:
#   - part number ends in the M&S '-X' special/finishing suffix (e.g. 12301-08-04X), OR
#   - description names a tile/mosaic/graphic/vinyl item
# Keyed on BOTH so a future '-X' that is genuinely a different item still needs the
# description to match, and a tile item without the suffix is still caught.
_SPECIAL_ITEM_DESC_RE = re.compile(
    r"\b(TILE|TILES|MOSAIC|GRAPHIC\s+PANEL|GRAPHIC|VINYL|DECAL)\b",
    re.IGNORECASE,
)


def _is_special_bought_in_item(part: Dict[str, Any]) -> bool:
    pn = str(part.get("part_number") or "").strip().upper()
    desc = " ".join([
        str(part.get("description") or ""),
        str(part.get("part_description") or ""),
    ]).upper()
    _suffix = re.search(r"\d([A-Z])$", pn)
    x_suffix = bool(_suffix and _suffix.group(1) == "X")
    return x_suffix or bool(_SPECIAL_ITEM_DESC_RE.search(desc))


_SPECIAL_ITEM_FAB_OPS = {
    "laser_cutting", "saw", "cnc", "cnc_routing", "guillotine", "punch",
    "folding", "fold", "weld", "welding", "dress_welds", "glue", "wet_spray",
    "powder_coating", "diamond_polish", "edge_banding", "bench_work",
    "hole_machining", "drilling", "linebend",
}


def estimate_process_times(part: Dict[str, Any], quantity: int = 1) -> Dict[str, Any]:
    geom = part.get("geometry_rollup", {})
    ops = _part_ops(part)
    # Special / bought-in finishing items (tiles, mosaics, graphics, vinyl, -X suffix):
    # strip all fabrication ops — they are bought in, not made. Handling is retained so
    # the item is still received/assembled; pricing routes through the bought-in path.
    if _is_special_bought_in_item(part):
        ops = [o for o in ops if o not in _SPECIAL_ITEM_FAB_OPS]
        for _op_field in ("textual_operations", "inferred_operations"):
            if isinstance(part.get(_op_field), list):
                part[_op_field] = [o for o in part[_op_field] if o not in _SPECIAL_ITEM_FAB_OPS]   # precedence: direct-write ok — removes ops, adds no evidence
        _roles = [str(r).lower() for r in (part.get("page_roles") or [])]
        if "bought_in" not in _roles:
            part.setdefault("page_roles", []).append("bought_in")
        part["special_finish_item"] = True
    manufacturing_features = part.get("manufacturing_features", {})
    geometry_confidence = 0.0
    if isinstance(geom.get("confidence"), dict):
        geometry_confidence = geom["confidence"].get("geometry_reliability", 0.0) or 0.0

    dims_pm = infer_primary_dimensions(part)
    blank_length_pm, blank_width_pm = estimate_blank_size(dims_pm)

    raw_cut_length_mm = manufacturing_features.get("raw_cut_length_mm", geom.get("estimated_cut_length_mm", 0.0) or 0.0)
    cut_length_mm = manufacturing_features.get("cut_length_mm", raw_cut_length_mm * max(0.25, geometry_confidence) if raw_cut_length_mm else 0.0)
    pierces = geom.get("estimated_pierce_count", 0) or 0
    holes = max(
        int(manufacturing_features.get("hole_count") or 0),
        int(geom.get("estimated_hole_count") or 0),
        int(geom.get("estimated_pierce_count") or 0),
        len(part.get("hole_sizes_mm", []) or []),
    )
    bends = manufacturing_features.get("bend_count") or max(len(part.get("angles_deg", [])), len(part.get("fold_values_mm", [])), part.get("fold_count_textual", 0) or 0)  # fold-shadowing fix: present-but-zero bend_count falls through to PDF fold evidence (angles_deg/fold_count_textual), so parts folded from PDF callouts (no DXF BENDLINES layer) get their Fold op
    bend_length_mm = sum([_safe_float(value) or 0.0 for value in part.get("fold_values_mm", [])])
    thickness_mm = _safe_thickness_mm(part)

    # SDI Intelligence — infer a cutting operation when the drawing text did not
    # name one. Any sheet/board part with a cut length MUST be cut somehow, so
    # assign laser cutting (steel + acrylic are laser cut at SDI). Without this,
    # parts with valid flat-pattern geometry got zero operations -> zero labour.
    _mat_u = str(part.get("normalized_material") or "").upper()
    _SHEET_METALS = {"MILD_STEEL", "MILD STEEL", "STAINLESS_STEEL", "STAINLESS STEEL",
                     "ALUMINIUM", "ALUMINUM", "ZINTEC", "BRIGHT_DRAWN"}
    _CUT_BOARDS = {"ACRYLIC", "POLYCARBONATE", "PETG", "HIPS", "MDF", "VENEERED_MDF",
                   "OAK_VENEER_MDF", "PLYWOOD", "BIRCH_PLYWOOD", "HDPE_PLASTIC",
                   "FOAMEX", "DIBOND", "TIMBER"}
    _CUTTING_OPS = ("laser_cutting", "cnc_routing", "cnc", "punch", "guillotine", "saw")
    _has_cut_op = any(o in ops for o in _CUTTING_OPS)

    # SDI Intelligence — metal holes are LASER-CUT, not a separate hole/drill op. Tim's
    # sheets have no metal hole op (only "Drill (Acrylic)"); job 1282 (all metal) carries
    # none. But a metal part with holes can arrive with a stale hole_machining/drilling in
    # textual_operations (from the note/geometry extractor), which then gets costed -> a
    # wrong Guillotine line on the sheet. Strip it from BOTH the costing ops and the part's
    # displayed textual_operations, for sheet-metal only. Acrylic/board KEEP drilling.
    # Broadened metal gate: normalized_material may not be set yet at this point in the
    # pipeline (seen None on 1298-01 while the raw `materials` list already held MILD STEEL),
    # which silently skipped the strip. Check ALL material fields so a not-yet-normalized
    # part is still recognised as sheet metal. Acrylic/board won't match on any field.
    _mat_fields = [_mat_u]
    _mat_fields.append(str(part.get("material") or "").upper())
    for _m in (part.get("materials") or []):
        _mat_fields.append(str(_m or "").upper().replace(" ", "_"))
        _mat_fields.append(str(_m or "").upper())
    _is_metal_any = any(mf in _SHEET_METALS for mf in _mat_fields if mf)
    if _is_metal_any:
        _metal_hole_ops = ("hole_machining", "drilling")
        ops = [o for o in ops if o not in _metal_hole_ops]
        if isinstance(part.get("textual_operations"), list):
            part["textual_operations"] = [
                o for o in part["textual_operations"] if o not in _metal_hole_ops
            ]
        if isinstance(part.get("inferred_operations"), list):
            part["inferred_operations"] = [
                o for o in part["inferred_operations"] if o not in _metal_hole_ops
            ]
    # diamond_polish is an acrylic-EDGE finishing op — steel is never diamond polished
    # (it is linished/dressed). It leaks onto steel because the standard drawing boilerplate
    # "CHROME PLATING - POLISHING SPECIFICATION IS 400 GRIT FINAL POLISH" sits on every page
    # and the op-detector reads "POLISH", booking large spurious DPOL lines (e.g. £83 on a
    # powder-coated base mesh, £32 on a base shelf). Strip it from metal parts unless the
    # part's OWN finish explicitly calls a mirror / diamond polish. Acrylic parts are not
    # metal, so they are unaffected here and still get DPOL via the acrylic route below.
    # General de-pollution, same class as the material-boilerplate fix — not a per-job patch.
    if _is_metal_any and "diamond_polish" in ops:
        _fin_all = " ".join([
            str(part.get("normalized_finish") or ""),
            " ".join(str(f) for f in (part.get("surface_finishes") or [])),
            str(part.get("finish") or ""),
        ]).upper()
        _genuine_polish = ("MIRROR" in _fin_all) or ("DIAMOND POLISH" in _fin_all)
        if not _genuine_polish:
            ops = [o for o in ops if o != "diamond_polish"]
            for _op_field in ("textual_operations", "inferred_operations"):
                if isinstance(part.get(_op_field), list):
                    part[_op_field] = [o for o in part[_op_field] if o != "diamond_polish"]   # precedence: direct-write ok — removes ops, adds no evidence
    # Section/tube/wire parts without a flat DXF are SAWN/MITRED to length, not laser
    # profile-cut. Their PDF "cut length" is the whole-GA-page geometry rollup (e.g.
    # 24,508mm on a 600mm frame), so it must never drive laser cost or trigger a laser
    # op. The DXF guard means any section that DOES carry a flat pattern is left alone.
    _section_no_dxf = (
        _is_section_or_wire_candidate(part, part.get("normalized_material"))
        and not _dxf_geometry_trusted(part, part.get("normalized_geometry", {}) or {})
    )
    # SDI buys the RHS/tube as a length (does NOT make it) -> no in-house cut, neither
    # laser profile nor saw. But SDI DOES bend the tube, so the bend op is RETAINED.
    # Material = bought-in length; cost = material + bend + finish + handling.
    if _section_no_dxf:
        ops = [o for o in ops if o not in ("laser_cutting", "saw")]
        if isinstance(part.get("inferred_operations"), list):
            part["inferred_operations"] = [
                o for o in part["inferred_operations"] if o not in ("laser_cutting", "saw")
            ]
        # Also correct the part's DISPLAYED operations so the workbook / decision report
        # don't show "laser_cutting" on a tube that is bought as a length and never lasered.
        # (Previously only the local `ops` used for labour was stripped, leaving the part's
        # textual_operations stale and misleading in the output sheet.)
        if isinstance(part.get("textual_operations"), list):
            part["textual_operations"] = [
                o for o in part["textual_operations"] if o not in ("laser_cutting", "saw")
            ]
        part["section_costing_adjustment"] = {
            "rule": "section_bought_as_length_bent_inhouse",
            "basis": "bought_in_length_plus_bend_finish_handling",
            "note": "RHS/tube bought as a length (not made in-house) -- no cut/saw. SDI "
                    "bends the tube, so the bend op is retained; the bend COUNT may be "
                    "under-read from the drawing -- verify bend count/time with the tube-bend "
                    "operator. Coated in-house (SDI sprays everything).",
        }
    if not _has_cut_op and cut_length_mm and cut_length_mm > 0 and not _section_no_dxf:
        if _mat_u in _SHEET_METALS or _mat_u in _CUT_BOARDS:
            ops = list(ops) + ["laser_cutting"]
            part.setdefault("inferred_operations", [])
            if "laser_cutting" not in part["inferred_operations"]:
                part["inferred_operations"].append("laser_cutting")
    # Every fabricated part also needs handling/assembly time at the bench.
    if (_mat_u in _SHEET_METALS or _mat_u in _CUT_BOARDS) and "handling" not in ops:
        ops = list(ops) + ["handling"]

    # ── BOUGHT-IN PARTS TAKE NO FABRICATION LABOUR ───────────────────────────────
    # Runs before every route rule below, because a purchased component is not a routing
    # question at all. The UPC sticker was a catalogue line on the BOM and, at the same
    # time, a record carrying weld, powder and glue on the route — the same item classified
    # twice, at different stages, with different answers. Identity is settled once here.
    #
    # Handling/assembly is deliberately NOT stripped: we do fit bought-in components, and
    # that bench time is real work that must keep being charged.
    try:
        from bought_in_policy import (bought_in_conflict, is_bought_in,
                                      strip_fabrication_ops)
        if is_bought_in(part):
            _bi_removed = strip_fabrication_ops(part)
            _bi_ops = set(part.get("textual_operations") or [])
            ops = [o for o in ops if o in _bi_ops or str(o).lower() in ("handling", "assembly")]
            if _bi_removed:
                part.setdefault("review_flags", []).append(
                    f"bought-in part — fabrication operations removed "
                    f"({', '.join(_bi_removed)}). We buy this item; only handling/assembly "
                    f"time applies. Price it from the catalogue, not from a route")
            if bought_in_conflict(part):
                # Identity says buy, geometry says make. Do not let the engine pick a side.
                part.setdefault("review_flags", []).append(
                    "CONFLICT: classified bought-in, but the part also carries its own "
                    "measured flat pattern. One of the two is wrong — confirm whether this "
                    "is a purchased item or one we fabricate")
    except Exception:
        pass

    # WELDING IS A METAL PROCESS. Timber, board and plastic parts are glued, screwed or
    # solvent-bonded — never CO2/MIG welded. The weld op leaks onto joinery the same way
    # diamond polish leaked onto steel: a weld note somewhere in the drawing text (an
    # assembly instruction, a spec block, a neighbouring detail) is read as a cue for the
    # part, and because `welding` automatically chains `dress_welds` below, ONE bad cue
    # books TWO departments. On the Horti Crate — a wooden crate — that was Weld (CO2)
    # plus Dress Welds against parts the engine itself had identified as TIMBER.
    #
    # Gated on POSITIVE evidence the part is non-metal (a named board/timber/plastic
    # family), the same standard as the polish gate, so a part whose material has not been
    # resolved yet is left alone rather than stripped on a guess. Where the material is
    # genuinely mis-read the fix belongs upstream in the material read, not here.
    _is_board_any = any(mf in _CUT_BOARDS for mf in _mat_fields if mf)
    if _is_board_any and not _is_metal_any:
        _weld_ops = ("welding", "dress_welds", "spot_welding", "resistance_welding")
        _stripped = [o for o in ops if o in _weld_ops]
        if _stripped:
            ops = [o for o in ops if o not in _weld_ops]
            for _op_field in ("textual_operations", "inferred_operations"):
                if isinstance(part.get(_op_field), list):
                    part[_op_field] = [o for o in part[_op_field] if o not in _weld_ops]   # precedence: direct-write ok — removes ops, adds no evidence
            part.setdefault("review_flags", []).append(
                f"{'/'.join(_stripped)} removed: part is {_mat_u or 'a board/timber family'}, "
                f"which is not welded — joining is by glue/fixings. A weld cue was read from "
                f"the drawing text; confirm it belongs to a different (metal) part")
            # Clear the weld SIGNALS too, not just the costed ops. welding_required is
            # synthesised from textual_operations back at document-build time, so without
            # this the sheet correctly shows no weld while the job report still tells the
            # estimator to "verify weld/dress content" on the same part. A report that
            # contradicts the sheet it accompanies is worse than either alone.
            _mf_w = part.get("manufacturing_features")
            if isinstance(_mf_w, dict):
                _mf_w["welding_required"] = False
            if isinstance(part.get("risk_flags"), list):
                part["risk_flags"] = [f for f in part["risk_flags"] if f != "weld_required"]

    # DRES — a structural (CO2/WELD) weld is dressed/linished to clean the bead before
    # finishing. Chain a dress_welds op after the welding op so the DRES dept labour
    # lands on the route (timing set in the run/setup tables below). Config-gated; spot/
    # resistance welds leave no proud bead and are not dressed, so only `welding` triggers.
    if (
        getattr(config, "DRESS_AFTER_STRUCTURAL_WELD", True)
        and "welding" in ops
        and "dress_welds" not in ops
    ):
        ops = list(ops) + ["dress_welds"]
        part.setdefault("inferred_operations", [])
        if "dress_welds" not in part["inferred_operations"]:
            part["inferred_operations"].append("dress_welds")

    setup_times_min: Dict[str, float] = {}
    run_times_min: Dict[str, float] = {}
    powder_coating_detail: Optional[Dict[str, Any]] = None

    _is_wire_op_part = any(
        op in ops
        for op in ("wire_forming", "welding", "resistance_welding", "spot_welding", "deburring")
    )

    # SDI Intelligence — punch recognition. A dense field of holes (e.g. a peg
    # panel: 380+ identical small holes) is a PUNCH job, not laser. Pricing every
    # hole as a 1.2s laser pierce massively over-costs these parts. Swap an
    # assigned/inferred laser op for punch so the holes cost as hits, not pierces.
    _punch_blob = " ".join([
        str(part.get("description") or ""),
        str(part.get("part_number") or ""),
        ";".join(part.get("process_notes") or []),
    ]).upper()
    # Recognise on the geometry pierce/hole count (DXF truth, e.g. 386), not the
    # manufacturing "hole_count" field, which can collapse to distinct-size count.
    _punch_hole_signal = int(max(holes or 0, pierces or 0))
    if (_mat_u in _SHEET_METALS) and "punch" not in ops and _is_punch_part(part, _punch_hole_signal, _punch_blob):
        ops = [o for o in ops if o != "laser_cutting"] + ["punch"]
        part.setdefault("inferred_operations", [])
        if "punch" not in part["inferred_operations"]:
            part["inferred_operations"].append("punch")

    # Known peg-family panels carry a measured machine cycle time; force punch
    # (drop laser) so the calibrated time below replaces the collapsed hit model.
    _punch_cycle = _peg_family_punch_cycle(part)
    if _punch_cycle is not None:
        ops = [o for o in ops if o != "laser_cutting"]
        if "punch" not in ops:
            ops = ops + ["punch"]
        part.setdefault("inferred_operations", [])
        if "punch" not in part["inferred_operations"]:
            part["inferred_operations"].append("punch")

    if "laser_cutting" in ops:
        rule = LABOUR_RULES["laser_cutting"]
        setup_times_min["laser_cutting"] = round(rule["setup_min"], 2)
        speed_table = rule.get("cutting_speeds_mm_per_sec", {})
        if speed_table:
            speed_key = min(speed_table.keys(), key=lambda key: abs(float(key) - (thickness_mm or 1.0)))
            cutting_speed = float(speed_table[speed_key])
        else:
            cutting_speed = 80.0
        # For section parts without a flat DXF, charge a realistic cut-to-length using
        # the inferred stock length, not the phantom PDF perimeter. Stamp the adjustment
        # so the inferred basis is visible downstream rather than silently applied.
        _laser_cut_length_mm = cut_length_mm
        if _section_no_dxf:
            _stock_len = _infer_section_length_mm(part)
            _laser_cut_length_mm = min(cut_length_mm, _stock_len) if (_stock_len and _stock_len > 0) else 0.0
            part["section_costing_adjustment"] = {
                "rule": "section_no_flat_dxf",
                "laser_basis": "cut_to_length",
                "pdf_cut_length_mm": round(cut_length_mm, 1),
                "applied_cut_length_mm": round(_laser_cut_length_mm, 1),
                "note": "Tube/section sawn to length, not laser profile-cut. "
                        "Cut length INFERRED from stock length — verify manually.",
            }
        load_unload_sec = float(rule.get("load_unload_sec", 0.0))
        profile_cutting_sec = (_laser_cut_length_mm / cutting_speed) if cutting_speed > 0 else 0.0
        pierce_sec = pierces * float(rule["pierce_sec_each"])
        run_times_min["laser_cutting"] = round((load_unload_sec + profile_cutting_sec + pierce_sec) / 60.0, 2)

    if "punch" in ops:
        prule = LABOUR_RULES.get("punch", {}) or {}
        setup_times_min["punch"] = round(float(prule.get("setup_min", 3.0)), 2)
        load_unload = float(prule.get("load_unload_sec", 30.0))
        sec_per_hit = float(prule.get("sec_per_hit", 0.7))
        profile_speed = float(prule.get("profile_speed_mm_per_sec", 60.0))
        hit_count = int(max(holes, pierces) or 0)
        # Outline only (perimeter), NOT cut_length — cut_length includes hole edges
        # that are single punch hits here, so using it would double-count.
        _perim = 2.0 * ((blank_length_pm or 0.0) + (blank_width_pm or 0.0))
        profile_sec = (_perim / profile_speed) if profile_speed > 0 else 0.0
        run_times_min["punch"] = round((load_unload + hit_count * sec_per_hit + profile_sec) / 60.0, 2)
        if _punch_cycle is not None:
            run_times_min["punch"] = round(_punch_cycle[0], 2)
            part["punch_calibration"] = {"cycle_min": round(_punch_cycle[0], 2), "basis": _punch_cycle[1]}

    if "hole_machining" in ops:
        rule = LABOUR_RULES["hole_machining"]
        setup_times_min["hole_machining"] = round(rule["setup_min"], 2)
        run_times_min["hole_machining"] = round((holes * rule["sec_per_hole"]) / 60.0, 2)

    # ---- Fold operation inference (general, evidence-based) ----------------------
    # A part folds if it carries fold evidence — PDF callouts (UP/DOWN + angle -> angles_deg
    # / fold_count_textual), a DXF BENDLINES bend count, or textual bend mentions — even when
    # the extractor did not emit "folding" in textual_operations (folds often live ONLY in the
    # PDF, not a DXF layer). Add the op so it is costed. Same shape as the laser/punch
    # inference above. Sheet metal / board ONLY: a tube is bent on a tubebender (its own op),
    # a bought section is not press-folded. Uses `bends` (already set from PDF fold evidence).
    if "folding" not in ops and (_mat_u in _SHEET_METALS or _mat_u in _CUT_BOARDS) and not _section_no_dxf:
        _fold_evidence = (
            (bends or 0) > 0
            or len(part.get("angles_deg") or []) > 0
            or int(part.get("fold_count_textual") or 0) > 0
            or int((part.get("manufacturing_features") or {}).get("bend_count") or 0) > 0
        )
        if _fold_evidence:
            ops = list(ops) + ["folding"]
            part.setdefault("inferred_operations", [])
            if "folding" not in part["inferred_operations"]:
                part["inferred_operations"].append("folding")

    if "folding" in ops:
        rule = LABOUR_RULES["folding"]
        setup_times_min["folding"] = round(rule["setup_min"], 2)
        run_times_min["folding"] = round((bends * rule["sec_per_bend"] + bend_length_mm * rule["sec_per_mm_bend_length"]) / 60.0, 2)

    if "powder_coating" in ops:
        pc_rule = LABOUR_RULES["powder_coating"]
        setup_pm = float(pc_rule.get("setup_min_per_part", pc_rule.get("min_per_part", 0.75)))
        throughput = float(pc_rule.get("throughput_m2_per_hour", 15.0))
        _reliable_m2 = part.get("_powder_reliable_coated_m2")
        if _reliable_m2 is not None and float(_reliable_m2) > 0:
            coated_m2 = float(_reliable_m2)
            coated_detail = {"coated_area_source": "powder_consumable_reliable_blank"}
        else:
            # No reliable blank => powder material was suppressed. Do NOT invent an
            # inflated area from drawing-extent dims; floor to nominal handling + flag.
            coated_m2 = 0.0
            coated_detail = {"coated_area_source": "no_reliable_blank_floored", "powder_labour_floored": True}
        run_min = 0.0
        if throughput > 0 and coated_m2 > 0:
            run_min = (coated_m2 / throughput) * 60.0
        # The elevated wire/formed powder floor (extra manual hanging/handling time) applies
        # only to genuinely wire-formed parts that have NO flat sheet blank. A flat sheet part
        # that merely carries a weld (e.g. welded footbase 3886-02) coats like sheet and must
        # use the normal floor — the 3-min wire floor is what produced the £17.82 phantom.
        _has_flat_blank = bool(blank_length_pm and blank_width_pm)
        _wire_pc_floor = float(pc_rule.get("wire_min_run_min", 3.0))
        _normal_pc_floor = float(pc_rule.get("min_run_min", 0.25))
        _pc_min = _wire_pc_floor if (_is_wire_op_part and not _has_flat_blank) else _normal_pc_floor
        run_min = max(_pc_min, run_min)
        setup_times_min["powder_coating"] = round(setup_pm, 2)
        run_times_min["powder_coating"] = round(run_min, 2)
        powder_coating_detail = {
            "coated_m2": round(coated_m2, 4),
            "throughput_m2_per_hour": throughput,
            "setup_min_per_part": round(setup_pm, 2),
            "run_min_per_unit": round(run_min, 2),
            "hourly_rate_note_gbp": "P/C → powder_coating; SPRY → wet_spray via HOURLY_RATES_GBP / labour_rates",
            **coated_detail,
        }

    if "wet_spray" in ops:
        ws_rule = LABOUR_RULES.get("wet_spray") or {}
        setup_pm = float(ws_rule.get("setup_min_per_part", 0.75))
        throughput = float(ws_rule.get("throughput_m2_per_hour", 22.0))
        coated_m2, coated_detail_ws = _powder_coated_area_m2(part, blank_length_pm, blank_width_pm)
        run_min = 0.0
        if throughput > 0 and coated_m2 > 0:
            run_min = (coated_m2 / throughput) * 60.0
        run_min = max(float(ws_rule.get("min_run_min", 0.25)), run_min)
        setup_times_min["wet_spray"] = round(setup_pm, 2)
        run_times_min["wet_spray"] = round(run_min, 2)
        if powder_coating_detail is None:
            powder_coating_detail = {
                "coated_m2": round(coated_m2, 4),
                "throughput_m2_per_hour": throughput,
                "setup_min_per_part": round(setup_pm, 2),
                "run_min_per_unit": round(run_min, 2),
                "hourly_rate_note_gbp": "wet_spray booth labour (area model shared with powder costing)",
                **coated_detail_ws,
            }

    if "cnc" in ops:
        cnc_rule = LABOUR_RULES.get("cnc") or {}
        setup_times_min["cnc"] = round(float(cnc_rule.get("setup_min", 4.0)), 2)
        sec_per_mm = float(cnc_rule.get("sec_per_mm_contour", 0.04))
        run_sec = max(float(cnc_rule.get("min_run_min", 1.0)) * 60.0, cut_length_mm * sec_per_mm)
        run_times_min["cnc"] = round(run_sec / 60.0, 2)

    if "cnc_routing" in ops:
        cnc_rule = LABOUR_RULES.get("cnc_routing") or LABOUR_RULES.get("cnc") or {}
        setup_times_min["cnc_routing"] = round(float(cnc_rule.get("setup_min", 4.0)), 2)
        sec_per_mm = float(cnc_rule.get("sec_per_mm_contour", 0.04))
        run_sec = max(float(cnc_rule.get("min_run_min", 8.0)) * 60.0, cut_length_mm * sec_per_mm)
        run_times_min["cnc_routing"] = round(run_sec / 60.0, 2)

    if "edge_banding" in ops:
        eb_rule = LABOUR_RULES.get("edge_banding") or {}
        setup_times_min["edge_banding"] = round(float(eb_rule.get("setup_min", 3.0)), 2)
        edge_mm = 2.0 * ((blank_length_pm or 0.0) + (blank_width_pm or 0.0))
        sec_per_mm = float(eb_rule.get("sec_per_mm_edge", 0.08))
        run_sec = max(float(eb_rule.get("min_run_min", 4.0)) * 60.0, edge_mm * sec_per_mm)
        run_times_min["edge_banding"] = round(run_sec / 60.0, 2)

    if "bench_work" in ops:
        bw = LABOUR_RULES.get("bench_work") or {}
        run_times_min["bench_work"] = round(float(bw.get("min_per_part", 2.0)), 2)

    if "diamond_polish" in ops:
        setup_times_min["diamond_polish"] = 0.5
        run_times_min["diamond_polish"] = round(max(1.0, (cut_length_mm / 500.0)) if cut_length_mm else 1.5, 2)

    if "glue" in ops:
        setup_times_min["glue"] = 0.5
        run_times_min["glue"] = 1.0

    if "dress_welds" in ops:
        setup_times_min["dress_welds"] = 0.5
        # Tim's 12120 "Dress (Minimal)" = 120/hr = 0.5 min/unit (config lever).
        run_times_min["dress_welds"] = float(getattr(config, "DRESS_WELD_RUN_MINUTES", 0.5))

    if "handling" in ops:
        run_times_min["handling"] = round(LABOUR_RULES["handling"]["min_per_part"], 2)

    if "wire_forming" in ops:
        _wire_len_mm = _safe_float(part.get("wire_total_length_mm")) or cut_length_mm
        setup_times_min["wire_forming"] = 5.0
        run_times_min["wire_forming"] = round(
            max(1.0, (_wire_len_mm / 500.0) if _wire_len_mm else 1.0), 2
        )

    if "welding" in ops:
        setup_times_min["welding"] = 3.0
        run_times_min["welding"] = round(
            max(1.0, (pierces * 90.0 + cut_length_mm * 0.01) / 60.0), 2
        )

    if "resistance_welding" in ops or "spot_welding" in ops:
        _weld_key = "resistance_welding" if "resistance_welding" in ops else "spot_welding"
        setup_times_min[_weld_key] = 2.0
        run_times_min[_weld_key] = round(max(0.5, (pierces * 45.0) / 60.0), 2)

    if "deburring" in ops:
        setup_times_min["deburring"] = 1.0
        run_times_min["deburring"] = round(max(0.5, (pierces * 30.0) / 60.0), 2)

    # ── TIMBER / BOARD process allowance (no-geometry) ──────────────────────────────────
    # A wood/board part on a PDF gives a printed WEIGHT but no blank L×W, so every geometry-based
    # timer above reads 0 and the panel gets ZERO labour — yet a sawn, rebated, glued-and-pinned,
    # lacquered timber panel plainly has labour content. When no cutting op fired and there is no
    # cut length, assign flat per-part ALLOWANCES at the REAL shop rates (SAW/CNC-rout/GLUE/SPRY/
    # assembly) so labour is a sensible, FLAGGED figure the estimator refines — never £0, never a
    # metal-laser lie. Minutes are config-tunable (TIMBER_LABOUR_ALLOWANCE_MIN). Geometry-backed
    # timber (from a DXF) keeps its real timing and skips this.
    _mat_family = _mat_u.replace(" ", "_")
    _TIMBER_FAMILIES = {"TIMBER", "WOOD", "MDF", "MDF_BOARD", "VENEERED_MDF", "OAK_VENEER_MDF",
                        "PLYWOOD", "BIRCH_PLYWOOD", "SOFTWOOD", "HARDWOOD", "PINE"}
    # Fire for ANY no-DXF timber/board part. We deliberately do NOT gate on cut_length: a PDF
    # vector rollup often yields a phantom cut length, which previously (a) skipped this whole
    # allowance and (b) let a metal 'laser_cutting' op attach to timber. A timber panel is sawn/
    # routed, never metal-lasered, so we STRIP any inferred laser and assign the joinery route.
    # Real DXF-backed timber keeps its measured timing and skips this.
    _timber_dxf = ("dxf" in str(part.get("geometry_source") or "").lower()
                   or bool(part.get("dxf_augmented")) or bool(part.get("flat_pattern_detected")))
    # A tube / section / wire / bar is a bought steel section — SDI saws-to-length, bends and
    # welds it; it is NEVER joinery-routed (saw+CNC-rout+glue+wet-spray). When such a part is
    # mis-tagged as a timber family (e.g. a steel FRONT POST CROSS RAIL that the boilerplate
    # scan called TIMBER), the timber allowance below would bolt a full joinery route onto it
    # and blow the labour up. Gate the allowance off for section-form parts, whatever the
    # material tag says — its real route (weld/handling) comes from the tube path. General.
    _stock_form_now = str((part.get("material_estimate") or {}).get("stock_form")
                          or (part.get("manufacturing_interpretation") or {}).get("stock_form")
                          or "").lower()
    _section_like = (
        _stock_form_now in ("tube", "wire", "section", "bar")
        or _is_section_or_wire_candidate(part, part.get("normalized_material"))
    )
    if (_mat_family in _TIMBER_FAMILIES and not _timber_dxf and not _section_like
            and not part.get("is_assembly_parent")
            and not any(o in ("saw", "cnc_routing", "cnc") for o in set(run_times_min))):
        # Timber is not laser-cut — drop any metal laser op the sheet/board inference attached.
        for _bad in ("laser_cutting", "guillotine", "punch"):
            run_times_min.pop(_bad, None)
            setup_times_min.pop(_bad, None)
        _alloc = getattr(config, "TIMBER_LABOUR_ALLOWANCE_MIN", None) or {
            "saw": 1.5, "cnc_routing": 2.0, "glue": 1.5, "wet_spray": 1.5, "handling": 1.0,
        }
        for _top, _mins in _alloc.items():
            _m = float(_mins or 0.0)
            if _m <= 0:
                continue
            run_times_min[_top] = round(run_times_min.get(_top, 0.0) + _m, 2)
            setup_times_min.setdefault(_top, 1.0)
        part["timber_labour_allowance"] = True
        part.setdefault("review_flags", []).append(
            "timber labour is a FLAT PER-PART ALLOWANCE (saw/rout/glue/lacquer at shop rates) — "
            "no panel dimensions on the PDF to time it precisely; estimator to refine")

    # Special / bought-in finishing items (tiles, mosaics, graphics, vinyl, -X suffix) carry
    # NO fabrication labour, whatever the inference or timber-allowance blocks above added —
    # they are bought in, not made. Final strip so only handling/assembly survives.
    if part.get("special_finish_item"):
        for _timing in (setup_times_min, run_times_min):
            for _op in list(_timing.keys()):
                if _op in _SPECIAL_ITEM_FAB_OPS:
                    _timing.pop(_op, None)

    unit_times_min: Dict[str, float] = {}
    total_times_min: Dict[str, float] = {}
    for op in set(setup_times_min) | set(run_times_min):
        unit_times_min[op] = round(setup_times_min.get(op, 0.0) + run_times_min.get(op, 0.0), 2)
        total_times_min[op] = round(setup_times_min.get(op, 0.0) + (run_times_min.get(op, 0.0) * quantity), 2)

    return {
        "cut_length_mm": round(cut_length_mm, 2),
        "raw_cut_length_mm": round(raw_cut_length_mm, 2),
        "pierce_count": pierces,
        "hole_count": holes,
        "bend_count": bends,
        "bend_length_mm": round(bend_length_mm, 2),
        "setup_times_min": setup_times_min,
        "run_times_min_per_unit": run_times_min,
        "unit_times_min": unit_times_min,
        "times_min": total_times_min,
        "unit_time_min": round(sum(unit_times_min.values()), 2),
        "total_time_min": round(sum(total_times_min.values()), 2),
        "feature_rollup": part.get("feature_rollup", {}),
        "manufacturing_features": manufacturing_features,
        "routing": part.get("manufacturing_interpretation", {}).get("routing", []),
        "geometry_reliability": geometry_confidence,
        "powder_coating_detail": powder_coating_detail,
    }


def estimate_labour_costs(process: Dict[str, Any], job_quantity: int = 1, material: Optional[str] = None) -> Dict[str, Any]:
    """
    Compute per-unit labour cost matching the workbook M63 formula exactly:

        M = H + (rate/60 × setup_mins) / D6

    Where H = run_cost_per_unit = rate × run_hours_per_unit
    And the setup cost is amortised across the job quantity (D6).

    The workbook's J63 (total batch hours) is also computed for reference:
        J = run_hours_per_unit × job_qty + setup_mins/60
    """
    breakdown: Dict[str, float] = {}
    setup_amortised: Dict[str, float] = {}
    run_costs: Dict[str, float] = {}
    batch_hours: Dict[str, float] = {}
    rate_sources: Dict[str, Any] = {}
    missing_rate_operations: List[str] = []

    setup_times = process.get("setup_times_min", {})
    run_times = process.get("run_times_min_per_unit", {})
    all_ops = set(setup_times) | set(run_times)
    qty = max(1, int(job_quantity))

    _mat_u = str(material or "").upper()
    _ACRYLIC_LIKE = {"ACRYLIC", "POLYCARBONATE", "PETG", "HIPS", "HDPE_PLASTIC", "FOAMEX"}
    for op in all_ops:
        external_rate = _resolve_labour_rate(op)
        applied_hourly_rate = external_rate.get("applied_hourly_rate")
        # Material-aware rate key: acrylic/plastic laser cutting + assembly use
        # the cheaper non-metal rates (laser_cutting_acrylic, assembly_acrylic).
        _rate_key = op
        # acrylic_rate_key_override (2026-07-15): for an acrylic part, an acrylic op must be
        # priced at its ACRYLIC department rate (MANA/LASA/PACP/DPOL from the rate card), NOT
        # the metal department. The pricing resolver returns the METAL manual rate (MANM
        # £31.18) for manual_labour, and that was winning over the correct MANA £25.43 — the
        # Peel line came out 23% over. This picks the authoritative acrylic rate from
        # HOURLY_RATES_GBP and OVERRIDES the resolved metal rate for acrylic parts.
        _acr_rate = None
        if _mat_u in _ACRYLIC_LIKE:
            # existing laser/assembly remaps (kept), now also actually applied via _acr_rate
            if op == "laser_cutting" and "laser_cutting_acrylic" in HOURLY_RATES_GBP:
                _rate_key = "laser_cutting_acrylic"
            elif op == "assembly" and "assembly_acrylic" in HOURLY_RATES_GBP:
                _rate_key = "assembly_acrylic"
            # general: the op's own explicit "<op>_acrylic" variant, or the op name if it is
            # already an acrylic-specific key (manual_labour_acrylic, diamond_polish, linebend).
            for _cand in (f"{op}_acrylic", _rate_key, op):
                if _cand in HOURLY_RATES_GBP:
                    _acr_rate = HOURLY_RATES_GBP[_cand]
                    _rate_key = _cand
                    break
        if _acr_rate is not None:
            rate = _acr_rate   # authoritative acrylic dept rate wins for acrylic parts
        else:
            rate = applied_hourly_rate if applied_hourly_rate is not None else HOURLY_RATES_GBP.get(_rate_key)
        if rate is None:
            run_min = run_times.get(op, 0.0)
            setup_min = setup_times.get(op, 0.0)
            if run_min or setup_min:
                missing_rate_operations.append(op)
            continue

        run_min = float(run_times.get(op, 0.0))
        setup_min = float(setup_times.get(op, 0.0))

        run_cost_unit = rate * (run_min / 60.0)
        setup_cost_unit = (rate / 60.0 * setup_min) / qty
        unit_cost = run_cost_unit + setup_cost_unit

        run_hours_unit = run_min / 60.0
        j_batch_hours = run_hours_unit * qty + (setup_min / 60.0)

        breakdown[op] = round(unit_cost, 4)
        run_costs[op] = round(run_cost_unit, 4)
        setup_amortised[op] = round(setup_cost_unit, 4)
        batch_hours[op] = round(j_batch_hours, 4)
        rate_sources[op] = _build_price_source_metadata(
            external_rate.get("result", {}),
            fallback_source=f"config_default_labour_rate:{op}",
            applied=applied_hourly_rate is not None,
            applied_basis=external_rate.get("applied_basis") if applied_hourly_rate is not None else "config_fallback_GBP_per_hour",
        ) | {"hourly_rate_gbp": rate}

    return {
        "costs_gbp": {op: round(v, 2) for op, v in breakdown.items()},
        "run_costs_gbp": run_costs,
        "setup_amortised_gbp": setup_amortised,
        "batch_hours": batch_hours,
        "total_labour_cost_gbp": round(sum(breakdown.values()), 2),
        "rate_sources": rate_sources,
        "missing_rate_operations": missing_rate_operations,
        "job_quantity_used": qty,
        "workbook_formula": "M = run_cost_per_unit + (rate/60 × setup_mins) / job_qty",
    }


def _sanitise_part_quantity(part: Dict[str, Any]) -> int:
    """
    Guard against the PDF parser reading drawing-number prefixes as quantities.
    e.g. part_number="8172-01_WELDMENT" -> quantity=8172 (WRONG, should be 1).

    Rules:
      1. If quantity matches the leading numeric block of the part number -> reset to 1.
      2. If quantity > MAX_PART_QTY_PER_UNIT (default 50) -> reset to 1.
      Both cases add a review_flag warning to the part.
    """
    raw_qty = _safe_int(part.get("quantity")) or 1
    if raw_qty <= 1:
        return 1

    _MAX = int(getattr(config, "MAX_PART_QTY_PER_UNIT", 50))
    pn = str(part.get("part_number") or "").replace(" ", "")

    _m = re.match(r"^(\d+)", pn)
    if _m and int(_m.group(1)) == raw_qty:
        part.setdefault("review_flags", []).append({
            "severity": "warning",
            "flag": "quantity_from_part_number",
            "detail": f"qty {raw_qty} matched leading digits of part_number '{pn}' — reset to 1",
        })
        return 1

    if raw_qty > _MAX:
        part.setdefault("review_flags", []).append({
            "severity": "warning",
            "flag": "quantity_capped",
            "detail": f"qty {raw_qty} > MAX_PART_QTY_PER_UNIT ({_MAX}) — reset to 1",
        })
        return 1

    return raw_qty


def estimate_part(part: Dict[str, Any], job_quantity: Optional[int] = None) -> Dict[str, Any]:
    debug = os.getenv("SCAN_DEBUG", "").lower() in {"1", "true", "yes"}
    quantity = _sanitise_part_quantity(part)
    # Sanitisation of the part's OWN quantity (None/0/negative -> 1), not a new observation,
    # so the source that supplied it stands. Writing it through the resolver would re-stamp a
    # model-supplied quantity as if the estimator had measured it.
    part["quantity"] = quantity   # precedence: direct-write ok — sanitises the part's own value

    # Commercial placeholders (PACKAGING, DELIVERY) are NOT parts to be estimated — they are
    # always-present reminder lines whose real cost is order-specific and lives in the enquiry,
    # not the drawing. They must pass through UNPRICED (£0, estimator-to-price); running them
    # through material/labour/PricingService would assign a spurious handling/web-AI cost and
    # defeat the whole point. Return the stub's £0 intact.
    if part.get("_commercial_placeholder") or str(part.get("source") or "") == "commercial_placeholder":
        part["material_estimate"] = {"unit_material_cost_gbp": 0.0, "cost_per_part_gbp": 0.0,
                                     "extended_material_cost_gbp": 0.0, "cost_method": "commercial_placeholder_unpriced"}
        part["labour_estimate"] = {"unit_labour_cost_gbp": 0.0, "extended_labour_cost_gbp": 0.0}
        part["unit_cost_gbp"] = 0.0
        part["unit_total_cost_gbp"] = 0.0
        part["extended_total_cost_gbp"] = 0.0
        return part

    # A bought-in line that already carries a price from the deterministic recogniser or
    # the LLM note-scan must KEEP that price — those layers matched it to a genuine SDI
    # historical/catalogue line (e.g. Foam Tape -> "Foam Tape 890x10x1.5mm" @ £0.28).
    # Re-deriving it via the material+labour path produced absurd figures (a £132 foam
    # tape) because these stubs have no real geometry to cost. Respect the upstream price.
    _preset_src = str(part.get("source") or "")
    _preset_unit = part.get("unit_cost_gbp")
    # SDI BOM-code stubs (FIXING/VINYL priced from UDEF, or flagged unpriced) must also keep
    # their upstream state — a genuine catalogue price, or an honest "estimator to price".
    if _preset_src == "sdi_bom_code_unpriced":
        # Recognised but unpriced — pass through £0/None, flagged, NOT re-costed by geometry.
        part["material_estimate"] = {"unit_material_cost_gbp": None, "cost_per_part_gbp": None,
                                     "extended_material_cost_gbp": None,
                                     "cost_method": "sdi_bom_code_estimator_to_price"}
        part["labour_estimate"] = {"unit_labour_cost_gbp": 0.0, "extended_labour_cost_gbp": 0.0}
        part["unit_total_cost_gbp"] = None
        part["extended_total_cost_gbp"] = None
        part["costing_basis"] = "sdi_bom_code_estimator_to_price"
        return part
    if (
        (_preset_src in ("prose_recogniser_layer2", "llm_note_scan", "sdi_bom_code_udef_priced")
         or part.get("_layer2_recognised") or part.get("_note_scan"))
        and _preset_unit is not None
    ):
        _bi_unit = _round_money(float(_preset_unit))
        _bi_ext = _round_money(float(_preset_unit) * quantity)
        part["material_estimate"] = {
            "unit_material_cost_gbp": _bi_unit, "cost_per_part_gbp": _bi_unit,
            "extended_material_cost_gbp": _bi_ext,
            "cost_method": f"bought_in_recognised_price:{_preset_src or 'recogniser'}",
        }
        part["labour_estimate"] = {"unit_labour_cost_gbp": 0.0, "extended_labour_cost_gbp": 0.0}
        part["unit_total_cost_gbp"] = _bi_unit
        part["extended_total_cost_gbp"] = _bi_ext
        part["unit_cost_gbp"] = _bi_unit
        part["costing_basis"] = f"bought_in_recognised_price:{_preset_src or 'recogniser'}"
        return part

    # Machine SETUP amortises over the ORDER (job) quantity, not the per-part
    # qty-per-unit. `quantity` above is qty-per-unit (e.g. 1 peg per bay);
    # `order_qty` is how many units the customer asked us to price. This matches
    # the manual estimate, which spreads setup over the job qty (e.g. 100).
    # Source order: explicit arg -> qty the scan stamped on the part/summary ->
    # config default. Costing setup at qty 1 was the root cause of every part
    # reading 2-10x over the manual.
    order_qty = job_quantity if job_quantity else part.get("assumed_job_quantity")
    order_qty = max(1, int(order_qty or getattr(config, "DEFAULT_JOB_QUANTITY", 180)))
    part["assumed_job_quantity"] = order_qty
    part_number = part.get("part_number") or part.get("item_number") or "unknown_part"
    if debug:
        print(f"[DEBUG] estimate_part start {part_number}")
    # ── GA / overall-unit parent detected by number pattern ────────────────────────
    # A part numbered <job>-00-<xxx> is the top-level unit/GA line (the whole product),
    # not a fabricated leaf. Left as a leaf it double-counts: its stated whole-unit weight
    # becomes a huge material line (Cocktails 12301-00-101 = £389) and it takes a phantom
    # fabrication route. Its children are costed individually, so mark it an assembly parent
    # BEFORE material costing -> material is suppressed (carried by children) and the fab/
    # joinery route is gated off. Guarded on 'no flat pattern of its own', since a genuine
    # fabricated leaf would carry DXF/blank geometry. General, not a Cocktails patch.
    _pn_ga = str(part.get("part_number") or "").upper().strip()
    if (re.match(r"^\d+-0+-\d+$", _pn_ga) and not part.get("flat_pattern_detected")
            and not part.get("is_assembly_parent")):
        part["is_assembly_parent"] = True
        part.setdefault("review_flags", []).append(
            "top-level unit/GA line (…-00-…) treated as assembly parent — material carried "
            "by children, fabrication route suppressed; estimator to verify")
    material = estimate_material(part)
    if debug:
        print(f"[DEBUG] estimate_part material done {part_number}")
    # FIX 1: feed powder LABOUR area from the SAME reliable blank the powder MATERIAL
    # consumable used, so labour can't diverge from material. None => consumable was
    # suppressed (no reliable blank) => powder labour floors instead of inventing an
    # inflated drawing-extent area (the 3886-02 £17.82 phantom vs its mirror's £1.53).
    try:
        part["_powder_reliable_coated_m2"] = ((material or {}).get("powder_consumable") or {}).get("coated_area_m2")
    except Exception:
        part["_powder_reliable_coated_m2"] = None
    process = estimate_process_times(part, quantity=quantity)
    if debug:
        print(f"[DEBUG] estimate_part process done {part_number}")
    # Assembly/sub-assembly parent: no flat DXF of its own, so it performs no
    # cutting/folding — those are carried by its costed children. Strip the
    # geometry-derived fab ops so it can't bill a phantom laser/fold from the
    # assembly PDF cut-length (TANK 04 read 12.1h laser = £8.26). Genuine assembly
    # ops (weld/glue/assemble/handle/powder) are left intact. CNC is intentionally
    # NOT stripped here — that is a weldment-routing concern handled separately.
    if part.get("is_assembly_parent"):
        _PARENT_FAB_STRIP = {
            "laser_cutting", "laser_cutting_acrylic", "folding", "punch",
            "hole_machining", "guillotine", "plasma_cutting", "waterjet",
            "drilling", "tapping", "countersinking",
        }
        # EVERY TIME MAP, not two of five. estimate_process_times returns setup_times_min,
        # run_times_min_per_unit, unit_times_min and times_min — the last two derived from
        # the first two and built BEFORE this strip runs. Popping only the first two left a
        # part record that says "does not fold" in one map and "folds" in another.
        #
        # That inconsistency is what produced missing_labour_rate:folding on 12120's 101 and
        # 103. The risk flag is computed from times_min (estimator.py:3224) as
        # requested_ops - costed_ops: folding survived in times_min, was correctly NOT costed
        # because the strip had removed it from the maps costing reads, and the subtraction
        # reported it as an operation with no configured rate. It reads as under-costing —
        # work identified and not priced — when the truth is the opposite: the fold belongs
        # to the CHILDREN, they carry it, and suppressing it on the parent is correct. The
        # flag sent an estimator looking for a missing rate that was never missing.
        for _bucket in ("run_times_min_per_unit", "setup_times_min",
                        "unit_times_min", "times_min"):
            _m = process.get(_bucket)
            if isinstance(_m, dict):
                for _op in [o for o in _m if o in _PARENT_FAB_STRIP]:
                    _m.pop(_op, None)
        # The totals are sums of those maps and go stale the moment anything is removed.
        try:
            process["unit_time_min"] = round(
                sum((process.get("unit_times_min") or {}).values()), 2)
            process["total_time_min"] = round(
                sum((process.get("times_min") or {}).values()), 2)
        except Exception:
            pass
        process["assembly_parent_fab_suppressed"] = True

    # Acrylic route, costed the SDI way (canonical model from the M18 workbook). The laser
    # op is recomputed to the SDI acrylic model — load/unload (per sheet ÷ parts nested) +
    # profile cut (perimeter ÷ speed) + hole cutting — then estimate_labour_costs applies the
    # LASA rate. Linebend scales per bend. Glue + flame-polish are ONE op per bonded/display
    # assembly, attached to the FORMED (bent) body panel so a multi-panel tank isn't charged
    # per panel. All time-drivers in config.ACRYLIC_OP_DRIVERS.
    _mat_acr2 = str(part.get("normalized_material") or "").upper().replace("_", " ")
    if _mat_acr2 in {"ACRYLIC", "HIGH IMPACT ACRYLIC", "PERSPEX", "PMMA", "POLYCARBONATE"} and not part.get("is_assembly_parent"):
        _drv = getattr(config, "ACRYLIC_OP_DRIVERS", {}) or {}
        _rt = process.setdefault("run_times_min_per_unit", {})
        _st = process.setdefault("setup_times_min", {})
        _ng = part.get("normalized_geometry") or {}
        _geom = part.get("dxf_raw_geometry") or {}
        _L = _safe_float(part.get("overall_length_mm")) or _safe_float(_ng.get("blank_length_mm")) or 0.0
        _W = _safe_float(part.get("overall_width_mm")) or _safe_float(_ng.get("blank_width_mm")) or 0.0
        _holes = _safe_int(part.get("hole_count")) or _safe_int(_geom.get("estimated_hole_count")) or 0
        _bends = _safe_int(part.get("bend_count_dxf")) or _safe_int(_geom.get("estimated_bend_line_count")) or 0
        if _L > 0 and _W > 0:
            _spd = float(_drv.get("laser_cut_mm_per_sec", 50.0)) or 50.0
            _pps = (select_sheet_size(part.get("normalized_material"), _L, _W) or {}).get("parts_per_sheet") or 1
            _pps = max(1, int(_pps))
            _laser_sec = (
                float(_drv.get("laser_load_unload_sec_per_sheet", 300.0)) / _pps
                + (2.0 * (_L + _W)) / _spd
                + _holes * float(_drv.get("laser_sec_per_hole", 3.0))
            )
            _rt["laser_cutting"] = round(_laser_sec / 60.0, 4)   # LASA rate applied by labour-coster
            _st.setdefault("laser_cutting", float(_drv.get("laser_setup_min", 5.0)))
        # acrylic_route_v2 (2026-07-15): route matches the estimator's acrylic sheets.
        # An acrylic part is SIMPLER than metal. Every acrylic part gets Diamond Polish
        # (the finish — acrylic is NOT powder coated) and Peel (protective film). Linebend
        # scales per bend. GLUE + flame are added ONLY for a genuinely BONDED assembly
        # (multi-panel display / tank), never for a single formed part. LASER is added only
        # when there is an actual laser-cut signal; a lone formed part from sheet is
        # guillotine/router + line-bent, not lasered.

        # Is this a bonded multi-panel assembly (glue + flame apply), or a single formed part?
        _bonded = bool(part.get("is_bonded_assembly")) or bool(part.get("acrylic_bonded"))
        _kids = part.get("child_parts") or part.get("children") or []
        if not _bonded and isinstance(_kids, (list, tuple)) and len(_kids) >= 2:
            _bonded = True   # multiple bonded panels under this part

        # Is the part actually laser-cut? Only then does laser apply. Absent a signal, a
        # single formed acrylic part is not lasered (matches the estimator).
        _laser_signal = bool(part.get("is_laser_cut")) or bool(part.get("laser_cut_acrylic"))
        _cut_method = str(part.get("cut_method") or part.get("cutting_method") or "").lower()
        if "laser" in _cut_method:
            _laser_signal = True
        if _cut_method in ("guillotine", "router", "rout", "saw", "cnc_rout"):
            _laser_signal = False
        if not (_laser_signal or _bonded):
            # not lasered: drop the laser op the block added above
            _rt.pop("laser_cutting", None)
            _st.pop("laser_cutting", None)

        # FINISH: Diamond Polish for every acrylic part; powder is invalid on acrylic.
        _rt["diamond_polish"] = round(_rt.get("diamond_polish", 0.0)
                                      + float(_drv.get("diamond_polish_min_per_part", 0.5)), 4)
        _st.setdefault("diamond_polish", float(_drv.get("diamond_polish_setup_min", 10.0)))
        # Peel the protective film — present on every acrylic part.
        _rt["manual_labour_acrylic"] = round(_rt.get("manual_labour_acrylic", 0.0)
                                             + float(_drv.get("peel_min_per_part", 0.5)), 4)
        _st.setdefault("manual_labour_acrylic", float(_drv.get("peel_setup_min", 15.0)))
        # Acrylic is never powder coated — strip any powder op the finish-resolver added.
        for _pw in ("powder_coating",):
            _rt.pop(_pw, None)
            _st.pop(_pw, None)
        part["acrylic_no_powder"] = True   # signal downstream: suppress the powder BOM line

        if _bends > 0:
            _rt["linebend"] = round(_rt.get("linebend", 0.0) + float(_drv.get("min_per_linebend", 1.0)) * _bends, 4)
            _st.setdefault("linebend", float(_drv.get("linebend_setup_min", 30.0)))

        if _bonded:
            # bonded multi-panel assembly: glue joints + flame-polish, ONE op per assembly
            _rt["glue"] = round(_rt.get("glue", 0.0) + float(_drv.get("glue_min_per_assembly", 2.4)), 4)
            _st.setdefault("glue", float(_drv.get("glue_setup_min", 30.0)))
            _rt["manual_labour_acrylic"] = round(_rt.get("manual_labour_acrylic", 0.0) + float(_drv.get("flame_min_per_assembly", 1.2)), 4)
            _st.setdefault("manual_labour_acrylic", float(_drv.get("flame_setup_min", 15.0)))

        process["acrylic_ops_canonical"] = True
        process["acrylic_route_v2"] = True
        process["acrylic_bonded_detected"] = _bonded
        process["acrylic_laser_applied"] = bool(_laser_signal or _bonded)
    labour = estimate_labour_costs(process, job_quantity=order_qty, material=part.get("normalized_material"))
    if debug:
        print(f"[DEBUG] estimate_part labour done {part_number}")
    system_cost = _resolve_part_system_cost(part)
    if debug:
        print(f"[DEBUG] estimate_part system_cost done {part_number}")
    system_unit_cost = _safe_float(system_cost.get("applied_unit_cost"))
    system_cost_result = system_cost.get("result", {})
    matched_part_code = system_cost.get("matched_part_code")
    material_extended = material.get("extended_material_cost_gbp")
    extended_material_cost = _safe_float(material_extended) or 0.0
    total_labour_cost = labour.get("total_labour_cost_gbp") or 0.0

    # Default laser_cutting for any fabricated sheet metal part that has blank
    # dimensions but no cutting op detected — all sheet parts start on the laser.
    _mat_upper = str(part.get("normalized_material") or "").upper()
    _is_sheet_metal = _mat_upper in {
        "MILD_STEEL", "MILD STEEL", "STAINLESS_STEEL", "STAINLESS STEEL",
        "ALUMINIUM", "ALUMINUM", "ZINTEC",
    }
    _has_blank = bool(
        _safe_float(part.get("blank_length_mm")) or
        _safe_float(part.get("overall_length_mm")) or
        _safe_float(part.get("normalized_thickness_mm"))
    )
    _existing_ops = list(_part_ops(part) or [])
    _cutting_ops = {"laser_cutting", "guillotine", "plasma_cutting", "waterjet"}
    if _is_sheet_metal and _has_blank and not any(op in _cutting_ops for op in _existing_ops):
        part.setdefault("textual_operations", [])
        if "laser_cutting" not in part["textual_operations"]:
            part["textual_operations"] = ["laser_cutting"] + part["textual_operations"]

    op_set = {str(op).strip().lower() for op in _part_ops(part) if str(op).strip()}
    no_ops_except_handling = op_set <= {"handling"}
    desc_blob = " ".join(
        [
            str(part.get("description") or ""),
            ";".join(part.get("process_notes") or []),
            ";".join(_part_ops(part) or []),
        ]
    ).upper()
    # BOUGHT_IN normalised material means customer supplies it — SDI cost = £0
    if (part.get("normalized_material") or "").upper() in {"BOUGHT_IN", "PAPER", "PRINTED_PAPER"}:
        return {
            "part_number": part.get("part_number"),
            "description": part.get("description"),
            "quantity": quantity,
            "unit_total_cost_gbp": 0.0,
            "extended_total_cost_gbp": 0.0,
            "costing_basis": "customer_supplied",
            "material_estimate": {"cost_per_part_gbp": 0.0, "extended_material_cost_gbp": 0.0},
            "labour_estimate": {"total_labour_cost_gbp": 0.0},
            "process_estimate": {"operations": []},
            "risk_flags": ["customer_supplied_zero_cost"],
        }

    bought_in_keywords = (
        "BOUGHT IN",
        "BOUGHT-IN",
        "PURCHASED",
        "OFF THE SHELF",
        "CATALOGUE",
        "CATALOG",
        "HARDWARE",
        "CASTOR",
        "CASTER",
        "TENTE",
        "STEM",
        "BUSH",
        "FIXING",
        "SCREW",
        "WOOD SCREW",
        "WOODSCREW",
        "KNURLED",
        "UPC STICKER",
        "STICKER",
        "VINYL",
        "PALLET",
        "LENS COVER",
        "UPC",
        "HINGE",
        "HAFELE",
        "FINGER PULL",
        "HANDLE",
        "DOWEL",
        "T-NUT",
        "PEM STUD",
        "THREADED INSERT",
        "WOODEN DOWEL",
        "MOUNTING PLATE",
    )
    bought_in_candidate = (no_ops_except_handling and not part.get("flat_pattern_detected")) or any(
        k in desc_blob for k in bought_in_keywords
    )

    # GUARD 1 — A part the inference engine is provisionally costing is an SDI
    # FABRICATED part, not a catalogue buy. Routing it through the system-cost
    # (catalogue) match produces wild fuzzy-match prices (e.g. "BRACKET" -> £13k).
    if part.get("geometry_inferred"):
        bought_in_candidate = False

    # A special finishing item (tiles/mosaic/graphic/vinyl, -X suffix) is bought in, not
    # fabricated — even when the engine gave it provisional geometry. Price it via the
    # bought-in path (UDEF match, or left flagged/unpriced if nothing matches). Overrides
    # GUARD 1; the plausibility cap (GUARD 2) below still applies.
    if part.get("special_finish_item"):
        bought_in_candidate = True

    # GUARD 2 — Plausibility cap on the matched system cost. A genuine bought-in
    # fitting (castor, hinge, screw, Hafele part) is cheap. A four/five-figure hit
    # is a bad fuzzy match (catalogue assembly price, per-tonne value, or wrong code)
    # OR a genuine high-value buy that MUST get a human look — either way it is never
    # safe to apply silently to an auto-detected bought-in line. Reject + flag.
    if bought_in_candidate and system_unit_cost is not None:
        _max_plausible = float(getattr(config, "BOUGHT_IN_MAX_PLAUSIBLE_GBP", 750.0) or 750.0)
        if float(system_unit_cost) > _max_plausible:
            part.setdefault("risk_flags", []).append(
                f"implausible_system_cost_rejected_price_manually:GBP{float(system_unit_cost):.0f}"
            )
            bought_in_candidate = False
            system_unit_cost = None

    # A bought-in line that already carries a price from the deterministic recogniser or
    # the LLM note-scan must KEEP that price — those layers matched it to a genuine SDI
    # historical/catalogue line (e.g. Foam Tape -> "Foam Tape 890x10x1.5mm" @ £0.28). Re-
    # deriving it via the material+labour path below produced absurd figures (a £132 foam-
    # tape) because these stubs have no real geometry to cost. Respect the upstream price.
    if bought_in_candidate and system_unit_cost is not None:
        _fitting_min = float(getattr(config, "BOUGHT_IN_FITTING_MIN_PER_PART", 2.0) or 2.0)
        _manm_rate = float((HOURLY_RATES_GBP or {}).get("handling", 31.18))
        _fitting_cost = (_fitting_min / 60.0) * _manm_rate
        unit_total_raw = float(system_unit_cost) + _fitting_cost
        extended_total_raw = unit_total_raw * quantity
        costing_basis = "system_cost_per_part"
    else:
        # Material Price Break LOOKUP — workbook col J formula (rows 11-25):
        # J = LOOKUP($D$6, 'Material Price Break'!$D$4:$N$4, price_row)
        # Replicates per-line quantity-adjusted pricing from the 11-band break table.
        # When a filled Material Price Break sheet is scanned, wb_line_prices overrides the multiplier.
        qty_multiplier = _quantity_break_multiplier(quantity)
        part_number_key = str(part.get("part_number") or "").strip().upper()
        wb_line_prices: Dict[str, float] = {}  # populated from workbook scan when available
        if part_number_key in wb_line_prices:
            wb_line_cost = float(wb_line_prices[part_number_key])
            extended_total_raw = wb_line_cost * quantity
            unit_total_raw = wb_line_cost
            costing_basis = "material_price_break_lookup_workbook"
        else:
            extended_total_raw = float((extended_material_cost + total_labour_cost) * qty_multiplier)
            unit_total_raw = (extended_total_raw / quantity) if quantity else extended_total_raw
            costing_basis = f"computed_material_plus_labour_qty_break_x{qty_multiplier:.3f}"
    unit_total = _round_money(unit_total_raw)
    extended_total = _round_money(extended_total_raw)
    markups = (WORKBOOK_EQUIVALENT_PRICING or {}).get("sell_markup_options_pct") or {"low": 10.0, "standard": 20.0, "premium": 35.0}
    margin_options: List[Dict[str, Any]] = []
    if not bool(getattr(config, "OUTPUT_MANUFACTURING_COST_ONLY", False)):
        for name, pct in markups.items():
            factor = 1.0 + (float(pct) / 100.0)
            margin_options.append(
                {
                    "name": str(name),
                    "markup_pct": float(pct),
                    "unit_sell_price_gbp": round(unit_total * factor, 2),
                    "extended_sell_price_gbp": round(extended_total * factor, 2),
                }
            )

    # Surface missing price/rate conditions for human review.
    risk_flags = list(part.get("risk_flags", []))
    ps_mat = material.get("price_source") or {}
    if str(ps_mat.get("source_type") or "").lower() == "web_ai_fallback":
        risk_flags.append("web_ai_indicative_material_price")
    sc_sel = _extract_selected_price(system_cost_result) or {}
    ev_sc = sc_sel.get("evidence") or {}
    if isinstance(ev_sc, dict) and ev_sc.get("pricing_mode") == "web_ai_llm_estimate":
        risk_flags.append("web_ai_indicative_system_cost")
    section_blob = " ".join(
        [
            str(material.get("material") or ""),
            str(part.get("description") or ""),
            str(part.get("normalized_material") or ""),
        ]
    ).upper()
    if any(
        token in section_blob
        for token in (
            "TUBE",
            "RHS",
            "SHS",
            "BOX SECTION",
            "WIRE MESH",
            "WELDED WIRE",
            "LINEAR M",
            "KG/M",
        )
    ):
        risk_flags.append("section_or_wire_stock_pricing_review")

    if material.get("extended_material_cost_gbp") is None:
        if not material.get("material"):
            risk_flags.append("missing_material_spec")
        elif material.get("thickness_mm") is None:
            risk_flags.append("missing_material_thickness")
        else:
            risk_flags.append("missing_material_price")

    requested_ops = set((process.get("times_min") or {}).keys())
    costed_ops = set((labour.get("costs_gbp") or {}).keys())
    missing_ops = requested_ops - costed_ops
    for op in sorted(missing_ops):
        risk_flags.append(f"missing_labour_rate:{op}")

    return {
        "part_number": part.get("part_number"),
        "description": part.get("description"),
        "quantity": quantity,
        # SDI Intelligence — surface material/thickness/blank dims at the top
        # level so xlsx_output Sheet Steel / Other Sheet Material sections can
        # find them (they read pe.get("normalized_material") directly).
        "normalized_material": part.get("normalized_material") or material.get("material"),
        "normalized_thickness_mm": _safe_thickness_mm(part) or material.get("thickness_mm"),
        "material_estimate": material,
        "process_estimate": process,
        "labour_estimate": labour,
        "normalized_geometry": part.get("normalized_geometry", {}),
        "cost_breakdown": {
            "material": {
                "unit_material_mass_kg": material.get("unit_material_mass_kg"),
                "unit_material_cost_gbp": material.get("unit_material_cost_gbp"),
                "extended_sheet_material_cost_gbp": material.get("extended_sheet_material_cost_gbp"),
                "powder_consumable": material.get("powder_consumable"),
                "extended_material_cost_gbp": material.get("extended_material_cost_gbp"),
                "supplier_source": material.get("price_source", {}).get("supplier_source"),
                "price_date": material.get("price_source", {}).get("price_date"),
            },
            "labour": {
                "unit_time_min": process.get("unit_time_min"),
                "total_time_min": process.get("total_time_min"),
                "costs_gbp": labour.get("costs_gbp", {}),
                "total_labour_cost_gbp": labour.get("total_labour_cost_gbp"),
                "rate_sources": labour.get("rate_sources", {}),
            },
            "system_cost": {
                "unit_cost_gbp": round(system_unit_cost, 2) if system_unit_cost is not None else None,
                "extended_cost_gbp": round((system_unit_cost or 0.0) * quantity, 2) if system_unit_cost is not None else None,
                "matched_part_code": matched_part_code,
                "part_description": part.get("description"),
                "source": _build_price_source_metadata(
                    system_cost_result,
                    fallback_source="system_cost_not_found",
                    applied=system_unit_cost is not None,
                    applied_basis="GBP_each" if system_unit_cost is not None else None,
                ),
                "applied_to_total": bought_in_candidate and system_unit_cost is not None,
            },
            "overhead": {
                "unit_overhead_cost_gbp": None,
                "extended_overhead_cost_gbp": None,
            },
            "unit_total_cost_gbp": unit_total,
            "extended_total_cost_gbp": extended_total,
            "costing_basis": costing_basis,
            "margin_options": margin_options,
            "assumptions": {
                "material_price_source": material.get("price_source", {}),
                "labour_model": "external_or_config_fallback",
                "geometry_basis": "normalized_geometry",
                "part_confidence_overall": _part_confidence_overall(part),
                "part_geometry_reliability": _part_geometry_reliability(part),
                "part_provenance_source": (part.get("provenance") or {}).get("source"),
            },
        },
        "alternative_processes": [],
        "unit_total_cost_gbp": unit_total,
        "extended_total_cost_gbp": extended_total,
        "unit_total_cost_raw_gbp": unit_total_raw,
        "extended_total_cost_raw_gbp": extended_total_raw,
        "notes": [
            "Geometry-derived timings are heuristic until calibrated against known jobs.",
            "Primary dimensions are inferred from extracted values; verify against the drawing before quoting.",
        ],
        "part_provenance": part.get("provenance", {}),
        "part_confidence": part.get("confidence", {}),
        "risk_flags": risk_flags,
        # Stamped during process costing — Basis & Provisos reads these from the part record.
        "punch_calibration": part.get("punch_calibration"),
        "section_costing_adjustment": part.get("section_costing_adjustment"),
        "review_flags": part.get("review_flags") or [],
    }


def _build_workbook_equivalent_pricing(part_estimates: List[Dict[str, Any]], material_total: float, labour_total: float) -> Dict[str, Any]:
    cfg = WORKBOOK_EQUIVALENT_PRICING or {}
    # Exact workbook M105: =((M59+M103)/(1-M107))/0.92
    # overhead_absorption_factor = 0.92 hard-coded in the workbook cell (~8.7% overhead uplift).
    # M107 = rebate fraction (TTI default 0.066). M109 = sell margin (blank=0, estimator fills in).
    overhead_factor = float(cfg.get("overhead_absorption_factor", 0.92))
    m107 = float(cfg.get("default_m107", 0.066))
    m109 = float(cfg.get("default_m109", 0.0))
    m59 = round(material_total, 4)
    m103 = round(labour_total, 4)
    denominator_m107 = max(0.0001, 1.0 - m107)
    denominator_m109 = max(0.0001, 1.0 - m109)
    m105 = round(((m59 + m103) / denominator_m107) / overhead_factor, 4)
    l111 = round(m105 / denominator_m109, 4)
    labour_hours_total = round(
        sum((_safe_float(item.get("process_estimate", {}).get("total_time_min")) or 0.0) / 60.0 for item in part_estimates),
        4,
    )
    manufacturing_only = bool(getattr(config, "OUTPUT_MANUFACTURING_COST_ONLY", False))
    result: Dict[str, Any] = {
        "m59_material_subtotal_gbp": m59,
        "m103_labour_subtotal_gbp": m103,
        "m107_rebate_fraction": m107,
        "m109_sell_margin_fraction": m109,
        "overhead_absorption_factor": overhead_factor,
        "m105_total_unit_cost_gbp": m105,
        "l105_total_unit_cost_gbp": m105,
        "l111_sell_price_gbp": l111,
        "labour_hours_total": labour_hours_total,
        "formula_strings": {
            "m105": "=((M59+M103)/(1-M107))/overhead_absorption_factor",
            "l111": "=M105/(1-M109)",
            "note": "overhead_absorption_factor=0.92 hard-coded in workbook. M107=rebate (TTI 0.066). M109=sell margin (estimator fills in).",
        },
        "assumptions": {
            "overhead_absorption_factor": overhead_factor,
            "rebate_fraction": m107,
            "sell_margin_fraction": m109,
            "source": "workbook_equivalent_pricing",
        },
    }
    if manufacturing_only:
        result["l111_sell_price_gbp"] = None
        result["assumptions"]["sell_price_suppressed"] = True
        result["assumptions"]["sell_price_reason"] = "OUTPUT_MANUFACTURING_COST_ONLY"
    return result


def _page_text_for_bought_in_scan(page: Dict[str, Any]) -> str:
    """Join all likely text fields from a scan summary page (structure varies by pipeline stage)."""
    chunks: List[str] = []
    rt = page.get("region_text") or {}
    if isinstance(rt, dict):
        for v in rt.values():
            if v:
                chunks.append(str(v))
    for key in ("pdfplumber_text", "normalized_text", "pypdf_text", "text", "text_preview"):
        v = page.get(key)
        if v:
            chunks.append(str(v))
    ps = page.get("pattern_summary") or {}
    if isinstance(ps, dict):
        raw = ps.get("raw_text")
        if raw:
            chunks.append(str(raw))
    return " ".join(chunks)


def _bought_in_part_stub(part_number: str, description: str, quantity: Any) -> Dict[str, Any]:
    """Minimal shape compatible with document_builder + estimate_part."""
    return {
        "part_number": part_number,
        "description": description,
        "quantity": quantity,
        "pages": [],
        "page_roles": ["bought_in"],
        "materials": [],
        "surface_finishes": [],
        "colours": [],
        "thicknesses_mm": [],
        "weights": [],
        "textual_operations": ["handling"],
        "inferred_operations": [],
        "flat_pattern_detected": False,
        "assembly_candidate": False,
        "process_notes": [],
        "review_flags": [],
        "confidence": {},
        "geometry_rollup": {
            "vector_path_count": 0,
            "line_segments": 0,
            "rectangles": 0,
            "curves": 0,
            "filled_paths": 0,
            "approx_total_line_length_points": 0.0,
            "approx_total_curve_length_points": 0.0,
            "estimated_cut_length_mm": 0.0,
            "estimated_hole_count": 0,
            "estimated_circle_like_features": 0,
            "estimated_slot_like_features": 0,
            "estimated_bend_line_count": 0,
            "estimated_pierce_count": 0,
            "contour_complexity": 0,
            "closed_path_count": 0,
            "long_axis_aligned_lines": 0,
            "dashed_long_axis_lines": 0,
            "confidence": {
                "geometry_reliability": 0.0,
                "estimated_cut_length_mm": 0.0,
                "estimated_hole_count": 0.0,
                "estimated_slot_like_features": 0.0,
                "estimated_bend_line_count": 0.0,
            },
        },
        "hole_sizes_mm": [],
        "angles_deg": [],
        "slot_detected": False,
        "slot_sizes_mm": [],
        "mirrored_detected": False,
        "manufacturing_features": {},
        "manufacturing_interpretation": {"routing": [{"operation": "handling", "phase": "logistics", "driver": "part_count", "source": "default"}]},
        "risk_flags": [],
        "normalized_material": None,
        "normalized_finish": None,
        "normalized_thickness_mm": None,
        "_bought_in_from_text_scan": True,
    }


def _lookup_udef_exact_code(code: str) -> Optional[Dict[str, Any]]:
    """Look up a single SDI part code (e.g. FIXING125, VINYL76) in the UDEF catalogue by
    EXACT code match. Returns {description, unit_price_gbp, supplier} or None.

    Exact match only — NEVER LIKE. A loose LIKE '%FIXING2%' matches FIXING236, FIXING2538,
    FIXING2658 (a £15 hinge) etc., which would attach a wildly wrong price to a cable tie.
    Exact-code is the safe path: the code on the drawing IS the catalogue key.
    """
    try:
        import config as _cfg
        cn = _cfg.get_connection(timeout=20)
    except Exception:
        return None
    try:
        cur = cn.cursor()
        cur.execute(
            "SELECT TOP 1 [Part code],[Description],[System cost per],[Supplier name] "
            "FROM dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING "
            "WHERE [Part code] = ? AND [System cost per] > 0",
            code.strip().upper(),
        )
        row = cur.fetchone()
    except Exception:
        try:
            cn.close()
        except Exception:
            pass
        return None
    finally:
        try:
            cn.close()
        except Exception:
            pass
    if not row:
        return None
    return {
        "code": str(row[0] or "").strip(),
        "description": str(row[1] or "").strip(),
        "unit_price_gbp": float(row[2]) if row[2] is not None else None,
        "supplier": str(row[3] or "").strip() or None,
    }


# A real SDI code binds the digits TIGHTLY to the prefix: FIXING125 / FIXING 125 / FIXING-125.
# It must NOT match the prefix word followed by an unrelated dimension (e.g. "NO VINYL 535.2 EXT"
# on a drawing) — that produced false positives VINYL535/VINYL497 from page-9 dimension noise.
# Rules: at most ONE space/hyphen between prefix and digits; digits NOT followed by a decimal
# point or a dimension/unit token (EXT, CRS, INT, MM, PITCH, THRU, DIA, R) which mark a measurement.
_SDI_BOUGHT_IN_CODE_RE = re.compile(
    r"\b(FIXING|VINYL|PRINT|SUBPLAS|POWDER)[ \-]?(\d{1,5})\b(?![.\d])"
    r"(?!\s*(?:EXT|CRS|INT|MM|PITCH|THRU|DIA|R\b|W\b|H\b|X\b))",
    re.IGNORECASE,
)

# A logo/vinyl callout in drawing prose, e.g. "MILWAUKEE LOGO WHITE 425 W X 190 H".
# Captures the W×H dimensions so we can match to a UDEF vinyl SKU by dimension (the only
# discriminator distinctive enough to price safely — a bare "vinyl" matches dozens of SKUs).
_VINYL_CALLOUT_RE = re.compile(
    r"(LOGO|VINYL|GRAPHIC)[^\n]{0,80}?(\d{2,4})\s*(?:W|WIDE|MM\s*W)?\s*[xX×]\s*(\d{2,4})\s*(?:H|HIGH|MM\s*H)?",
    re.IGNORECASE,
)


def _lookup_udef_vinyl_by_dimensions(w_mm: int, h_mm: int) -> Optional[Dict[str, Any]]:
    """Match a vinyl/logo callout to a UDEF vinyl SKU by its stated W×H dimensions.

    Prices ONLY when the dimensions resolve to exactly ONE priced vinyl SKU — dimensions are
    the safe discriminator (e.g. '425 x 190' uniquely identifies VINYL76). If 0 or >1 priced
    SKUs match, returns a 'flag' verdict (estimator to price) rather than guess among them.
    """
    try:
        import config as _cfg
        cn = _cfg.get_connection(timeout=20)
    except Exception:
        return None
    try:
        cur = cn.cursor()
        # Search both dimension orderings (425x190 / 190x425) within vinyl-ish rows.
        like_a = f"%{w_mm}%{h_mm}%"
        like_b = f"%{h_mm}%{w_mm}%"
        cur.execute(
            "SELECT [Part code],[Description],[System cost per],[Supplier name] "
            "FROM dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING "
            "WHERE [System cost per] > 0 "
            "AND ([Part code] LIKE 'VINYL%' OR [Description] LIKE '%VINYL%') "
            "AND ([Description] LIKE ? OR [Description] LIKE ?)",
            like_a, like_b,
        )
        rows = cur.fetchall()
    except Exception:
        try:
            cn.close()
        except Exception:
            pass
        return None
    finally:
        try:
            cn.close()
        except Exception:
            pass
    priced = [r for r in rows if r[2] is not None and float(r[2]) > 0]
    if len(priced) == 1:
        r = priced[0]
        return {"verdict": "priced", "code": str(r[0] or "").strip(),
                "description": str(r[1] or "").strip(),
                "unit_price_gbp": float(r[2]), "supplier": str(r[3] or "").strip() or None}
    # 0 or many -> ambiguous: recognise but do NOT price (honest flag, never guess among many).
    return {"verdict": "flag", "candidate_count": len(priced)}



# ---------------------------------------------------------------------------
# JOB-IDENTITY GUARD  (added after job 1310: a £105 phantom "Drill Stud Holder")
#
# The deterministic prose recogniser matches component head-words ("stud", "clip",
# "loom"...) against SDI quote history. On 1310 it read the PROJECT TITLE out of the
# title block — "DRILL STUD HOLDER" — matched it 1.0 against a historical quote line
# for that same finished product, and costed the job we are BUILDING as a part we BUY.
#
# The existing `_fab_descs` guard excludes fabricated PART descriptions (HOOK PLATE,
# STUD). It cannot catch this, because the assembly/product name is not a part.
#
# So: never recognise a bought-in whose description is made only of words that already
# name the job. "Drill Stud Holder" ⊂ {1310, DRILL, STUD, HOLDER, REV, C} -> dropped.
# A genuine purchased component is never named solely by the job's own title words.
# ---------------------------------------------------------------------------
_JOB_IDENT_STOPWORDS = {
    "REV", "REVISION", "DRAWING", "DRAWINGS", "ASSEMBLY", "GENERAL", "JSON", "PDF",
    "DXF", "AND", "THE", "FOR", "WITH", "OFF", "NEW", "OLD", "COPY", "FINAL",
}


def _job_identity_tokens(summary: Dict[str, Any]) -> set:
    """Words that name THIS job: job/file name, project title, drawing description."""
    import re as _re
    cands: List[str] = []
    for _k in ("job_name", "job", "source_file", "document_name", "file_name",
               "project_title", "drawing_title", "title", "description"):
        _v = summary.get(_k)
        if isinstance(_v, str) and _v.strip():
            cands.append(_v)
    _da = summary.get("document_analysis") or {}
    if isinstance(_da, dict):
        for _k in ("project_title", "drawing_title", "title", "job_title", "description"):
            _v = _da.get(_k)
            if isinstance(_v, str) and _v.strip():
                cands.append(_v)
    toks: set = set()
    for _c in cands:
        for _t in _re.findall(r"[A-Za-z]{3,}", _c.upper()):
            toks.add(_t)
    return toks - _JOB_IDENT_STOPWORDS


def _is_job_identity_desc(desc: Any, job_tokens: set) -> bool:
    """True when a candidate bought-in is named ONLY by the job's own title words."""
    import re as _re
    if not desc or not job_tokens:
        return False
    dt = set(_re.findall(r"[A-Za-z]{3,}", str(desc).upper())) - _JOB_IDENT_STOPWORDS
    if not dt:
        return False
    return dt.issubset(job_tokens)


def _recognise_vinyl_callouts(all_text: str, existing_pns: set,
                              existing_descs: set) -> List[Dict[str, Any]]:
    """Recognise logo/vinyl callouts in drawing prose and price by UNIQUE dimension match.

    Catches vinyl referenced by description (not code) — e.g. page-9 'MILWAUKEE LOGO WHITE
    425 W X 190 H' -> VINYL76 @ £0.85 (unique 425x190 match). Ambiguous callouts are added
    as flagged 'estimator to price' lines so the BOM line still appears without a guessed price.
    Generalises: any drawing's logo/vinyl callout with stated W×H is handled the same way.
    """
    found: List[Dict[str, Any]] = []
    seen_dims: set = set()
    for m in _VINYL_CALLOUT_RE.finditer(all_text):
        try:
            w = int(m.group(2)); h = int(m.group(3))
        except (TypeError, ValueError):
            continue
        if w <= 0 or h <= 0 or (w, h) in seen_dims:
            continue
        # Plausibility: vinyl panels are tens-to-hundreds of mm, not microns or metres.
        if not (10 <= w <= 3000 and 10 <= h <= 3000):
            continue
        seen_dims.add((w, h))
        verdict = _lookup_udef_vinyl_by_dimensions(w, h)
        if not verdict:
            continue
        if verdict.get("verdict") == "priced":
            code = verdict["code"]
            if code.strip().upper() in existing_pns:
                continue
            stub = _bought_in_part_stub(code, verdict["description"] or code, 1)
            stub["unit_cost_gbp"] = verdict["unit_price_gbp"]
            stub["unit_material_cost_gbp"] = verdict["unit_price_gbp"]
            stub["extended_total_cost_gbp"] = round(verdict["unit_price_gbp"], 2)
            stub["source"] = "sdi_bom_code_udef_priced"   # reuse the price-preserving guard
            stub["cost_source"] = "udef_catalogue_vinyl_dimension_match"
            stub["supplier"] = verdict.get("supplier")
            stub["price_verified"] = False
            stub.setdefault("review_flags", []).append(
                f"Vinyl matched by dimensions {w}x{h}mm -> {code} "
                f"(\u00a3{verdict['unit_price_gbp']:.2f}"
                + (f", {verdict['supplier']}" if verdict.get("supplier") else "") + ") — verify")
            found.append(stub)
        else:
            # Ambiguous (0 or many SKUs at these dims). These "GRAPHIC SIZE" callouts are typically
            # DISPLAY BOARD (printed foam/PVC substrate; artwork customer free-issue) — NOT vinyl.
            # Give a PROVISIONAL area-based price (documented placeholder, mirrors acrylic_sheet_
            # provisional) so the line carries a real number, flagged for the estimator to confirm
            # substrate + rate + in-house-vs-subcontract. Not a silent guess: the flag says PROVISIONAL.
            pn = f"VINYL-{w}X{h}"
            if pn in existing_pns:
                continue
            _DISPLAY_BOARD_PRICE_GBP_PER_M2 = 25.0   # provisional midpoint of £15–£40 printed board
            _area_m2 = (w / 1000.0) * (h / 1000.0)
            _prov_price = round(_area_m2 * _DISPLAY_BOARD_PRICE_GBP_PER_M2, 2)
            stub = _bought_in_part_stub(
                pn, f"DISPLAY BOARD {w}x{h}mm (PROVISIONAL @ £{_DISPLAY_BOARD_PRICE_GBP_PER_M2:.0f}/m²)", 1)
            stub["unit_cost_gbp"] = _prov_price
            stub["unit_material_cost_gbp"] = _prov_price
            stub["extended_total_cost_gbp"] = _prov_price
            stub["source"] = "sdi_bom_code_udef_priced"   # price-preserving guard (has a price now)
            stub["cost_source"] = "display_board_provisional_area"
            stub["price_verified"] = False
            stub.setdefault("review_flags", []).append(
                f"DISPLAY BOARD {w}x{h}mm ({_area_m2:.3f} m²) priced PROVISIONALLY at "
                f"£{_DISPLAY_BOARD_PRICE_GBP_PER_M2:.0f}/m² = £{_prov_price:.2f} — "
                f"VERIFY substrate + rate; confirm in-house print vs sub-contract; artwork is "
                f"customer free-issue per drawing")
            found.append(stub)
    return found


def _recognise_sdi_coded_bought_in(
    all_text: str,
    existing_pns: set,
    bom_rows: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Find any FIXING/VINYL/etc coded line in the BOM text, price it from UDEF by EXACT code.

    This replaces reliance on the hard-coded `patterns` list for SDI-coded fixings & vinyl:
    those rows (e.g. FIXING125 M8 GLIDE, VINYL76 BASE PLATE) appear in the BOM table on every
    job but were silently skipped unless their exact code was pre-listed. General recognition
    + exact-code UDEF pricing catches them genuinely and generalises to all drawings.

    Quantity is read GENUINELY from the structured bom_rows quantity column when a matching row
    exists (Option B — not text-scraped, which is unreliable on flattened tables). When no
    structured qty is available, qty defaults to 1 and the line is flagged for the estimator to
    confirm — never a guessed multiple.
    """
    # Build a code -> quantity map from the STRUCTURED bom rows (genuine column, not text).
    _qty_by_code: Dict[str, int] = {}
    for _row in (bom_rows or []):
        _blob = f"{_row.get('part_number','')} {_row.get('description','')}"
        _cm = _SDI_BOUGHT_IN_CODE_RE.search(_blob)
        if not _cm:
            continue
        _rcode = f"{_cm.group(1).upper()}{_cm.group(2)}"
        _q = _safe_int(_row.get("quantity"))
        if _q and _q > 0:
            # If the same code appears on multiple BOM rows (e.g. per-sub-assembly), sum them.
            _qty_by_code[_rcode] = _qty_by_code.get(_rcode, 0) + _q

    found: List[Dict[str, Any]] = []
    seen: set = set()
    for m in _SDI_BOUGHT_IN_CODE_RE.finditer(all_text):
        prefix = m.group(1).upper()
        digits = m.group(2)
        code = f"{prefix}{digits}"
        if code in seen or code in existing_pns:
            continue
        seen.add(code)
        _qty = _qty_by_code.get(code)            # genuine structured qty, or None
        _qty_known = _qty is not None and _qty > 0
        _use_qty = _qty if _qty_known else 1
        cat = _lookup_udef_exact_code(code)
        if cat and cat.get("unit_price_gbp") is not None:
            stub = _bought_in_part_stub(code, cat["description"] or code, _use_qty)
            # A record built on the line above, so this overwrites nothing — but a datum
            # with no source is invisible to arbitration, and a later pass would find an
            # unclaimed quantity it is free to replace.
            _apply_field(stub, "quantity", _use_qty, "bom_tree")
            stub["unit_cost_gbp"] = cat["unit_price_gbp"]
            stub["unit_material_cost_gbp"] = cat["unit_price_gbp"]
            stub["extended_total_cost_gbp"] = round(cat["unit_price_gbp"] * _use_qty, 2)
            stub["source"] = "sdi_bom_code_udef_priced"
            stub["cost_source"] = "udef_catalogue_exact_code"
            stub["supplier"] = cat.get("supplier")
            stub["price_verified"] = False
            _qnote = (f"qty {_use_qty} from BOM table" if _qty_known
                      else "qty defaulted to 1 (not in structured BOM) — estimator to confirm")

            # ── CONSUMABLES: never invent a quantity ─────────────────────────────────
            # For a DISCRETE item (rivet, junction box, light) "assume 1" is a defensible
            # default. For a CONSUMABLE sold by WEIGHT or VOLUME, "assume 1" means ONE
            # KILOGRAM — which is not a default, it is a fabricated number with a price on it.
            #
            # 7670: the drawing carries POWDER308 but no quantity. The engine priced 1kg at
            # £7.72 -> £8.03, to coat a wire frame with 0.023 m2 of surface. A kilo covers
            # ~6 m2. That is 300x more powder than the part can physically hold, and it became
            # the biggest line on a £6.74 job.
            #
            # Powder is ALSO costed by the workbook's own Powder Qty Calculator (AF82/AF83 ->
            # Total Material). A priced BOM line therefore risks DOUBLE-COUNTING on any job
            # with both sheet parts and a powder code in the drawing text. On 7670 that only
            # escaped because the calculator returns 0 for wire. Dropping the money from this
            # line closes that hazard too.
            #
            # Keep the ROW: the code and colour are real, drawing-derived and useful. Drop the
            # invented money and say plainly that the estimator must supply the quantity.
            if (not _qty_known) and any(
                str(code or "").upper().startswith(_cp)
                for _cp in ("POWDER", "PAINT", "LACQUER", "PRIMER",
                            "ADHESIVE", "SEALANT", "SOLVENT")
            ):
                # Clear EVERY field that holds this price. The last attempt cleared two of
                # four and wb_populate's BOM fallback chain simply moved to the next one and
                # re-priced it at £7.72. One value living in four places is the root cause of
                # four separate bugs today; until that is fixed properly, unprice defensively.
                for _pk in ("unit_cost_gbp", "unit_material_cost_gbp", "cost_per_part_gbp",
                            "extended_total_cost_gbp", "extended_material_cost_gbp",
                            "unit_total_cost_gbp"):
                    stub[_pk] = None
                _me_c = stub.get("material_estimate")
                if isinstance(_me_c, dict):
                    for _pk in ("unit_material_cost_gbp", "cost_per_part_gbp",
                                "extended_material_cost_gbp"):
                        _me_c[_pk] = None
                    _me_c["cost_method"] = "consumable_qty_unknown_estimator_to_price"
                stub["source"] = "sdi_bom_code_unpriced"
                stub["cost_source"] = "consumable_qty_unknown_estimator_to_price"
                stub["_consumable_qty_unknown"] = True
                # The explicit marker. wb_populate must honour this and NOT go hunting for a
                # price in some other field. "Not priced" is a DECISION, not a missing value.
                stub["_price_explicitly_withheld"] = True
                # Keep the catalogue RATE (£/kg) even though the price is withheld. We
                # withheld because we could not know the QUANTITY — not because the rate is
                # unknown. If geometry can later supply a quantity (a wire frame's coated
                # area is real, computable, and invisible to the sheet-only powder
                # calculator), the reason for withholding evaporates and we can cost it.
                try:
                    stub["_catalogue_rate_gbp"] = float(cat["unit_price_gbp"])
                except Exception:
                    pass
                stub.setdefault("review_flags", []).append(
                    f"CONSUMABLE {code}: NOT PRICED. The quantity is not on the drawing, and a "
                    f"consumable is sold by weight/volume — defaulting to 1 would mean 1kg "
                    f"(that is how this line reached £8.03 on a £6.74 job). Estimator to "
                    f"supply the quantity. Catalogue rate £{cat['unit_price_gbp']:.2f}/unit"
                    + (f", {cat['supplier']}" if cat.get("supplier") else "")
                    + ". NOTE: powder is also computed by the workbook's Powder Qty Calculator, "
                      "which only understands SHEET area — wire/tube parts contribute nothing, "
                      "so a wire job gets zero powder until that is fixed."
                )
            stub.setdefault("review_flags", []).append(
                f"BOM-code bought-in: {code} priced from UDEF catalogue "
                f"(\u00a3{cat['unit_price_gbp']:.2f}"
                + (f", {cat['supplier']}" if cat.get("supplier") else "")
                + f"); {_qnote}")
        else:
            # Recognised the code but it's not priced in UDEF — honest flag, never guess.
            stub = _bought_in_part_stub(code, code, _use_qty)
            _apply_field(stub, "quantity", _use_qty, "bom_tree")
            stub["unit_cost_gbp"] = None
            stub["extended_total_cost_gbp"] = None
            stub["source"] = "sdi_bom_code_unpriced"
            stub["cost_source"] = "estimator_to_price"
            stub["price_verified"] = False
            _qnote = (f"qty {_use_qty} from BOM table" if _qty_known
                      else "qty defaulted to 1 — estimator to confirm")
            stub.setdefault("review_flags", []).append(
                f"BOM-code bought-in: {code} recognised but not found in UDEF catalogue "
                f"— estimator to price; {_qnote}")
        found.append(stub)
    return found


def extract_bought_in_from_pages(
    summary: Dict[str, Any],
    *,
    existing_part_records: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Scan assembly/BOM text for bought-in items that are not detail parts."""
    pages = summary.get("pages", [])
    if existing_part_records is not None:
        existing_parts = existing_part_records
    else:
        existing_parts = summary.get("manufacturing_writeup", {}).get("parts") or summary.get("parts") or []
    existing_pns = {str(p.get("part_number", "")).strip().upper() for p in existing_parts if p.get("part_number")}

    primary = " ".join(
        str(page.get("pdfplumber_text", "") or "") + " " + str(page.get("normalized_text", "") or "") for page in pages
    )
    secondary = " ".join(_page_text_for_bought_in_scan(p) for p in pages)
    all_text = (primary + " " + secondary).upper()

    patterns: List[Tuple[str, str, str, int]] = [
        (r"(\d+)?\s*(SHFP28|UKPOS[:.\s-]*SHFP28)", "SHFP28", "Pusher and Guide Rail 28mm", 4),
        (r"(\d+)?\s*(MAGNET23)", "MAGNET23", "Magnet 20mm DIA x 5mm", 6),
        (r"(\d+)?\s*(DBR39|VKF[:.\s-]*DBR39)", "VKF DBR39", "39mm Scanner Profile 280mm", 2),
        (r"(\d+)?\s*(DBR18|VKF[:.\s-]*DBR18)", "VKF DBR18", "18mm Scanner Profile 280mm", 2),
        (r"(\d+)?\s*(FIXING1784|RUBUSECSTRIP)", "FIXING1784", "Edging Seal Rubusecstrip 10m", 1),
        (r"(\d+)?\s*(FIXING47|NUTSERT\s*M4|M4\s+THIN\s+SHEET)", "FIXING47", "M4 Thin Sheet Nutsert", 6),
        (r"(\d+)?\s*(FIXING1067|BOLT\s*M4|M4\s*x\s*20)", "FIXING1067", "M4 x 20mm C/Snk Bolt", 6),
        (r"(\d+)?\s*(PALLET1|PALLET\b)", "PALLET1", "Pallet", 1),
        (r"(\d+)?\s*(BOX[- ]?296\s*[xX×]\s*404\s*[xX×]\s*40|BOX-296x404x40)", "BOX-296x404x40", "Box 296w x 404d x 40h", 1),
    ]

    bought_in: List[Dict[str, Any]] = []
    seen_codes: set[str] = set()

    for regex, code, desc, default_qty in patterns:
        pn_key = code.strip().upper()
        if pn_key in existing_pns or code in seen_codes:
            continue
        matches = re.findall(regex, all_text, flags=re.IGNORECASE)
        if not matches:
            continue
        seen_codes.add(code)

        qty = default_qty
        first = matches[0]
        if isinstance(first, tuple):
            lead = first[0] if first else ""
            if lead and str(lead).strip().isdigit():
                qty = int(str(lead).strip())

        bought_in.append(_bought_in_part_stub(code, desc, qty))

    # General SDI-coded bought-in recognition (FIXING/VINYL/PRINT/SUBPLAS/POWDER by exact UDEF
    # code). Runs AFTER the hard-coded patterns and dedups against both existing parts and the
    # codes the patterns already produced, so nothing is double-counted. This is what catches
    # the per-job fixings & vinyl (FIXING125, VINYL76, ...) generically, no enumeration needed.
    _already = set(existing_pns) | {str(b.get("part_number", "")).strip().upper() for b in bought_in}
    _bom_rows = (summary.get("document_analysis") or {}).get("bom_rows") or []
    _coded = _recognise_sdi_coded_bought_in(all_text, _already, bom_rows=_bom_rows)
    if _coded:
        bought_in.extend(_coded)
        print(f"[DEBUG] SDI-coded bought-in recognised: {len(_coded)} -> "
              f"{[b['part_number'] for b in _coded]}")

    # Vinyl/logo callouts referenced by DESCRIPTION (not code), priced by unique dimension match
    # or flagged when ambiguous. Dedup against everything found so far.
    _already2 = set(existing_pns) | {str(b.get("part_number", "")).strip().upper() for b in bought_in}
    _existing_descs = {str(p.get("description", "")).strip().upper()
                       for p in existing_parts if p.get("description")}
    _vinyl = _recognise_vinyl_callouts(all_text, _already2, _existing_descs)
    if _vinyl:
        bought_in.extend(_vinyl)
        print(f"[DEBUG] Vinyl/logo callouts recognised: {len(_vinyl)} -> "
              f"{[b['part_number'] for b in _vinyl]}")

    if bought_in:
        print(f"[DEBUG] Bought-in items merged: {len(bought_in)} -> {[b['part_number'] for b in bought_in]}")

    return bought_in


def extract_bought_in_items_from_assembly(
    summary: Dict[str, Any],
    *,
    existing_part_records: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Alias for callers that name the scan by assembly page text (same as extract_bought_in_from_pages)."""
    return extract_bought_in_from_pages(summary, existing_part_records=existing_part_records)


def _merge_sheet_into_estimate_workbook_inputs(out_doc: Dict[str, Any], summary: Optional[Dict[str, Any]]) -> None:
    """Overlay qty and manual rates from the Estimate sheet when a workbook path is available."""
    ewb = out_doc.get("estimate_workbook_inputs")
    if not isinstance(ewb, dict):
        return
    candidates: List[Path] = []
    if summary:
        for key in ("estimate_workbook_path", "paired_estimate_workbook", "primary_spreadsheet_path"):
            raw = summary.get(key)
            if raw:
                candidates.append(Path(str(raw)))
    ss = (getattr(config, "PRICE_SOURCE_CONFIG", {}) or {}).get("spreadsheet", {}) or {}
    tb = ss.get("template_workbook")
    if tb:
        candidates.append(Path(str(tb)))
    seen: set[str] = set()
    for path in candidates:
        try:
            key = str(path.resolve())
        except Exception:
            key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if not path.is_file():
            continue
        try:
            from estimate_sheet_discovery import read_estimate_workbook_inputs

            scan = read_estimate_workbook_inputs(path)
        except Exception as exc:
            ewb["sheet_scan_error"] = str(exc)
            return
        ewb["sheet_scan"] = scan
        if not scan.get("ok"):
            return
        if scan.get("assumed_job_quantity") is not None:
            ewb["assumed_job_quantity"] = scan["assumed_job_quantity"]
        if scan.get("wire_cost_per_tonne_gbp") is not None:
            ewb["wire_cost_per_tonne_gbp"] = scan["wire_cost_per_tonne_gbp"]
        if scan.get("sheet_steel_cost_per_tonne_gbp") is not None:
            ewb["sheet_steel_cost_per_tonne_gbp"] = scan["sheet_steel_cost_per_tonne_gbp"]
        return


# Source authority ranking for reconciliation: when two layers find the SAME physical item
# under different identifiers, the most-grounded source wins. Higher = more authoritative.
_BOUGHT_IN_SOURCE_RANK = {
    "sdi_bom_code_udef_priced": 5,        # exact UDEF catalogue code — most grounded
    "udef_catalogue_section": 5,
    "non_sdi_bom_row": 4,                 # a structured BOM-table row
    "sdi_bom_row_no_geometry": 4,
    "prose_recogniser_layer2": 3,         # deterministic prose match to SDI history
    "sdi_bom_code_unpriced": 2,           # recognised, flagged for pricing
    "llm_note_scan": 1,                   # LLM-found from prose — least grounded price
    "commercial_placeholder": 0,          # packaging/delivery — never dedup-dropped
}

_BI_STOPWORDS = {
    "the", "a", "an", "of", "to", "and", "for", "with", "mm", "black", "white", "x",
    "lighting", "loose", "all", "be", "used", "secure", "cm", "m", "no", "ref",
}


def _bought_in_token_set(part: Dict[str, Any]) -> Optional[set]:
    """Distinctive content tokens for a bought-in line (head nouns + numbers), for overlap
    dedup. Returns None when too little to compare on (then we never dedup — a possible
    duplicate is safer than a wrong merge).
    """
    desc = str(part.get("description") or "").upper()
    if not desc.strip():
        return None
    import re as _re
    toks = _re.findall(r"[A-Z]+|\d+(?:\.\d+)?", desc)
    keep = {t for t in toks if t.lower() not in _BI_STOPWORDS and len(t) > 1}
    # Stem words to 6 chars so ELECTRICS/ELECTRIC etc. align; keep numbers as-is.
    stemmed = {(t[:6] if not t.replace(".", "").isdigit() else t) for t in keep}
    words = {t for t in stemmed if not t.replace(".", "").isdigit()}
    if not words:
        return None
    return stemmed


def _bought_in_same_item(a: set, b: set) -> bool:
    """Two bought-in lines describe the same physical item if their distinctive WORD tokens
    overlap strongly AND any numbers present are consistent. Containment counts: the shorter
    description's words being a subset of the longer's is a match (e.g. {LOOM,50} ⊂
    {ELECTR,LOOM,50}; {DOME,RIVET} ⊂ {DOME,FIXING,RIVET,10,4.0}).
    """
    aw = {t for t in a if not t.replace(".", "").isdigit()}
    bw = {t for t in b if not t.replace(".", "").isdigit()}
    an = {t for t in a if t.replace(".", "").isdigit()}
    bn = {t for t in b if t.replace(".", "").isdigit()}
    if not aw or not bw:
        return False
    shared_w = aw & bw
    smaller_w = min(len(aw), len(bw))
    # Word side: the smaller description's words must be (almost) wholly contained in the other.
    if smaller_w == 0:
        return False
    word_contained = len(shared_w) >= max(1, smaller_w)  # full containment of the smaller set
    if not word_contained:
        # allow one-word slack on larger sets (e.g. 3-word vs 3-word sharing 2)
        if smaller_w >= 3 and len(shared_w) >= smaller_w - 1:
            word_contained = True
    if not word_contained:
        return False
    # Number side: if BOTH carry numbers, they must share at least one (don't merge a 50cm
    # loom with a 100cm loom). If only one side has numbers, the contained-word match stands.
    if an and bn and not (an & bn):
        return False
    return True


def _reconcile_bought_in(parts: List[Dict[str, Any]], *, all_text: str = "", debug: bool = False) -> List[Dict[str, Any]]:
    """Collapse cross-layer duplicate bought-in lines, keeping the most-grounded source.

    Same-identifier dupes are already prevented upstream by existing_pns guards. THIS pass
    catches the harder case: the same physical item found by two DIFFERENT layers under
    different part numbers (BOM-table loom vs note-scan loom; FIXING5 vs BI-DOMERIVET). Lines
    whose distinctive tokens overlap (containment) are merged — the higher-authority source is
    kept, the duplicate dropped, and the survivor flagged so the merge is auditable, never
    silent. Fabricated parts and commercial placeholders are never dedup-dropped.
    """
    def _is_fabricated_part(p: Dict[str, Any]) -> bool:
        # A part with its own flat-pattern DXF (or a real SDI part number + geometry) is a
        # MANUFACTURED part, not a bought-in line — even if it also carries a 'bought_in'
        # page-role. Such parts must never be collapsed by the bought-in description dedup
        # (which caused distinct GRAPHIC CHANNEL parts to be merged by token overlap).
        _gs = str(p.get("geometry_source") or "").lower()
        if ("dxf" in _gs or p.get("dxf_augmented") or p.get("dxf_source_file")
                or _has_native_flat(p)):
            return True
        import re as _re
        _pn = str(p.get("part_number") or "").upper()
        if _re.match(r"^\d{4,5}-\d{2}-\d{2,3}[A-Z]?$", _pn) and (
            p.get("blank_length_mm") or p.get("overall_length_mm")
            or (p.get("dxf_raw_geometry") or {}).get("blank_area_mm2")
        ):
            return True
        return False

    def _is_bought_in(p: Dict[str, Any]) -> bool:
        if _is_fabricated_part(p):
            return False
        roles = p.get("page_roles") or []
        return "bought_in" in roles or str(p.get("source") or "") in _BOUGHT_IN_SOURCE_RANK

    keep: List[Dict[str, Any]] = []
    kept_tokens: List[Tuple[int, set]] = []   # (index in keep, token set) for bought-in lines
    dropped = 0
    for p in parts:
        if not _is_bought_in(p) or p.get("_commercial_placeholder"):
            keep.append(p)
            continue
        toks = _bought_in_token_set(p)
        match_idx = None
        if toks is not None:
            for idx_in_keep, ktoks in kept_tokens:
                if _bought_in_same_item(toks, ktoks):
                    match_idx = idx_in_keep
                    break
        # Guard: never merge two lines that carry DIFFERENT, non-empty part numbers. Distinct
        # part numbers = distinct items (e.g. VINYL-668X200 vs VINYL-668X1264 are different display
        # boards that only *look* similar because their descriptions share words + the spurious "25"
        # from "£25/m²"). The token-overlap merge is meant for the SAME item found under different
        # numbers by different layers, not for genuinely distinct catalogue lines.
        if match_idx is not None:
            _pn_new = str(p.get("part_number") or "").strip().upper()
            _pn_old = str(keep[match_idx].get("part_number") or "").strip().upper()
            if _pn_new and _pn_old and _pn_new != _pn_old:
                # Cancel the merge only when the two codes are genuinely DISTINCT catalogue
                # lines, not the same physical item found by two layers under different
                # identifiers. Distinct = same alphabetic family differing in detail
                # (VINYL-668X200 vs VINYL-668X1264 — real different boards), OR both
                # numeric-style SDI codes. DIFFERENT identifier schemes for one item
                # (ELECTRICS 50CM vs BI-50CMLOOM — a described BOM commodity vs its
                # catalogue code) SHOULD still merge: that is the cross-layer duplicate
                # this pass exists to catch.
                import re as _re_fam
                _fam_new = (_re_fam.match(r"[A-Za-z]+", _pn_new) or [None])
                _fam_new = _fam_new.group(0) if hasattr(_fam_new, "group") else ""
                _fam_old = (_re_fam.match(r"[A-Za-z]+", _pn_old) or [None])
                _fam_old = _fam_old.group(0) if hasattr(_fam_old, "group") else ""
                _same_family = bool(_fam_new and _fam_old and _fam_new == _fam_old)
                _both_numeric = (not _fam_new) and (not _fam_old)
                if _same_family or _both_numeric:
                    match_idx = None
        if match_idx is None:
            if toks is not None:
                kept_tokens.append((len(keep), toks))
            keep.append(p)
            continue
        # Duplicate of an already-kept bought-in line — keep the more-grounded source.
        existing = keep[match_idx]
        rank_new = _BOUGHT_IN_SOURCE_RANK.get(str(p.get("source") or ""), 0)
        rank_old = _BOUGHT_IN_SOURCE_RANK.get(str(existing.get("source") or ""), 0)
        winner, loser = (p, existing) if rank_new > rank_old else (existing, p)
        winner.setdefault("review_flags", []).append(
            f"Reconciled: same item also found as '{loser.get('part_number')}' "
            f"({loser.get('source')}) — kept '{winner.get('part_number')}' "
            f"({winner.get('source')}, more grounded), dropped the duplicate")
        keep[match_idx] = winner
        # refresh the token set for the winner at that slot
        kept_tokens = [(i, (_bought_in_token_set(winner) if i == match_idx else t)) for (i, t) in kept_tokens]
        dropped += 1
    if dropped and debug:
        print(f"[DEBUG] Bought-in reconciliation: dropped {dropped} cross-layer duplicate(s)")
    if dropped:
        print(f"   [reconcile] {dropped} duplicate bought-in line(s) merged (kept most-grounded source)")
    return keep


def estimate_document(parts: List[Dict[str, Any]], summary: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    debug = os.getenv("SCAN_DEBUG", "").lower() in {"1", "true", "yes"}
    if summary is not None:
        bought_in_items = extract_bought_in_from_pages(summary, existing_part_records=parts)
        if bought_in_items:
            parts.extend(bought_in_items)
            if debug:
                print(f"[DEBUG] Bought-in items merged into estimate: {len(bought_in_items)} -> {[b.get('part_number') for b in bought_in_items]}")

        # Loose bought-in components in assembly-note PROSE (not BOM rows): e.g. the
        # header assembly page lists "JUNCTION BOX ... 5m MAINS CABLE ... EARTH STRAP
        # ... ADHESIVE CABLE CLIP ... FOAM TAPE" as fitting instructions, never as
        # table rows, so extract_bought_in_from_pages (BOM-row based) cannot see them.
        # scan_notes_for_bought_in reads the note text and surfaces these as flagged,
        # AI-identified lines (priced via the shared waterfall, "estimator to verify").
        # Additive + reconciled against what we already found — never double-counts the
        # loom/fixings already captured above. Gated behind NOTE_SCAN_POLICY.enable; a
        # no-op (returns []) if disabled, the LLM is unavailable, or nothing new is found.
        try:
            from note_scan import scan_notes_for_bought_in
            # Assemble the assembly-page note text the engine already extracted.
            _note_chunks: List[str] = []
            for _pg in summary.get("pages", []) or []:
                _role = (_pg.get("page_role") or {})
                _is_assembly = (
                    (isinstance(_role, dict) and _role.get("primary_role") == "assembly")
                    or _role == "assembly"
                )
                # Include assembly pages; their region_text.notes / full text carry the prose.
                if _is_assembly:
                    # GUARD 1 (job 1310): notes region first, then ONE page-text variant.
                    # Previously ALL FOUR text variants were appended — the recogniser was
                    # handed four copies of the whole page (title block included).
                    _rt = _pg.get("region_text") or {}
                    if isinstance(_rt, dict) and _rt.get("notes"):
                        _note_chunks.append(str(_rt["notes"]))
                    # GUARD-1 REVERTED 2026-07-13. The `break` here took only the FIRST text
                    # variant. These four keys are DIFFERENT extractions of the same page, not
                    # duplicates — pdfplumber_text is nearly always present, so the loop broke on
                    # it and normalized_text / pypdf_text / text_preview were never read. That
                    # deterministically lost BI-LEDDOWNLIGHTS (£26) from 1282 for three runs.
                    # _note_text feeds BOTH the prose recogniser AND the LLM note-scan, so
                    # starving it blinded both. Append every variant, as before.
                    # The £105 phantom stays fixed by GUARD 2 (_job_identity_tokens), which does
                    # not depend on this loop.
                    for _k in ("pdfplumber_text", "normalized_text", "pypdf_text", "text_preview"):
                        _v = _pg.get(_k)
                        if _v:
                            _note_chunks.append(str(_v))
            _note_text = "\n".join(_note_chunks)
            if _note_text.strip():
                _existing_pns = {str(p.get("part_number", "")).strip().upper() for p in parts if p.get("part_number")}
                _seen_codes = set(_existing_pns)
                _existing_descs = {str(p.get("description", "")).strip().upper() for p in parts if p.get("description")}

                # DETERMINISTIC-PRIMARY: run the deterministic prose recogniser FIRST.
                # It matches a vocabulary of bought-in component TYPES mined from SDI's own
                # history (clip/strap/tie/cable/loom...), prices confident matches from
                # historical quote lines, and guards against double-counting fabricated
                # parts (passed as fabricated_descriptions). Same input -> same output every
                # run (no LLM), so it protects parity. The LLM note-scan then only needs to
                # backstop genuinely-novel prose items the vocabulary doesn't yet know.
                # Degrades to [] if no DB / no vocab — the LLM backstop still carries.
                try:
                    from bought_in_recogniser import recognise_bought_in_in_prose
                    import config as _cfg_det
                    # Fabricated (made-in) part descriptions — so the recogniser never prices
                    # a part that's already counted as a DXF/sheet fabricated item.
                    _fab_descs = {
                        str(p.get("description", "")).strip().upper()
                        for p in parts
                        if p.get("description") and "bought_in" not in (p.get("page_roles") or [])
                    }
                    _det_items = recognise_bought_in_in_prose(
                        _note_text,
                        get_connection=_cfg_det.get_connection,
                        existing_pns=_existing_pns,
                        existing_descriptions=_existing_descs,
                        fabricated_descriptions=_fab_descs,
                        stub_builder=_bought_in_part_stub,
                    )
                    # GUARD 2 (job 1310): never keep a bought-in that IS the job itself.
                    # The recogniser read the PROJECT TITLE from the title block, matched it
                    # 1.0 against a historical quote line for the same finished product, and
                    # costed it as a purchased part (£105 on a £6.90 job).
                    _job_toks = _job_identity_tokens(summary)
                    _kept_di, _dropped_di = [], []
                    for _di in (_det_items or []):
                        if _is_job_identity_desc(_di.get("description"), _job_toks):
                            _dropped_di.append(_di)
                        else:
                            _kept_di.append(_di)
                    for _dd in _dropped_di:
                        print("   [recogniser] DROPPED self-referential bought-in "
                              f"{_dd.get('description')!r} (£{_dd.get('unit_cost_gbp')}) — "
                              "its name is the JOB TITLE, not a purchased component.")
                    _det_items = _kept_di
                    
                    # GUARD 3: a recognised bought-in that carries a price it could not verify
                    # must SAY SO on the console. Previously confidence=0.0 / price_verified=False
                    # was recorded in JSON and silently ignored — £105 landed unannounced.
                    for _di in (_det_items or []):
                        _c = _di.get("unit_cost_gbp")
                        if _c and not _di.get("price_verified", False):
                            try:
                                _cf = float(_c)
                            except Exception:
                                continue
                            _lvl = "!! HIGH-VALUE" if _cf >= 25.0 else "!"
                            print(f"   [recogniser] {_lvl} UNVERIFIED price £{_cf:.2f} on "
                                  f"{_di.get('description')!r} "
                                  f"(source: {_di.get('source')}) — estimator to verify.")
                    
                    if _det_items:
                        parts.extend(_det_items)
                        # Feed deterministic finds into the dedup sets so the LLM backstop
                        # does not re-find the same items.
                        for _di in _det_items:
                            _pn = str(_di.get("part_number", "")).strip().upper()
                            if _pn:
                                _existing_pns.add(_pn); _seen_codes.add(_pn)
                            _dd = str(_di.get("description", "")).strip().upper()
                            if _dd:
                                _existing_descs.add(_dd)
                        print(f"   [recogniser] {len(_det_items)} bought-in item(s) deterministically "
                              f"recognised in notes: {[b.get('description') for b in _det_items]}")
                except Exception as _de:
                    if debug:
                        print(f"[DEBUG] deterministic recogniser skipped: {_de}")

                # LLM BACKSTOP: only finds what the deterministic layer missed (the dedup
                # sets above now include the deterministic finds).
                _note_items = scan_notes_for_bought_in(
                    _note_text,
                    existing_pns=_existing_pns,
                    seen_codes=_seen_codes,
                    existing_descriptions=_existing_descs,
                    stub_builder=_bought_in_part_stub,
                )
                if _note_items:
                    parts.extend(_note_items)
                    print(f"   [note-scan] {len(_note_items)} loose bought-in item(s) found in assembly notes: "
                          f"{[b.get('description') for b in _note_items]} (flagged for verification)")
        except Exception as _e:
            if debug:
                print(f"[DEBUG] note_scan skipped: {_e}")

        # Commercial lines that every quote carries but the DRAWINGS do not price:
        # packaging and delivery. Their real cost is order-specific (box size, pallet
        # count, destination, haulier) and lives in the enquiry, not the engineering —
        # the engine cannot genuinely derive a price from the drawings, so we add them
        # as ALWAYS-PRESENT, UNPRICED placeholder lines flagged for the estimator. This
        # makes the BOM complete (these lines are never silently omitted) without
        # inventing a number. Reconciled so they are not added twice if a re-estimate runs.
        _existing_now = {str(p.get("part_number", "")).strip().upper() for p in parts if p.get("part_number")}
        for _code, _desc in (
            ("PACKAGING", "Packaging (box / pallet — per-unit share, estimator to price)"),
            ("DELIVERY", "Delivery (per-unit share of order haulage — estimator to price)"),
        ):
            if _code in _existing_now:
                continue
            _stub = _bought_in_part_stub(_code, _desc, 1)
            _stub["source"] = "commercial_placeholder"
            _stub["price_verified"] = False
            _stub["unit_cost_gbp"] = 0.0
            _stub["unit_material_cost_gbp"] = 0.0
            _stub["extended_total_cost_gbp"] = 0.0
            _stub["cost_source"] = "estimator_to_price"
            # No operations — these are pure commercial placeholders, not fabricated/handled
            # parts, so they must not accrue handling labour. Keep them genuinely £0.
            _stub["textual_operations"] = []
            _stub["inferred_operations"] = []
            _stub["_commercial_placeholder"] = True
            _stub["review_flag"] = True
            _stub["review_flags"] = [
                "Commercial line — not derivable from drawings; estimator to price "
                "(order-specific: packaging size / pallet count / destination)."
            ]
            parts.append(_stub)
        if debug:
            print("[DEBUG] Added Packaging + Delivery placeholder lines (unpriced, flagged)")

        # SDI Intelligence — powder coating / wet spray is declared once in the
        # drawing title block (e.g. "POWDER COATED"), not per part. Stamp the
        # finish op onto fabricated metal parts so booth labour + powder
        # consumable are costed. Acrylic/board parts are not powder coated.
        _tb = ((summary.get("document_analysis") or {}).get("title_block") or {})
        _finishes = [str(x) for x in (_tb.get("surface_finishes") or []) if x]
        _finishes_blob = " ".join(_finishes).upper()
        _doc_powder = "POWDER" in _finishes_blob
        _doc_wet = any(t in _finishes_blob for t in ("WET SPRAY", "WET PAINT", "LINE PAINT", "SPRAY PAINT"))
        if _doc_powder or _doc_wet:
            _coat_op = "powder_coating" if _doc_powder else "wet_spray"
            _coat_metals = {"MILD_STEEL", "MILD STEEL", "STAINLESS_STEEL", "STAINLESS STEEL",
                            "ALUMINIUM", "ALUMINUM", "ZINTEC", "BRIGHT_DRAWN"}
            for _p in parts:
                if str(_p.get("normalized_material") or "").upper() not in _coat_metals:
                    continue
                _existing = list(_p.get("textual_operations") or []) + list(_p.get("inferred_operations") or [])
                if _coat_op not in _existing:
                    _p.setdefault("inferred_operations", []).append(_coat_op)
                if not _p.get("surface_finishes"):
                    _p["surface_finishes"] = list(_finishes)
            if debug:
                print(f"[DEBUG] {_coat_op} stamped onto metal parts from title-block finish {_finishes}")
    started = time.time()

    def _is_weldment_parent_part(p: Dict[str, Any], all_parts: List[Dict[str, Any]]) -> bool:
        """
        Skip SA weldment parent lines when fabricated child parts exist on the same
        drawing prefix (e.g. 10777-01-SA01 vs 10777-01-01/02/03) to avoid double-count.
        """
        pn = str(p.get("part_number") or "").upper().strip()
        if not re.search(r"-SA\d*$", pn):
            return False
        prefix = re.sub(r"-SA\d*$", "", pn)
        if not prefix:
            return False
        children = [
            x for x in all_parts
            if str(x.get("part_number") or "").upper().startswith(prefix + "-")
            and not re.search(r"-SA\d*$", str(x.get("part_number") or "").upper())
            and not str(x.get("part_number") or "").upper().endswith("-GA")
        ]
        if not children:
            return False
        desc = str(p.get("description") or "").upper()
        if any(k in desc for k in ("WELDMENT", "WELD ASSY", "WELDED ASSEMBLY", "FRAME WELDMENT")):
            return True
        # Generic SA row (12137-03-SA etc.) — skip when leaf parts are costed separately
        if "dxf" not in str(p.get("geometry_source") or "").lower():
            return True
        return False

    def _is_estimable_part(p: Dict[str, Any]) -> bool:
        """Return False for junk parts that have no meaningful content to estimate."""
        # Suppress NAMELESS phantom parts: part_number AND description both empty/None. These arise
        # from SECTION/DETAIL callouts (e.g. page-21 SECTION G-G is a view of BACK WALL 12532-03-06M,
        # already costed) that the extractor turned into a separate record with no identity. A real
        # fabricated part always has at least a part number, so keying on namelessness suppresses
        # only the phantom (proven: exactly one nameless record; 'has section callout' is NOT safe
        # to key on because real parts also carry section views). Must run BEFORE the has_dims/has_ops
        # rescue below, since the phantom carries incidental geometry that would otherwise keep it.
        _pn_raw = str(p.get("part_number") or "").strip()
        _desc_raw = str(p.get("description") or "").strip()
        if _pn_raw in ("", "None") and _desc_raw in ("", "None"):
            return False
        # Suppress GA/SA overview parts with no DXF geometry
        _pn_up = str(p.get("part_number") or "").upper().rstrip("_")
        _geo = str(p.get("geometry_source") or "")
        if ((_pn_up.endswith("-GA") or _pn_up.endswith("-GA1") or
             _pn_up.endswith("-SA") or _pn_up.endswith("-SA01"))
                and "dxf" not in _geo.lower()
                and not p.get("description")):
            return False
        has_part_number = bool(
            p.get("part_number")
            and not str(p.get("part_number", "")).startswith("part_")
            and str(p.get("part_number", "")).strip() not in ("", "None", "?")
        )
        has_material = bool(
            p.get("normalized_material")
            and str(p.get("normalized_material", "")).strip() not in ("", "None", "?", "UNKNOWN")
        )
        has_dims = bool(
            _safe_float(p.get("blank_length_mm"))
            or _safe_float(p.get("overall_length_mm"))
            or _safe_float(p.get("blank_width_mm"))
        )
        has_ops = bool(
            p.get("fab_ops")
            or p.get("operations")
            or p.get("textual_operations")
            or (p.get("manufacturing_features") or {}).get("operations")
            or p.get("_bought_in_from_text_scan")
        )
        return has_part_number or has_material or has_dims or has_ops

    # Reconcile cross-layer duplicate bought-in lines (same item, different identifier/source)
    # before estimation, so a doubled loom / rivet / fixing can't reach the workbook. Keeps
    # the most-grounded source, drops the duplicate, flags the merge for audit. The pooled page
    # text lets reconciliation use drawing co-location ("FIXING5 ... DOME RIVET") as a merge
    # signal in addition to description-token overlap.
    _recon_text = ""
    if summary is not None:
        try:
            _pgs = summary.get("pages", []) or []
            _recon_text = " ".join(
                str(_pg.get("pdfplumber_text", "") or "") + " "
                + str(_pg.get("normalized_text", "") or "") + " "
                + _page_text_for_bought_in_scan(_pg)
                for _pg in _pgs
            ).upper()
        except Exception:
            _recon_text = ""
    parts = _reconcile_bought_in(parts, all_text=_recon_text, debug=debug)

    estimable_parts = [
        p for p in parts
        if _is_estimable_part(p) and not _is_weldment_parent_part(p, parts)
    ]
    skipped = len(parts) - len(estimable_parts)
    if skipped:
        print(f"   -> Skipped {skipped} junk part(s) with no material, dimensions, or operations")

    # Order quantity for setup/batch amortisation: the per-job qty the scan
    # captured (summary['assumed_job_quantity']; file_scan stamps
    # DEFAULT_JOB_QUANTITY when the enquiry doesn't state one). Passed into every
    # part so machine setup is spread over the order — as the manual estimate does.
    _order_qty = None
    if summary is not None:
        _order_qty = summary.get("assumed_job_quantity") or summary.get("quantity")
    _order_qty = max(1, int(_order_qty or getattr(config, "DEFAULT_JOB_QUANTITY", 180)))
    if debug:
        print(f"[DEBUG] estimate_document order_qty for setup amortisation = {_order_qty}")

    part_estimates: List[Dict[str, Any]] = []
    for idx, part in enumerate(estimable_parts, start=1):
        part_number = part.get("part_number") or part.get("item_number") or f"part_{idx}"
        if debug:
            print(
                f"[DEBUG] estimate_document start part {idx}/{len(estimable_parts)}: "
                f"{part_number} (+{round(time.time()-started,2)}s)"
            )
        part_estimate = estimate_part(part, job_quantity=_order_qty)
        part_estimates.append(part_estimate)
        if debug:
            print(
                f"[DEBUG] estimate_document done part {idx}/{len(estimable_parts)}: "
                f"{part_number} (+{round(time.time()-started,2)}s)"
            )
    material_total_raw = sum((item.get("material_estimate", {}).get("extended_material_cost_gbp") or 0.0) for item in part_estimates)
    labour_total_raw = sum((item.get("labour_estimate", {}).get("total_labour_cost_gbp") or 0.0) for item in part_estimates)
    material_total = _round_money(material_total_raw)
    labour_total = _round_money(labour_total_raw)
    operation_totals: Dict[str, float] = {}
    for item in part_estimates:
        for op, cost in item.get("labour_estimate", {}).get("costs_gbp", {}).items():
            operation_totals[op] = round(operation_totals.get(op, 0.0) + (cost or 0.0), 2)
    mode = _rounding_mode()
    if mode == "per_line":
        document_total_raw = sum(float(item.get("extended_total_cost_gbp") or 0.0) for item in part_estimates)
    else:
        document_total_raw = sum(float(item.get("extended_total_cost_raw_gbp") or item.get("extended_total_cost_gbp") or 0.0) for item in part_estimates)
    if mode == "per_section":
        document_total_raw = material_total + labour_total
    document_total = _round_money(document_total_raw)

    data_sufficiency = _assess_estimate_data_sufficiency(
        estimable_parts, part_estimates, document_total
    )
    reportable_total = data_sufficiency.get("document_total_reportable_gbp")
    if data_sufficiency.get("suppress_headline_total"):
        document_total_out = None
    else:
        document_total_out = document_total

    powder_material_total_raw = sum(_part_powder_material_extended_gbp(p) for p in part_estimates)
    powder_labour_total_raw = sum(_part_powder_labour_gbp(p) for p in part_estimates)
    pc_policy = getattr(config, "POWDER_COSTING_POLICY", {}) or {}
    pc_labour = LABOUR_RULES.get("powder_coating", {}) or {}
    powder_scrap_frac = (
        float(getattr(config, "SCRAP_PERCENTAGE", 0.0) or 0.0) if pc_policy.get("apply_global_scrap_to_powder_kg", True) else 0.0
    )
    powder_coating_summary = {
        "powder_material_gbp": _round_money(powder_material_total_raw),
        "powder_labour_gbp": _round_money(powder_labour_total_raw),
        "powder_total_gbp": _round_money(powder_material_total_raw + powder_labour_total_raw),
        "costing_inputs": {
            "coverage_m2_per_kg": float(pc_policy.get("coverage_m2_per_kg", 6.0)),
            "throughput_m2_per_hour": float(pc_labour.get("throughput_m2_per_hour", 15.0)),
            "setup_min_per_part": float(pc_labour.get("setup_min_per_part", pc_labour.get("min_per_part", 0.75))),
            "min_run_min": float(pc_labour.get("min_run_min", 0.25)),
            "hourly_rate_powder_coating_gbp": float(HOURLY_RATES_GBP.get("powder_coating", 0.0) or 0.0),
            "powder_material_gbp_per_kg_standard": float(pc_policy.get("powder_material_gbp_per_kg", 0.0)),
            "powder_material_gbp_per_kg_special_finish": float(pc_policy.get("powder_material_gbp_per_kg_special", 0.0)),
            "global_scrap_fraction_on_powder_kg": powder_scrap_frac,
            "bend_coating_strip_mm": float(pc_policy.get("bend_coating_strip_mm", 40.0)),
        },
        "one_line": (
            f"Powder coating: £{_round_money(powder_material_total_raw):.2f} material + "
            f"£{_round_money(powder_labour_total_raw):.2f} labour"
        ),
        "by_part": [
            {
                "part_number": p.get("part_number"),
                "description": p.get("description"),
                "quantity": p.get("quantity"),
                "powder_material_gbp": _round_money(_part_powder_material_extended_gbp(p)),
                "powder_labour_gbp": _round_money(_part_powder_labour_gbp(p)),
                "powder_total_gbp": _round_money(
                    _part_powder_material_extended_gbp(p) + _part_powder_labour_gbp(p)
                ),
            }
            for p in part_estimates
            if _part_powder_material_extended_gbp(p) > 0 or _part_powder_labour_gbp(p) > 0
        ],
    }

    workbook_equivalent_pricing = _build_workbook_equivalent_pricing(part_estimates, material_total=material_total, labour_total=labour_total)
    estimate_source_extract = build_estimate_source_extract(part_estimates)
    historical_comparison_projection = {
        "schema": "estimate_projection_for_historical.v1",
        "totals": {
            "material_subtotal_gbp": material_total,
            "labour_subtotal_gbp": labour_total,
            "document_total_estimated_cost_gbp": reportable_total if reportable_total is not None else document_total_out,
            "workbook_equivalent_total_unit_cost_gbp": workbook_equivalent_pricing.get("l105_total_unit_cost_gbp"),
            "workbook_equivalent_sell_price_gbp": workbook_equivalent_pricing.get("l111_sell_price_gbp"),
        },
        "parts": [
            {
                "part_number": p.get("part_number"),
                "description": p.get("description"),
                "quantity": p.get("quantity"),
                "unit_total_cost_gbp": p.get("unit_total_cost_gbp"),
                "extended_total_cost_gbp": p.get("extended_total_cost_gbp"),
                "material_cost_gbp": p.get("cost_breakdown", {}).get("material", {}).get("extended_material_cost_gbp"),
                "labour_cost_gbp": p.get("cost_breakdown", {}).get("labour", {}).get("total_labour_cost_gbp"),
                "costing_basis": p.get("cost_breakdown", {}).get("costing_basis"),
                "operations_costs_gbp": p.get("cost_breakdown", {}).get("labour", {}).get("costs_gbp", {}),
            }
            for p in part_estimates
        ],
    }
    out_doc: Dict[str, Any] = {
        "part_estimates": part_estimates,
        "powder_coating_summary": powder_coating_summary,
        "estimate_policy_manifest": _build_estimate_policy_manifest(),
        "estimate_review_signals": _build_estimate_review_signals(part_estimates),
        "data_sufficiency": data_sufficiency,
        "estimate_status": data_sufficiency.get("status", "ok"),
        "document_total_estimated_cost_gbp": reportable_total if reportable_total is not None else document_total_out,
        "document_total_provisional_gbp": data_sufficiency.get("document_total_provisional_gbp"),
        "document_total_raw_gbp": document_total_raw,
        "workbook_equivalent_pricing": workbook_equivalent_pricing,
        "estimate_source_extract": estimate_source_extract,
        "historical_comparison_projection": historical_comparison_projection,
        "cost_breakdown": {
            "material": {
                "total": material_total,
                "per_part": [
                    {
                        "part_number": item.get("part_number"),
                        "extended_material_cost_gbp": item.get("material_estimate", {}).get("extended_material_cost_gbp"),
                        "supplier_source": item.get("material_estimate", {}).get("price_source", {}).get("supplier_source"),
                        "price_date": item.get("material_estimate", {}).get("price_source", {}).get("price_date"),
                    }
                    for item in part_estimates
                ],
            },
            "labour": {
                "total": labour_total,
                "by_operation": operation_totals,
            },
            "overhead": {},
            "margin_options": ["low", "standard", "premium"],
            "pricing_metadata": {
                "latest_price_date": max(
                    [item.get("material_estimate", {}).get("price_source", {}).get("price_date") for item in part_estimates if item.get("material_estimate", {}).get("price_source", {}).get("price_date")],
                    default=None,
                ),
                "supplier_sources": sorted(
                    {
                        item.get("material_estimate", {}).get("price_source", {}).get("supplier_source")
                        for item in part_estimates
                        if item.get("material_estimate", {}).get("price_source", {}).get("supplier_source")
                    }
                ),
                "pricing_basis": "external_or_config_fallback",
            },
        },
    }
    wb_defaults = getattr(config, "WORKBOOK_INPUT_DEFAULTS", {}) or {}
    out_doc["estimate_workbook_inputs"] = {
        "estimate_policy_version": getattr(config, "ESTIMATE_POLICY_VERSION", ""),
        "assumed_job_quantity": wb_defaults.get("default_job_quantity"),
        "scrap_pct": wb_defaults.get("scrap_pct"),
        "wire_cost_per_tonne_gbp": wb_defaults.get("wire_cost_per_tonne_gbp"),
        "sheet_steel_cost_per_tonne_gbp": wb_defaults.get("sheet_steel_cost_per_tonne_gbp"),
        "output_manufacturing_cost_only": bool(getattr(config, "OUTPUT_MANUFACTURING_COST_ONLY", False)),
        "material_price_break_headers": getattr(config, "MATERIAL_PRICE_BREAK_HEADERS", {}),
        "workbook_source_map": getattr(config, "WORKBOOK_SOURCE_MAP", {}),
        "reverse_engineer": "Run: python src/extract_workbook_constants.py --workbook <path-to.xlsx>",
    }
    _merge_sheet_into_estimate_workbook_inputs(out_doc, summary)
    mopts = out_doc["cost_breakdown"].get("margin_options")
    if bool(getattr(config, "OUTPUT_MANUFACTURING_COST_ONLY", False)) and isinstance(mopts, list):
        out_doc["cost_breakdown"]["margin_options"] = []
    return out_doc


def build_estimate_input_rows(summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    estimate_lookup = {item["part_number"]: item for item in summary.get("estimate_summary", {}).get("part_estimates", [])}

    for part in summary.get("manufacturing_writeup", {}).get("parts", []):
        estimate = estimate_lookup.get(part.get("part_number"), {})
        material_estimate = estimate.get("material_estimate", {})
        process_estimate = estimate.get("process_estimate", {})
        labour_estimate = estimate.get("labour_estimate", {})
        rows.append(
            {
                "source_file": summary["source_file"],
                "part_number": part.get("part_number"),
                "description": part.get("description"),
                "quantity": part.get("quantity"),
                "page_roles": _join(part.get("page_roles", [])),
                "material": _join(part.get("materials", [])),
                "thickness_mm": _join(part.get("thicknesses_mm", [])),
                "finish": _join(part.get("surface_finishes", [])),
                "colour": _join(part.get("colours", [])),
                "revision": _join(part.get("revisions", [])),
                "dates": _join(part.get("dates", [])),
                "overall_length_mm": part.get("overall_length_mm"),
                "overall_width_mm": part.get("overall_width_mm"),
                "overall_sizes_mm": _join(part.get("overall_sizes_mm", [])),
                "dimensions_mm": _join(part.get("all_dimensions_mm", [])),
                "angles_deg": _join(part.get("angles_deg", [])),
                "hole_sizes_mm": _join(part.get("hole_sizes_mm", [])),
                "slot_sizes_mm": _join(part.get("slot_sizes_mm", [])),
                "manufacturing_features": _join(
                    [
                        f"laser={part.get('manufacturing_features', {}).get('laser_required')}",
                        f"fold={part.get('manufacturing_features', {}).get('fold_required')}",
                        f"holes={part.get('manufacturing_features', {}).get('hole_count')}",
                        f"slots={part.get('manufacturing_features', {}).get('slot_count')}",
                        f"bends={part.get('manufacturing_features', {}).get('bend_count')}",
                        f"finish={part.get('manufacturing_features', {}).get('finish_required')}",
                    ]
                ),
                "operations": _join(part.get("textual_operations", [])),
                "process_notes": _join(part.get("process_notes", [])),
                "estimated_cut_length_mm": process_estimate.get("cut_length_mm"),
                "estimated_hole_count": process_estimate.get("hole_count"),
                "estimated_slot_like_features": part.get("geometry_rollup", {}).get("estimated_slot_like_features"),
                "estimated_bend_line_count": process_estimate.get("bend_count"),
                "blank_length_mm": material_estimate.get("blank_length_mm"),
                "blank_width_mm": material_estimate.get("blank_width_mm"),
                "material_cost_gbp": material_estimate.get("extended_material_cost_gbp"),
                "total_time_min": process_estimate.get("total_time_min"),
                "unit_labour_cost_gbp": labour_estimate.get("total_labour_cost_gbp"),
                "unit_total_cost_gbp": estimate.get("unit_total_cost_gbp"),
                "extended_total_cost_gbp": estimate.get("extended_total_cost_gbp"),
            }
        )
    return rows


def generate_client_quote_pack(summary: Dict[str, Any]) -> Dict[str, Any]:
    """
    Clean executive summary + full priced breakdown for PDF or customer email.
    Expects scan-style summary with estimate_summary (from estimate_document).
    """
    estimate = summary.get("estimate_summary") or {}
    powder = estimate.get("powder_coating_summary") or {}
    part_estimates = estimate.get("part_estimates") or []

    total_manufacturing = float(estimate.get("document_total_estimated_cost_gbp") or 0.0)
    cb = estimate.get("cost_breakdown") or {}
    total_material = float((cb.get("material") or {}).get("total") or 0.0)
    total_labour = float((cb.get("labour") or {}).get("total") or 0.0)

    wb_def = getattr(config, "WORKBOOK_INPUT_DEFAULTS", {}) or {}
    assumed_qty = int(wb_def.get("default_job_quantity", getattr(config, "DEFAULT_JOB_QUANTITY", 600)))
    scrap_pct = int(round(float(getattr(config, "SCRAP_PERCENTAGE", 0.04)) * 100))
    pcov = float((getattr(config, "POWDER_COSTING_POLICY", {}) or {}).get("coverage_m2_per_kg", 6.0))
    mfg_only = bool(getattr(config, "OUTPUT_MANUFACTURING_COST_ONLY", False))

    stem = Path(str(summary.get("source_file") or "drawing")).stem
    key_assumptions = [
        (
            "Manufacturing cost only (sales margin applied separately)"
            if mfg_only
            else "Costs shown before optional sales margin uplift (see internal workbook policy)."
        ),
        f"{scrap_pct}% material scrap allowance",
        f"Powder coverage {pcov:g} m² per kg",
        "Geometry-derived labour times (verify against drawing before production)",
    ]

    pack: Dict[str, Any] = {
        "schema": "client_quote_pack.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "drawing_reference": summary.get("source_file", "unknown"),
        "executive_summary": {
            "one_page_header": f"Manufacturing Cost Estimate – {stem}",
            "total_manufacturing_cost_gbp": round(total_manufacturing, 2),
            "total_material_gbp": round(total_material, 2),
            "total_labour_gbp": round(total_labour, 2),
            "powder_coating_summary": powder.get("one_line") or "Powder coating: not applicable",
            "assumed_order_quantity": assumed_qty,
            "key_assumptions": key_assumptions,
        },
        "full_priced_breakdown": {
            "parts": [
                {
                    "part_number": p.get("part_number"),
                    "description": p.get("description"),
                    "quantity": p.get("quantity"),
                    "unit_total_cost_gbp": round(float(p.get("unit_total_cost_gbp") or 0.0), 2),
                    "extended_total_cost_gbp": round(float(p.get("extended_total_cost_gbp") or 0.0), 2),
                    "material_cost_gbp": round(float((p.get("material_estimate") or {}).get("extended_material_cost_gbp") or 0.0), 2),
                    "labour_cost_gbp": round(float((p.get("labour_estimate") or {}).get("total_labour_cost_gbp") or 0.0), 2),
                    "powder_material_gbp": round(_part_powder_material_extended_gbp(p), 2),
                    "powder_labour_gbp": round(_part_powder_labour_gbp(p), 2),
                }
                for p in part_estimates
            ],
            "totals": {
                "material_subtotal_gbp": round(total_material, 2),
                "labour_subtotal_gbp": round(total_labour, 2),
                "powder_material_gbp": round(float(powder.get("powder_material_gbp") or 0.0), 2),
                "powder_labour_gbp": round(float(powder.get("powder_labour_gbp") or 0.0), 2),
                "grand_total_manufacturing_cost_gbp": round(total_manufacturing, 2),
            },
        },
        "notes_for_customer": [
            "All prices shown are manufacturing cost only.",
            "Final selling price will include SDI margin and any agreed commercial terms.",
            "Quantities and lead times subject to confirmation.",
            "Geometry and process assumptions are derived from the drawing; final verification recommended before production.",
        ],
    }

    return pack


def append_rows_to_csv(csv_path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    row_list = list(rows)
    if not row_list:
        return
    write_header = not csv_path.exists()
    with csv_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_HEADERS)
        if write_header:
            writer.writeheader()
        writer.writerows(row_list)
