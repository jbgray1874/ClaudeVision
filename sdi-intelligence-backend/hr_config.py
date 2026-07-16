"""
BrightHR -> InVentry pipeline configuration.
Reads the SAME .env as the backend (config.py). Nothing secret is hard-coded.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))


def _opt(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


# ── BrightHR environment ─────────────────────────────────────────────────
BH_ENV = _opt("BH_ENV", "sandbox").lower()          # "sandbox" | "production"
_SANDBOX = BH_ENV != "production"

# Token URL auto-selects from BH_ENV unless explicitly overridden.
BH_TOKEN_URL = _opt("BH_TOKEN_URL") or (
    "https://sandbox-login.brighthr.com/connect/token" if _SANDBOX
    else "https://login.brighthr.com/connect/token"
)
# MUST be verified against BrightHR's developer docs / sandbox before production.
BH_EMPLOYEE_URL = _opt("BH_EMPLOYEE_URL")

# ── Auth (pluggable) ─────────────────────────────────────────────────────
# "client_credentials" = app auth (NO user context — may 403 on user endpoints)
# "pat"                = Personal Access Token (carries user context)
BH_AUTH_MODE = _opt("BH_AUTH_MODE", "client_credentials").lower()
BH_CLIENT_ID = _opt("BH_CLIENT_ID")
BH_CLIENT_SECRET = _opt("BH_CLIENT_SECRET")
BH_SCOPE = _opt("BH_SCOPE")          # space-separated, if BrightHR requires scopes
BH_PAT = _opt("BH_PAT")              # used only when BH_AUTH_MODE = "pat"

# ── Networking / paging ──────────────────────────────────────────────────
BH_TIMEOUT = int(_opt("BH_TIMEOUT", "30"))
BH_PAGE_SIZE = int(_opt("BH_PAGE_SIZE", "100"))
BH_MAX_PAGES = int(_opt("BH_MAX_PAGES", "200"))     # safety cap on the page loop

# ── Local storage (audit trail + the load source) ────────────────────────
HR_SNAPSHOT_DIR = _opt("HR_SNAPSHOT_DIR", r"C:\SDIIntelligence\hr\snapshots")

# ── InVentry watched-folder CSV (the load target) ────────────────────────
INVENTRY_CSV_PATH = _opt("INVENTRY_CSV_PATH", r"C:\InVentryImports\brighthr_staff.csv")

# ── Safety guards ────────────────────────────────────────────────────────
HR_MIN_RECORDS = int(_opt("HR_MIN_RECORDS", "1"))       # abort if fewer than this
HR_MAX_DROP_PCT = float(_opt("HR_MAX_DROP_PCT", "30"))  # flag if active drops > this % vs last good

HR_OUTPUT_DIR = _opt("HR_OUTPUT_DIR", r"K:\IT\HRSystemsOutput")
