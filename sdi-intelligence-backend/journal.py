"""
SDI Intelligence — update journal for the Voice CRM write path.

The architecture requires that every proposed change is recorded durably, that
the outcome is recorded honestly, and that **a retry can never repeat a saved
change**. This is the component that makes those true.

A change is a two-step conversation:

    propose  → validated, read back to the person, recorded as "proposed"
    confirm  → re-checked, written, recorded as "applied" (or "failed"/"conflict")

The proposal id is the idempotency key. If a confirm arrives twice — a dropped
call that redials, a retry after a timeout, a voice agent that did not hear the
acknowledgement — the second one returns the recorded outcome of the first and
writes nothing. That is the specific failure the pilot must not have: a record
silently updated twice because the line dropped.

States
    proposed  validated and read back, awaiting confirmation
    applied   written to SharePoint, old and new values recorded
    failed    the write was attempted and refused; `outcome` says why
    conflict  the record changed between proposal and confirmation, so the
              proposal was abandoned rather than overwriting someone's edit
    expired   never confirmed within the window

Nothing here deletes. The journal is the audit trail.
"""

import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

_DEFAULT_PATH = Path(__file__).with_name("voicecrm_journal.db")
_local = threading.local()

PROPOSAL_TTL_SECONDS = 15 * 60


class UpdateJournal:
    def __init__(self, path: Optional[str] = None):
        self.path = str(path or os.getenv("SDI_VOICECRM_JOURNAL_DB", "") or _DEFAULT_PATH)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(_local, "jconn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.row_factory = sqlite3.Row
            _local.jconn = conn
        return conn

    def _init_db(self) -> None:
        self._conn().execute("""
            CREATE TABLE IF NOT EXISTS updates (
                proposal_id TEXT PRIMARY KEY,
                created     REAL NOT NULL,
                applied     REAL,
                user_oid    TEXT,
                user_name   TEXT,
                source      TEXT,
                item_id     TEXT NOT NULL,
                project_ref TEXT,
                field       TEXT NOT NULL,
                old_value   TEXT,
                new_value   TEXT,
                etag        TEXT,
                state       TEXT NOT NULL,
                outcome     TEXT
            )
        """)
        self._conn().execute("CREATE INDEX IF NOT EXISTS ix_updates_created ON updates(created DESC)")

    def propose(self, *, user: dict, item_id: str, project_ref: str, field: str,
                old_value: Any, new_value: Any, etag: str, source: str = "app") -> str:
        pid = uuid.uuid4().hex
        self._conn().execute(
            """INSERT INTO updates (proposal_id, created, user_oid, user_name, source,
                                    item_id, project_ref, field, old_value, new_value,
                                    etag, state)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,'proposed')""",
            (pid, time.time(), user.get("oid", ""), user.get("name", ""), source,
             item_id, project_ref, field, _s(old_value), _s(new_value), etag),
        )
        return pid

    def get(self, proposal_id: str) -> Optional[dict]:
        row = self._conn().execute(
            "SELECT * FROM updates WHERE proposal_id = ?", (proposal_id,)
        ).fetchone()
        if not row:
            return None
        entry = dict(row)
        if entry["state"] == "proposed" and entry["created"] < time.time() - PROPOSAL_TTL_SECONDS:
            self.finish(proposal_id, "expired", "Not confirmed within 15 minutes.")
            entry["state"] = "expired"
            entry["outcome"] = "Not confirmed within 15 minutes."
        return entry

    def finish(self, proposal_id: str, state: str, outcome: str = "") -> None:
        """Record a terminal state. Only a proposal still open can be closed."""
        self._conn().execute(
            """UPDATE updates SET state = ?, outcome = ?, applied = ?
               WHERE proposal_id = ? AND state = 'proposed'""",
            (state, outcome, time.time() if state == "applied" else None, proposal_id),
        )

    def recent(self, limit: int = 25) -> list[dict]:
        rows = self._conn().execute(
            "SELECT * FROM updates ORDER BY created DESC LIMIT ?", (int(limit),)
        ).fetchall()
        return [dict(r) for r in rows]

    def counts(self) -> dict[str, int]:
        rows = self._conn().execute("SELECT state, COUNT(*) c FROM updates GROUP BY state").fetchall()
        return {r["state"]: r["c"] for r in rows}


def _s(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return str(value)
