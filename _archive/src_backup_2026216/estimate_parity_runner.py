from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List


def _index_parts(parts: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {str(item.get("part_number") or ""): item for item in parts if item.get("part_number")}


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def build_part_metric_variance(expected: Dict[str, Any], actual: Dict[str, Any]) -> List[Dict[str, Any]]:
    expected_parts = _index_parts(expected.get("parts", []))
    actual_parts = _index_parts(actual.get("parts", []))
    all_parts = sorted(set(expected_parts.keys()) | set(actual_parts.keys()))
    rows: List[Dict[str, Any]] = []

    metric_map = [
        ("material_cost_gbp", "material_cost_gbp"),
        ("labour_cost_gbp", "labour_cost_gbp"),
        ("unit_total_cost_gbp", "unit_total_cost_gbp"),
    ]
    for part_number in all_parts:
        exp = expected_parts.get(part_number, {})
        act = actual_parts.get(part_number, {})
        for metric_name, key in metric_map:
            exp_val = _to_float(exp.get(key))
            act_val = _to_float(act.get(key))
            abs_var = act_val - exp_val
            pct_var = (abs_var / exp_val * 100.0) if exp_val else None
            rows.append(
                {
                    "part_number": part_number,
                    "metric": metric_name,
                    "expected": round(exp_val, 4),
                    "actual": round(act_val, 4),
                    "variance": round(abs_var, 4),
                    "variance_pct": round(pct_var, 4) if pct_var is not None else None,
                }
            )
    return rows


def write_parity_reports(rows: List[Dict[str, Any]], out_csv: Path, out_json: Path) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    csv_fields = ["part_number", "metric", "expected", "actual", "variance", "variance_pct"]
    with out_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=csv_fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    with out_json.open("w", encoding="utf-8") as handle:
        json.dump(rows, handle, indent=2, ensure_ascii=False)
