import argparse
import re
from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import config
from estimate_template_parser import parse_estimate_template

try:
    import pyodbc  # type: ignore
except ImportError:  # pragma: no cover
    pyodbc = None


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


def _extract_tonne_prices(workbook_path: Path) -> Dict[str, float]:
    parsed = parse_estimate_template(workbook_path)
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

    results: Dict[str, float] = {}
    if sheet_steel_per_tonne is not None:
        results["sheet_steel_per_tonne"] = sheet_steel_per_tonne
    if wire_per_tonne is not None:
        results["wire_per_tonne"] = wire_per_tonne
    return results


def _connect_sqlserver(cfg: Dict[str, Any]):
    if pyodbc is None:
        raise RuntimeError("pyodbc is not installed in this environment.")
    driver = cfg.get("driver", "ODBC Driver 18 for SQL Server")
    encrypt = "yes" if bool(cfg.get("encrypt", True)) else "no"
    trust = "yes" if bool(cfg.get("trust_server_certificate", True)) else "no"
    conn_str = (
        f"DRIVER={{{driver}}};"
        f"SERVER={cfg.get('server', '')};"
        f"DATABASE={cfg.get('database', '')};"
        f"UID={cfg.get('username', '')};"
        f"PWD={cfg.get('password', '')};"
        f"Encrypt={encrypt};"
        f"TrustServerCertificate={trust};"
    )
    return pyodbc.connect(conn_str, timeout=10)


def _upsert_material_price(
    cursor,
    material_code: str,
    price_gbp_per_kg: float,
    effective_date: date,
    source_note: str,
    supplier_name: str = "Spreadsheet Sync",
) -> Tuple[int, int]:
    update_sql = """
UPDATE dbo.material_prices
SET is_active = 0
WHERE material_code = ?
  AND thickness_mm IS NULL
  AND is_active = 1;
"""
    insert_sql = """
INSERT INTO dbo.material_prices
(
    material_code,
    thickness_mm,
    price_gbp_per_kg,
    supplier_code,
    supplier_name,
    effective_date,
    expires_date,
    is_active,
    source_note
)
VALUES (?, NULL, ?, NULL, ?, ?, NULL, 1, ?);
"""
    cursor.execute(update_sql, material_code)
    updated = cursor.rowcount if cursor.rowcount is not None else 0
    cursor.execute(
        insert_sql,
        material_code,
        price_gbp_per_kg,
        supplier_name,
        effective_date.isoformat(),
        source_note,
    )
    inserted = cursor.rowcount if cursor.rowcount is not None else 0
    return updated, inserted


def parse_args() -> argparse.Namespace:
    sql_cfg = config.PRICE_SOURCE_CONFIG.get("sqlserver", {})
    workbook_default = config.PRICE_SOURCE_CONFIG.get("spreadsheet", {}).get(
        "template_workbook", str(config.SPREADSHEETS_DIR / "EmptyEstimating" / "Blank Estimate Sheet 2026.xls")
    )

    parser = argparse.ArgumentParser(description="Sync sheet steel/wire rates from workbook into dbo.material_prices.")
    parser.add_argument("--workbook", type=str, default=workbook_default, help="Path to estimate workbook.")
    parser.add_argument("--effective-date", type=str, default=date.today().isoformat(), help="Effective date (YYYY-MM-DD).")
    parser.add_argument("--sheet-material-code", type=str, default="MILD_STEEL", help="Material code for sheet steel entry.")
    parser.add_argument("--wire-material-code", type=str, default="STEEL_WIRE", help="Material code for wire entry.")
    parser.add_argument("--sheet-steel-per-tonne", type=float, default=None, help="Override sheet steel GBP/tonne.")
    parser.add_argument("--wire-per-tonne", type=float, default=None, help="Override wire GBP/tonne.")
    parser.add_argument("--dry-run", action="store_true", help="Print detected/upsert values without writing DB.")
    parser.add_argument("--server", type=str, default=sql_cfg.get("server", ""))
    parser.add_argument("--database", type=str, default=sql_cfg.get("database", ""))
    parser.add_argument("--username", type=str, default=sql_cfg.get("username", ""))
    parser.add_argument("--password", type=str, default=sql_cfg.get("password", ""))
    parser.add_argument("--driver", type=str, default=sql_cfg.get("driver", "ODBC Driver 18 for SQL Server"))
    parser.add_argument("--encrypt", action="store_true", default=bool(sql_cfg.get("encrypt", True)))
    parser.add_argument("--trust-server-certificate", action="store_true", default=bool(sql_cfg.get("trust_server_certificate", True)))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    workbook_path = Path(args.workbook)
    if not workbook_path.exists():
        raise FileNotFoundError(f"Workbook not found: {workbook_path}")

    detected = _extract_tonne_prices(workbook_path)
    sheet_steel_per_tonne = args.sheet_steel_per_tonne if args.sheet_steel_per_tonne is not None else detected.get("sheet_steel_per_tonne")
    wire_per_tonne = args.wire_per_tonne if args.wire_per_tonne is not None else detected.get("wire_per_tonne")

    if sheet_steel_per_tonne is None and wire_per_tonne is None:
        raise RuntimeError("No tonne prices found. Provide overrides via --sheet-steel-per-tonne / --wire-per-tonne.")

    effective = date.fromisoformat(args.effective_date)
    source_note = f"synced_from_workbook:{workbook_path.name}"

    pending_rows = []
    if sheet_steel_per_tonne is not None:
        pending_rows.append((args.sheet_material_code, round(sheet_steel_per_tonne / 1000.0, 6), sheet_steel_per_tonne))
    if wire_per_tonne is not None:
        pending_rows.append((args.wire_material_code, round(wire_per_tonne / 1000.0, 6), wire_per_tonne))

    print(f"Workbook: {workbook_path}")
    print(f"Effective date: {effective.isoformat()}")
    for material_code, per_kg, per_tonne in pending_rows:
        print(f"- {material_code}: {per_tonne:.2f} GBP/tonne => {per_kg:.6f} GBP/kg")

    if args.dry_run:
        print("Dry-run mode: no database changes written.")
        return

    sql_cfg = {
        "server": args.server,
        "database": args.database,
        "username": args.username,
        "password": args.password,
        "driver": args.driver,
        "encrypt": args.encrypt,
        "trust_server_certificate": args.trust_server_certificate,
    }
    if not all([sql_cfg["server"], sql_cfg["database"], sql_cfg["username"], sql_cfg["password"]]):
        raise RuntimeError("Missing SQL connection details. Provide server/database/username/password.")

    with _connect_sqlserver(sql_cfg) as connection:
        cursor = connection.cursor()
        total_updated = 0
        total_inserted = 0
        for material_code, per_kg, _ in pending_rows:
            updated, inserted = _upsert_material_price(
                cursor=cursor,
                material_code=material_code,
                price_gbp_per_kg=per_kg,
                effective_date=effective,
                source_note=source_note,
            )
            total_updated += updated
            total_inserted += inserted
        connection.commit()

    print(f"Sync complete. Updated rows: {total_updated}, inserted rows: {total_inserted}.")


if __name__ == "__main__":
    main()

