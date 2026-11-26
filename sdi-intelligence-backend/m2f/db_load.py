"""
Load a tracker import into the m2f staging tables on SDILive.

  python -m m2f.db_load --schema                 create or update the m2f tables
  python -m m2f.db_load <tracker.xlsx>           import the tracker into staging

Staging keeps the workbook exactly as read, with its issues. Nothing reaches
the live project and forecast tables until the review decisions are made.
"""
from __future__ import annotations

import argparse
import getpass
import json
import re
import sys
from dataclasses import asdict
from pathlib import Path

from m2f.tracker_import import TrackerImport, import_tracker, summarise

SCHEMA_FILE = Path(__file__).with_name("schema_m2f.sql")
_GO = re.compile(r"^\s*GO\s*$", re.I | re.M)


def schema_batches(sql: str) -> list[str]:
    """Split a script on GO lines, as SSMS does, dropping empty batches."""
    return [b.strip() for b in _GO.split(sql) if b.strip() and not all(
        line.strip().startswith("--") or not line.strip() for line in b.splitlines())]


def connect():
    import pyodbc  # imported here so the importer runs on machines without the driver
    import config
    if not config.DB_CONFIGURED:
        raise RuntimeError("Database is not configured in .env (SDI_DB_SERVER / SDI_DB_NAME).")
    return pyodbc.connect(config.db_connection_string(), autocommit=False, timeout=15)


def apply_schema(conn, path: Path = SCHEMA_FILE) -> int:
    cur = conn.cursor()
    batches = schema_batches(path.read_text(encoding="utf-8"))
    for batch in batches:
        cur.execute(batch)
    conn.commit()
    return len(batches)


def _period_date(period: str | None):
    return f"{period}-01" if period else None


def load_staging(conn, result: TrackerImport, imported_by: str | None = None) -> int:
    """Write one import batch with its projects, forecast lines and issues. Returns batch_id."""
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT m2f.import_batch (source_file, imported_by, summary_json) "
            "OUTPUT INSERTED.batch_id VALUES (?, ?, ?)",
            result.source, imported_by, json.dumps(summarise(result), default=str))
        batch_id = int(cur.fetchone()[0])
        cur.fast_executemany = True
        if result.projects:
            cur.executemany(
                "INSERT m2f.stg_project (batch_id, source_key, tab, source_row, hidden, segment, account, "
                "name, fields_json, extra_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(batch_id, p.review_key, p.tab.strip(), p.row, int(p.hidden), p.segment, p.account,
                  p.name[:300], json.dumps(p.fields, default=str), json.dumps(p.extra, default=str))
                 for p in result.projects])
        if result.forecast_lines:
            cur.executemany(
                "INSERT m2f.stg_forecast_line (batch_id, source_key, tab, cell, period_month, amount, raw, "
                "value_type, status, fill) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(batch_id, x.review_key, x.tab.strip(), x.cell, _period_date(x.period), x.amount,
                  x.raw[:100], x.value_type, x.status, x.fill[:30]) for x in result.forecast_lines])
        if result.issues:
            cur.executemany(
                "INSERT m2f.import_issue (batch_id, code, severity, message, tab, cell, source_key) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(batch_id, i.code, i.severity, i.message[:1000], i.tab.strip() or None, i.cell or None,
                  i.review_key or None) for i in result.issues])
        conn.commit()
        return batch_id
    except Exception:
        conn.rollback()
        raise


def main(argv=None):
    ap = argparse.ArgumentParser(description="Load the account tracker into Monday2Friday staging.")
    ap.add_argument("workbook", nargs="?")
    ap.add_argument("--schema", action="store_true", help="create or update the m2f tables first")
    args = ap.parse_args(argv)
    if not args.schema and not args.workbook:
        ap.error("give a workbook to import, --schema, or both")
    conn = connect()
    if args.schema:
        print(f"Applied {apply_schema(conn)} schema batches.")
    if args.workbook:
        result = import_tracker(args.workbook)
        batch_id = load_staging(conn, result, imported_by=getpass.getuser())
        print(json.dumps({"batch_id": batch_id, **summarise(result)}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
