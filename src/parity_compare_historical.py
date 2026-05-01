"""
Compare historical estimate-template parses against workbook totals and
report price-source connectivity from configured connectors.

Outputs a CSV to output/csv by default.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import config
from price_sources import PriceRequest, get_best_price


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        text = str(value).strip().replace("£", "").replace(",", "")
        if text in {"", "-", "None"}:
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def _pct_diff(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    if abs(a) < 1e-9:
        return None
    return round(abs(b - a) / abs(a) * 100.0, 2)


def _quote_key(source: str) -> str:
    h = hashlib.sha256(source.encode("utf-8")).hexdigest()[:40]
    return f"hq_{h}"


def _extract_totals(data: Dict[str, Any]) -> Dict[str, Optional[float]]:
    totals = (data.get("key_cells") or {}).get("totals") or []
    by_addr: Dict[str, Optional[float]] = {}
    for row in totals:
        addr = str(row.get("address") or "").upper()
        by_addr[addr] = _safe_float(row.get("value"))
    return {
        "l59_material_subtotal_gbp": by_addr.get("L59"),
        "l101_labour_subtotal_gbp": by_addr.get("L101"),
        "l105_unit_total_gbp": by_addr.get("L105"),
        "l111_sell_gbp": by_addr.get("L111"),
    }


def _sum_operation_rows(data: Dict[str, Any]) -> Optional[float]:
    ops = (data.get("key_cells") or {}).get("operation_rows") or []
    # L column entries hold per-row op cost in the estimate sheet.
    total = 0.0
    count = 0
    for row in ops:
        addr = str(row.get("address") or "").upper()
        if not addr.startswith("L"):
            continue
        v = _safe_float(row.get("value"))
        if v is None:
            continue
        total += v
        count += 1
    return round(total, 4) if count else None


def _sum_material_lines(data: Dict[str, Any]) -> Optional[float]:
    mats = (data.get("key_cells") or {}).get("material_unit_prices") or []
    total = 0.0
    count = 0
    for row in mats:
        v = _safe_float(row.get("value"))
        if v is None:
            continue
        total += v
        count += 1
    return round(total, 4) if count else None


def _workbook_equivalent(material_total: float, labour_total: float) -> Tuple[float, float]:
    cfg = config.WORKBOOK_EQUIVALENT_PRICING or {}
    fixed_factor = float(cfg.get("fixed_factor", 0.95))
    m107 = float(cfg.get("default_m107", 0.0))
    m109 = float(cfg.get("default_m109", 0.0))
    m105 = ((material_total + labour_total) / max(0.0001, (1.0 - m107))) / max(0.0001, fixed_factor)
    l111 = m105 / max(0.0001, (1.0 - m109))
    return round(m105, 4), round(l111, 4)


def _sample_db_price_sources(data: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "db_material_source": None,
        "db_material_price": None,
        "db_labour_source": None,
        "db_labour_price": None,
    }
    key_cells = data.get("key_cells") or {}

    # material probe
    material_hint = None
    for e in (data.get("parsed_entries") or [])[:2000]:
        labels = e.get("labels") or {}
        blob = " ".join(str(labels.get(k, "")) for k in ("left", "left_2", "right")).upper()
        if "MILD STEEL" in blob:
            material_hint = "MILD STEEL"
            break
        if "STAINLESS" in blob:
            material_hint = "STAINLESS STEEL"
            break
        if "ALUMIN" in blob:
            material_hint = "ALUMINIUM"
            break

    if material_hint:
        res = get_best_price(PriceRequest(kind="material_price", material=material_hint, thickness_mm=1.5, quantity=1))
        selected = res.get("selected") or {}
        out["db_material_source"] = selected.get("source")
        out["db_material_price"] = selected.get("price")

    # labour probe
    op = None
    for e in key_cells.get("operation_rows") or []:
        addr = str(e.get("address") or "").upper()
        if addr.startswith("F"):
            val = str(e.get("value") or "").strip()
            if val:
                op = val.lower()
                break
    if op:
        res = get_best_price(PriceRequest(kind="labour_rate", operation=op))
        selected = res.get("selected") or {}
        out["db_labour_source"] = selected.get("source")
        out["db_labour_price"] = selected.get("price")
    return out


def build_rows(root: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    files = sorted(root.rglob("*.formula_parse.json"))
    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        source = str(data.get("workbook_path") or path)
        totals = _extract_totals(data)
        labour_rows_total = _sum_operation_rows(data)
        material_lines_total = _sum_material_lines(data)
        if totals["l59_material_subtotal_gbp"] is not None and totals["l101_labour_subtotal_gbp"] is not None:
            model_m105, model_l111 = _workbook_equivalent(
                float(totals["l59_material_subtotal_gbp"]),
                float(totals["l101_labour_subtotal_gbp"]),
            )
        else:
            model_m105, model_l111 = None, None

        db_probe = _sample_db_price_sources(data)
        rows.append(
            {
                "quote_key": _quote_key(source),
                "workbook_name": data.get("workbook_name"),
                "source_json_path": str(path),
                "source_workbook_path": source,
                "wb_l59_material_subtotal_gbp": totals["l59_material_subtotal_gbp"],
                "wb_l101_labour_subtotal_gbp": totals["l101_labour_subtotal_gbp"],
                "wb_l105_unit_total_gbp": totals["l105_unit_total_gbp"],
                "wb_l111_sell_gbp": totals["l111_sell_gbp"],
                "rows_l_total_labour_gbp": labour_rows_total,
                "rows_material_lines_sum_gbp": material_lines_total,
                "model_m105_unit_total_gbp": model_m105,
                "model_l111_sell_gbp": model_l111,
                "var_pct_labour_rows_vs_l101": _pct_diff(totals["l101_labour_subtotal_gbp"], labour_rows_total),
                "var_pct_material_lines_vs_l59": _pct_diff(totals["l59_material_subtotal_gbp"], material_lines_total),
                "var_pct_model_m105_vs_l105": _pct_diff(totals["l105_unit_total_gbp"], model_m105),
                "var_pct_model_l111_vs_l111": _pct_diff(totals["l111_sell_gbp"], model_l111),
                "db_material_source": db_probe["db_material_source"],
                "db_material_price": db_probe["db_material_price"],
                "db_labour_source": db_probe["db_labour_source"],
                "db_labour_price": db_probe["db_labour_price"],
            }
        )
    return rows


def write_csv(rows: List[Dict[str, Any]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    headers = list(rows[0].keys()) if rows else [
        "quote_key",
        "workbook_name",
        "source_json_path",
    ]
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> None:
    parser = argparse.ArgumentParser(description="Historical workbook parity + DB source probe report")
    parser.add_argument("--root", required=True, help="Folder containing *.formula_parse.json files")
    parser.add_argument("--out", default=str(config.CSV_DIR / "historical_parity_report.csv"), help="CSV output path")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        raise SystemExit(f"Not a folder: {root}")

    rows = build_rows(root)
    out_path = Path(args.out).resolve()
    write_csv(rows, out_path)

    db_mat_hits = sum(1 for r in rows if str(r.get("db_material_source") or "").lower() == "sqlserver")
    db_lab_hits = sum(1 for r in rows if str(r.get("db_labour_source") or "").lower() == "sqlserver")
    print(f"Report rows: {len(rows)}")
    print(f"CSV: {out_path}")
    print(f"DB probe hits: material={db_mat_hits}/{len(rows)} labour={db_lab_hits}/{len(rows)}")


if __name__ == "__main__":
    main()

