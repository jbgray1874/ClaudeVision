"""
Demo-friendly rollups: where estimating numbers came from (SQL, spreadsheet template, config).

Read by stakeholders from JSON key: estimate_summary.estimate_source_extract
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

import config


def _safe_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", text)
    try:
        return float(cleaned) if cleaned else None
    except (TypeError, ValueError):
        return None


def _skip_workbook_template() -> bool:
    return os.environ.get("SDI_SKIP_WB_TEMPLATE", "").strip().lower() in {"1", "true", "yes"}


def _workbook_cache_path(workbook: Path) -> Path:
    return workbook.parent / f".{workbook.stem}_aimvision_cache.json"


# In-process cache — one parse per Python process when disk/env allow
_WB_TEMPLATE_CACHE: Optional[Dict[str, Any]] = None
_WB_TEMPLATE_CACHED: bool = False


def extract_workbook_headline_rates(parsed: Dict[str, Any]) -> Dict[str, Optional[float]]:
    sheet_steel_per_tonne: Optional[float] = None
    wire_per_tonne: Optional[float] = None
    for entry in parsed.get("parsed_entries", []):
        labels = " ".join(
            [
                str(entry.get("labels", {}).get("left", "")),
                str(entry.get("labels", {}).get("left_2", "")),
                str(entry.get("labels", {}).get("right", "")),
            ]
        ).upper()
        value = _safe_float(entry.get("value"))
        if value is None or value <= 0:
            continue
        if "SHEET STEEL" in labels and "TONNE" in labels:
            sheet_steel_per_tonne = value
        if "WIRE" in labels and "TONNE" in labels:
            wire_per_tonne = value
    out: Dict[str, Optional[float]] = {}
    if sheet_steel_per_tonne is not None:
        out["sheet_steel_gbp_per_tonne"] = sheet_steel_per_tonne
        out["sheet_steel_implied_gbp_per_kg"] = round(sheet_steel_per_tonne / 1000.0, 6)
    if wire_per_tonne is not None:
        out["wire_gbp_per_tonne"] = wire_per_tonne
        out["wire_implied_gbp_per_kg"] = round(wire_per_tonne / 1000.0, 6)
    return out


def _load_workbook_disk_cache(workbook: Path) -> Optional[Dict[str, Any]]:
    cache_file = _workbook_cache_path(workbook)
    if not cache_file.exists() or not workbook.exists():
        return None
    try:
        wb_mtime = workbook.stat().st_mtime
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        if abs(float(cached.get("_mtime", 0)) - wb_mtime) < 1.0:
            return {k: v for k, v in cached.items() if not str(k).startswith("_")}
    except Exception:
        pass
    return None


def _save_workbook_disk_cache(workbook: Path, result: Dict[str, Any]) -> None:
    if not result.get("parsed_ok"):
        return
    try:
        cache_data = dict(result)
        cache_data["_mtime"] = workbook.stat().st_mtime
        _workbook_cache_path(workbook).write_text(
            json.dumps(cache_data, default=str, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def workbook_template_extract_for_demo() -> Dict[str, Any]:
    """
    Template workbook metadata for demos — in-process + disk cache (cross-process).
    Set SDI_SKIP_WB_TEMPLATE=1 to skip entirely in batch mode.
    """
    global _WB_TEMPLATE_CACHE, _WB_TEMPLATE_CACHED
    if _WB_TEMPLATE_CACHED:
        return _WB_TEMPLATE_CACHE or {}

    if _skip_workbook_template():
        result = {"parsed_ok": False, "note": "Skipped: SDI_SKIP_WB_TEMPLATE=1"}
        _WB_TEMPLATE_CACHE = result
        _WB_TEMPLATE_CACHED = True
        return result

    ss = config.PRICE_SOURCE_CONFIG.get("spreadsheet", {})
    path_str = ss.get("template_workbook", "")
    workbook = Path(path_str) if path_str else None

    if workbook and workbook.exists():
        disk_hit = _load_workbook_disk_cache(workbook)
        if disk_hit is not None:
            _WB_TEMPLATE_CACHE = disk_hit
            _WB_TEMPLATE_CACHED = True
            return disk_hit

    result = _workbook_template_extract_impl()
    if workbook and workbook.exists():
        _save_workbook_disk_cache(workbook, result)

    _WB_TEMPLATE_CACHE = result
    _WB_TEMPLATE_CACHED = True
    return result


def _workbook_template_extract_impl() -> Dict[str, Any]:
    """Parse the template workbook via openpyxl (expensive — use caches above)."""
    ss = config.PRICE_SOURCE_CONFIG.get("spreadsheet", {})
    path_str = ss.get("template_workbook", "")
    enabled = bool(ss.get("enabled"))
    path = Path(path_str) if path_str else Path()
    base: Dict[str, Any] = {
        "spreadsheet_connector_enabled": enabled,
        "template_workbook_configured": bool(path_str),
        "template_workbook_path": str(path) if path_str else None,
        "template_exists": path.exists() if path_str else False,
        "parsed_ok": False,
    }
    if not enabled or not path_str or not path.exists():
        base["note"] = "Enable spreadsheet in PRICE_SOURCE_CONFIG and point template_workbook at your Blank Estimate workbook."
        return base

    try:
        from estimate_template_parser import parse_estimate_template

        parsed = parse_estimate_template(path)
    except Exception as exc:  # pragma: no cover
        base["parse_error"] = str(exc)
        return base

    kfs = parsed.get("key_formula_summary") or {}
    kc = parsed.get("key_cells") or {}
    base.update(
        {
            "parsed_ok": True,
            "workbook_name": parsed.get("workbook_name"),
            "sheet_names": parsed.get("sheet_names") or [],
            "formula_summary_counts": {
                "material_formulas": len(kfs.get("material_formulas") or []),
                "labour_formulas": len(kfs.get("labour_formulas") or []),
                "total_formulas": len(kfs.get("total_formulas") or []),
                "lookup_formulas": len(kfs.get("lookup_formulas") or []),
            },
            "key_cells_counts": {key: len(val or []) for key, val in kc.items()},
            "headline_rates_from_cells": extract_workbook_headline_rates(parsed),
        }
    )
    return base


def _material_price_origin(part_estimate: Dict[str, Any]) -> Dict[str, Any]:
    ps = part_estimate.get("material_estimate", {}).get("price_source") or {}
    applied = ps.get("applied")
    src = str(ps.get("source_name") or "").strip().lower()
    basis = ps.get("applied_basis")
    if applied and src:
        label = src
    elif applied:
        label = "resolved"
    else:
        label = "config_fallback_GBP_per_kg"
    return {
        "connector_or_origin": label,
        "supplier_display": ps.get("supplier_source"),
        "price_date": ps.get("price_date"),
        "applied": bool(applied),
        "basis": basis,
    }


def _labour_origins(part_estimate: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    rate_sources = part_estimate.get("labour_estimate", {}).get("rate_sources") or {}
    out: Dict[str, Dict[str, Any]] = {}
    for op, meta in rate_sources.items():
        if not isinstance(meta, dict):
            continue
        src = str(meta.get("source_name") or "").strip().lower()
        applied = meta.get("applied")
        out[str(op)] = {
            "connector_or_origin": src if applied and src else ("config_fallback_GBP_per_hour" if not applied else src),
            "hourly_rate_gbp": meta.get("hourly_rate_gbp"),
            "applied": bool(applied),
            "price_date": meta.get("price_date"),
        }
    return out


def _system_cost_origin(part_estimate: Dict[str, Any]) -> Dict[str, Any]:
    sc = part_estimate.get("cost_breakdown", {}).get("system_cost") or {}
    src_meta = sc.get("source") or {}
    unit = sc.get("unit_cost_gbp")
    return {
        "matched_part_code": sc.get("matched_part_code"),
        "unit_cost_gbp": unit,
        "supplier_code": src_meta.get("supplier_code"),
        "supplier_name": src_meta.get("supplier_source"),
        "connector": str(src_meta.get("source_name") or "").strip().lower() or None,
        "applied_lookup": bool(unit is not None and src_meta.get("applied")),
    }


def build_estimate_source_extract(part_estimates: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Roll up pricing provenance for demos: spreadsheet vs sqlserver vs config.
    """
    material_origins: Counter[str] = Counter()
    labour_origins: Counter[str] = Counter()
    system_hits = 0
    demo_parts: List[Dict[str, Any]] = []

    for pe in part_estimates:
        mo = _material_price_origin(pe)
        material_origins[mo["connector_or_origin"]] += 1

        lo = _labour_origins(pe)
        for _op, od in lo.items():
            labour_origins[od["connector_or_origin"]] += 1

        sc = _system_cost_origin(pe)
        if sc.get("unit_cost_gbp") is not None:
            system_hits += 1

        demo_parts.append(
            {
                "part_number": pe.get("part_number"),
                "description": pe.get("description"),
                "quantity": pe.get("quantity"),
                "costing_basis": pe.get("cost_breakdown", {}).get("costing_basis"),
                "unit_total_cost_gbp": pe.get("unit_total_cost_gbp"),
                "extended_total_cost_gbp": pe.get("extended_total_cost_gbp"),
                "material_price": mo,
                "labour_rates_by_operation": lo,
                "database_system_cost": sc,
            }
        )

    sql_cfg = config.PRICE_SOURCE_CONFIG.get("sqlserver", {})
    return {
        "purpose": "Where estimate figures were sourced (template workbook, SDILive, or config fallbacks).",
        "price_source_priority": list(config.PRICE_SOURCE_PRIORITY),
        "connectors": {
            "sqlserver": {
                "enabled": bool(sql_cfg.get("enabled")),
                "server": sql_cfg.get("server"),
                "database": sql_cfg.get("database"),
                "has_material_query": bool(sql_cfg.get("material_price_query")),
                "has_labour_query": bool(sql_cfg.get("labour_rate_query")),
                "has_part_system_cost_query": bool(sql_cfg.get("part_system_cost_query")),
            },
            "spreadsheet": {
                "enabled": bool(config.PRICE_SOURCE_CONFIG.get("spreadsheet", {}).get("enabled")),
                "template_workbook": config.PRICE_SOURCE_CONFIG.get("spreadsheet", {}).get("template_workbook"),
            },
        },
        "workbook_template": workbook_template_extract_for_demo(),
        "rollup_counts": {
            "parts": len(part_estimates),
            "material_price_by_connector": dict(material_origins),
            "labour_rate_selections_by_connector": dict(labour_origins),
            "parts_with_database_system_cost": system_hits,
        },
        "parts_for_demo": demo_parts,
    }
