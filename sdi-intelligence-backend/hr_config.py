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

# ── InVentry roster CSV (the load target) ────────────────────────────────
# UNVERIFIED DESTINATION: this default was never confirmed with InVentry, and a
# local C:\ path cannot be read by an off-box or cloud InVentry instance. See
# docs/INVENTRY_INTEGRATION_REQUEST.md.
INVENTRY_CSV_PATH = _opt("INVENTRY_CSV_PATH", r"C:\InVentryImports\brighthr_staff.csv")

# ── InVentry on-site presence CSV (Blip -> InVentry, stage 3) ────────────
# Separate file from the staff roster: the roster says who exists, this says who
# is in the building right now (fire roll call). Same caveat as above - the
# destination is a placeholder until InVentry confirm how they ingest data.
INVENTRY_ONSITE_CSV_PATH = _opt("INVENTRY_ONSITE_CSV_PATH", r"C:\InVentryImports\brighthr_onsite.csv")

# Presence is only useful while it is current — refuse to load a Blip snapshot
# older than this (a stale fire roll is worse than no update).
BLIP_MAX_STALE_MINUTES = int(_opt("BLIP_MAX_STALE_MINUTES", "15"))

# Blip queries one endpoint per employee. If some of those calls fail, the
# snapshot under-reports who is on site, which is the dangerous direction for
# an evacuation list. Refuse to publish a snapshot with more failures than this.
BLIP_MAX_FAIL_PCT = float(_opt("BLIP_MAX_FAIL_PCT", "2"))

# ── Safety guards ────────────────────────────────────────────────────────
HR_MIN_RECORDS = int(_opt("HR_MIN_RECORDS", "1"))       # abort if fewer than this
HR_MAX_DROP_PCT = float(_opt("HR_MAX_DROP_PCT", "30"))  # flag if active drops > this % vs last good

HR_OUTPUT_DIR = _opt("HR_OUTPUT_DIR", r"K:\IT\HRSystemsOutput")

# ── InVentry Partner API (the supported integration route) ───────────────
# Confirmed from InVentry's Partner API documentation, Sep 2026:
#   * Auth: apikey + partnersecret, both in request HEADERS.
#     - apikey        created in the InVentry console: Setup & Options ->
#                     (bottom) Partner API -> toggle ON -> Add API Key ->
#                     choose the partner (e.g. "End User Developer") -> copy.
#     - partnersecret issued by InVentry Ltd; same for all their on-premises
#                     installs. Request it from InVentry if not held.
#   * The API is ON-PREMISES ONLY and not reachable externally. It usually runs
#     on the main reception sign-in touchscreen. SDI-APP01 is on the network, so
#     it can reach it directly; nothing cloud-hosted could.
#   * Certificates are locally issued and SELF-SIGNED - see INVENTRY_API_VERIFY.
#   * Rate limit: 20 GET calls/minute (429 on exceed). POST is exempt.
#   * POST bodies are x-www-form-urlencoded, NOT JSON.
INVENTRY_API_BASE_URL = _opt("INVENTRY_API_BASE_URL")          # e.g. https://<touchscreen-host>
INVENTRY_API_KEY = _opt("INVENTRY_API_KEY")
INVENTRY_PARTNER_SECRET = _opt("INVENTRY_PARTNER_SECRET")
INVENTRY_API_TIMEOUT = int(_opt("INVENTRY_API_TIMEOUT", "30"))

# TLS verification. Their certificate is self-signed, so plain verification
# fails. Preferred: export the certificate and point INVENTRY_API_CA_BUNDLE at
# it, which keeps verification on. Otherwise set INVENTRY_API_VERIFY=false,
# which trusts any certificate on that host - acceptable only because this is a
# LAN-local call to a known machine.
INVENTRY_API_CA_BUNDLE = _opt("INVENTRY_API_CA_BUNDLE")
INVENTRY_API_VERIFY = _opt("INVENTRY_API_VERIFY", "false").lower() not in ("false", "0", "no", "off")

# Endpoint paths. UNCONFIRMED - the exact routes live in InVentry's Postman
# collection, which we do not have yet. They are config precisely so that
# collection can be applied without touching code.
INVENTRY_PATH_PERSONNEL = _opt("INVENTRY_PATH_PERSONNEL", "/api/partner/personnel")
INVENTRY_PATH_PERSONNEL_ADD = _opt("INVENTRY_PATH_PERSONNEL_ADD", "/api/partner/personnel/add")
INVENTRY_PATH_PERSONNEL_UPDATE = _opt("INVENTRY_PATH_PERSONNEL_UPDATE", "/api/partner/personnel/update")
INVENTRY_PATH_SIGN_IN = _opt("INVENTRY_PATH_SIGN_IN", "/api/partner/signin")
INVENTRY_PATH_SIGN_OUT = _opt("INVENTRY_PATH_SIGN_OUT", "/api/partner/signout")

# Event type values written to the events table (EventType is varchar(10)).
INVENTRY_EVENT_TYPE_IN = _opt("INVENTRY_EVENT_TYPE_IN", "IN")
INVENTRY_EVENT_TYPE_OUT = _opt("INVENTRY_EVENT_TYPE_OUT", "OUT")

# LastActivityType values InVentry reports for a person who is currently on
# site. Read-only on their side; used to work out who is already signed in.
INVENTRY_ACTIVITY_IN_VALUES = [
    v.strip().upper() for v in _opt("INVENTRY_ACTIVITY_IN_VALUES", "IN,SIGNIN,SIGNED IN").split(",") if v.strip()
]

# Location recorded against sign-in events (LocID is settable).
INVENTRY_LOCATION_ID = _opt("INVENTRY_LOCATION_ID")

# Sign people OUT of InVentry when BrightHR no longer shows them clocked in?
# Off by default: signing someone out of the fire roll wrongly is the dangerous
# direction, so enable only once sign-ins are proven correct.
INVENTRY_ENABLE_SIGN_OUT = _opt("INVENTRY_ENABLE_SIGN_OUT", "false").lower() in ("true", "1", "yes", "on")

# Cap on sign-outs in a single push, as a backstop against a bad on-site list
# emptying InVentry's register. Exceeding it suppresses the sign-outs.
INVENTRY_MAX_SIGN_OUTS_PER_RUN = int(_opt("INVENTRY_MAX_SIGN_OUTS_PER_RUN", "25"))
