"""
Load completed estimate workbook parses (*.formula_parse.json) into dbo.historical_quote_* tables.

Input JSON is produced by:
  python src/main.py --parse-estimate-template "C:\\path\\to\\Quote.xlsx"
which writes:  Quote.formula_parse.json  next to the workbook (or pass output path).

Batch all parses under one folder (recursive), then:
  python src/load_historical_quotes.py --root "D:\\estimates\\parsed"

Requires: pyodbc, tables from historical_quote_ddl.sql.

Optional (recommended): run sql/historical_quote_add_readable_extract.sql so the loader can store
pretty-printed reconciliation JSON on the header row. If that column is missing, loads still work;
only the long-form JSON summary is omitted from SQL.

Optional: sql/historical_quote_reconciliation_view.sql for a simple SSMS browse view.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import config

try:
    import pyodbc  # type: ignore
except ImportError:
    pyodbc = None


def _is_sql_permission_error(exc: Exception) -> bool:
    msg = str(exc).upper()
    return (
        "PERMISSION WAS DENIED" in msg
        or "(229)" in msg
        or "SQLSTATE=42000" in msg
    )


def _connect():
    if pyodbc is None:
        raise RuntimeError("pyodbc is required for load_historical_quotes")
    c = config.PRICE_SOURCE_CONFIG.get("sqlserver", {})
    conn_str = (
        f"DRIVER={{{c.get('driver', 'ODBC Driver 18 for SQL Server')}}};"
        f"SERVER={c.get('server', '')};"
        f"DATABASE={c.get('database', '')};"
        f"UID={c.get('username', '')};"
        f"PWD={c.get('password', '')};"
        f"Encrypt={'yes' if c.get('encrypt', True) else 'no'};"
        f"TrustServerCertificate={'yes' if c.get('trust_server_certificate', True) else 'no'};"
    )
    return pyodbc.connect(conn_str, timeout=30)


def _detect_readable_extract_column(conn) -> bool:
    cur = conn.cursor()
    cur.execute(
        """
SELECT 1
FROM sys.columns c
INNER JOIN sys.tables t ON c.object_id = t.object_id
WHERE SCHEMA_NAME(t.schema_id) = N'dbo'
  AND t.name = N'historical_quote_header'
  AND c.name = N'readable_extract_json';
"""
    )
    return cur.fetchone() is not None


def _detect_detailed_line_tables(conn) -> bool:
    cur = conn.cursor()
    cur.execute(
        """
SELECT COUNT(*) AS c
FROM sys.tables t
INNER JOIN sys.schemas s ON t.schema_id = s.schema_id
WHERE s.name = N'dbo'
  AND t.name IN (N'historical_quote_material_line', N'historical_quote_labour_line');
"""
    )
    row = cur.fetchone()
    return bool(row and int(row[0]) == 2)


def _reconciliation_sidecar_path(json_path: Path) -> Path:
    name = json_path.name
    if name.endswith(".formula_parse.json"):
        return json_path.with_name(name.replace(".formula_parse.json", ".reconciliation.json", 1))
    return json_path.with_suffix(".reconciliation.json")


def _quote_key(json_path: Path, data: Dict[str, Any]) -> str:
    base = str(data.get("workbook_path") or json_path.with_suffix("").stem)
    h = hashlib.sha256(base.encode("utf-8")).hexdigest()[:40]
    return f"hq_{h}"


def _parse_money(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    s = re.sub(r"[£$,]", "", str(value).strip())
    s = s.replace(" ", "")
    try:
        return float(s) if s and s != "-" else None
    except ValueError:
        return None


def _parse_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        return float(value)
    try:
        return float(str(value).strip().replace(",", ""))
    except ValueError:
        return None


def _row_from_address(address: str) -> Optional[int]:
    m = re.search(r"(\d+)$", str(address).upper())
    return int(m.group(1)) if m else None


def _col_from_address(address: str) -> Optional[str]:
    m = re.match(r"^([A-Z]+)", str(address).upper())
    return m.group(1) if m else None


def _extract_header_fields(data: Dict[str, Any]) -> Dict[str, Any]:
    drawing_number = None
    customer_name = None
    revision = None
    for entry in data.get("parsed_entries", []):
        if str(entry.get("sheet", "")).upper() != "ESTIMATE":
            continue
        labels = entry.get("labels") or {}
        blob = " ".join(
            str(labels.get(k, "")) for k in ("left", "left_2", "right")
        ).upper()
        if drawing_number is None and "DWG" in blob and "NO" in blob:
            # neighbour cells often hold value in label_right
            v = str(labels.get("right") or labels.get("left") or "").strip()
            if v and len(v) < 120:
                drawing_number = v
        if customer_name is None and "CLIENT" in blob:
            v = str(labels.get("right") or "").strip()
            if v and len(v) < 200:
                customer_name = v
        if revision is None and "REV" in blob and "ISION" not in blob:
            v = str(labels.get("right") or "").strip()
            if v and len(v) < 50:
                revision = v

    totals = (data.get("key_cells") or {}).get("totals") or []
    total_unit = None
    material_sub = None
    labour_sub = None
    for t in totals:
        addr = str(t.get("address", "")).upper()
        if addr == "L105":
            total_unit = _parse_money(t.get("value"))
        if addr == "L59":
            material_sub = _parse_money(t.get("value"))
        if addr == "L101":
            labour_sub = _parse_money(t.get("value"))

    return {
        "drawing_number": drawing_number,
        "customer_name": customer_name,
        "revision": revision,
        "total_unit_cost_gbp": total_unit,
        "material_subtotal_gbp": material_sub,
        "labour_subtotal_gbp": labour_sub,
    }


def _group_labour_operations(key_cells: Dict[str, Any]) -> List[Dict[str, Any]]:
    by_row: Dict[int, Dict[str, Any]] = defaultdict(dict)
    for entry in key_cells.get("operation_rows") or []:
        addr = str(entry.get("address", ""))
        row = _row_from_address(addr)
        col = _col_from_address(addr)
        if row is None or col is None:
            continue
        by_row[row][col] = entry

    out: List[Dict[str, Any]] = []
    for row in sorted(by_row):
        cells = by_row[row]
        f = cells.get("F") or cells.get("E") or {}
        op_val = str(f.get("value") or "").strip()
        if not op_val or op_val in {"0", "-"}:
            continue
        rate = _parse_money((cells.get("J") or {}).get("value"))
        run_hours = _parse_float((cells.get("I") or {}).get("value"))
        cost = _parse_money((cells.get("L") or {}).get("value"))
        setup_min = _parse_float((cells.get("K") or {}).get("value"))
        labels = (cells.get("F") or {}).get("labels") or {}
        desc_bits = [str(labels.get(k, "")).strip() for k in ("left", "left_2", "right")]
        desc = " | ".join(b for b in desc_bits if b)
        out.append(
            {
                "estimate_row": row,
                "operation_code": op_val,
                "description_hint": desc,
                "hourly_rate_gbp": rate,
                "run_hours": run_hours,
                "setup_min": setup_min,
                "operation_cost_gbp": cost,
            }
        )
    return out


def _material_lines(key_cells: Dict[str, Any]) -> List[Dict[str, Any]]:
    lines: List[Dict[str, Any]] = []
    for entry in key_cells.get("material_unit_prices") or []:
        addr = str(entry.get("address", ""))
        row = _row_from_address(addr)
        labels = entry.get("labels") or {}
        blob = " ".join(str(labels.get(k, "")) for k in ("left", "left_2", "right"))
        price = _parse_money(entry.get("value"))
        lines.append(
            {
                "estimate_row": row,
                "label_context": blob.strip()[:500],
                "unit_price_gbp": price,
                "address": addr,
            }
        )
    return lines


def _build_estimate_row_index(data: Dict[str, Any]) -> Dict[int, Dict[str, Dict[str, Any]]]:
    out: Dict[int, Dict[str, Dict[str, Any]]] = defaultdict(dict)
    for entry in data.get("parsed_entries") or []:
        if str(entry.get("sheet", "")).upper() != "ESTIMATE":
            continue
        addr = str(entry.get("address", ""))
        row = _row_from_address(addr)
        col = _col_from_address(addr)
        if row is None or col is None:
            continue
        out[row][col] = entry
    return out


def _numeric_from_cell(cell: Dict[str, Any]) -> Optional[float]:
    if not isinstance(cell, dict):
        return None
    for k in (
        "value",
        "numeric_value",
        "evaluated_value",
        "formula_value",
        "computed_value",
        "calc_value",
        "result",
        "resolved_value",
        "raw_value",
    ):
        v = _parse_money(cell.get(k))
        if v is not None:
            return v
    labels = cell.get("labels") or {}
    for k in ("right", "left_2", "left"):
        v = _parse_money(labels.get(k))
        if v is not None:
            return v
    return None


def _qty_from_description(desc: str) -> Optional[float]:
    if not desc:
        return None
    parts = [p.strip() for p in desc.split("|") if p and p.strip()]
    for p in reversed(parts):
        q = _parse_float(p)
        if q is not None:
            return q
    m = re.search(r"(\d+(?:\.\d+)?)\s*$", desc)
    if m:
        return _parse_float(m.group(1))
    return None


def _norm_text(value: str) -> str:
    s = re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper()).strip()
    return re.sub(r"\s+", " ", s)


def _token_set(value: str) -> set[str]:
    return {t for t in _norm_text(value).split(" ") if t and len(t) >= 2}


def _build_material_price_break_key_map(data: Dict[str, Any]) -> Dict[str, float]:
    by_row: Dict[int, Dict[str, Dict[str, Any]]] = defaultdict(dict)
    for entry in data.get("parsed_entries") or []:
        if str(entry.get("sheet", "")).upper() != "MATERIAL PRICE BREAK":
            continue
        row = _row_from_address(str(entry.get("address", "")))
        col = _col_from_address(str(entry.get("address", "")))
        if row is None or col is None:
            continue
        by_row[row][col] = entry

    out: Dict[str, float] = {}
    for row, cols in by_row.items():
        b = cols.get("B") or {}
        desc = str(b.get("value") or "").strip()
        if not desc:
            continue
        price_candidates: List[float] = []
        # Some parses place resolved cost in label_right on B-row.
        labels = b.get("labels") or {}
        for k in ("right", "left_2", "left"):
            v = _parse_money(labels.get(k))
            if v is not None and v > 0:
                price_candidates.append(v)
        # Also inspect C..I row values as possible break prices.
        for col in ("C", "D", "E", "F", "G", "H", "I"):
            v = _numeric_from_cell(cols.get(col) or {})
            if v is not None and v > 0:
                price_candidates.append(v)
        if not price_candidates:
            continue
        # Prefer smallest positive candidate as unit-ish price.
        p = min(price_candidates)
        key = _norm_text(desc)
        if key:
            out[key] = p
    return out


def _resolve_missing_material_prices_from_price_break(
    mats_detailed: List[Dict[str, Any]],
    price_break_map: Dict[str, float],
) -> List[Dict[str, Any]]:
    if not price_break_map:
        return mats_detailed
    map_items = [(k, _token_set(k), v) for k, v in price_break_map.items()]
    resolved: List[Dict[str, Any]] = []
    for m in mats_detailed:
        if m.get("unit_price_gbp") is not None and m.get("line_total_gbp") is not None:
            resolved.append(m)
            continue
        desc = str(m.get("line_description") or "")
        tok = _token_set(desc)
        best_price: Optional[float] = None
        best_score = 0.0
        if tok:
            for _k, ktok, price in map_items:
                inter = len(tok.intersection(ktok))
                if inter == 0:
                    continue
                score = inter / max(1, len(tok))
                if score > best_score:
                    best_score = score
                    best_price = price
        if best_price is not None and best_score >= 0.34:
            qty = _parse_float(m.get("qty_per_unit"))
            if qty is None or qty <= 0:
                qty = 1.0
            if m.get("unit_price_gbp") is None:
                m["unit_price_gbp"] = round(float(best_price), 6)
            if m.get("line_total_gbp") is None:
                scrap = _parse_float(m.get("scrap_pct")) or 0.0
                m["line_total_gbp"] = round(float(best_price) * float(qty) * (1.0 + (float(scrap) / 100.0)), 4)
            raw = m.get("raw") or {}
            if isinstance(raw, dict):
                raw["price_break_resolved"] = True
                raw["price_break_match_score"] = round(float(best_score), 4)
        resolved.append(m)
    return resolved


def _impute_material_prices_from_historical_db(
    cursor,
    mats_detailed: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    # Build lightweight in-memory map from existing loaded rows.
    cursor.execute(
        """
SELECT line_description, unit_price_gbp
FROM dbo.historical_quote_material_line
WHERE unit_price_gbp IS NOT NULL
  AND line_description IS NOT NULL
  AND LTRIM(RTRIM(line_description)) <> '';
"""
    )
    rows = cursor.fetchall()
    if not rows:
        return mats_detailed
    price_by_key: Dict[str, List[float]] = defaultdict(list)
    for r in rows:
        desc = str(r[0] or "").strip()
        price = _parse_float(r[1])
        if not desc or price is None or price <= 0:
            continue
        k = _norm_text(desc)
        if k:
            price_by_key[k].append(float(price))

    avg_price_by_key: Dict[str, float] = {
        k: round(sum(v) / len(v), 6) for k, v in price_by_key.items() if v
    }
    keyed = [(k, _token_set(k), p) for k, p in avg_price_by_key.items()]

    out: List[Dict[str, Any]] = []
    for m in mats_detailed:
        if m.get("unit_price_gbp") is not None and m.get("line_total_gbp") is not None:
            out.append(m)
            continue
        desc = str(m.get("line_description") or "")
        tok = _token_set(desc)
        if not tok:
            out.append(m)
            continue
        best_price: Optional[float] = None
        best_score = 0.0
        for _k, ktok, p in keyed:
            inter = len(tok.intersection(ktok))
            if inter == 0:
                continue
            score = inter / max(1, len(tok))
            if score > best_score:
                best_score = score
                best_price = p
        if best_price is not None and best_score >= 0.5:
            qty = _parse_float(m.get("qty_per_unit"))
            if qty is None or qty <= 0:
                qty = 1.0
            if m.get("unit_price_gbp") is None:
                m["unit_price_gbp"] = round(float(best_price), 6)
            if m.get("line_total_gbp") is None:
                scrap = _parse_float(m.get("scrap_pct")) or 0.0
                m["line_total_gbp"] = round(float(best_price) * float(qty) * (1.0 + (float(scrap) / 100.0)), 4)
            raw = m.get("raw") or {}
            if isinstance(raw, dict):
                raw["historical_imputed_price"] = True
                raw["historical_imputed_score"] = round(float(best_score), 4)
        out.append(m)
    return out


def _detect_material_row_upper_bound(data: Dict[str, Any]) -> int:
    # Default legacy estimate layout material subtotal row.
    upper = 59
    totals = ((data.get("key_cells") or {}).get("totals")) or []
    for t in totals:
        addr = str(t.get("address", "")).upper()
        if addr.startswith("L"):
            row = _row_from_address(addr)
            if row and 20 <= row <= 120:
                upper = min(upper, row)
    entries = data.get("parsed_entries") or []
    for e in entries:
        if str(e.get("sheet", "")).upper() != "ESTIMATE":
            continue
        blob = " ".join(
            [
                str(e.get("value") or ""),
                str((e.get("labels") or {}).get("left") or ""),
                str((e.get("labels") or {}).get("left_2") or ""),
                str((e.get("labels") or {}).get("right") or ""),
            ]
        ).upper()
        if "MATERIAL" in blob and "SUB" in blob and "TOTAL" in blob:
            row = _row_from_address(str(e.get("address", "")))
            if row and 20 <= row <= 140:
                upper = min(upper, row)
    return upper


def _material_price_break_by_row(data: Dict[str, Any]) -> Dict[int, float]:
    out: Dict[int, float] = {}
    formulas = ((data.get("estimate_sheet") or {}).get("formulas")) or []
    for f in formulas:
        addr = str(f.get("address", "")).upper()
        row = _row_from_address(addr)
        if row is None or not addr.startswith("I"):
            continue
        formula = str(f.get("formula") or "").upper()
        if "MATERIAL PRICE BREAK" not in formula:
            continue
        v = _parse_money(f.get("value"))
        if v is not None and v > 0:
            out[row] = v
    return out


def _material_lines_detailed(
    key_cells: Dict[str, Any],
    estimate_row_index: Optional[Dict[int, Dict[str, Dict[str, Any]]]] = None,
) -> List[Dict[str, Any]]:
    by_row: Dict[int, Dict[str, Any]] = defaultdict(dict)
    for entry in key_cells.get("material_unit_prices") or []:
        addr = str(entry.get("address", ""))
        row = _row_from_address(addr)
        col = _col_from_address(addr)
        if row is None or col is None:
            continue
        by_row[row][col] = entry

    out: List[Dict[str, Any]] = []
    for row in sorted(by_row):
        cells = dict(by_row[row])
        fallback_cells = (estimate_row_index or {}).get(row) or {}
        for col, fb in fallback_cells.items():
            if col not in cells:
                cells[col] = fb
            else:
                cur_val = str((cells[col] or {}).get("value") or "").strip()
                if cur_val in {"", "-", "0"}:
                    cells[col] = fb
        primary = cells.get("J") or cells.get("I") or next(iter(cells.values()), {})
        labels = primary.get("labels") or {}
        line_desc = " | ".join(
            v for v in [str(labels.get("left", "")).strip(), str(labels.get("left_2", "")).strip(), str(labels.get("right", "")).strip()] if v
        )
        if not line_desc:
            desc_candidates: List[str] = []
            for c in ("F", "G", "H", "I", "J", "K"):
                cell = cells.get(c) or {}
                raw = str(cell.get("value") or "").strip()
                if raw and _parse_money(raw) is None and len(raw) <= 200:
                    desc_candidates.append(raw)
                cl = cell.get("labels") or {}
                for lk in ("left", "left_2", "right"):
                    t = str(cl.get(lk) or "").strip()
                    if t and _parse_money(t) is None and len(t) <= 200:
                        desc_candidates.append(t)
            if desc_candidates:
                seen = []
                for t in desc_candidates:
                    if t not in seen:
                        seen.append(t)
                line_desc = " | ".join(seen[:4])
        unit_price = None
        for col in ("J", "I", "H", "G", "F", "K", "M", "N", "O", "P"):
            unit_price = _numeric_from_cell(cells.get(col) or {})
            if unit_price is not None:
                break
        qty_per_unit = _parse_float((cells.get("K") or {}).get("value"))
        if qty_per_unit is None:
            qty_per_unit = _numeric_from_cell(cells.get("H") or {})
        if qty_per_unit is None:
            qty_per_unit = _qty_from_description(line_desc)
        if qty_per_unit is None:
            qty_per_unit = 1.0
        scrap_raw = _parse_float((cells.get("L") or {}).get("value"))
        scrap_pct = scrap_raw if scrap_raw is not None and 0 <= scrap_raw <= 100 else 0.0
        total_val = None
        for col in ("L", "M", "N"):
            total_val = _numeric_from_cell(cells.get(col) or {})
            if total_val is not None:
                break
        if total_val is None:
            # Last-chance: use the largest numeric on the row as likely line total.
            nums: List[float] = []
            for col in ("F", "G", "H", "I", "J", "K", "L", "M", "N", "O", "P"):
                v = _numeric_from_cell(cells.get(col) or {})
                if v is not None and v > 0:
                    nums.append(v)
            if nums:
                total_val = max(nums)
        if total_val is None and unit_price is not None:
            total_val = round(unit_price * qty_per_unit * (1.0 + (scrap_pct / 100.0)), 4)
        if unit_price is None and total_val is not None and qty_per_unit not in (None, 0):
            unit_price = round(float(total_val) / float(qty_per_unit), 6)
        out.append(
            {
                "line_no": row,
                "source_sheet": "Estimate",
                "source_cell_ref": f"ROW_{row}",
                "part_code": None,
                "line_description": line_desc[:1000] if line_desc else None,
                "supplier_name": None,
                "unit": "GBP_per_unit",
                "unit_price_gbp": unit_price,
                "qty_per_unit": qty_per_unit,
                "scrap_pct": scrap_pct,
                "line_total_gbp": total_val,
                "raw": cells,
            }
        )
    return out


def _labour_lines_detailed(key_cells: Dict[str, Any]) -> List[Dict[str, Any]]:
    by_row: Dict[int, Dict[str, Any]] = defaultdict(dict)
    for entry in key_cells.get("operation_rows") or []:
        addr = str(entry.get("address", ""))
        row = _row_from_address(addr)
        col = _col_from_address(addr)
        if row is None or col is None:
            continue
        by_row[row][col] = entry

    out: List[Dict[str, Any]] = []
    for row in sorted(by_row):
        cells = by_row[row]
        op_cell = cells.get("F") or cells.get("E") or {}
        op_code = str(op_cell.get("value") or "").strip() or None
        if op_code in {None, "", "-", "0"}:
            continue
        labels = op_cell.get("labels") or {}
        desc = " | ".join(v for v in [str(labels.get("left", "")).strip(), str(labels.get("left_2", "")).strip(), str(labels.get("right", "")).strip()] if v)
        qty_per = _parse_float((cells.get("H") or {}).get("value")) or 1.0
        rate = _parse_money((cells.get("J") or {}).get("value"))
        total_hours = _parse_float((cells.get("I") or {}).get("value"))
        setup_mins = _parse_float((cells.get("K") or {}).get("value"))
        line_total = _parse_money((cells.get("L") or {}).get("value"))
        out.append(
            {
                "line_no": row,
                "source_sheet": "Estimate",
                "source_cell_ref": f"ROW_{row}",
                "operation_code": op_code,
                "department_code": op_code,
                "part_description": desc[:1000] if desc else None,
                "qty_per_unit": qty_per,
                "rate_per_hour_gbp": rate,
                "total_hours": total_hours,
                "setup_mins": setup_mins,
                "line_total_gbp": line_total,
                "raw": cells,
            }
        )
    return out


def _material_lines_from_estimate_formulas(
    data: Dict[str, Any],
    estimate_row_index: Dict[int, Dict[str, Dict[str, Any]]],
    material_row_upper_bound: int,
    material_price_break_lookup: Dict[int, float],
) -> List[Dict[str, Any]]:
    formulas = ((data.get("estimate_sheet") or {}).get("formulas")) or []
    out: List[Dict[str, Any]] = []
    seen_rows: set[int] = set()
    for f in formulas:
        addr = str(f.get("address", ""))
        row = _row_from_address(addr)
        col = _col_from_address(addr)
        if row is None or col != "L":
            continue
        # Material block in these templates is generally above the subtotal band.
        if row >= material_row_upper_bound or row < 8:
            continue
        cells = estimate_row_index.get(row) or {}
        desc_parts: List[str] = []
        for c in ("F", "G", "H", "I"):
            cell = cells.get(c) or {}
            raw = str(cell.get("value") or "").strip()
            if raw and _parse_money(raw) is None:
                desc_parts.append(raw)
            labels = cell.get("labels") or {}
            for lk in ("left", "left_2", "right"):
                t = str(labels.get(lk) or "").strip()
                if t and _parse_money(t) is None:
                    desc_parts.append(t)
        line_desc = " | ".join(dict.fromkeys(desc_parts))[:1000] if desc_parts else None
        unit_price = _numeric_from_cell(cells.get("J") or {})
        if unit_price is None:
            unit_price = material_price_break_lookup.get(row)
        qty_per_unit = _numeric_from_cell(cells.get("K") or {})
        if qty_per_unit is None:
            qty_per_unit = _parse_float(f.get("label_left_2"))
        if qty_per_unit is None:
            qty_per_unit = _qty_from_description(line_desc or "")
        if qty_per_unit is None:
            qty_per_unit = 1.0
        scrap_pct = _parse_float(f.get("label_left"))
        if scrap_pct is None or scrap_pct < 0 or scrap_pct > 100:
            scrap_pct = 0.0
        total_val = _parse_money(f.get("value"))
        if total_val is None:
            total_val = _numeric_from_cell(cells.get("L") or {})
        if total_val is None and unit_price is not None and qty_per_unit not in (None, 0):
            total_val = round(float(unit_price) * float(qty_per_unit) * (1.0 + (float(scrap_pct) / 100.0)), 4)
        if unit_price is None and total_val is not None and qty_per_unit not in (None, 0):
            unit_price = round(float(total_val) / float(qty_per_unit), 6)
        out.append(
            {
                "line_no": row,
                "source_sheet": "Estimate",
                "source_cell_ref": f"L{row}",
                "part_code": None,
                "line_description": line_desc,
                "supplier_name": None,
                "unit": "GBP_per_unit",
                "unit_price_gbp": unit_price,
                "qty_per_unit": qty_per_unit,
                "scrap_pct": scrap_pct,
                "line_total_gbp": total_val,
                "raw": {"formula_row": f, "row_cells": cells},
            }
        )
        seen_rows.add(row)

    # Fallback for variants where parser does not emit expected L-cell formulas:
    # inspect estimate row index directly and synthesize material rows from row cells.
    for row, cells in sorted(estimate_row_index.items()):
        if row in seen_rows:
            continue
        if row >= material_row_upper_bound or row < 8:
            continue
        l_cell = cells.get("L") or {}
        l_total = _numeric_from_cell(l_cell)
        if l_total is None:
            continue
        desc_parts: List[str] = []
        for c in ("F", "G", "H", "I"):
            cell = cells.get(c) or {}
            raw = str(cell.get("value") or "").strip()
            if raw and _parse_money(raw) is None:
                desc_parts.append(raw)
            labels = cell.get("labels") or {}
            for lk in ("left", "left_2", "right"):
                t = str(labels.get(lk) or "").strip()
                if t and _parse_money(t) is None:
                    desc_parts.append(t)
        line_desc = " | ".join(dict.fromkeys(desc_parts))[:1000] if desc_parts else None
        qty_per_unit = _numeric_from_cell(cells.get("K") or {})
        if qty_per_unit is None:
            qty_per_unit = _numeric_from_cell(cells.get("H") or {})
        if qty_per_unit is None:
            qty_per_unit = _qty_from_description(line_desc or "")
        if qty_per_unit is None:
            qty_per_unit = 1.0
        unit_price = _numeric_from_cell(cells.get("J") or {})
        if unit_price is None:
            unit_price = material_price_break_lookup.get(row)
        if unit_price is None and qty_per_unit not in (None, 0):
            unit_price = round(float(l_total) / float(qty_per_unit), 6)
        out.append(
            {
                "line_no": row,
                "source_sheet": "Estimate",
                "source_cell_ref": f"L{row}",
                "part_code": None,
                "line_description": line_desc,
                "supplier_name": None,
                "unit": "GBP_per_unit",
                "unit_price_gbp": unit_price,
                "qty_per_unit": qty_per_unit,
                "scrap_pct": 0.0,
                "line_total_gbp": l_total,
                "raw": {"row_cells": cells, "fallback_mode": "row_index_l_cell"},
            }
        )
    return out


def _merge_material_line_candidates(lines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    best_by_row: Dict[int, Dict[str, Any]] = {}
    for line in lines:
        row = int(line.get("line_no") or 0)
        if row <= 0:
            continue
        prev = best_by_row.get(row)
        cur_score = int(line.get("unit_price_gbp") is not None) + int(line.get("line_total_gbp") is not None)
        prev_score = 0
        if prev is not None:
            prev_score = int(prev.get("unit_price_gbp") is not None) + int(prev.get("line_total_gbp") is not None)
        if prev is None or cur_score > prev_score:
            best_by_row[row] = line
    return [best_by_row[k] for k in sorted(best_by_row)]


def _build_readable_payload(
    data: Dict[str, Any],
    header: Dict[str, Any],
    ops: List[Dict[str, Any]],
    mats: List[Dict[str, Any]],
    mats_detailed: List[Dict[str, Any]],
    labour_detailed: List[Dict[str, Any]],
    json_path: Path,
) -> Dict[str, Any]:
    """Structured JSON for drawing ↔ spreadsheet reconciliation (kept out of the giant raw parse blob)."""
    reconciliation = {
        "drawing_number": header.get("drawing_number"),
        "customer_name": header.get("customer_name"),
        "revision": header.get("revision"),
        "totals_gbp": {
            "unit_total": header.get("total_unit_cost_gbp"),
            "material_subtotal": header.get("material_subtotal_gbp"),
            "labour_subtotal": header.get("labour_subtotal_gbp"),
        },
        "labour": [
            {
                "estimate_row": o.get("estimate_row"),
                "operation_code": o.get("operation_code"),
                "description_hint": o.get("description_hint"),
                "hourly_rate_gbp": o.get("hourly_rate_gbp"),
                "run_hours": o.get("run_hours"),
                "setup_min": o.get("setup_min"),
                "operation_cost_gbp": o.get("operation_cost_gbp"),
            }
            for o in ops
        ],
        "materials": [
            {
                "estimate_row": m.get("estimate_row"),
                "label_context": m.get("label_context"),
                "unit_price_gbp": m.get("unit_price_gbp"),
                "cell": m.get("address"),
            }
            for m in mats
        ],
        "material_lines_detailed": [
            {
                "line_no": m.get("line_no"),
                "part_code": m.get("part_code"),
                "line_description": m.get("line_description"),
                "supplier_name": m.get("supplier_name"),
                "unit": m.get("unit"),
                "unit_price_gbp": m.get("unit_price_gbp"),
                "qty_per_unit": m.get("qty_per_unit"),
                "scrap_pct": m.get("scrap_pct"),
                "line_total_gbp": m.get("line_total_gbp"),
                "source_cell_ref": m.get("source_cell_ref"),
            }
            for m in mats_detailed
        ],
        "labour_lines_detailed": [
            {
                "line_no": l.get("line_no"),
                "operation_code": l.get("operation_code"),
                "department_code": l.get("department_code"),
                "part_description": l.get("part_description"),
                "qty_per_unit": l.get("qty_per_unit"),
                "rate_per_hour_gbp": l.get("rate_per_hour_gbp"),
                "total_hours": l.get("total_hours"),
                "setup_mins": l.get("setup_mins"),
                "line_total_gbp": l.get("line_total_gbp"),
                "source_cell_ref": l.get("source_cell_ref"),
            }
            for l in labour_detailed
        ],
    }
    historical_comparison_projection = {
        "schema": "estimate_projection_for_historical.v1",
        "totals": {
            "material_subtotal_gbp": header.get("material_subtotal_gbp"),
            "labour_subtotal_gbp": header.get("labour_subtotal_gbp"),
            "workbook_equivalent_total_unit_cost_gbp": header.get("total_unit_cost_gbp"),
            "document_total_estimated_cost_gbp": header.get("total_unit_cost_gbp"),
        },
        "parts": [
            {
                "part_number": "__WORKBOOK_SUMMARY__",
                "description": data.get("workbook_name"),
                "quantity": 1,
                "unit_total_cost_gbp": header.get("total_unit_cost_gbp"),
                "extended_total_cost_gbp": header.get("total_unit_cost_gbp"),
                "material_cost_gbp": header.get("material_subtotal_gbp"),
                "labour_cost_gbp": header.get("labour_subtotal_gbp"),
                "costing_basis": "historical_workbook_parse",
                "operations_costs_gbp": {
                    str(o.get("operation_code") or f"ROW_{o.get('estimate_row')}"): o.get("operation_cost_gbp")
                    for o in ops
                    if o.get("operation_cost_gbp") is not None
                },
            }
        ],
    }
    return {
        "schema": "historical_quote_readable.v1",
        "source": {
            "formula_parse_json": str(json_path.resolve()),
            "workbook_path": data.get("workbook_path"),
            "workbook_name": data.get("workbook_name"),
        },
        "reconciliation": reconciliation,
        "historical_comparison_projection": historical_comparison_projection,
        "formula_counts": {
            k: len(v or [])
            for k, v in (data.get("key_formula_summary") or {}).items()
        },
    }


def _readable_json_string(payload: Dict[str, Any], max_chars: int = 400_000) -> str:
    s = json.dumps(payload, ensure_ascii=False, indent=2)
    if len(s) <= max_chars:
        return s
    rec = dict(payload.get("reconciliation") or {})
    labour = list(rec.get("labour") or [])
    materials = list(rec.get("materials") or [])
    for cap in (500, 200, 80, 40, 20):
        rec["labour"] = labour[:cap]
        rec["materials"] = materials[:cap]
        rec["_preview_row_cap"] = cap
        p2 = {
            **payload,
            "reconciliation": rec,
            "_truncated": True,
            "_truncation_note": f"Lists capped at {cap} rows; see child tables for full detail.",
        }
        s = json.dumps(p2, ensure_ascii=False, indent=2)
        if len(s) <= max_chars:
            return s
    return json.dumps(
        {
            "schema": payload.get("schema"),
            "source": payload.get("source"),
            "_truncated": True,
            "_error": "readable_extract_json still exceeded max length after row caps",
        },
        ensure_ascii=False,
        indent=2,
    )[:max_chars]


def load_one_json(
    cursor,
    json_path: Path,
    dry_run: bool,
    use_readable_column: bool,
    write_sidecar: bool,
    use_detailed_tables: bool,
) -> Tuple[str, Optional[str]]:
    raw = json_path.read_text(encoding="utf-8")
    data = json.loads(raw)
    if data.get("schema_version") != "estimate_template_parse.v1":
        return json_path.name, "unsupported_schema_version"

    qkey = _quote_key(json_path, data)
    wb_path = str(data.get("workbook_path") or "")
    header = _extract_header_fields(data)
    key_cells = data.get("key_cells") or {}
    ops = _group_labour_operations(key_cells)
    mats = _material_lines(key_cells)
    estimate_row_index = _build_estimate_row_index(data)
    material_row_upper_bound = _detect_material_row_upper_bound(data)
    material_price_break_lookup = _material_price_break_by_row(data)
    mats_detailed_keycells = _material_lines_detailed(key_cells, estimate_row_index=estimate_row_index)
    mats_detailed_formula = _material_lines_from_estimate_formulas(
        data,
        estimate_row_index=estimate_row_index,
        material_row_upper_bound=material_row_upper_bound,
        material_price_break_lookup=material_price_break_lookup,
    )
    mats_detailed = _merge_material_line_candidates(mats_detailed_keycells + mats_detailed_formula)
    mats_detailed = _resolve_missing_material_prices_from_price_break(
        mats_detailed,
        _build_material_price_break_key_map(data),
    )
    mats_detailed = _impute_material_prices_from_historical_db(cursor, mats_detailed)
    labour_detailed = _labour_lines_detailed(key_cells)
    readable_payload = _build_readable_payload(data, header, ops, mats, mats_detailed, labour_detailed, json_path)
    readable = _readable_json_string(readable_payload)

    if dry_run:
        print(f"[dry-run] {qkey} <- {json_path.name} ops={len(ops)} mats={len(mats)}")
        return json_path.name, None

    cursor.execute("SELECT quote_id FROM dbo.historical_quote_header WHERE quote_key = ?", qkey)
    row = cursor.fetchone()
    if row:
        quote_id = int(row[0])
        cursor.execute(
            "DELETE FROM dbo.historical_quote_operation WHERE quote_part_id IN (SELECT quote_part_id FROM dbo.historical_quote_part WHERE quote_id = ?)",
            quote_id,
        )
        cursor.execute(
            "DELETE FROM dbo.historical_quote_material WHERE quote_part_id IN (SELECT quote_part_id FROM dbo.historical_quote_part WHERE quote_id = ?)",
            quote_id,
        )
        cursor.execute("DELETE FROM dbo.historical_quote_part WHERE quote_id = ?", quote_id)
        if use_detailed_tables:
            try:
                cursor.execute("DELETE FROM dbo.historical_quote_material_line WHERE quote_id = ?", quote_id)
                cursor.execute("DELETE FROM dbo.historical_quote_labour_line WHERE quote_id = ?", quote_id)
            except Exception as exc:
                if _is_sql_permission_error(exc):
                    use_detailed_tables = False
                    print(
                        "Note: no DELETE permission on detailed line tables; continuing without detailed line table writes.",
                        file=sys.stderr,
                    )
                else:
                    raise
        if use_readable_column:
            cursor.execute(
                """
UPDATE dbo.historical_quote_header SET
    source_workbook_path = ?,
    source_json_path = ?,
    customer_name = ?,
    drawing_number = ?,
    revision = ?,
    total_unit_cost_gbp = ?,
    parse_confidence = 0.85,
    readable_extract_json = ?,
    updated_at = sysdatetime()
WHERE quote_id = ?;
""",
                wb_path,
                str(json_path.resolve()),
                header.get("customer_name"),
                header.get("drawing_number"),
                header.get("revision"),
                header.get("total_unit_cost_gbp"),
                readable,
                quote_id,
            )
        else:
            cursor.execute(
                """
UPDATE dbo.historical_quote_header SET
    source_workbook_path = ?,
    source_json_path = ?,
    customer_name = ?,
    drawing_number = ?,
    revision = ?,
    total_unit_cost_gbp = ?,
    parse_confidence = 0.85,
    updated_at = sysdatetime()
WHERE quote_id = ?;
""",
                wb_path,
                str(json_path.resolve()),
                header.get("customer_name"),
                header.get("drawing_number"),
                header.get("revision"),
                header.get("total_unit_cost_gbp"),
                quote_id,
            )
    else:
        if use_readable_column:
            cursor.execute(
                """
INSERT INTO dbo.historical_quote_header (
    quote_key, source_workbook_path, source_json_path, customer_name, drawing_number, revision,
    quote_date, currency, total_unit_cost_gbp, total_sell_price_gbp, parse_confidence, readable_extract_json
) VALUES (?, ?, ?, ?, ?, ?, ?, N'GBP', ?, NULL, 0.85, ?);
""",
                qkey,
                wb_path,
                str(json_path.resolve()),
                header.get("customer_name"),
                header.get("drawing_number"),
                header.get("revision"),
                date.today(),
                header.get("total_unit_cost_gbp"),
                readable,
            )
        else:
            cursor.execute(
                """
INSERT INTO dbo.historical_quote_header (
    quote_key, source_workbook_path, source_json_path, customer_name, drawing_number, revision,
    quote_date, currency, total_unit_cost_gbp, total_sell_price_gbp, parse_confidence
) VALUES (?, ?, ?, ?, ?, ?, ?, N'GBP', ?, NULL, 0.85);
""",
                qkey,
                wb_path,
                str(json_path.resolve()),
                header.get("customer_name"),
                header.get("drawing_number"),
                header.get("revision"),
                date.today(),
                header.get("total_unit_cost_gbp"),
            )
        cursor.execute("SELECT quote_id FROM dbo.historical_quote_header WHERE quote_key = ?", qkey)
        id_row = cursor.fetchone()
        if not id_row or id_row[0] is None:
            return json_path.name, "insert_header_missing_quote_id"
        quote_id = int(id_row[0])

    if use_detailed_tables:
        try:
            for m in mats_detailed:
                cursor.execute(
                    """
INSERT INTO dbo.historical_quote_material_line (
    quote_id, line_no, source_sheet, source_cell_ref, part_code, line_description, supplier_name,
    unit, unit_price_gbp, qty_per_unit, scrap_pct, line_total_gbp, raw_line_json
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
""",
                    quote_id,
                    m.get("line_no"),
                    m.get("source_sheet"),
                    m.get("source_cell_ref"),
                    m.get("part_code"),
                    m.get("line_description"),
                    m.get("supplier_name"),
                    m.get("unit"),
                    m.get("unit_price_gbp"),
                    m.get("qty_per_unit"),
                    m.get("scrap_pct"),
                    m.get("line_total_gbp"),
                    json.dumps(m.get("raw", {}), ensure_ascii=False),
                )
            for l in labour_detailed:
                cursor.execute(
                    """
INSERT INTO dbo.historical_quote_labour_line (
    quote_id, line_no, source_sheet, source_cell_ref, operation_code, department_code, part_description,
    qty_per_unit, rate_per_hour_gbp, total_hours, setup_mins, line_total_gbp, raw_line_json
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
""",
                    quote_id,
                    l.get("line_no"),
                    l.get("source_sheet"),
                    l.get("source_cell_ref"),
                    l.get("operation_code"),
                    l.get("department_code"),
                    l.get("part_description"),
                    l.get("qty_per_unit"),
                    l.get("rate_per_hour_gbp"),
                    l.get("total_hours"),
                    l.get("setup_mins"),
                    l.get("line_total_gbp"),
                    json.dumps(l.get("raw", {}), ensure_ascii=False),
                )
        except Exception as exc:
            if _is_sql_permission_error(exc):
                print(
                    "Note: no INSERT permission on detailed line tables; core historical tables still loaded.",
                    file=sys.stderr,
                )
            else:
                raise

    part_json = {
        "role": "workbook_summary",
        "header": header,
        "labour_row_count": len(ops),
        "material_row_count": len(mats),
        "readable_cross_ref": "historical_quote_header.readable_extract_json" if use_readable_column else None,
    }
    cursor.execute(
        """
INSERT INTO dbo.historical_quote_part (
    quote_id, part_code, part_description, normalized_description, quantity,
    unit_total_cost_gbp, extended_total_cost_gbp, source_sheet, raw_part_json
) VALUES (?, ?, ?, ?, 1, ?, ?, 'Estimate', ?);
""",
        quote_id,
        "__WORKBOOK_SUMMARY__",
        data.get("workbook_name") or json_path.stem,
        (data.get("workbook_name") or "").upper()[:1000],
        header.get("total_unit_cost_gbp"),
        header.get("total_unit_cost_gbp"),
        json.dumps(part_json, ensure_ascii=False, indent=2),
    )
    cursor.execute(
        """
SELECT TOP 1 quote_part_id
FROM dbo.historical_quote_part
WHERE quote_id = ? AND part_code = ?
ORDER BY quote_part_id DESC;
""",
        quote_id,
        "__WORKBOOK_SUMMARY__",
    )
    pr = cursor.fetchone()
    if not pr or pr[0] is None:
        return json_path.name, "insert_part_missing_quote_part_id"
    part_id = int(pr[0])

    for op in ops:
        hourly = op.get("hourly_rate_gbp")
        run_h = op.get("run_hours")
        total_min = (run_h * 60.0) if run_h is not None else None
        op_cost = op.get("operation_cost_gbp")
        cursor.execute(
            """
INSERT INTO dbo.historical_quote_operation (
    quote_part_id, operation_code, department_code, setup_min, run_min_per_unit, total_min,
    hourly_rate_gbp, operation_cost_gbp, source_sheet, source_cell_ref, raw_operation_json
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Estimate', ?, ?);
""",
            part_id,
            op.get("operation_code"),
            op.get("operation_code"),
            op.get("setup_min"),
            total_min,
            total_min,
            hourly,
            op_cost,
            f"ROW_{op.get('estimate_row')}",
            json.dumps(op, ensure_ascii=False),
        )

    for m in mats:
        cursor.execute(
            """
INSERT INTO dbo.historical_quote_material (
    quote_part_id, material_code, unit, unit_price_gbp, quantity_per_unit, material_cost_gbp,
    source_sheet, source_cell_ref, raw_material_json
) VALUES (?, NULL, 'each', ?, 1, ?, 'Estimate', ?, ?);
""",
            part_id,
            m.get("unit_price_gbp"),
            m.get("unit_price_gbp"),
            m.get("address"),
            json.dumps(m, ensure_ascii=False),
        )

    if write_sidecar:
        side = _reconciliation_sidecar_path(json_path)
        side.write_text(readable, encoding="utf-8")

    return json_path.name, None


def main() -> None:
    parser = argparse.ArgumentParser(description="Load *.formula_parse.json files into historical quote tables.")
    parser.add_argument("--root", type=str, required=True, help="Folder to scan recursively for .formula_parse.json")
    parser.add_argument("--dry-run", action="store_true", help="List files only; no database writes")
    parser.add_argument("--limit", type=int, default=0, help="Max files to process (0 = no limit)")
    parser.add_argument(
        "--write-sidecar-reconciliation",
        action="store_true",
        help="Write a *.reconciliation.json next to each loaded file (same content as readable_extract_json when the DB column exists)",
    )
    args = parser.parse_args()
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"Not a directory: {root}", file=sys.stderr)
        sys.exit(1)

    files = sorted(root.rglob("*.formula_parse.json"))
    if args.limit:
        files = files[: args.limit]

    rejects: List[Tuple[str, str]] = []
    ok = 0

    if args.dry_run:
        for p in files:
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                qkey = _quote_key(p, data)
                ops = _group_labour_operations(data.get("key_cells") or {})
                print(f"{qkey}\t{p}\tops={len(ops)}")
                ok += 1
            except Exception as exc:
                rejects.append((str(p), str(exc)))
        print(f"\nDry-run done. files={len(files)} ok={ok} rejects={len(rejects)}")
        for path, err in rejects[:50]:
            print(f"REJECT\t{path}\t{err}", file=sys.stderr)
        return

    conn = _connect()
    try:
        use_readable = _detect_readable_extract_column(conn)
        use_detailed_tables = _detect_detailed_line_tables(conn)
        if not use_readable:
            print(
                "Note: dbo.historical_quote_header.readable_extract_json not found; "
                "run sql/historical_quote_add_readable_extract.sql to store indented reconciliation JSON in SQL.",
                file=sys.stderr,
            )
        if not use_detailed_tables:
            print(
                "Note: detailed line tables not found (historical_quote_material_line/historical_quote_labour_line); skipping detailed inserts.",
                file=sys.stderr,
            )
        cursor = conn.cursor()
        for p in files:
            try:
                name, err = load_one_json(
                    cursor,
                    p,
                    dry_run=False,
                    use_readable_column=use_readable,
                    write_sidecar=args.write_sidecar_reconciliation,
                    use_detailed_tables=use_detailed_tables,
                )
                if err:
                    rejects.append((name, err))
                else:
                    ok += 1
            except Exception as exc:
                rejects.append((str(p), str(exc)))
        conn.commit()
    finally:
        conn.close()

    print(f"Loaded {ok} file(s), {len(rejects)} reject(s).")
    for path, err in rejects[:100]:
        print(f"REJECT\t{path}\t{err}", file=sys.stderr)


if __name__ == "__main__":
    main()
