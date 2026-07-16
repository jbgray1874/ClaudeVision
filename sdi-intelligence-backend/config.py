"""
SDI Intelligence — backend configuration loader.

Reads the values you populated in ".env", validates them, and exposes them
as simple typed attributes for the rest of the service. Nothing secret is
hard-coded here — it all comes from .env, which is never committed.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env sitting next to this file
load_dotenv(Path(__file__).with_name(".env"))


def _req(name: str) -> str:
    val = os.getenv(name, "").strip()
    if not val or val.startswith("<"):
        raise RuntimeError(
            f"Config value {name} is not set in .env "
            f"(still shows a <placeholder> or is blank)."
        )
    return val


def _opt(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


# ── Service ───────────────────────────────────────────────────────────────
HOST = _opt("SDI_HOST", "0.0.0.0")
PORT = int(_opt("SDI_PORT", "8071"))
ALLOWED_ORIGINS = [o.strip() for o in _opt("SDI_ALLOWED_ORIGINS").split(",") if o.strip()]

# ── Access gate ─────────────────────────────────────────────────────────────
API_KEY = _opt("SDI_API_KEY")  # empty disables the gate (not recommended)

# ── File shares ─────────────────────────────────────────────────────────────
FILE_ROOTS = [r.strip() for r in _opt("SDI_FILE_ROOTS").split("|") if r.strip()]
ALLOWED_EXTENSIONS = {
    e.strip().lower() if e.strip().startswith(".") else "." + e.strip().lower()
    for e in _opt("SDI_ALLOWED_EXTENSIONS", ".xlsx,.html,.json,.jpg").split(",")
    if e.strip()
}

# ── Database ────────────────────────────────────────────────────────────────
DB_DRIVER = _opt("SDI_DB_DRIVER", "ODBC Driver 18 for SQL Server")
DB_SERVER = _opt("SDI_DB_SERVER")
DB_NAME = _opt("SDI_DB_NAME")
DB_AUTH = _opt("SDI_DB_AUTH", "sql").lower()
DB_USER = _opt("SDI_DB_USER")
DB_PASSWORD = _opt("SDI_DB_PASSWORD")
DB_ENCRYPT = _opt("SDI_DB_ENCRYPT", "yes")
DB_TRUST_CERT = _opt("SDI_DB_TRUST_CERT", "yes")

DB_CONFIGURED = bool(DB_SERVER and not DB_SERVER.startswith("<") and DB_NAME and not DB_NAME.startswith("<"))


def db_connection_string() -> str:
    """Build the pyodbc connection string from the .env parts."""
    parts = [
        f"DRIVER={{{DB_DRIVER}}}",
        f"SERVER={DB_SERVER}",
        f"DATABASE={DB_NAME}",
        f"Encrypt={DB_ENCRYPT}",
        f"TrustServerCertificate={DB_TRUST_CERT}",
    ]
    if DB_AUTH == "windows":
        parts.append("Trusted_Connection=yes")
    else:
        parts.append(f"UID={DB_USER}")
        parts.append(f"PWD={DB_PASSWORD}")
    return ";".join(parts) + ";"


def validate() -> None:
    """Called at startup — fails loudly if anything essential is unset."""
    if not FILE_ROOTS or any(r.startswith("\\\\<") or "<" in r for r in FILE_ROOTS):
        raise RuntimeError("SDI_FILE_ROOTS is not set to real UNC paths in .env")
    if not ALLOWED_ORIGINS:
        raise RuntimeError("SDI_ALLOWED_ORIGINS is not set in .env")
    if not API_KEY:
        print("[WARN] SDI_API_KEY is blank — the access gate is OFF. Set it before going live.")
    if not DB_CONFIGURED:
        print("[WARN] Database not configured — DB endpoints will report 'not configured'.")
