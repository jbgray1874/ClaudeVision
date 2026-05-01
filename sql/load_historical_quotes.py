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


def _build_readable_payload(
    data: Dict[str, Any],
    header: Dict[str, Any],
    ops: List[Dict[str, Any]],
    mats: List[Dict[str, Any]],
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
    readable_payload = _build_readable_payload(data, header, ops, mats, json_path)
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
        cursor.execute("SELECT CAST(SCOPE_IDENTITY() AS bigint)")
        quote_id = int(cursor.fetchone()[0])

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
    cursor.execute("SELECT CAST(SCOPE_IDENTITY() AS bigint)")
    part_id = int(cursor.fetchone()[0])

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
        if not use_readable:
            print(
                "Note: dbo.historical_quote_header.readable_extract_json not found; "
                "run sql/historical_quote_add_readable_extract.sql to store indented reconciliation JSON in SQL.",
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
