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


def _part_has_part_dxf(mfg: Dict[str, Any]) -> bool:
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
    rf_blob = " ".join(str(x) for x in (est_part.get("risk_flags") or []))

    if mfg.get("geometry_inferred"):
        reasons.append("geometry_inferred_provisional")
    if "implausible_system_cost_rejected" in rf_blob:
        reasons.append("rejected_catalogue_match")

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


def _infer_section_length_mm(part: Dict[str, Any]) -> Optional[float]:
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

    return {"result": best_result, "applied_unit_cost": best_price, "matched_part_code": matched_part_code}


def _dxf_geometry_trusted(part: Dict[str, Any], ng: Dict[str, Any]) -> bool:
    """True when blank/bbox extents came from flat DXF, not PDF page vectors."""
    if part.get("dxf_augmented") or part.get("flat_pattern_detected"):
        return True
    if part.get("geometry_source") == "dxf_flat_pattern":
        return True
    if str(ng.get("geometry_source") or "").lower() in {"dxf_flat_pattern", "dxf"}:
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
    _dfn = str(part.get("dxf_source_file") or part.get("geometry_source_path") or "")
    if _dfn:
        _tm = re.search(r"[_\-\s](\d+\.?\d*)\s*mm", _dfn, re.IGNORECASE)
        if _tm:
            _tv = _safe_float(_tm.group(1))
            if _tv and 0.3 <= _tv <= 25.0:
                return _tv

    # Already-normalised thickness — skip tolerance-table noise when DXF exists
    raw = part.get("normalized_thickness_mm")
    if raw:
        v = _safe_float(raw)
        if v and 0.4 <= v <= 50.0 and not (1900 <= v <= 2100):
            if round(v, 1) not in _TOLERANCE_TABLE_SEQUENCE or not _dfn:
                return v

    # thicknesses_mm list with tolerance-table stripping
    candidates = [_safe_float(x) for x in part.get("thicknesses_mm", [])]
    candidates = [v for v in candidates if v and v > 0 and not (1900 <= v <= 2100)]
    if not candidates:
        return None

    cand_set = set(round(v, 1) for v in candidates)
    if _TOLERANCE_TABLE_SEQUENCE.issubset(cand_set):
        stripped = [v for v in candidates if round(v, 1) not in _TOLERANCE_TABLE_SEQUENCE]
        # Only use the stripped list if something survives; otherwise the
        # original values ARE the real thickness (e.g. a 2mm-only acrylic part).
        if stripped:
            candidates = stripped
    if not candidates:
        return None

    from collections import Counter
    rounded = [round(v, 2) for v in candidates]
    _best = Counter(rounded).most_common(1)[0][0]
    return _best or None


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
        return {
            "overall_length_mm": dxf_l,
            "overall_width_mm": dxf_w,
            "all_dimensions_mm": sorted([dxf_l, dxf_w], reverse=True),
            "source": "dxf_flat_pattern",
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
    Exact workbook nesting formula (rows 37-48, col K):
        nx = INT((sheet_length - 80) / (part_length + 10))
        ny = INT((sheet_width  - 80) / (part_width  + 10))
        parts_per_sheet = nx × ny
    Edge margin = 80mm, inter-part gap = 10mm (5mm × 2 sides).
    Both orientations tried; best yield wins.
    """
    if blank_length is None or blank_width is None:
        return {"candidate_sheet_size_mm": None, "parts_per_sheet": None, "utilisation_pct": None}

    sizes = STANDARD_SHEET_SIZES_MM.get(material or "", STANDARD_SHEET_SIZES_MM["DEFAULT"])
    edge_margin = float(NESTING_RULES.get("edge_margin_mm", 80.0))
    inter_part_gap = float(NESTING_RULES.get("part_spacing_mm", 5.0)) * 2.0  # 5mm each side = 10mm pitch

    best: Optional[Dict[str, Any]] = None
    for sheet_length, sheet_width in sizes:
        for part_l, part_w in [(blank_length, blank_width), (blank_width, blank_length)]:
            nx = int((sheet_length - edge_margin) / (part_l + inter_part_gap)) if (part_l + inter_part_gap) > 0 else 0
            ny = int((sheet_width  - edge_margin) / (part_w + inter_part_gap)) if (part_w + inter_part_gap) > 0 else 0
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
                "nesting_formula": f"INT(({sheet_length}-{edge_margin:.0f})/({part_l}+{inter_part_gap:.0f})) × INT(({sheet_width}-{edge_margin:.0f})/({part_w}+{inter_part_gap:.0f}))",
            }
            if best is None or qty > best["parts_per_sheet"]:
                best = candidate

    return best or {"candidate_sheet_size_mm": None, "parts_per_sheet": None, "utilisation_pct": None}


def estimate_material(part: Dict[str, Any]) -> Dict[str, Any]:
    material = part.get("normalized_material") or _first(part.get("materials", []))
    thickness = _safe_thickness_mm(part)
    quantity = _safe_int(part.get("quantity")) or 1
    dims = infer_primary_dimensions(part)
    blank_length, blank_width = estimate_blank_size(dims)
    external_price = _resolve_material_price(material, thickness, quantity, part=part)
    external_result = external_price.get("result", {})

    # Section/tube/wire path: uses linear stock mass estimate when profile+length is available.
    if _is_section_or_wire_candidate(part, material):
        side_a_mm, side_b_mm, wall_t_mm = _parse_section_profile(str(part.get("description") or ""))
        length_mm = _infer_section_length_mm(part)

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
                "stock_form": part.get("manufacturing_interpretation", {}).get("stock_form"),
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
    parts_per_sheet = sheet_estimate.get("parts_per_sheet") or 1

    # Sheet steel cost — workbook rows 37-48 formula:
    # cost_per_part = (sheet_steel_£_per_tonne / 1000 × kg_per_sheet) / parts_per_sheet × (1+scrap)
    wb_defaults = getattr(config, "WORKBOOK_INPUT_DEFAULTS", {}) or {}
    is_steel = (material or "").upper() in {
        "MILD STEEL", "MILD_STEEL", "ZINTEC", "GALVANISED STEEL",
        "GALVANIZED STEEL", "STAINLESS STEEL", "STAINLESS_STEEL",
        "MILD_STEEL_SPCC", "STAINLESS_STEEL_304", "STAINLESS_STEEL_316",
    }
    sheet_steel_per_tonne = float(wb_defaults.get("sheet_steel_cost_per_tonne_gbp") or 0.0)
    scrap_frac = float(getattr(config, "SCRAP_PERCENTAGE", 0.04))

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
        material_cost = mass_kg * price_per_kg * (1.0 + scrap_frac)
        cost_method = "mass_times_price_per_kg"

    powder_block = _powder_consumable_estimate(part, blank_length, blank_width, quantity)
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


def estimate_process_times(part: Dict[str, Any], quantity: int = 1) -> Dict[str, Any]:
    geom = part.get("geometry_rollup", {})
    ops = _part_ops(part)
    manufacturing_features = part.get("manufacturing_features", {})
    geometry_confidence = 0.0
    if isinstance(geom.get("confidence"), dict):
        geometry_confidence = geom["confidence"].get("geometry_reliability", 0.0) or 0.0

    dims_pm = infer_primary_dimensions(part)
    blank_length_pm, blank_width_pm = estimate_blank_size(dims_pm)

    raw_cut_length_mm = manufacturing_features.get("raw_cut_length_mm", geom.get("estimated_cut_length_mm", 0.0) or 0.0)
    cut_length_mm = manufacturing_features.get("cut_length_mm", raw_cut_length_mm * max(0.25, geometry_confidence) if raw_cut_length_mm else 0.0)
    pierces = geom.get("estimated_pierce_count", 0) or 0
    holes = manufacturing_features.get("hole_count", max(geom.get("estimated_hole_count", 0) or 0, len(part.get("hole_sizes_mm", []))))
    bends = manufacturing_features.get("bend_count", max(len(part.get("angles_deg", [])), len(part.get("fold_values_mm", [])), part.get("fold_count_textual", 0) or 0))
    bend_length_mm = sum([_safe_float(value) or 0.0 for value in part.get("fold_values_mm", [])])
    thickness_mm = _safe_thickness_mm(part)

    # SDI Intelligence — infer a cutting operation when the drawing text did not
    # name one. Any sheet/board part with a cut length MUST be cut somehow, so
    # assign laser cutting (steel + acrylic are laser cut at SDI). Without this,
    # parts with valid flat-pattern geometry got zero operations -> zero labour.
    _mat_u = str(part.get("normalized_material") or "").upper()
    _SHEET_METALS = {"MILD_STEEL", "MILD STEEL", "STAINLESS_STEEL", "STAINLESS STEEL",
                     "ALUMINIUM", "ALUMINUM", "ZINTEC", "BRIGHT_DRAWN"}
    _CUT_BOARDS = {"ACRYLIC", "POLYCARBONATE", "PETG", "MDF", "VENEERED_MDF",
                   "OAK_VENEER_MDF", "PLYWOOD", "BIRCH_PLYWOOD", "HDPE_PLASTIC",
                   "FOAMEX", "DIBOND", "TIMBER"}
    _CUTTING_OPS = ("laser_cutting", "cnc_routing", "cnc", "punch", "guillotine", "saw")
    _has_cut_op = any(o in ops for o in _CUTTING_OPS)
    # Section/tube/wire parts without a flat DXF are SAWN/MITRED to length, not laser
    # profile-cut. Their PDF "cut length" is the whole-GA-page geometry rollup (e.g.
    # 24,508mm on a 600mm frame), so it must never drive laser cost or trigger a laser
    # op. The DXF guard means any section that DOES carry a flat pattern is left alone.
    _section_no_dxf = (
        _is_section_or_wire_candidate(part, part.get("normalized_material"))
        and not _dxf_geometry_trusted(part, part.get("normalized_geometry", {}) or {})
    )
    if not _has_cut_op and cut_length_mm and cut_length_mm > 0 and not _section_no_dxf:
        if _mat_u in _SHEET_METALS or _mat_u in _CUT_BOARDS:
            ops = list(ops) + ["laser_cutting"]
            part.setdefault("inferred_operations", [])
            if "laser_cutting" not in part["inferred_operations"]:
                part["inferred_operations"].append("laser_cutting")
    # Every fabricated part also needs handling/assembly time at the bench.
    if (_mat_u in _SHEET_METALS or _mat_u in _CUT_BOARDS) and "handling" not in ops:
        ops = list(ops) + ["handling"]

    setup_times_min: Dict[str, float] = {}
    run_times_min: Dict[str, float] = {}
    powder_coating_detail: Optional[Dict[str, Any]] = None

    _is_wire_op_part = any(
        op in ops
        for op in ("wire_forming", "welding", "resistance_welding", "spot_welding", "deburring")
    )

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

    if "hole_machining" in ops:
        rule = LABOUR_RULES["hole_machining"]
        setup_times_min["hole_machining"] = round(rule["setup_min"], 2)
        run_times_min["hole_machining"] = round((holes * rule["sec_per_hole"]) / 60.0, 2)

    if "folding" in ops:
        rule = LABOUR_RULES["folding"]
        setup_times_min["folding"] = round(rule["setup_min"], 2)
        run_times_min["folding"] = round((bends * rule["sec_per_bend"] + bend_length_mm * rule["sec_per_mm_bend_length"]) / 60.0, 2)

    if "powder_coating" in ops:
        pc_rule = LABOUR_RULES["powder_coating"]
        setup_pm = float(pc_rule.get("setup_min_per_part", pc_rule.get("min_per_part", 0.75)))
        throughput = float(pc_rule.get("throughput_m2_per_hour", 15.0))
        coated_m2, coated_detail = _powder_coated_area_m2(part, blank_length_pm, blank_width_pm)
        run_min = 0.0
        if throughput > 0 and coated_m2 > 0:
            run_min = (coated_m2 / throughput) * 60.0
        _pc_min = 3.0 if _is_wire_op_part else float(pc_rule.get("min_run_min", 0.25))
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
        run_times_min["dress_welds"] = 2.0

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
    _ACRYLIC_LIKE = {"ACRYLIC", "POLYCARBONATE", "PETG", "HDPE_PLASTIC", "FOAMEX"}
    for op in all_ops:
        external_rate = _resolve_labour_rate(op)
        applied_hourly_rate = external_rate.get("applied_hourly_rate")
        # Material-aware rate key: acrylic/plastic laser cutting + assembly use
        # the cheaper non-metal rates (laser_cutting_acrylic, assembly_acrylic).
        _rate_key = op
        if _mat_u in _ACRYLIC_LIKE:
            if op == "laser_cutting" and "laser_cutting_acrylic" in HOURLY_RATES_GBP:
                _rate_key = "laser_cutting_acrylic"
            elif op == "assembly" and "assembly_acrylic" in HOURLY_RATES_GBP:
                _rate_key = "assembly_acrylic"
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


def estimate_part(part: Dict[str, Any]) -> Dict[str, Any]:
    debug = os.getenv("SCAN_DEBUG", "").lower() in {"1", "true", "yes"}
    quantity = _sanitise_part_quantity(part)
    part["quantity"] = quantity
    part_number = part.get("part_number") or part.get("item_number") or "unknown_part"
    if debug:
        print(f"[DEBUG] estimate_part start {part_number}")
    material = estimate_material(part)
    if debug:
        print(f"[DEBUG] estimate_part material done {part_number}")
    process = estimate_process_times(part, quantity=quantity)
    if debug:
        print(f"[DEBUG] estimate_part process done {part_number}")
    labour = estimate_labour_costs(process, job_quantity=quantity, material=part.get("normalized_material"))
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


def estimate_document(parts: List[Dict[str, Any]], summary: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    debug = os.getenv("SCAN_DEBUG", "").lower() in {"1", "true", "yes"}
    if summary is not None:
        bought_in_items = extract_bought_in_from_pages(summary, existing_part_records=parts)
        if bought_in_items:
            parts.extend(bought_in_items)
            if debug:
                print(f"[DEBUG] Bought-in items merged into estimate: {len(bought_in_items)} -> {[b.get('part_number') for b in bought_in_items]}")

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

    estimable_parts = [
        p for p in parts
        if _is_estimable_part(p) and not _is_weldment_parent_part(p, parts)
    ]
    skipped = len(parts) - len(estimable_parts)
    if skipped:
        print(f"   -> Skipped {skipped} junk part(s) with no material, dimensions, or operations")

    part_estimates: List[Dict[str, Any]] = []
    for idx, part in enumerate(estimable_parts, start=1):
        part_number = part.get("part_number") or part.get("item_number") or f"part_{idx}"
        if debug:
            print(
                f"[DEBUG] estimate_document start part {idx}/{len(estimable_parts)}: "
                f"{part_number} (+{round(time.time()-started,2)}s)"
            )
        part_estimate = estimate_part(part)
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
