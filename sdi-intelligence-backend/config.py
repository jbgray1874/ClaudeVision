"""
SDI Intelligence — backend configuration loader.

THREE LAYERS, AND WHICH ONE A VALUE BELONGS IN IS DECIDED BY WHAT THE VALUE IS,
not by which machine it is on.

    env/common.env      committed    the same everywhere: UNC roots, file types
    env/<profile>.env   committed    differs by machine, not secret: port, origins
    .env                NEVER        secrets, and any local override

The real environment beats all three. Later layers beat earlier ones, so .env
wins over a profile, which wins over common.

WHY THIS IS NOT ONE FILE ANY MORE. It was, and that file was doing two
incompatible jobs. It carried live SQL Server and BrightHR credentials into the
repository, and — because it was committed — a git merge on a second machine
would overwrite that machine's own settings with the first machine's. A single
file cannot be both "the same everywhere" and "different per machine", and
trying to make it both is how a deployment breaks the thing it was copied from.
"""

import os
import platform
from pathlib import Path
from dotenv import load_dotenv

_HERE = Path(__file__).parent

# WHICH PROFILE. Explicit via SDI_PROFILE, otherwise this machine's hostname,
# otherwise none. Hostname means a new machine needs no argument to start
# correctly; naming it out loud below means that is convenience rather than
# magic, because you can see which file was chosen and why.
_profile = os.getenv("SDI_PROFILE", "").strip() or platform.node().strip().lower()

# LOADED IN DESCENDING PRECEDENCE. python-dotenv's override=False means "do not
# replace what is already set", so whatever is loaded FIRST wins — and the real
# environment, being already in os.environ, wins over all of it.
# THE REPO ROOT .env IS READ TOO, BECAUSE THERE ARE TWO FILES CALLED .env AND
# NOTHING TOLD YOU WHICH ONE YOU WERE EDITING.
#
# This loaded only the one beside itself. The engine has its own at the repo
# root, and "put it in .env" means that one to anybody who has been working in
# C:\ClaudeVision all day. Settings added there were read by nothing, the
# service reported the feature as "not configured", and the file plainly
# contained the line saying otherwise. That is not a mistake anybody makes once.
#
# So both are read, most specific first: a value set beside the service wins,
# then the shared one at the root, then the committed defaults. Local secrets
# still beat committed files either way, which is the rule that matters.
_layers = [
    (_HERE / ".env",                       "secrets and local overrides, service-specific"),
    (_HERE.parent / ".env",                "secrets and local overrides, shared with the engine"),
    (_HERE / "env" / f"{_profile}.env",    f"profile '{_profile}'"),
    (_HERE / "env" / "common.env",         "settings common to every machine"),
]

_loaded = []
for _path, _what in _layers:
    if _path.is_file():
        load_dotenv(_path, override=False)
        # THE FOLDER, NOT JUST THE NAME. Two of these are called '.env', and printing
        # the bare name was how a file that had been read and a file that had not
        # looked identical in the startup line.
        _loaded.append(f"{_path.parent.name}\\{_path.name} ({_what})")

# SAY WHERE THE VALUES CAME FROM. An evening was lost to a port set in one
# PowerShell window and not another; a configuration that will not tell you
# which file it read is one you will eventually argue with.
print("[config] " + (" <- ".join(_loaded) if _loaded
                     else "NO configuration files found; using defaults and the environment"))


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
    # .csv IS NOT OPTIONAL HERE. The parity route hands the page a bundle_csv_url pointing at
    # /api/file, and the card renders it as a button — so leaving .csv off the list means the
    # service offers a link it then refuses with "Extension .csv is not served". An endpoint
    # that will not serve what another endpoint just told the page to fetch is a broken button,
    # not a security setting.
    for e in _opt("SDI_ALLOWED_EXTENSIONS", ".xlsx,.html,.json,.jpg,.csv").split(",")
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

# ── Staging: the drawings an estimate was actually run on ───────────────────
# Every drawing the estimator selected is copied here, into one folder per client and job, and
# the engine is pointed at that folder. Selection then means selection — before this, the picks
# only chose a parent folder and the engine read everything in it — and drawings from two
# sources (the estimating share and a Document Manager extract) can be combined, which two
# separate parent folders made impossible.
#
# REPLACED ON A RE-RUN, NOT ADDED TO, so a second run cannot inherit a drawing that has since
# been taken off the list.
#
# THE DEFAULT IS A UNC PATH, NOT K:. A mapped drive letter belongs to a login session, so a
# service running under a service account has no K: at all — the first attempt failed with
# "The system cannot find the path specified: 'K:\\'" for exactly that reason. K: maps to
# \\sdi-dc01\shareddata$\Shared, so this is the same folder by a name that works everywhere.
STAGING_ROOT = _opt(
    "SDI_STAGING_ROOT",
    r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\AI Estimating\AISheets"
    r"\SDIIntelligenceAISheet")


# A DRIVE LETTER IS SOMEBODY ELSE'S SESSION, AND PATHS ARRIVE FROM OTHER MACHINES.
#
# The Document Manager reports where it wrote a pack as a path seen from ITS host, and that
# path is a K: one. K: is a per-logon-session mapping: it means nothing to a service, it can
# differ between two machines, and it is not the form SDI_FILE_ROOTS is written in — so a
# perfectly reachable folder fails both the containment check and the open. Staging already
# failed exactly this way once ("cannot find the path specified: 'K:\\'").
#
# So a letter is translated to its UNC form the moment a foreign path enters. Written as
# "K=\\\\server\\share" pairs separated by ';'. The default is the one mapping this business
# actually uses; set SDI_DRIVE_MAP to change or extend it, or to "" to switch it off.
def _parse_drive_map(raw: str) -> dict:
    out = {}
    for pair in str(raw or "").split(";"):
        if "=" not in pair:
            continue
        letter, unc = pair.split("=", 1)
        letter, unc = letter.strip().rstrip(":").upper(), unc.strip().rstrip("\\/")
        if len(letter) == 1 and letter.isalpha() and unc:
            out[letter] = unc
    return out


DRIVE_MAP = _parse_drive_map(
    _opt("SDI_DRIVE_MAP", r"K=\\sdi-dc01\shareddata$\Shared"))


# ── Document Manager (DM) extract tool ──────────────────────────────────────
# Yogesh's DM API tool extracts a job's CAD files out of Document Manager and writes them to an
# output share. This portal does not run that extraction; it IMPORTS what the extraction left
# behind, so the two can be deployed, upgraded and broken independently of one another.
#
# Set DM_OUTPUT_ROOT to the folder the DM tool writes its packs into. It must also appear in
# SDI_FILE_ROOTS, because everything this service reads goes through the same containment
# check — there is no second, looser path rule for this one feature.
#
# DM_API_BASE is for the NEXT step: asking the tool to run an extract rather than picking up
# one that has already run. It is deliberately unset by default, and the endpoint says so
# plainly rather than guessing at somebody else's API.
DM_OUTPUT_ROOT = _opt("SDI_DM_OUTPUT_ROOT")
DM_API_BASE = _opt("SDI_DM_API_BASE")
DM_API_KEY = _opt("SDI_DM_API_KEY")


# ── brand assets ────────────────────────────────────────────────────────────
# The portal header shows the SAME we.are.sdi logo the client quote puts on its header. Pointing
# both at one folder is deliberate: a logo that lives in two places drifts, and the customer-facing
# document is the one that must never be wrong. src/client_quote_html.py reads this same folder.
BRAND_ASSETS_DIR = _opt("SDI_BRAND_ASSETS_DIR", r"C:\ClaudeVision\assets\customer_logos")
BRAND_SDI_LOGO_KEY = _opt("SDI_BRAND_LOGO_KEY", "wearesdi")


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
