"""
BrightHR -> InVentry pipeline configuration.
Reads the SAME .env as the backend (config.py). Nothing secret is hard-coded.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Which .env this is matters more than it looks. A git worktree gets its own
# copy, .env is deliberately untracked, and the two drift - a setting added to
# the wrong one looks exactly like a setting that did not work. Both are
# reported, so the answer is one line of output rather than an afternoon.
ENV_FILE = Path(__file__).with_name(".env")
ENV_FILE_FOUND = ENV_FILE.is_file()
load_dotenv(ENV_FILE)


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
# Confirmed against InVentry's Partner API documentation AND their Postman
# collection (received 16 and 25 Sep 2026). The collection is authoritative -
# several field names in the field-information PDF differ from the live JSON.
#
#   Base      https://<host>:4816/PartnerAPI/
#   Host      the main reception touchscreen, unless the site runs its own VM
#             for the InVentry software. InVentry support can confirm which.
#   Auth      apikey + partnersecret, both as request HEADERS.
#             apikey: InVentry console -> Setup & Options -> Partner API ->
#             Add API Key -> partner "End User Development" (confirmed by
#             InVentry as the right option for a customer's own integration).
#   Certs     self-signed; exportable from the V4 folder on the main unit.
#   Limits    20 GET/minute (429 on exceed). POST is exempt.
INVENTRY_API_BASE_URL = _opt("INVENTRY_API_BASE_URL")          # e.g. https://10.0.0.50:4816
INVENTRY_API_KEY = _opt("INVENTRY_API_KEY")
INVENTRY_PARTNER_SECRET = _opt("INVENTRY_PARTNER_SECRET")
INVENTRY_API_TIMEOUT = int(_opt("INVENTRY_API_TIMEOUT", "30"))

# TLS verification. The certificate is self-signed, so plain verification
# fails. Preferred: export it from the V4 folder on the InVentry unit and point
# INVENTRY_API_CA_BUNDLE at it, which keeps verification on. Otherwise set
# INVENTRY_API_VERIFY=false, which trusts any certificate on that host -
# acceptable only because this is a LAN call to a known machine.
INVENTRY_API_CA_BUNDLE = _opt("INVENTRY_API_CA_BUNDLE")
INVENTRY_API_VERIFY = _opt("INVENTRY_API_VERIFY", "false").lower() not in ("false", "0", "no", "off")

# Check the hostname against the certificate as well as the certificate itself?
#
# InVentry's certificate carries CN=InVentry-PC and NO subjectAltName. Modern
# TLS stacks ignore CN entirely, so the name can never match, however the host
# is addressed - by IP, or by a hosts entry for InVentry-PC. Proven on the live
# system 6 Oct 2026: "certificate is not valid for 'inventry-pc'". curl still
# falls back to CN and so appears to work, which is what misled us.
#
# Turning this off is NOT the same as turning verification off. With
# INVENTRY_API_CA_BUNDLE pinned to their exported certificate, the connection
# is still refused unless the server presents that exact certificate - verified
# against a CN-only certificate before this was committed. Hostname checking
# guards against a CA issuing a certificate for the wrong name, which means
# nothing when the "CA" is the one self-signed certificate we pinned.
#
# The proper fix is InVentry reissuing with a subjectAltName. Until then, set
# this false AND keep INVENTRY_API_CA_BUNDLE set. Setting it false WITHOUT a
# pinned bundle is the genuinely weak configuration, and is warned about.
INVENTRY_API_CHECK_HOSTNAME = _opt("INVENTRY_API_CHECK_HOSTNAME", "true").lower() not in ("false", "0", "no", "off")

# Endpoint paths, from the Postman collection.
INVENTRY_PATH_CHECK_AUTH = _opt("INVENTRY_PATH_CHECK_AUTH", "/PartnerAPI/CheckAuth")
INVENTRY_PATH_PERSONNEL = _opt("INVENTRY_PATH_PERSONNEL", "/PartnerAPI/GetPersonnel/")
INVENTRY_PATH_PERSONNEL_ADD = _opt("INVENTRY_PATH_PERSONNEL_ADD", "/PartnerAPI/AddPersonnel")
INVENTRY_PATH_PERSONNEL_ACTION = _opt("INVENTRY_PATH_PERSONNEL_ACTION", "/PartnerAPI/AddPersonnelAction")
INVENTRY_PATH_LATEST_ACTIONS = _opt("INVENTRY_PATH_LATEST_ACTIONS", "/PartnerAPI/GetLatestPersonnelActions")
INVENTRY_PATH_SYSTEM_TIME = _opt("INVENTRY_PATH_SYSTEM_TIME", "/PartnerAPI/GetSystemTime")

# GetPersonnel returns staff only unless asked otherwise.
INVENTRY_INCLUDE_NON_STAFF = _opt("INVENTRY_INCLUDE_NON_STAFF", "false").lower() in ("true", "1", "yes", "on")

# ActionType values for AddPersonnelAction. The live data shows LastActivity
# holding exactly "IN" or "OUT".
INVENTRY_EVENT_TYPE_IN = _opt("INVENTRY_EVENT_TYPE_IN", "IN")
INVENTRY_EVENT_TYPE_OUT = _opt("INVENTRY_EVENT_TYPE_OUT", "OUT")

# LastActivity values meaning "currently on site".
INVENTRY_ACTIVITY_IN_VALUES = [
    v.strip().upper() for v in _opt("INVENTRY_ACTIVITY_IN_VALUES", "IN").split(",") if v.strip()
]

# ActionLocation sent with our sign-in events. InVentry reports it back as
# LastEventLocation, alongside values like "CONSOLE" or a location id for
# sign-ins made at a touchscreen or the Anywhere app - so a distinctive value
# here is how we recognise our own writes later, which is what makes automatic
# sign-out safe. Unverified: InVentry may require an existing location rather
# than free text. Leave blank to send none.
INVENTRY_ACTION_LOCATION = _opt("INVENTRY_ACTION_LOCATION", "BRIGHTHR SYNC")

# Sign people OUT of InVentry when BrightHR no longer shows them clocked in?
# Off by default. With INVENTRY_ONLY_SIGN_OUT_OUR_OWN left on, only people
# whose last event came from INVENTRY_ACTION_LOCATION are ever signed out, so a
# sign-in made at reception is never undone by us.
INVENTRY_ENABLE_SIGN_OUT = _opt("INVENTRY_ENABLE_SIGN_OUT", "false").lower() in ("true", "1", "yes", "on")
INVENTRY_ONLY_SIGN_OUT_OUR_OWN = _opt("INVENTRY_ONLY_SIGN_OUT_OUR_OWN", "true").lower() not in ("false", "0", "no", "off")

# Cap on sign-outs in a single push, as a backstop against a bad on-site list
# emptying InVentry's register. Exceeding it suppresses the sign-outs.
INVENTRY_MAX_SIGN_OUTS_PER_RUN = int(_opt("INVENTRY_MAX_SIGN_OUTS_PER_RUN", "25"))

# A BrightHR point-in-time query returns anyone whose clocking is still open,
# so someone who forgot to clock out stays "on site" indefinitely. Real data
# from 28 Sep 2026: 15 of 104 had clock-ins over 2 days old, one of them 61
# days. Those people are not in the building, and must not reach a fire roll.
# Clock-ins older than this are treated as forgotten, and reported separately.
# 0 disables the check.
# 20h, not 16: the earliest shifts in the real data start at 04:33, and a 16h
# window would flag one of those as forgotten by 21:00 the same day. 20h still
# catches anything left open from a previous day.
BLIP_MAX_CLOCKIN_AGE_HOURS = float(_opt("BLIP_MAX_CLOCKIN_AGE_HOURS", "20"))
