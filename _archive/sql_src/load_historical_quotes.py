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
    conn = pyodbc.connect(conn_str, timeout=30, autocommit=False)
    # SET NOCOUNT ON stops row-count messages confusing fetchone() after INSERT ... OUTPUT.
    init_cur = conn.cursor()
    init_cur.execute("SET NOCOUNT ON;")
    init_cur.close()
    return conn


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


def _is_sql_permission_error(exc: Exception) -> bool:
    msg = str(exc).upper()
    return (
        "PERMISSION WAS DENIED" in msg
        or "(229)" in msg
        or "SQLSTATE=42000" in msg
    )


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
    # Strip £, Â£ (UTF-8/Windows-1252 mojibake), $, commas, and padded spaces.
    s = str(value).strip()
    s = s.replace("Â£", "").replace("Â", "").replace("£", "").replace("$", "").replace(",", "")
    s = re.sub(r"\s+", "", s)
    if s in {"", "-"}:
        return None
    try:
        return float(s)
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


def _lookup_estimate_cell(data: Dict[str, Any], address: str) -> Optional[Dict[str, Any]]:
    """Resolve a cell from estimate_sheet.formulas first, then parsed_entries."""
    addr = str(address).upper()
    for f in ((data.get("estimate_sheet") or {}).get("formulas")) or []:
        if str(f.get("address", "")).upper() != addr:
            continue
        return {
            "sheet": "Estimate",
            "address": addr,
            "value": f.get("value"),
            "formula": f.get("formula"),
            "number_format": f.get("number_format"),
            "labels": {
                "left": f.get("label_left", ""),
                "left_2": f.get("label_left_2", ""),
                "right": f.get("label_right", ""),
            },
        }
    for entry in data.get("parsed_entries") or []:
        if str(entry.get("sheet", "")).upper() == "ESTIMATE" and str(entry.get("address", "")).upper() == addr:
            return entry
    return None


def _money_from_addresses(data: Dict[str, Any], *addresses: str) -> Optional[float]:
    for addr in addresses:
        cell = _lookup_estimate_cell(data, addr)
        if not cell:
            continue
        v = _numeric_from_cell(cell)
        if v is not None:
            return v
    return None


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


def _norm_text(value: str) -> str:
    s = re.sub(r"[^A-Z0-9]+", " ", str(value or "").upper()).strip()
    return re.sub(r"\s+", " ", s)


def _token_set(value: str) -> set[str]:
    return {t for t in _norm_text(value).split(" ") if t and len(t) >= 2}


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


def _is_currency_cell(cell: Dict[str, Any]) -> bool:
    if not isinstance(cell, dict):
        return False
    val = str(cell.get("value") or "")
    nf = str(cell.get("number_format") or "")
    return "£" in val or "Â£" in val or "\\£" in nf or "GBP" in val.upper()


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


def _detect_material_row_upper_bound(data: Dict[str, Any]) -> int:
    upper = 59
    totals = ((data.get("key_cells") or {}).get("totals")) or []
    for t in totals:
        addr = str(t.get("address", "")).upper()
        if addr.startswith("L"):
            row = _row_from_address(addr)
            if row and 20 <= row <= 120:
                upper = min(upper, row)
    for e in data.get("parsed_entries") or []:
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
    cell = _lookup_estimate_cell(data, "L59")
    if cell:
        row = _row_from_address("L59")
        if row:
            upper = min(upper, row)
    return upper


def _detect_labour_row_lower_bound(material_row_upper_bound: int) -> int:
    if material_row_upper_bound >= 55:
        return material_row_upper_bound + 1
    return 28


def _row_has_operation_lookup(cells: Dict[str, Dict[str, Any]]) -> bool:
    for col in ("F", "G", "C"):
        cell = cells.get(col) or {}
        tags = cell.get("tags") or []
        if "operation_table_lookup" in tags:
            return True
        formula = str(cell.get("formula") or "").upper()
        if "LOOKUP" in formula and "ESTIMATE!" in formula and "$H$" in formula:
            return True
    return False


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
    addr_vals = {str(t.get("address", "")).upper(): t.get("value") for t in totals}
    total_unit = _parse_money(addr_vals.get("L105"))
    material_sub = None
    for k in ("L60", "L59"):
        if k in addr_vals:
            v = _parse_money(addr_vals[k])
            if v is not None:
                material_sub = v
                break
    labour_sub = None
    for k in ("L106", "L101"):
        if k in addr_vals:
            v = _parse_money(addr_vals[k])
            if v is not None:
                labour_sub = v
                break

    if total_unit is None:
        total_unit = _money_from_addresses(data, "L105", "G6", "F6", "M105")
    if material_sub is None:
        material_sub = _money_from_addresses(data, "L59", "L60")
    if labour_sub is None:
        labour_sub = _money_from_addresses(data, "L101", "L106")

    return {
        "drawing_number": drawing_number,
        "customer_name": customer_name,
        "revision": revision,
        "total_unit_cost_gbp": total_unit,
        "material_subtotal_gbp": material_sub,
        "labour_subtotal_gbp": labour_sub,
    }


def _plain_text_cell_value(cell: Dict[str, Any]) -> Optional[str]:
    if not isinstance(cell, dict):
        return None
    val = str(cell.get("value") or "").strip()
    if not val or val in {"0", "-"} or _parse_money(val) is not None:
        return None
    if cell.get("is_plain_text") or not str(cell.get("formula") or "").startswith("="):
        return val
    return None


def _material_description_from_row(cells: Dict[str, Dict[str, Any]]) -> Optional[str]:
    for col in ("C", "G"):
        desc = _plain_text_cell_value(cells.get(col) or {})
        if desc:
            return desc
    return None


def _extract_labour_row(row: int, cells: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    op_code = _plain_text_cell_value(cells.get("C") or {})
    if not op_code:
        op_code = _plain_text_cell_value(cells.get("G") or {})

    if not op_code and not _row_has_operation_lookup(cells):
        return None

    if not op_code:
        for col in ("F", "G", "E"):
            cell = cells.get(col) or {}
            val = str(cell.get("value") or "").strip()
            if val and val not in {"0", "-"} and _parse_money(val) is None:
                op_code = val
                break
    if not op_code:
        return None

    rate: Optional[float] = None
    for col in ("K", "J"):
        cell = cells.get(col) or {}
        if _is_currency_cell(cell) or "operation_table_lookup" in (cell.get("tags") or []):
            rate = _numeric_from_cell(cell)
            if rate is not None:
                break

    run_hours = _parse_float((cells.get("I") or {}).get("value"))
    if run_hours is None:
        run_hours = _numeric_from_cell(cells.get("I") or {})

    setup_min: Optional[float] = None
    l_cell = cells.get("L") or {}
    if not _is_currency_cell(l_cell):
        setup_min = _parse_float(l_cell.get("value"))
        if setup_min is None:
            setup_min = _numeric_from_cell(l_cell)

    line_total: Optional[float] = None
    m_cell = cells.get("M") or {}
    if _is_currency_cell(m_cell):
        line_total = _numeric_from_cell(m_cell)
    if line_total is None and _is_currency_cell(l_cell):
        line_total = _numeric_from_cell(l_cell)

    desc = _plain_text_cell_value(cells.get("C") or {}) or _plain_text_cell_value(cells.get("G") or {})

    return {
        "estimate_row": row,
        "operation_code": op_code,
        "description_hint": desc,
        "hourly_rate_gbp": rate,
        "run_hours": run_hours,
        "setup_min": setup_min,
        "operation_cost_gbp": line_total,
    }


def _labour_lines_from_estimate_index(
    estimate_row_index: Dict[int, Dict[str, Dict[str, Any]]],
    labour_row_lower: int,
    labour_row_upper: int = 200,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in sorted(estimate_row_index):
        if row < labour_row_lower or row > labour_row_upper:
            continue
        cells = estimate_row_index[row]
        op = _extract_labour_row(row, cells)
        if not op:
            continue
        out.append(
            {
                "line_no": row,
                "source_sheet": "Estimate",
                "source_cell_ref": f"ROW_{row}",
                "operation_code": op.get("operation_code"),
                "department_code": op.get("operation_code"),
                "part_description": op.get("description_hint"),
                "qty_per_unit": _parse_float((cells.get("H") or {}).get("value")) or 1.0,
                "rate_per_hour_gbp": op.get("hourly_rate_gbp"),
                "total_hours": op.get("run_hours"),
                "setup_mins": op.get("setup_min"),
                "line_total_gbp": op.get("operation_cost_gbp"),
                "raw": cells,
            }
        )
    return out


def _group_labour_operations(
    key_cells: Dict[str, Any],
    data: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    if data is not None:
        estimate_row_index = _build_estimate_row_index(data)
        material_upper = _detect_material_row_upper_bound(data)
        labour_lower = _detect_labour_row_lower_bound(material_upper)
        out: List[Dict[str, Any]] = []
        for row in sorted(estimate_row_index):
            if row < labour_lower:
                continue
            op = _extract_labour_row(row, estimate_row_index[row])
            if op:
                out.append(op)
        if out:
            return out

    by_row: Dict[int, Dict[str, Any]] = defaultdict(dict)
    for entry in key_cells.get("operation_rows") or []:
        if str(entry.get("sheet", "")).upper() != "ESTIMATE":
            continue
        addr = str(entry.get("address", ""))
        row = _row_from_address(addr)
        col = _col_from_address(addr)
        if row is None or col is None:
            continue
        by_row[row][col] = entry

    legacy: List[Dict[str, Any]] = []
    for row in sorted(by_row):
        cells = by_row[row]
        op = _extract_labour_row(row, cells)
        if op:
            legacy.append(op)
    return legacy


def _material_price_break_by_row(data: Dict[str, Any]) -> Dict[int, float]:
    out: Dict[int, float] = {}
    formulas = ((data.get("estimate_sheet") or {}).get("formulas")) or []
    for f in formulas:
        addr = str(f.get("address", "")).upper()
        row = _row_from_address(addr)
        if row is None or not addr.startswith(("I", "J")):
            continue
        formula = str(f.get("formula") or "").upper()
        if "MATERIAL PRICE BREAK" not in formula:
            continue
        v = _parse_money(f.get("value"))
        if v is not None and v > 0:
            out[row] = v
    return out


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
        labels = b.get("labels") or {}
        for k in ("right", "left_2", "left"):
            v = _parse_money(labels.get(k))
            if v is not None and v > 0:
                price_candidates.append(v)
        for col in ("C", "D", "E", "F", "G", "H", "I"):
            v = _numeric_from_cell(cols.get(col) or {})
            if v is not None and v > 0:
                price_candidates.append(v)
        if not price_candidates:
            continue
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


def _material_lines_from_estimate_formulas(
    data: Dict[str, Any],
    estimate_row_index: Dict[int, Dict[str, Dict[str, Any]]],
    material_row_upper_bound: int,
    material_price_break_lookup: Dict[int, float],
) -> List[Dict[str, Any]]:
    formulas = ((data.get("estimate_sheet") or {}).get("formulas")) or []
    out: List[Dict[str, Any]] = []
    seen_rows: set[int] = set()

    def _append_material_row(row: int, total_col: str, total_val: Optional[float], formula_row: Optional[Dict[str, Any]] = None) -> None:
        if row in seen_rows or row >= material_row_upper_bound or row < 8:
            return
        cells = estimate_row_index.get(row) or {}
        if _row_has_operation_lookup(cells):
            return
        line_desc = _material_description_from_row(cells)
        if not line_desc:
            desc_parts: List[str] = []
            for c in ("F", "H", "I"):
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
        unit_price = None
        for col in ("J", "I", "H"):
            unit_price = _numeric_from_cell(cells.get(col) or {})
            if unit_price is not None:
                break
        if unit_price is None:
            unit_price = material_price_break_lookup.get(row)
        qty_per_unit = _numeric_from_cell(cells.get("K") or {})
        if qty_per_unit is None:
            qty_per_unit = _numeric_from_cell(cells.get("H") or {})
        if qty_per_unit is None and formula_row:
            qty_per_unit = _parse_float(formula_row.get("label_left_2"))
        if qty_per_unit is None:
            qty_per_unit = _qty_from_description(line_desc or "")
        if qty_per_unit is None:
            qty_per_unit = 1.0
        scrap_pct = 0.0
        if formula_row:
            scrap_raw = _parse_float(formula_row.get("label_left"))
            if scrap_raw is not None and 0 <= scrap_raw <= 100:
                scrap_pct = scrap_raw
        if total_val is None:
            for col in (total_col, "L", "M"):
                total_val = _numeric_from_cell(cells.get(col) or {})
                if total_val is not None:
                    break
        if total_val is None and unit_price is not None and qty_per_unit not in (None, 0):
            total_val = round(float(unit_price) * float(qty_per_unit) * (1.0 + (float(scrap_pct) / 100.0)), 4)
        if unit_price is None and total_val is not None and qty_per_unit not in (None, 0):
            unit_price = round(float(total_val) / float(qty_per_unit), 6)
        if total_val is None and unit_price is None:
            return
        out.append(
            {
                "line_no": row,
                "source_sheet": "Estimate",
                "source_cell_ref": f"{total_col}{row}",
                "part_code": None,
                "line_description": line_desc,
                "supplier_name": None,
                "unit": "GBP_per_unit",
                "unit_price_gbp": unit_price,
                "qty_per_unit": qty_per_unit,
                "scrap_pct": scrap_pct,
                "line_total_gbp": total_val,
                "raw": {"formula_row": formula_row, "row_cells": cells},
            }
        )
        seen_rows.add(row)

    for f in formulas:
        addr = str(f.get("address", ""))
        row = _row_from_address(addr)
        col = _col_from_address(addr)
        if row is None or col not in ("L", "M"):
            continue
        if row >= material_row_upper_bound or row < 8:
            continue
        total_val = _parse_money(f.get("value"))
        _append_material_row(row, col, total_val, f)

    for row, cells in sorted(estimate_row_index.items()):
        if row in seen_rows or row >= material_row_upper_bound or row < 8:
            continue
        if _row_has_operation_lookup(cells):
            continue
        total_val = None
        total_col = "L"
        for col in ("M", "L"):
            cell = cells.get(col) or {}
            if _is_currency_cell(cell):
                total_val = _numeric_from_cell(cell)
                if total_val is not None:
                    total_col = col
                    break
            elif total_val is None:
                v = _numeric_from_cell(cell)
                if v is not None and v > 0:
                    total_val = v
                    total_col = col
        if total_val is None:
            continue
        _append_material_row(row, total_col, total_val, None)

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
        line_desc = _material_description_from_row(cells)
        primary = cells.get("J") or cells.get("I") or next(iter(cells.values()), {})
        labels = primary.get("labels") or {}
        if not line_desc:
            line_desc = " | ".join(
                v
                for v in (
                    str(labels.get("left", "")).strip(),
                    str(labels.get("left_2", "")).strip(),
                    str(labels.get("right", "")).strip(),
                )
                if v
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
                seen: List[str] = []
                for t in desc_candidates:
                    if t not in seen:
                        seen.append(t)
                line_desc = " | ".join(seen[:4])
        unit_price = None
        for col in ("J", "I", "H", "G", "F", "K"):
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
        line_total = None
        for col in ("M", "L"):
            cell = cells.get(col) or {}
            if _is_currency_cell(cell):
                line_total = _numeric_from_cell(cell)
                if line_total is not None:
                    break
        if line_total is None and unit_price is not None:
            line_total = round(unit_price * qty_per_unit * (1.0 + (scrap_pct / 100.0)), 4)
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
                "line_total_gbp": line_total,
                "raw": cells,
            }
        )
    return out


def _labour_lines_detailed(
    key_cells: Dict[str, Any],
    data: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    if data is not None:
        estimate_row_index = _build_estimate_row_index(data)
        material_upper = _detect_material_row_upper_bound(data)
        labour_lower = _detect_labour_row_lower_bound(material_upper)
        lines = _labour_lines_from_estimate_index(estimate_row_index, labour_lower)
        if lines:
            return lines

    by_row: Dict[int, Dict[str, Any]] = defaultdict(dict)
    for entry in key_cells.get("operation_rows") or []:
        if str(entry.get("sheet", "")).upper() != "ESTIMATE":
            continue
        addr = str(entry.get("address", ""))
        row = _row_from_address(addr)
        col = _col_from_address(addr)
        if row is None or col is None:
            continue
        by_row[row][col] = entry
    out: List[Dict[str, Any]] = []
    for row in sorted(by_row):
        cells = by_row[row]
        op = _extract_labour_row(row, cells)
        if not op:
            continue
        out.append(
            {
                "line_no": row,
                "source_sheet": "Estimate",
                "source_cell_ref": f"ROW_{row}",
                "operation_code": op.get("operation_code"),
                "department_code": op.get("operation_code"),
                "part_description": op.get("description_hint"),
                "qty_per_unit": _parse_float((cells.get("H") or {}).get("value")) or 1.0,
                "rate_per_hour_gbp": op.get("hourly_rate_gbp"),
                "total_hours": op.get("run_hours"),
                "setup_mins": op.get("setup_min"),
                "line_total_gbp": op.get("operation_cost_gbp"),
                "raw": cells,
            }
        )
    return out


def _insert_detailed_lines(
    cursor,
    quote_id: int,
    mats_detailed: List[Dict[str, Any]],
    labour_detailed: List[Dict[str, Any]],
) -> None:
    for m in mats_detailed:
        if m.get("unit_price_gbp") is None and m.get("line_total_gbp") is None:
            continue
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
    return {
        "schema": "historical_quote_readable.v1",
        "source": {
            "formula_parse_json": str(json_path.resolve()),
            "workbook_path": data.get("workbook_path"),
            "workbook_name": data.get("workbook_name"),
        },
        "reconciliation": reconciliation,
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
    use_detailed_tables: bool = False,
) -> Tuple[str, Optional[str]]:
    raw = json_path.read_text(encoding="utf-8")
    data = json.loads(raw)
    if data.get("schema_version") != "estimate_template_parse.v1":
        return json_path.name, "unsupported_schema_version"

    qkey = _quote_key(json_path, data)
    wb_path = str(data.get("workbook_path") or "")
    header = _extract_header_fields(data)
    key_cells = data.get("key_cells") or {}
    estimate_row_index = _build_estimate_row_index(data)
    material_row_upper_bound = _detect_material_row_upper_bound(data)
    material_price_break_lookup = _material_price_break_by_row(data)
    ops = _group_labour_operations(key_cells, data)
    mats = _material_lines(key_cells)
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
    if not dry_run:
        mats_detailed = _impute_material_prices_from_historical_db(cursor, mats_detailed)
    if not mats and mats_detailed:
        mats = [
            {
                "estimate_row": m.get("line_no"),
                "label_context": m.get("line_description"),
                "unit_price_gbp": m.get("unit_price_gbp"),
                "address": m.get("source_cell_ref"),
            }
            for m in mats_detailed
            if m.get("unit_price_gbp") is not None or m.get("line_total_gbp") is not None
        ]
    labour_detailed = (
        _labour_lines_detailed(key_cells, data)
        if use_detailed_tables
        else []
    )
    readable_payload = _build_readable_payload(
        data, header, ops, mats, mats_detailed, labour_detailed, json_path
    )
    readable = _readable_json_string(readable_payload)

    if dry_run:
        print(
            f"[dry-run] {qkey} <- {json_path.name} ops={len(ops)} mats={len(mats)} "
            f"mat_lines={len(mats_detailed)} lab_lines={len(labour_detailed)}"
        )
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
) OUTPUT INSERTED.quote_id
VALUES (?, ?, ?, ?, ?, ?, ?, N'GBP', ?, NULL, 0.85, ?);
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
) OUTPUT INSERTED.quote_id
VALUES (?, ?, ?, ?, ?, ?, ?, N'GBP', ?, NULL, 0.85);
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
        id_row = cursor.fetchone()
        if not id_row or id_row[0] is None:
            return json_path.name, "insert_header_missing_quote_id"
        quote_id = int(id_row[0])

    if use_detailed_tables:
        try:
            _insert_detailed_lines(cursor, quote_id, mats_detailed, labour_detailed)
        except Exception as exc:
            if _is_sql_permission_error(exc):
                print(
                    "Note: no INSERT permission on detailed line tables; core tables still loaded.",
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
) OUTPUT INSERTED.quote_part_id
VALUES (?, ?, ?, ?, 1, ?, ?, 'Estimate', ?);
""",
        quote_id,
        "__WORKBOOK_SUMMARY__",
        data.get("workbook_name") or json_path.stem,
        (data.get("workbook_name") or "").upper()[:1000],
        header.get("total_unit_cost_gbp"),
        header.get("total_unit_cost_gbp"),
        json.dumps(part_json, ensure_ascii=False, indent=2),
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
                ops = _group_labour_operations(data.get("key_cells") or {}, data)
                estimate_row_index = _build_estimate_row_index(data)
                material_upper = _detect_material_row_upper_bound(data)
                mats_f = _material_lines_from_estimate_formulas(
                    data,
                    estimate_row_index,
                    material_upper,
                    _material_price_break_by_row(data),
                )
                lab = _labour_lines_from_estimate_index(
                    estimate_row_index,
                    _detect_labour_row_lower_bound(material_upper),
                )
                print(
                    f"{qkey}\t{p}\tops={len(ops)} mat_lines={len(mats_f)} lab_lines={len(lab)}"
                )
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
                "Note: detailed line tables not found; run sql/historical_quote_ddl.sql on SDILive first.",
                file=sys.stderr,
            )
        print(f"Connection OK — use_readable={use_readable} use_detailed={use_detailed_tables}")
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
                    print(f"  REJECT {name}: {err}")
                else:
                    ok += 1
                    print(f"  OK     {name}")
            except Exception as exc:
                rejects.append((str(p), str(exc)))
                print(f"  ERROR  {p.name}: {exc}")
        print(f"Committing {ok} file(s)...")
        conn.commit()
        print("Commit done.")
    finally:
        conn.close()

    print(f"Loaded {ok} file(s), {len(rejects)} reject(s).")
    for path, err in rejects[:100]:
        print(f"REJECT\t{path}\t{err}", file=sys.stderr)


if __name__ == "__main__":
    main()
