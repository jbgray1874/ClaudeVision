"""
SDI Intelligence — durable session storage.

Sessions used to live in a process dictionary, so restarting the service signed
everyone out and the portal could never run more than one worker. This keeps
them in SQLite instead: no extra service to install on the Windows host, it
survives a restart, and several workers on the same machine share it.

What is stored, and why it is encrypted
---------------------------------------
A session holds the user's claims (harmless) and the MSAL token cache (not
harmless — it contains a refresh token that can mint new access tokens). Writing
that to disk in the clear would mean a copied file, a stray backup, or a nightly
sync to the shares hands over the ability to act as that person.

So the payload is encrypted with Fernet (AES-128-CBC + HMAC) under a key derived
from SDI_SESSION_SECRET. Change that secret and every existing session becomes
unreadable, which is the correct behaviour — it is the emergency "sign everyone
out" lever.

Limits, stated plainly:
  * One machine. SQLite over a file share is not a clustering strategy — if this
    ever runs on two hosts, move to Redis and keep this interface.
  * The secret lives in .env next to the database, so this protects against a
    leaked file, not against someone who already owns the server.
"""

import base64
import hashlib
import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

_DEFAULT_PATH = Path(__file__).with_name("sessions.db")
_local = threading.local()


def _fernet(secret: str) -> Fernet:
    # Fernet needs 32 url-safe base64 bytes; SDI_SESSION_SECRET is free-form text.
    digest = hashlib.sha256(("sdi-session-store:" + secret).encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


class SessionStore:
    def __init__(self, secret: str, path: Optional[str] = None):
        self.path = str(path or os.getenv("SDI_SESSION_DB", "") or _DEFAULT_PATH)
        self._f = _fernet(secret)
        self._init_db()

    # sqlite3 connections are not shareable across threads; uvicorn uses several.
    def _conn(self) -> sqlite3.Connection:
        conn = getattr(_local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
            conn.execute("PRAGMA journal_mode=WAL")
            _local.conn = conn
        return conn

    def _init_db(self) -> None:
        conn = self._conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                sid      TEXT PRIMARY KEY,
                payload  BLOB NOT NULL,
                expires  REAL NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS ix_sessions_expires ON sessions(expires)")
        try:
            os.chmod(self.path, 0o600)   # best effort; a no-op on some Windows setups
        except OSError:
            pass

    def put(self, sid: str, data: dict, expires: float) -> None:
        blob = self._f.encrypt(json.dumps(data).encode("utf-8"))
        self._conn().execute(
            "INSERT OR REPLACE INTO sessions (sid, payload, expires) VALUES (?, ?, ?)",
            (sid, blob, expires),
        )

    def get(self, sid: str) -> Optional[dict]:
        row = self._conn().execute(
            "SELECT payload, expires FROM sessions WHERE sid = ?", (sid,)
        ).fetchone()
        if not row:
            return None
        blob, expires = row
        if expires < time.time():
            self.delete(sid)
            return None
        try:
            data = json.loads(self._f.decrypt(blob))
        except (InvalidToken, ValueError):
            # Written under a different SDI_SESSION_SECRET — treat as signed out.
            self.delete(sid)
            return None
        data["expires"] = expires
        return data

    def delete(self, sid: str) -> None:
        self._conn().execute("DELETE FROM sessions WHERE sid = ?", (sid,))

    def reap(self) -> int:
        cur = self._conn().execute("DELETE FROM sessions WHERE expires < ?", (time.time(),))
        return cur.rowcount or 0

    def count(self) -> int:
        return self._conn().execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
