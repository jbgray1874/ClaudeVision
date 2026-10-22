from __future__ import annotations

from typing import Any, Dict, List, Optional

import config


def _safe_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _variance_status(pct_variance: Optional[float]) -> str:
    if pct_variance is None:
        return "missing_manual"
    thresholds = config.WORKBOOK_EQUIVALENT_PRICING.get("variance_thresholds_pct", {})
    match_threshold = float(thresholds.get("match", 3.0))
    warning_threshold = float(thresholds.get("warning", 10.0))
    abs_pct = abs(pct_variance)
    if abs_pct <= match_threshold:
        return "match"
    if abs_pct <= warning_threshold:
        return "warning"
    return "fail"


def _build_metric_row(
    run_uuid: str,
    source_file_name: str,
    metric_name: str,
    ai_value: Optional[float],
    manual_value: Optional[float],
    comparison_scope: str = "document",
    part_number: Optional[str] = None,
    manual_source: Optional[str] = None,
    ai_source: Optional[str] = None,
) -> Dict[str, Any]:
    ai_num = _safe_float(ai_value)
    manual_num = _safe_float(manual_value)
    abs_variance = None
    pct_variance = None
    if ai_num is not None and manual_num is not None:
        abs_variance = round(ai_num - manual_num, 4)
        pct_variance = round(((ai_num - manual_num) / manual_num) * 100.0, 4) if manual_num != 0 else None

    return {
        "run_uuid": run_uuid,
        "source_file_name": source_file_name,
        "part_number": part_number,
        "comparison_scope": comparison_scope,
        "metric_name": metric_name,
        "manual_value": manual_num,
        "ai_value": ai_num,
        "abs_variance": abs_variance,
        "pct_variance": pct_variance,
        "status": _variance_status(pct_variance),
        "notes": None if manual_num is not None else "manual benchmark not provided",
        "manual_source": manual_source,
        "ai_source": ai_source,
    }


def build_pricing_variance_rows(summary: Dict[str, Any], manual_benchmark: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    manual = manual_benchmark or summary.get("manual_benchmark", {}) or {}
    metadata = summary.get("run_metadata", {})
    run_uuid = str(metadata.get("run_uuid") or "")
    source_file_name = str(summary.get("source_file") or "")
    estimate = summary.get("estimate_summary", {})
    cost_breakdown = estimate.get("cost_breakdown", {})
    workbook_equiv = estimate.get("workbook_equivalent_pricing", {})
    rows: List[Dict[str, Any]] = []

    rows.append(
        _build_metric_row(
            run_uuid,
            source_file_name,
            "total_unit_cost",
            ai_value=workbook_equiv.get("l105_total_unit_cost_gbp"),
            manual_value=manual.get("l105_total_unit_cost_gbp"),
            manual_source=manual.get("source"),
            ai_source="workbook_equivalent_pricing",
        )
    )
    rows.append(
        _build_metric_row(
            run_uuid,
            source_file_name,
            "sell_price",
            ai_value=workbook_equiv.get("l111_sell_price_gbp"),
            manual_value=manual.get("l111_sell_price_gbp"),
            manual_source=manual.get("source"),
            ai_source="workbook_equivalent_pricing",
        )
    )
    rows.append(
        _build_metric_row(
            run_uuid,
            source_file_name,
            "labour_hours_total",
            ai_value=workbook_equiv.get("labour_hours_total"),
            manual_value=manual.get("labour_hours_total"),
            manual_source=manual.get("source"),
            ai_source="estimate_summary.cost_breakdown.labour",
        )
    )
    rows.append(
        _build_metric_row(
            run_uuid,
            source_file_name,
            "material_subtotal",
            ai_value=cost_breakdown.get("material", {}).get("total"),
            manual_value=manual.get("material_subtotal_gbp"),
            manual_source=manual.get("source"),
            ai_source="estimate_summary.cost_breakdown.material",
        )
    )
    return rows

