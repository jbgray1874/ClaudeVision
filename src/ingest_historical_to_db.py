#!/usr/bin/env python3
"""
ingest_historical_to_db.py — Ingest corpus JSONL from corpus_ingest.py into
SDILive SQL Server historical quote tables for RAG pricing lookups.

Usage:
    python ingest_historical_to_db.py --jsonl corpus.jsonl
    python ingest_historical_to_db.py --glob "K:/Estimating/Completed/**/*.xls" --jsonl corpus.jsonl
    python ingest_historical_to_db.py --jsonl corpus.jsonl --dry-run

Tables written:
    AIEstimating.historical_quote_summary   (one row per job)
    AIEstimating.historical_quote_part      (one row per steel part)
    AIEstimating.historical_quote_material_line  (one row per bought-in item)
    AIEstimating.historical_quote_operation (one row per operation per part)

Idempotent: rows are upserted by (source_workbook, job_no) so re-running is safe.
"""

from __future__ import annotations

import argparse
import glob as _glob
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

LOG = logging.getLogger("ingest_historical_to_db")

# ── DB connection ──────────────────────────────────────────────────────────────
def _connect():
    import config
    return config.get_connection()


# ── DDL: ensure tables exist ───────────────────────────────────────────────────
DDL = """
IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name='AIEstimating')
    EXEC('CREATE SCHEMA AIEstimating');

IF NOT EXISTS (SELECT 1 FROM sys.tables t JOIN sys.schemas s ON t.schema_id=s.schema_id
               WHERE s.name='AIEstimating' AND t.name='historical_quote_summary')
CREATE TABLE AIEstimating.historical_quote_summary (
    id                          INT IDENTITY PRIMARY KEY,
    source_workbook             NVARCHAR(260) NOT NULL,
    job_no                      NVARCHAR(50),
    revision                    NVARCHAR(20),
    description                 NVARCHAR(500),
    customer                    NVARCHAR(200),
    quantity                    INT,
    year                        INT,
    prepared_by                 NVARCHAR(100),
    material_cost_gbp           DECIMAL(12,4),
    labour_cost_gbp             DECIMAL(12,4),
    raw_manufacturing_cost_gbp  DECIMAL(12,4),
    unit_cost_gbp               DECIMAL(12,4),
    sell_price_gbp              DECIMAL(12,4),
    rebate_fraction             DECIMAL(8,6),
    overhead_divisor_derived    DECIMAL(8,6),
    materials_used              NVARCHAR(500),
    departments_used            NVARCHAR(500),
    part_count                  INT,
    bought_in_count             INT,
    embedding_text              NVARCHAR(MAX),
    inserted_at                 DATETIME2 DEFAULT GETUTCDATE(),
    CONSTRAINT uq_hist_summary UNIQUE (source_workbook, job_no)
);

IF NOT EXISTS (SELECT 1 FROM sys.tables t JOIN sys.schemas s ON t.schema_id=s.schema_id
               WHERE s.name='AIEstimating' AND t.name='historical_quote_part')
CREATE TABLE AIEstimating.historical_quote_part (
    id                      INT IDENTITY PRIMARY KEY,
    summary_id              INT REFERENCES AIEstimating.historical_quote_summary(id),
    source_workbook         NVARCHAR(260),
    job_no                  NVARCHAR(50),
    year                    INT,
    part_number             NVARCHAR(100),
    description             NVARCHAR(500),
    material                NVARCHAR(100),
    thickness_mm            DECIMAL(8,3),
    length_mm               DECIMAL(10,3),
    width_mm                DECIMAL(10,3),
    quantity                INT,
    material_cost_gbp       DECIMAL(12,4),
    labour_cost_per_part_gbp DECIMAL(12,4),
    embedding_text          NVARCHAR(MAX),
    inserted_at             DATETIME2 DEFAULT GETUTCDATE()
);

IF NOT EXISTS (SELECT 1 FROM sys.tables t JOIN sys.schemas s ON t.schema_id=s.schema_id
               WHERE s.name='AIEstimating' AND t.name='historical_quote_material_line')
CREATE TABLE AIEstimating.historical_quote_material_line (
    id                  INT IDENTITY PRIMARY KEY,
    summary_id          INT REFERENCES AIEstimating.historical_quote_summary(id),
    source_workbook     NVARCHAR(260),
    job_no              NVARCHAR(50),
    year                INT,
    part_code           NVARCHAR(100),
    description         NVARCHAR(500),
    supplier            NVARCHAR(200),
    unit_price_gbp      DECIMAL(12,4),
    qty_per_unit        DECIMAL(10,3),
    total_gbp           DECIMAL(12,4),
    embedding_text      NVARCHAR(MAX),
    inserted_at         DATETIME2 DEFAULT GETUTCDATE()
);

IF NOT EXISTS (SELECT 1 FROM sys.tables t JOIN sys.schemas s ON t.schema_id=s.schema_id
               WHERE s.name='AIEstimating' AND t.name='historical_quote_operation')
CREATE TABLE AIEstimating.historical_quote_operation (
    id                      INT IDENTITY PRIMARY KEY,
    part_id                 INT REFERENCES AIEstimating.historical_quote_part(id),
    source_workbook         NVARCHAR(260),
    job_no                  NVARCHAR(50),
    part_number             NVARCHAR(100),
    operation               NVARCHAR(100),
    dept                    NVARCHAR(50),
    rate_per_hour           DECIMAL(10,4),
    total_hours             DECIMAL(10,4),
    setup_mins              DECIMAL(10,2),
    value_per_unit_gbp      DECIMAL(12,4),
    inserted_at             DATETIME2 DEFAULT GETUTCDATE()
);
"""


def ensure_tables(cur) -> None:
    for stmt in DDL.split(";"):
        stmt = stmt.strip()
        if stmt:
            try:
                cur.execute(stmt)
            except Exception as e:
                LOG.debug("DDL stmt skipped: %s", e)


# ── Upsert helpers ─────────────────────────────────────────────────────────────
def _s(v) -> Optional[str]:
    return str(v).strip()[:500] if v not in (None, "") else None

def _f(v) -> Optional[float]:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None

def _i(v) -> Optional[int]:
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def upsert_summary(cur, rec: Dict[str, Any]) -> int:
    """Upsert job summary. Returns the summary_id."""
    src = _s(rec.get("source", {}).get("workbook") or "")
    job = _s(rec.get("job_no") or "UNKNOWN")

    # Check existing
    cur.execute(
        "SELECT id FROM AIEstimating.historical_quote_summary "
        "WHERE source_workbook=? AND job_no=?", src, job
    )
    row = cur.fetchone()
    if row:
        return row[0]

    cur.execute("""
        INSERT INTO AIEstimating.historical_quote_summary
        (source_workbook, job_no, revision, description, customer, quantity, year,
         prepared_by, material_cost_gbp, labour_cost_gbp, raw_manufacturing_cost_gbp,
         unit_cost_gbp, sell_price_gbp, rebate_fraction, overhead_divisor_derived,
         materials_used, departments_used, part_count, bought_in_count, embedding_text)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """,
        src,
        job,
        _s(rec.get("revision")),
        _s(rec.get("description")),
        _s(rec.get("customer")),
        _i(rec.get("quantity")),
        _i(rec.get("year")),
        _s(rec.get("prepared_by")),
        _f(rec.get("material_cost_gbp")),
        _f(rec.get("labour_cost_gbp")),
        _f(rec.get("raw_manufacturing_cost_gbp")),
        _f(rec.get("unit_cost_gbp")),
        _f(rec.get("sell_price_gbp")),
        _f(rec.get("rebate_fraction")),
        _f(rec.get("overhead_divisor_derived")),
        _s(", ".join(rec.get("materials_used") or [])),
        _s(", ".join(rec.get("departments_used") or [])),
        _i(rec.get("part_count")),
        _i(rec.get("bought_in_count")),
        _s(rec.get("embedding_text")),
    )
    cur.execute("SELECT SCOPE_IDENTITY()")
    return int(cur.fetchone()[0])


def insert_parts(cur, summary_id: int, parts: List[Dict], src: str, job: str) -> Dict[str, int]:
    """Insert part records. Returns {part_number: part_id}."""
    pn_to_id: Dict[str, int] = {}
    for p in parts:
        cur.execute("""
            INSERT INTO AIEstimating.historical_quote_part
            (summary_id, source_workbook, job_no, year, part_number, description,
             material, thickness_mm, length_mm, width_mm, quantity,
             material_cost_gbp, labour_cost_per_part_gbp, embedding_text)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
            summary_id, src, job,
            _i(p.get("year")),
            _s(p.get("part_number")),
            _s(p.get("description")),
            _s(p.get("material")),
            _f(p.get("thickness_mm")),
            _f(p.get("length_mm")),
            _f(p.get("width_mm")),
            _i(p.get("quantity")),
            _f(p.get("material_cost_gbp")),
            _f(p.get("labour_cost_per_part_gbp")),
            _s(p.get("embedding_text")),
        )
        cur.execute("SELECT SCOPE_IDENTITY()")
        part_id = int(cur.fetchone()[0])
        pn = _s(p.get("part_number") or "")
        if pn:
            pn_to_id[pn] = part_id

        # Insert operations for this part
        for op in (p.get("operations") or []):
            cur.execute("""
                INSERT INTO AIEstimating.historical_quote_operation
                (part_id, source_workbook, job_no, part_number, operation, dept,
                 rate_per_hour, total_hours, setup_mins, value_per_unit_gbp)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
                part_id, src, job,
                _s(p.get("part_number")),
                _s(op.get("operation")),
                _s(op.get("dept")),
                _f(op.get("rate_per_hour")),
                _f(op.get("total_hours")),
                _f(op.get("setup_mins")),
                _f(op.get("value_per_unit_gbp")),
            )
    return pn_to_id


def insert_bought_in(cur, summary_id: int, items: List[Dict], src: str, job: str,
                     year: Optional[int]) -> None:
    for item in items:
        desc = _s(item.get("description") or item.get("part_code") or "")
        if not desc:
            continue
        cur.execute("""
            INSERT INTO AIEstimating.historical_quote_material_line
            (summary_id, source_workbook, job_no, year, part_code, description,
             supplier, unit_price_gbp, qty_per_unit, total_gbp, embedding_text)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
            summary_id, src, job, year,
            _s(item.get("part_code")),
            desc,
            _s(item.get("supplier")),
            _f(item.get("unit_price_gbp")),
            _f(item.get("qty_per_unit") or item.get("quantity")),
            _f(item.get("total_gbp")),
            _s(f"{desc} {item.get('part_code') or ''}".strip()),
        )


# ── Main ingest ────────────────────────────────────────────────────────────────
def ingest_jsonl(jsonl_path: Path, dry_run: bool = False) -> None:
    conn = _connect()
    cur = conn.cursor()

    LOG.info("Ensuring tables exist...")
    ensure_tables(cur)
    conn.commit()

    records = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as e:
                    LOG.warning("Skipping bad JSON line: %s", e)

    # Group records by job
    jobs: Dict[str, Dict] = {}
    for rec in records:
        rt = rec.get("record_type")
        src = rec.get("source", {}).get("workbook", "unknown")
        job = str(rec.get("job_no") or "UNKNOWN")
        key = f"{src}|{job}"

        if rt == "job":
            if key not in jobs:
                jobs[key] = {"summary": rec, "parts": [], "bought_in": []}
            else:
                jobs[key]["summary"] = rec
        elif rt == "part":
            if key not in jobs:
                jobs[key] = {"summary": None, "parts": [], "bought_in": []}
            jobs[key]["parts"].append(rec)
        elif rt == "bought_in":
            if key not in jobs:
                jobs[key] = {"summary": None, "parts": [], "bought_in": []}
            jobs[key]["bought_in"].append(rec)

    LOG.info("Found %d job groups to ingest", len(jobs))

    inserted = skipped = errors = 0
    for key, data in jobs.items():
        summary = data.get("summary")
        if not summary:
            LOG.debug("Skipping %s — no summary record", key)
            skipped += 1
            continue

        src = _s(summary.get("source", {}).get("workbook") or "")
        job = _s(summary.get("job_no") or "UNKNOWN")

        try:
            # Check if already exists
            cur.execute(
                "SELECT id FROM AIEstimating.historical_quote_summary "
                "WHERE source_workbook=? AND job_no=?", src, job
            )
            if cur.fetchone():
                skipped += 1
                continue

            if dry_run:
                LOG.info("[DRY RUN] Would insert: %s / %s (%d parts, %d bought-in)",
                         src, job, len(data["parts"]), len(data["bought_in"]))
                inserted += 1
                continue

            summary_id = upsert_summary(cur, summary)
            insert_parts(cur, summary_id, data["parts"], src, job)
            insert_bought_in(cur, summary_id, data["bought_in"], src, job,
                            _i(summary.get("year")))
            conn.commit()
            inserted += 1

            if inserted % 50 == 0:
                LOG.info("  Progress: %d inserted, %d skipped, %d errors", inserted, skipped, errors)

        except Exception as e:
            LOG.error("Error inserting %s / %s: %s", src, job, e)
            conn.rollback()
            errors += 1

    LOG.info("Complete: %d inserted, %d skipped (already exist), %d errors",
             inserted, skipped, errors)
    cur.close()
    conn.close()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s"
    )

    parser = argparse.ArgumentParser(description="Ingest corpus JSONL into SDILive historical tables")
    parser.add_argument("--jsonl", required=True, help="Path to corpus JSONL from corpus_ingest.py")
    parser.add_argument("--dry-run", action="store_true", help="Parse and count only, no DB writes")
    args = parser.parse_args()

    jsonl_path = Path(args.jsonl)
    if not jsonl_path.exists():
        LOG.error("JSONL file not found: %s", jsonl_path)
        sys.exit(1)

    LOG.info("Starting ingest from %s (dry_run=%s)", jsonl_path, args.dry_run)
    ingest_jsonl(jsonl_path, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
