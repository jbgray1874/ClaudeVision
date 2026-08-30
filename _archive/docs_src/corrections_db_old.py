"""
SDIAIVision — Corrections Database
====================================
Persistent learning store for the AI estimating system.
Every correction made by an estimator is stored here and
used to prevent the same mistake from ever happening again.

Location: C:\\ClaudeVision\\src\\corrections_db.py
Database: C:\\ClaudeVision\\data\\sdi_learning.db  (auto-created)

Tables:
    corrections         — estimator corrections, one row per field changed
    part_knowledge      — accumulated knowledge: part → material/cost/ops
    live_overrides      — active rules that fire on every future scan
    drawing_patterns    — OCR/text patterns and their meanings
    historical_estimates — ingested from K:\\Estimating historical files
    scan_log            — every scan recorded for tracking/audit
"""

import sqlite3
import json
import re
import os
from pathlib import Path
from datetime import datetime, date
from typing import Optional, Dict, Any, List

# ── Database location ──────────────────────────────────────────────────────────
_DB_DIR  = Path(__file__).parent.parent / "data"
_DB_PATH = _DB_DIR / "sdi_learning.db"


def get_db_path() -> Path:
    return _DB_PATH


def _connect() -> sqlite3.Connection:
    _DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ══════════════════════════════════════════════════════════════════════════════
# SCHEMA CREATION
# ══════════════════════════════════════════════════════════════════════════════

_SCHEMA = """
-- ── Estimator corrections ────────────────────────────────────────────────────
-- One row per field changed. Source of truth for all learning.
CREATE TABLE IF NOT EXISTS corrections (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id         TEXT,                   -- filename stem of the source PDF
    part_number     TEXT,                   -- e.g. "10886-25-01"
    job_number      TEXT,                   -- e.g. "10886"
    field_name      TEXT NOT NULL,          -- "material" / "thickness_mm" / "unit_cost"
    ai_value        TEXT,                   -- what AI produced
    correct_value   TEXT,                   -- what estimator changed it to
    corrected_by    TEXT,                   -- "Tim" / "Howard" / "Tony"
    confidence      REAL DEFAULT 1.0,
    notes           TEXT,
    processed       INTEGER DEFAULT 0,      -- 0=pending, 1=applied to knowledge base
    created_at      TEXT DEFAULT (datetime('now'))
);

-- ── Part knowledge base ───────────────────────────────────────────────────────
-- Accumulated certainty about specific part numbers.
-- confidence 1.0 = known for certain, 0.5 = inferred
CREATE TABLE IF NOT EXISTS part_knowledge (
    part_number         TEXT PRIMARY KEY,
    description         TEXT,
    material            TEXT,
    thickness_mm        REAL,
    operations          TEXT,               -- JSON list
    typical_unit_cost   REAL,
    min_cost            REAL,
    max_cost            REAL,
    confidence          REAL DEFAULT 0.5,
    source              TEXT,               -- "estimator_correction"/"historical"/"dxf_filename"
    correction_count    INTEGER DEFAULT 0,
    last_corrected_by   TEXT,
    job_numbers_seen    TEXT,               -- JSON list of jobs where seen
    last_updated        TEXT DEFAULT (datetime('now'))
);

-- ── Live override rules ────────────────────────────────────────────────────────
-- Rules that fire on every scan to prevent known errors.
-- Generated automatically when correction_count >= 3 for same pattern.
CREATE TABLE IF NOT EXISTS live_overrides (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_name       TEXT NOT NULL,
    pattern_type    TEXT NOT NULL,          -- "material_value"/"part_number_suffix"/"dxf_filename"/"description_text"
    trigger_field   TEXT,                   -- field that triggers this rule
    trigger_value   TEXT,                   -- value that triggers (can be regex)
    trigger_context TEXT,                   -- additional condition (JSON)
    correction_field TEXT NOT NULL,         -- field to correct
    correction_value TEXT NOT NULL,         -- value to apply
    confidence      REAL DEFAULT 1.0,
    active          INTEGER DEFAULT 1,      -- 0=disabled
    auto_generated  INTEGER DEFAULT 0,      -- 1=created by rule_generator
    trigger_count   INTEGER DEFAULT 0,      -- how many times this rule has fired
    source_corrections TEXT,               -- JSON list of correction IDs that created this
    created_at      TEXT DEFAULT (datetime('now')),
    last_fired      TEXT
);

-- ── Drawing text patterns ──────────────────────────────────────────────────────
-- Known OCR patterns and what they mean (or should be ignored)
CREATE TABLE IF NOT EXISTS drawing_patterns (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern_text    TEXT NOT NULL,          -- e.g. "NOITCERID DEHSURB"
    pattern_type    TEXT,                   -- "reversed_text"/"boilerplate"/"material_alias"
    meaning         TEXT,                   -- human-readable interpretation
    action          TEXT,                   -- "ignore"/"remap_material"/"extract_value"
    mapped_value    TEXT,                   -- if action=remap, what to map to
    confidence      REAL DEFAULT 1.0,
    occurrence_count INTEGER DEFAULT 1,
    first_seen_job  TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

-- ── Historical estimates (ingested from K:\\Estimating) ─────────────────────
CREATE TABLE IF NOT EXISTS historical_estimates (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file     TEXT,
    job_number      TEXT,
    drawing_number  TEXT,
    part_number     TEXT,
    description     TEXT,
    material        TEXT,
    thickness_mm    REAL,
    quantity        INTEGER,
    unit_cost       REAL,
    total_cost      REAL,
    estimator       TEXT,
    customer        TEXT,
    estimate_date   TEXT,
    ingested_at     TEXT DEFAULT (datetime('now'))
);

-- ── Scan log ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS scan_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id         TEXT NOT NULL,          -- PDF filename stem
    job_number      TEXT,
    pdf_path        TEXT,
    dxf_count       INTEGER DEFAULT 0,
    parts_count     INTEGER DEFAULT 0,
    parts_estimated INTEGER DEFAULT 0,
    total_estimate  REAL,
    quality_score   TEXT,                   -- "HIGHEST"/"HIGH"/"MEDIUM"/"LOW"
    overrides_applied INTEGER DEFAULT 0,   -- how many learning rules fired
    scan_date       TEXT DEFAULT (datetime('now'))
);

-- ── Indices ────────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_corrections_part    ON corrections(part_number);
CREATE INDEX IF NOT EXISTS idx_corrections_field   ON corrections(field_name, ai_value);
CREATE INDEX IF NOT EXISTS idx_corrections_proc    ON corrections(processed);
CREATE INDEX IF NOT EXISTS idx_overrides_active    ON live_overrides(active, pattern_type);
CREATE INDEX IF NOT EXISTS idx_historical_part     ON historical_estimates(part_number);
CREATE INDEX IF NOT EXISTS idx_historical_drawing  ON historical_estimates(drawing_number);
CREATE INDEX IF NOT EXISTS idx_scan_log_job        ON scan_log(job_number);
"""

# ── Seed overrides — known errors from today's scans ─────────────────────────
_SEED_OVERRIDES = [
    {
        "rule_name":        "led_ocr_to_mild_steel",
        "pattern_type":     "material_value",
        "trigger_field":    "normalized_material",
        "trigger_value":    "LED",
        "trigger_context":  json.dumps({"geometry_source_contains": "dxf"}),
        "correction_field": "normalized_material",
        "correction_value": "MILD_STEEL",
        "confidence":       0.95,
        "auto_generated":   0,
        "source_corrections": "[]",
    },
    {
        "rule_name":        "led_material_raw_to_mild_steel",
        "pattern_type":     "material_value",
        "trigger_field":    "materials_raw",
        "trigger_value":    "Led",
        "trigger_context":  json.dumps({"geometry_source_contains": "dxf"}),
        "correction_field": "normalized_material",
        "correction_value": "MILD_STEEL",
        "confidence":       0.95,
        "auto_generated":   0,
        "source_corrections": "[]",
    },
    {
        "rule_name":        "dxf_ms_filename_material",
        "pattern_type":     "dxf_filename",
        "trigger_field":    "dxf_source_file",
        "trigger_value":    "_MS_",
        "trigger_context":  json.dumps({}),
        "correction_field": "normalized_material",
        "correction_value": "MILD_STEEL",
        "confidence":       1.0,
        "auto_generated":   0,
        "source_corrections": "[]",
    },
    {
        "rule_name":        "dxf_petg_filename_material",
        "pattern_type":     "dxf_filename",
        "trigger_field":    "dxf_source_file",
        "trigger_value":    "PETG",
        "trigger_context":  json.dumps({}),
        "correction_field": "normalized_material",
        "correction_value": "ACRYLIC",
        "confidence":       1.0,
        "auto_generated":   0,
        "source_corrections": "[]",
    },
    {
        "rule_name":        "dxf_joinery_filename_material",
        "pattern_type":     "dxf_filename",
        "trigger_field":    "dxf_source_file",
        "trigger_value":    "JOINERY",
        "trigger_context":  json.dumps({}),
        "correction_field": "normalized_material",
        "correction_value": "MDF",
        "confidence":       0.95,
        "auto_generated":   0,
        "source_corrections": "[]",
    },
]

# ── Seed part knowledge — confirmed from today's scans ────────────────────────
_SEED_PARTS = [
    {"part_number": "10886-25-01", "material": "MILD_STEEL", "thickness_mm": 1.5,
     "description": "140DEG CORNER PROTECTOR", "confidence": 0.95,
     "source": "scan_correction_20260529"},
    {"part_number": "10886-25-02", "material": "MILD_STEEL", "thickness_mm": 1.5,
     "description": "130DEG CORNER PROTECTOR", "confidence": 0.95,
     "source": "scan_correction_20260529"},
    {"part_number": "10886-09-01", "material": "MILD_STEEL", "thickness_mm": 1.5,
     "description": "CLAD BRACKET PANEL", "confidence": 0.9,
     "source": "scan_correction_20260529"},
    {"part_number": "10886-35-03", "material": "MILD_STEEL", "thickness_mm": 1.5,
     "description": "FOOT PLATE", "confidence": 0.95,
     "source": "scan_correction_20260529"},
    {"part_number": "10886-01-005", "material": "MILD_STEEL", "thickness_mm": 2.0,
     "description": "STRIKE PLATE", "confidence": 0.95,
     "source": "scan_dxf_filename_20260529"},
]


def init_db() -> None:
    """Create all tables and seed known corrections from today."""
    with _connect() as conn:
        conn.executescript(_SCHEMA)
        # Seed live overrides if not already present
        for override in _SEED_OVERRIDES:
            existing = conn.execute(
                "SELECT id FROM live_overrides WHERE rule_name=?",
                (override["rule_name"],)
            ).fetchone()
            if not existing:
                conn.execute("""
                    INSERT INTO live_overrides
                    (rule_name, pattern_type, trigger_field, trigger_value,
                     trigger_context, correction_field, correction_value,
                     confidence, auto_generated, source_corrections)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                """, (
                    override["rule_name"], override["pattern_type"],
                    override["trigger_field"], override["trigger_value"],
                    override["trigger_context"], override["correction_field"],
                    override["correction_value"], override["confidence"],
                    override["auto_generated"], override["source_corrections"],
                ))
        # Seed part knowledge
        for p in _SEED_PARTS:
            existing = conn.execute(
                "SELECT part_number FROM part_knowledge WHERE part_number=?",
                (p["part_number"],)
            ).fetchone()
            if not existing:
                conn.execute("""
                    INSERT INTO part_knowledge
                    (part_number, description, material, thickness_mm,
                     confidence, source, correction_count)
                    VALUES (?,?,?,?,?,?,1)
                """, (
                    p["part_number"], p.get("description"), p["material"],
                    p.get("thickness_mm"), p["confidence"], p["source"],
                ))
        conn.commit()
    print(f"[corrections_db] Initialised: {_DB_PATH}")


# ══════════════════════════════════════════════════════════════════════════════
# READ — LOOKUP FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def lookup_part(part_number: str) -> Optional[Dict[str, Any]]:
    """Return known data for a part number, or None if unknown."""
    if not part_number:
        return None
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM part_knowledge WHERE part_number=?",
            (part_number.upper().strip(),)
        ).fetchone()
        return dict(row) if row else None


def get_active_overrides(pattern_type: Optional[str] = None) -> List[Dict]:
    """Return all active override rules, optionally filtered by type."""
    with _connect() as conn:
        if pattern_type:
            rows = conn.execute(
                "SELECT * FROM live_overrides WHERE active=1 AND pattern_type=?",
                (pattern_type,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM live_overrides WHERE active=1"
            ).fetchall()
        return [dict(r) for r in rows]


def get_historical_cost(part_number: str = None,
                        drawing_number: str = None,
                        material: str = None) -> Optional[Dict]:
    """Look up historical cost benchmarks."""
    with _connect() as conn:
        if part_number:
            rows = conn.execute("""
                SELECT material, AVG(unit_cost) as avg_cost,
                       MIN(unit_cost) as min_cost, MAX(unit_cost) as max_cost,
                       COUNT(*) as sample_count
                FROM historical_estimates
                WHERE part_number=? AND unit_cost > 0
                GROUP BY material
            """, (part_number,)).fetchall()
            if rows:
                return [dict(r) for r in rows]
        if drawing_number:
            rows = conn.execute("""
                SELECT material, AVG(unit_cost) as avg_cost,
                       MIN(unit_cost) as min_cost, MAX(unit_cost) as max_cost,
                       COUNT(*) as sample_count
                FROM historical_estimates
                WHERE drawing_number LIKE ? AND unit_cost > 0
                GROUP BY material
            """, (f"%{drawing_number}%",)).fetchall()
            if rows:
                return [dict(r) for r in rows]
    return None


# ══════════════════════════════════════════════════════════════════════════════
# WRITE — CORRECTION LOGGING
# ══════════════════════════════════════════════════════════════════════════════

def log_correction(scan_id: str, part_number: str, job_number: str,
                   field_name: str, ai_value: str, correct_value: str,
                   corrected_by: str = "estimator", notes: str = "") -> int:
    """Log a single field correction from an estimator. Returns correction id."""
    with _connect() as conn:
        cursor = conn.execute("""
            INSERT INTO corrections
            (scan_id, part_number, job_number, field_name,
             ai_value, correct_value, corrected_by, notes)
            VALUES (?,?,?,?,?,?,?,?)
        """, (scan_id, part_number, job_number, field_name,
              str(ai_value), str(correct_value), corrected_by, notes))
        conn.commit()
        return cursor.lastrowid


def update_part_knowledge(part_number: str, field: str, value: Any,
                          source: str = "estimator_correction",
                          corrected_by: str = "estimator") -> None:
    """Update part knowledge base with a confirmed value."""
    if not part_number:
        return
    pn = part_number.upper().strip()
    with _connect() as conn:
        existing = conn.execute(
            "SELECT * FROM part_knowledge WHERE part_number=?", (pn,)
        ).fetchone()
        if existing:
            conn.execute(f"""
                UPDATE part_knowledge
                SET {field}=?,
                    confidence=MIN(1.0, confidence + 0.15),
                    correction_count=correction_count+1,
                    last_corrected_by=?,
                    source=?,
                    last_updated=datetime('now')
                WHERE part_number=?
            """, (value, corrected_by, source, pn))
        else:
            data = {"material": None, "thickness_mm": None,
                    "operations": None, "typical_unit_cost": None}
            data[field] = value
            conn.execute("""
                INSERT INTO part_knowledge
                (part_number, material, thickness_mm, operations,
                 typical_unit_cost, confidence, source,
                 correction_count, last_corrected_by)
                VALUES (?,?,?,?,?,0.7,?,1,?)
            """, (pn, data["material"], data["thickness_mm"],
                  data["operations"], data["typical_unit_cost"],
                  source, corrected_by))
        conn.commit()


def log_scan(scan_id: str, job_number: str, pdf_path: str,
             dxf_count: int, parts_count: int, parts_estimated: int,
             total_estimate: float, quality_score: str,
             overrides_applied: int = 0) -> None:
    """Record a completed scan in the scan log."""
    with _connect() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO scan_log
            (scan_id, job_number, pdf_path, dxf_count, parts_count,
             parts_estimated, total_estimate, quality_score, overrides_applied)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (scan_id, job_number, pdf_path, dxf_count, parts_count,
              parts_estimated, total_estimate, quality_score, overrides_applied))
        conn.commit()


def fire_override(override_id: int) -> None:
    """Record that an override rule fired."""
    with _connect() as conn:
        conn.execute("""
            UPDATE live_overrides
            SET trigger_count=trigger_count+1,
                last_fired=datetime('now')
            WHERE id=?
        """, (override_id,))
        conn.commit()


# ══════════════════════════════════════════════════════════════════════════════
# STATS — FOR REPORTING
# ══════════════════════════════════════════════════════════════════════════════

def get_learning_stats() -> Dict[str, Any]:
    """Summary of learning state — how much the system knows."""
    with _connect() as conn:
        known_parts = conn.execute(
            "SELECT COUNT(*) FROM part_knowledge WHERE confidence >= 0.8"
        ).fetchone()[0]
        total_parts = conn.execute(
            "SELECT COUNT(*) FROM part_knowledge"
        ).fetchone()[0]
        corrections = conn.execute(
            "SELECT COUNT(*) FROM corrections"
        ).fetchone()[0]
        overrides = conn.execute(
            "SELECT COUNT(*) FROM live_overrides WHERE active=1"
        ).fetchone()[0]
        historical = conn.execute(
            "SELECT COUNT(*) FROM historical_estimates"
        ).fetchone()[0]
        scans = conn.execute(
            "SELECT COUNT(*) FROM scan_log"
        ).fetchone()[0]
        overrides_fired = conn.execute(
            "SELECT SUM(trigger_count) FROM live_overrides"
        ).fetchone()[0] or 0
        return {
            "known_parts_high_confidence": known_parts,
            "total_parts_in_kb":           total_parts,
            "total_corrections_logged":    corrections,
            "active_override_rules":       overrides,
            "overrides_fired_total":       overrides_fired,
            "historical_estimates":        historical,
            "total_scans_logged":          scans,
        }


if __name__ == "__main__":
    init_db()
    stats = get_learning_stats()
    print("\nSDIAIVision Learning Database — Status")
    print("=" * 45)
    for k, v in stats.items():
        print(f"  {k:<35} {v}")
