import os
from pathlib import Path

# ── .env IS LOADED HERE, BECAUSE THIS IS WHERE THE SETTINGS ARE READ ────────────────
# config reads ten environment variables at import time and used to load nothing. main.py
# loaded .env before importing config, so a RUN was configured correctly -- and every other
# entry point was not. why_this_price.py, the supplier profiler, check_tiers and every test
# that imports config got whatever the shell happened to hold, or a silent default.
#
# That is how a setting gets applied by accident: not by anyone choosing it, but by which
# door the code was entered through. Loading it here means one file decides, and every
# caller of config -- tools, tests, the runner's engine, main -- sees the same values.
#
# Resolved from __file__, so the working directory cannot change the answer. Idempotent, so
# main.py's early call and this one are the same event. Shell variables still WIN, because
# a deliberate `SDI_OFFLINE=1 python ...` must keep working -- what changes is that the
# default now comes from a file rather than from nothing, and a shell value that DISAGREES
# with the file is said out loud instead of quietly deciding the estimate.
_DOT_ENV_LOADED = False
# WHICH .env was actually read. Two are tried -- the repo root, then src/ -- and the FIRST one
# found wins and the other is never opened. An error message that names the wrong one sends
# somebody to edit a file nothing reads, which is exactly what happened.
_DOT_ENV_PATH = None


def load_dot_env(announce: bool = True, root=None) -> bool:
    """Load BASE_DIR/.env into the environment. Returns True if a file was read.

    THE ONE LOADER. A second copy in main.py is what this replaced, and two loaders with
    slightly different search orders is the shape of defect this codebase keeps paying for.

    `root` exists so a test can point this at a temporary directory. It is NOT a second
    search order: production callers pass nothing and get BASE_DIR, resolved from __file__.
    """
    global _DOT_ENV_LOADED
    if _DOT_ENV_LOADED and root is None:
        return True
    try:
        from dotenv import load_dotenv, dotenv_values
    except ImportError:
        return False                    # not installed: every switch falls back to the shell
    _places = ((Path(root) / ".env",) if root is not None
               else (BASE_DIR / ".env", Path(__file__).resolve().parent / ".env"))
    for candidate in _places:
        if not candidate.exists():
            continue
        if announce:
            try:
                for key, in_file in (dotenv_values(candidate) or {}).items():
                    if in_file is None or key not in os.environ:
                        continue
                    if os.environ[key] == in_file:
                        continue
                    _mask = key.upper().endswith(("KEY", "SECRET", "PASSWORD", "TOKEN", "PWD"))
                    print(f"   [env] {key} comes from THIS SHELL, not .env "
                          f"({'<hidden>' if _mask else os.environ[key]!r} overrides "
                          f"{'<hidden>' if _mask else in_file!r}). Deliberate overrides are "
                          f"fine; an unnoticed one makes this run unreproducible.", flush=True)
            except Exception:                                # noqa: BLE001
                pass                     # reporting must never stop the settings loading
        load_dotenv(candidate)
        if root is None:
            _DOT_ENV_LOADED = True
        global _DOT_ENV_PATH
        _DOT_ENV_PATH = candidate
        print(f"[env] Loaded {candidate}", flush=True)
        return True
    return False


# Canonical hand-edited source for this project lives in this repo's `src/`.
# After changes here, copy/sync the same files to your runtime tree (e.g. C:\ClaudeVision\src) before running scans.

BASE_DIR = Path(__file__).resolve().parents[1]
INPUT_DIR = BASE_DIR / "input"
DRAWINGS_DIR = INPUT_DIR / "drawings"
SPREADSHEETS_DIR = INPUT_DIR / "spreadsheets"
HISTORY_DIR = INPUT_DIR / "history"

load_dot_env()      # before any os.environ read below

OUTPUT_DIR = BASE_DIR / "output"
JSON_DIR = OUTPUT_DIR / "json"
LOG_DIR = OUTPUT_DIR / "logs"
TEXT_DIR = OUTPUT_DIR / "text"
CSV_DIR = OUTPUT_DIR / "csv"
SQL_DIR = OUTPUT_DIR / "sql"
PAGE_IMAGES_DIR = OUTPUT_DIR / "page_images"
HISTORY_JSON_DIR = OUTPUT_DIR / "history_json"
HISTORY_CSV_DIR = OUTPUT_DIR / "history_csv"
ARCHIVE_DIR = OUTPUT_DIR / "archive"
ARCHIVE_JSON_DIR = ARCHIVE_DIR / "json"
ARCHIVE_TEXT_DIR = ARCHIVE_DIR / "text"
ARCHIVE_LOG_DIR = ARCHIVE_DIR / "logs"
ARCHIVE_CSV_DIR = ARCHIVE_DIR / "csv"
ARCHIVE_SQL_DIR = ARCHIVE_DIR / "sql"

SUPPORTED_EXTENSIONS = {".pdf", ".dxf"}

# The ODA File Converter turns DWG into DXF offline and free, so a DWG flat pattern feeds the
# reader we already have instead of being ignored. Leave unset to auto-detect: PATH first,
# then the usual install roots.
#
# THIS IS THE BACKEND THAT DOES NOT NEED SOLIDWORKS, WHICH IS THE POINT OF IT.
#
# cad_inputs tries ODA first and SOLIDWORKS second, deliberately: a licensed interactive seat
# is not something an estimate may depend on. It can be closed, the licence can lapse, the
# runner can be in a different logon session -- all three look identical from here, and all
# three end with DWG files present and unread. ODA is free, offline and batch, and once it is
# installed the DWG path works with SOLIDWORKS shut for good.
#
# FROM THE ENVIRONMENT, because the machine that needs this is not the machine this file is
# edited on. It was a hard-coded None, so pointing the engine at a converter meant editing a
# git-tracked source file on the laptop -- which is then a local modification that fights
# every pull. SDI_DWG_CONVERTER in .env sets it per machine and nothing tracked changes.
#   e.g. SDI_DWG_CONVERTER=C:\Program Files\ODA\ODAFileConverter 25.4.0\ODAFileConverter.exe
DWG_CONVERTER_PATH = os.getenv("SDI_DWG_CONVERTER", "").strip() or None

# PDF GA + flat DXF per part: DXF augments geometry on the PDF scan JSON (see drawing_job_merge.py).
DRAWING_JOB_DISCOVERY = {
    "enabled": True,
    "auto_discover_on_pdf_scan": True,
    "exclude_flat_dxf_from_batch": True,
    "dxf_subdir": "DXF",
    # A SUBFOLDER NAMED FOR THE JOB IS STILL THE DXF SUBFOLDER. Discovery matched the literal
    # name "DXF" only, so M&S job 2085 — whose flats live in "2085 - DXFs_DEV1" — would have
    # had every part sized from drawing text if the root copy had not happened to exist. Any
    # immediate subfolder whose name contains one of these tokens is searched. Immediate only:
    # recursing a job folder pulls in whatever else has been left in it, and 12120 already had
    # another job's DXF sitting beside its own.
    "dxf_subdir_tokens": ["DXF"],
    # All DXFs in job folder — GA sheets filtered by is_ignored_ga_dxf()
    "flat_dxf_glob": "*.[Dd][Xx][Ff]",
    "ignore_dxf_name_tokens": ["-GA_", "_GA_", "-GA.", "_GA."],
    "part_number_from_dxf_patterns": [
        # 2–3 digit suffix, optional letter  e.g. 9376-01-001  12242-01-01M  11367-09-08A
        r"(?P<pn>\d{4,5}-\d{2}-\d{2,3}[A-Z]?)",
        # LETTER-FIRST detail  e.g. 10975-02-A01 / -G01 / -X01 — a whole pack can be
        # lettered, and without this the run staged two DXFs and matched zero.
        r"(?P<pn>\d{4,5}-\d{2}-[A-Z]{1,2}\d{1,3})",
        # GA / sub-assembly  e.g. 9376-01-GA (ignored downstream for geometry merge)
        r"(?P<pn>\d{4,5}-\d{2}-[A-Z]{2,4})",
    ],
}
SPREADSHEET_EXTENSIONS = {".xlsx", ".xls", ".csv", ".tsv"}

TITLE_BLOCK_LABELS = [
    "DWG NO",
    "DRAWING NO",
    "REVISION",
    "DESCRIPTION",
    "PROJECT TITLE",
    "DATE",
    "CLIENT",
    "SHEET",
    "SHEET SIZE",
    "DRAWN BY",
    "MODIFIED BY",
    "MATERIAL",
    "SURFACE FINISH",
    "COLOUR",
    "COLOR",
    "WEIGHT",
    "SCALE",
    "CLIENT REF",
    "QTY",
    "QUANTITY",
    "THK",
    "THICKNESS",
    "GAUGE",
]

# The head of a part number must carry a DIGIT. `[A-Z]{1,6}\d{0,4}` used to allow zero, which
# made any run of one to six letters a valid code head — and on 10575-02 that turned the title
# block's "DRAWN BY: P.Andrew - 14/11/2023" into a part called ANDREW-14, costed at £108.73.
#
# Every real SDI code has a digit up front: 10575-02, BE2030-10, 12173-02-GA. The alpha-led
# catalogue codes — FIXING591, VINYL03, SUBPLAS72 — attach their digits directly and never take
# the hyphenated shape this pattern reads, so nothing legitimate is lost by requiring one.
PART_NUMBER_PATTERN = r"\b(?:\d{4,5}[A-Z]?|[A-Z]{1,6}\d{1,4}|FIXING\d*)(?:-[A-Z0-9_]{1,12}|\s-\s[A-Z0-9_]{1,12}){1,4}\b"
PART_NUMBER_PATTERNS = [
    PART_NUMBER_PATTERN,
    r"\b[A-Z]{1,4}\s*-\s*\d{2,}\b",
]
DATE_PATTERN = r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b"
REVISION_PATTERN = r"\bREV(?:ISION)?\s*[:.\-]?\s*([A-Z0-9]+)\b"
SHEET_PATTERN = r"\b(\d+\s*/\s*\d+)\b"
SHEET_SIZE_PATTERN = r"\b(A[0-4])\b"
SCALE_PATTERN = r"\bSCALE\s*[:\-]?\s*([A-Z0-9:./\- ]+)"
DWG_NO_PATTERN = r"(?:DWG\s*NO|DRAWING\s*NO)\s*[:.\-]?\s*([0-9A-Z]+(?:-[0-9A-Z_]{1,12}|\s-\s[0-9A-Z_]{1,12}){0,4})"
DRAWING_NUMBER_PATTERN = DWG_NO_PATTERN
DESCRIPTION_PATTERN = r"DESCRIPTION\s*[:\-]?\s*(.+)"
DRAWN_BY_PATTERN = r"DRAWN\s*BY\s*[:\-]?\s*([A-Z0-9.\-_ ]+)"
MODIFIED_BY_PATTERN = r"MODIFIED\s*BY\s*[:\-]?\s*([A-Z0-9.\-_ ]+)"
CLIENT_PATTERN = r"CLIENT\s*[:\-]?\s*([A-Z0-9.\-_ ]+)"
PROJECT_TITLE_PATTERN = r"PROJECT\s*TITLE\s*[:\-]?\s*(.+)"

# THE FACED-BOARD FAMILY MUST BE IN HERE, AND ORDER IS PART OF THE RULE.
#
# Alternation is first-match, so the multi-word spellings come before the single words they
# contain: "MELAMINE FACED CHIPBOARD" before "CHIPBOARD", and every faced spelling before
# plain MDF so "MELAMINE FACED MDF" resolves as faced board rather than as MDF.
#
# WHY IT MATTERS THAT THIS LIST IS THE ONE THAT WAS SHORT. drawing_job_merge's DXF tokens,
# wb_populate._is_board, _TIMBER_TOKENS and json_normaliser's lexicon all know MFC. The
# title-block reader — the AUTHORITATIVE material source, the labelled "MATERIAL:" callout —
# did not, so on 12422-24 it fell through to its short-unknown-callout branch and took the
# drawing's own boilerplate with it: the end cap's material reached the sheet, the group
# keys and the labour block as "MFC DO NOT".
MATERIAL_PATTERN = (
    r"\b(MILD\s+STEEL|STAINLESS\s+STEEL|ALUMINIUM|ALUMINUM|ALU|ZINTEC"
    r"|GALVANISED\s+STEEL|GALVANIZED\s+STEEL"
    # MFC is melamine-faced CHIPBOARD and MFMDF is melamine-faced MDF — the facing is not
    # the substrate, and they are different sheets at different prices. Both spellings are
    # matched here; json_normaliser keeps them as separate codes.
    r"|MELAMINE\s+FACED\s+CHIPBOARD|MELAMINE\s+FACED\s+MDF|MELAMINE\s+FACED"
    # The faced spellings must SWALLOW the board word that follows them, not sit beside it:
    # "PRE-LAM MDF" matching PRE-LAM and MDF separately reports two materials for one panel.
    r"|PRE[\s-]?LAM(?:INATED?)?(?:\s+(?:MDF|CHIPBOARD|BOARD))?|MFMDF|MFC|CHIPBOARD"
    r"|TIMBER|WOOD|MDF|PLYWOOD|SOFTWOOD"
    r"|HIGH\s+IMPACT\s+ACRYLIC|ACRYLIC|PERSPEX|POLYCARBONATE)\b"
)
FINISH_PATTERN = r"(?:SURFACE\s+FINISH|FINISH)\s*[:\-]?\s*([A-Z0-9\s\-\[\]/,]+)"
COLOUR_PATTERN = r"(?:COLOUR|COLOR)\s*[:\-]?\s*([A-Z0-9\s\-,\[\]/]+)"
WEIGHT_PATTERN = r"WEIGHT\s*[:\-]?\s*([0-9.]+\s*(?:KG|kg|g|G))"
QUANTITY_PATTERN = r"\b(?:QTY|QUANTITY)\s*[:\-]?\s*(\d+)\b"
# THE VALUE COMES FIRST ON AN SDI DRAWING, AND THIS ONLY LOOKED AFTER THE LABEL.
#
# Every sheet in SDI's own template writes the gauge as "1.5 THK", "2 THK", "1.2 THK". This
# pattern read THK-then-number — "THK: 1.5" — which is a convention SDI does not use. Two
# failures came out of that, and the second is much worse than the first:
#
#   NOTHING READ. 12552's 02-05M, 02-09M, 01-03M and 02-03M all state their gauge and all
#   returned no thickness at all, so the gauge fell through to SolidWorks, a DXF, or inference.
#
#   THE WRONG NUMBER READ. On 12552's 01-04M the text runs "1.5 THK" then "39.5" — the box
#   section dimension on the next line. THK-then-number matched across the line break and
#   captured 39.5, so a 1.5 mm corner upright presents a title-block gauge of 39.5 mm, stamped
#   drawing_deterministic at rank 70 where almost nothing can displace it. That is twenty-six
#   times the material on four parts, from a pattern that was merely looking the wrong way
#   round.
#
# VALUE-FIRST IS TRIED FIRST, deliberately. On "1.5 THK 39.5" it consumes through the label,
# so the trailing dimension is no longer available to the label-first branch — the correct
# reading wins AND the wrong one becomes unreachable in the same step. The label-first form is
# kept because other people's drawings do write it that way.
THICKNESS_PATTERN = (
    r"\b(?:"
    r"(\d+(?:\.\d+)?)\s*(?:MM|mm)?\s*(?:THK|THICK|THICKNESS|GAUGE)"
    r"|(?:THK|THICKNESS|GAUGE)\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*(?:MM|mm)?"
    r")\b"
)

DIMENSION_PATTERN = r"(?<![A-Z0-9])(\d+(?:\.\d+)?)\s*(?:MM|mm)\b"
ANGLE_PATTERN = r"(\d+(?:\.\d+)?)\s*(?:°|º|Â°)"
HOLE_PATTERN = r"(\d+(?:\.\d+)?)\s+(?:HANGING\s+)?HOLE"
DIAMETER_HOLE_PATTERN = r"(?:Ø|DIA\.?|DIAMETER)\s*(\d+(?:\.\d+)?)"
PITCH_PATTERN = r"(\d+(?:\.\d+)?)\s+PITCH"
RADIUS_PATTERN = r"\bR\s*(\d+(?:\.\d+)?)\b"
FOLD_VALUE_PATTERN = r"(\d+(?:\.\d+)?)\s+(?:EXT\s+FOLD|INT\s+FOLD|FOLD)"
# FOLD_PATTERN counts bend lines from drawing text. Two annotation styles appear:
#   1. Word callouts:  "EXT FOLD", "INT FOLD", "FOLD", "BEND"  (older SDI drawings)
#   2. Flat-pattern callouts: "DOWN 90.00° R 1", "UP 47.33° R 1"  (SolidWorks — the
#      most common format; one per bend). Without style 2, PDF-only parts (e.g. tube
#      legs, footbases with no DXF) read zero bends even though the drawing annotates
#      every bend. The (?:UP|DOWN)\s+angle° form is tight enough to avoid matching
#      incidental "UP"/"DOWN" text or section-view angles.
FOLD_PATTERN = r"\b(?:EXT\s+FOLD|INT\s+FOLD|FOLD|BEND)\b|(?:\bUP\b|\bDOWN\b)\s+\d+(?:\.\d+)?\s*°"
FLAT_PATTERN_PATTERN = r"\bFLAT\s+PATTERN\b"
SLOT_PATTERN = r"\bSLOT\b"
LASER_PATTERN = r"\bLASER\b"
WELD_PATTERN = r"\bWELD(?:ED|ING)?\b"
TAP_PATTERN = r"\bTAP(?:PED|PING)?\b"
CSK_PATTERN = r"\b(?:CSK|COUNTERSINK(?:ING)?)\b"
DRILL_PATTERN = r"\bDRILL(?:ED|ING)?\b"
PUNCH_PATTERN = r"\bPUNCH(?:ED|ING)?\b"
DEBURR_PATTERN = r"\bDEBURR\b"
BREAK_EDGE_PATTERN = r"\bBREAK\s+SHARP\s+EDGES?\b"
# SolidWorks names a mirrored part "Mirror<partnumber>" with nothing between the two, so a
# trailing \b never matches: "Mirror11350-01-02M" is one unbroken run of word characters.
# The leading boundary is kept, so this still will not fire inside an unrelated word.
MIRROR_PATTERN = r"\bMIRROR(?:ED)?\b|\bMIRROR(?=[\d-])"
LENGTH_BY_WIDTH_PATTERN = r"\b(\d+(?:\.\d+)?)\s*[xX]\s*(\d+(?:\.\d+)?)\s*(?:mm)?\b"
SLOT_SIZE_PATTERN = r"\b(\d+(?:\.\d+)?)\s*[xX]\s*(\d+(?:\.\d+)?)\s*(?:MM|mm)\s+SLOT\b"
EDGE_DISTANCE_PATTERN = r"\b(\d+(?:\.\d+)?)\s*(?:MM|mm)\s+EDGE\b"

QTY_TABLE_ROW_PATTERN = r"(\d+)\s+([A-Z0-9_]+(?:-[A-Z0-9_]+|\s-\s[A-Z0-9_]+){1,4})-?\s+(.+?)\s+(\d+)"

# --- Punch cycle-time calibration (TruPunch 1000 setup-plan data) ---------------
# Peg-family panels are PUNCHED (cluster + tooth + perimeter), not lasered, and the
# DXF/PDF under-reads their perforation so the hole-count model collapses to ~0.
# Anchor on measured 1m machine times; scale to 500mm x0.65 (per Tim: peg 1.38->0.90).
# Surfaced on the estimate basis page; override here if a 500mm setup plan is supplied.
PUNCH_CYCLE_TIME_MIN = {
    "PEG_PANEL":  {"1000mm": 1.38, "500mm": 0.90},
    "HALF_PEG":   {"1000mm": 0.86, "500mm": 0.72},  # 500mm bumped to measured TruPunch time (2621 setup plan)
    "BASE_PLATE": {"1000mm": 0.62, "500mm": 0.40},
}

# --- Packaging (ad-hoc; compute when we can, else UNPRICED flagged line) ---------
# Rule (per SDI): if a unit fits a UK 1200x1000 pallet/box and the sizes are known,
# cost it (boxes + pallets + delivery) and show the working; if we cannot work it
# out, emit an UNPRICED line item for estimating/MD/FD to set. Box/unit dimensions
# and bays-per-box are unknown until the warehouse supplies them -> unpriced for now.
PACKAGING_CONFIG = {
    "pallet": {"length_mm": 1200, "width_mm": 1000, "price_gbp": 2.50},   # UK standard
    "pallet_eu_ref": {"length_mm": 1200, "width_mm": 800},                # Euro (reference)
    "box": {"code": "BOX82", "price_gbp": 10.48,
            "length_mm": None, "width_mm": None, "height_mm": None},       # footprint TBC
    "delivery_price_gbp": 280.0,
    "bays_per_box": None,        # warehouse to confirm; None => packaging flagged not costed
    "bays_per_pallet": None,     # warehouse to confirm
    "bays_per_delivery": None,   # bays per delivery load (delivery_price split across these)
}

# --- Packaging and delivery: the house figure, when there is one ------------------
#
# THE LEVER commercial_lines DOCUMENTS AND CONFIG DID NOT HAVE.
#
# `_held_rate` reads this and its own note tells an estimator to "put a per-order figure in
# config.COMMERCIAL_LINE_GBP_PER_ORDER['PACKAGING'] and every job carries it". The setting
# was never defined, so `getattr(config, ..., {})` returned an empty dict on every job, the
# catalogue rung of the ladder could not fire, and BOTH lines fell through to a market/LLM
# indication every single time. That is why packaging and delivery arrive on every estimate
# stamped "NOT A QUOTE, replace it" — not because nobody has a figure, but because there was
# nowhere to put one.
#
# On 12552 those two lines were £85.00 + £85.00 against a £930.39 unit at 1 off: 18% of the
# quote resting on a number that moves between runs.
#
# EMPTY ON PURPOSE. A figure invented here would be worse than the indication it replaced,
# because it would carry no "check me" flag. Put SDI's real per-order costs in and both lines
# become reproducible catalogue prices on every job, with the source named as this setting.
#
#   £ PER ORDER, not per unit — commercial_lines divides by the order quantity and writes the
#   divisor onto the line, so an estimator changing the quantity can see what moved.
#   HELD EMPTY BY DECISION: the estimators are producing their own calculation for packaging
#   and delivery, so both lines stay at the honest £0 "estimator to price" until those real
#   figures land. A real number from the people who ship the job beats an invented one, and an
#   invented figure here would carry no "check me" flag of its own.
#
#   When the calculation arrives, put the per-ORDER figures here and nothing else changes —
#   commercial_lines divides by the order quantity and flags the line for verify. e.g.
#   {"PACKAGING": 12.00, "DELIVERY": 15.00} gives £2.00 / £2.50 per unit at qty 6.
COMMERCIAL_LINE_GBP_PER_ORDER = {
}

# --- The estimator's two requests about the sheet itself --------------------------
#
# "For ease of process / check can all quantity breaks be on one sheet / show formulas
# selected."                          — Howard Thurley, 0355255 review, 9 Sep 2026
# "Could you show formulas on estimate sheet please"     — Tim Wilkes, 12349-02, 12 Sep 2026
#
# Two estimators, two jobs, the same ask — so it is a way of working rather than a
# preference. The sheet has held live formulas all along (every computed column is a
# formula; only the inputs are values), and what neither of them could do was SEE them
# without knowing Ctrl+` exists.
#
# SHIPPED OFF, AND THIS IS WHY. Show Formulas is a VIEW: with it selected the sheet opens
# showing =IF(H96=0,... in every cell instead of the money, which is exactly right for
# checking the working and useless for reading the price. The person who wants to check
# presses Ctrl+` and gets there in a second; the person who just wants the unit cost should
# not have to. Turn it on for an estimator who asks, per the line below — it changes nothing
# but which face the sheet opens on, and they can toggle it back.
SHOW_FORMULAS_ON_ESTIMATE = False
SHOW_FORMULAS_SHEETS = ("Estimate",)

# --- One sheet for every quantity: the Material Price Break table -----------------
#
# SDI has always had this table and it has always been empty — 0 non-empty price cells on
# 12349-02's book, every row, every column. Howard fills his in by hand; that is why his
# 0355255 estimate is one workbook covering 1/10/50/250/1000/1250/1500 and ours is a
# workbook per quantity.
#
# OFF UNTIL THE TEMPLATE IS WIDENED, and these numbers are why. Measured on a real book:
#
#   break-tab rows available   15 (rows 5-19) against a BOM of 40 rows (Estimate 11-50)
#   rows 14-19                 =_xlfn.SINGLE(Estimate!#REF!)
#   Estimate J45:J50           LOOKUP into break rows 14-19 — ALREADY USED by BOM rows
#                              20-25, so six lines would read six other lines' prices
#
# Turning this on against the template as it stands would fill a table that mis-routes six
# rows. `row_offset` is the one number that moves when the template is repaired: break row =
# BOM row + row_offset, uniformly -6 for rows 11-44 today.
# HOW MANY YOU BUY FOR AN ORDER OF N — the only thing that makes a break table move.
#
# "1 Box Suits 10 or 50 Components, 3 Boxes to Suit 250 Components 9 Boxes Suit 1000
# Components."                          — Howard Thurley, 0355255 packing note, 9 Sep 2026
#
# It is a STEP, not a rate: you cannot buy 1.4 boxes. His own sheet shows the consequence —
# at GBP 1.89 a box that is 0.189 / 0.0378 / 0.02268 / 0.01701 a unit across 10 / 50 / 250 /
# 1000, the one line on his entire estimate that moves with the order.
#
# EMPTY UNTIL THE PRICES ARE CONFIRMED, for the same reason COMMERCIAL_LINE_GBP_PER_ORDER is:
# his sheet implies GBP 1.89 for the box and we have not been told it, and a figure inferred
# from somebody else's arithmetic carries no "check me" flag. The RULE is recorded here
# because that is his and it is not in doubt; the money is not.
#
#   {"PACKAGING": {"10": 1, "50": 1, "250": 3, "1000": 9}}
#
# SUPERSEDED FOR PACKAGING by PACKING_METHOD below, which carries the same counts INSIDE
# the method that uses them. Kept for any other per-order code an estimator states counts
# for; the break table still reads it.
PER_ORDER_UNIT_COUNTS = {
}

# ── HOW AN ORDER IS PACKED — the method, never the money ───────────────────────────
#
#   "put it into config and start to build it in. if we're working it out and it's
#    scaleable and using more sensible calculations and numbers they will be accepted.
#    Better than 0 or crazy numbers."                        — James Gray, 15 Sep 2026
#
# The same split as the tape roll. HOW a job is packed is a stated fact — Howard gave the
# method in writing: every unit individually bagged (PACK56 — his email typed PACK13,
# his priced sheet buys PACK56, see the consumables note), then bulk-packed in stock
# boxes (BOX481) at 1 box for 10 or 50, 3 for 250, 9 for 1000. WHAT the bag and the box
# COST is money, and money comes live from SDI's own priced sources (UDEF first) at run
# time — nothing here holds a price, so nothing here can go stale invisibly.
#
# The box counts are a STEP FUNCTION and are used exactly as stated: the count at the
# smallest stated threshold >= the order quantity. BEYOND THE LAST STATED POINT, NOTHING —
# nothing Howard said tells us how 2,000 pack, and a straight line past the last real
# point is invention wearing derivation's clothes (the board-price rule, applied here).
#
# OPEN QUESTION, ASKED OF HOWARD 15 Sep: are those carton counts fixed for this job, or a
# capacity rule (a box holds roughly N units) we should generalise? Until he answers, the
# method applies to jobs whose parts match the basis it was stated for — small flat-packed
# acrylic display goods — and the line's note says which method priced it.
PACKING_METHOD = {
    "enabled": True,
    "stated_by": "Howard Thurley (SDI estimating)",
    "stated_on": "9 Sep 2026",
    "source_job": "0355255",
    # WHICH BAG: THE SHEET BEATS THE EMAIL. Howard's email named PACK13 (an 18 x 24 bag);
    # his own priced sheet for 0355255 (7 Sep 2026) bags the unit in PACK56 — "Poly Bag
    # 12 x 18 x 100G", The Packaging Company, £17.91 a thousand — which also matches the
    # 12 x 18 size his method describes. The sheet is the estimate he actually issued, so
    # PACK56 is what this method buys; the discrepancy is his to settle and is asked in
    # the covering email.
    "consumables": [
        {"code": "PACK56", "what": "individual bag 12 x 18, 100 gauge", "per_unit": 1},
        {"code": "BOX481", "what": "bulk stock box",
         "per_order_steps": {10: 1, 50: 1, 250: 3, 1000: 9}},
    ],
    # WHICH JOBS THE METHOD MAY PRICE. Howard stated it for small flat-packed acrylic
    # display goods; without a gate it would price a steel stand or a joinery unit into
    # poly bags. Material families are the hard fact. The weight ceiling is OURS — an
    # assumption marking "small", declared here and said on the line when it excludes a
    # job — because Howard stated no limit and a 30 kg all-acrylic counter is plainly not
    # bagged-and-boxed. Blank dimensions are deliberately NOT gated: a line-bent part
    # packs far smaller than its flat blank (the 0355255 L-stand's own blank is 760 mm
    # and the finished holder is a table-top item), so gating blanks would exclude the
    # exact job the method was stated for.
    "applies_to": {
        "material_families": ("ACRYLIC", "PERSPEX", "PMMA", "HIPS", "PETG",
                              "POLYCARBONATE", "ABS", "PVC", "FOAMEX"),
        "max_unit_weight_kg": 5.0,     # SDI Intelligence assumption, not Howard's figure
        # PACKED CONTENTS, NOT VETOES. The 18:21 run declined the whole method because
        # G01 — the PRINTED GRAPHIC the holder exists to hold — read as "a non-plastic
        # fabricated part". A graphic, a label, an insert goes INSIDE the bag; it cannot
        # change how the job packs, so it never vetoes the method. Suitability is judged
        # from the principal structural product; these tokens mark the contents.
        "packed_content_tokens": ("GRAPHIC", "LABEL", "STICKER", "INSERT", "LEAFLET",
                                  "PRINT", "PAPER", "CARD"),
    },
}

# ONE WORKBOOK, OR ONE PER QUANTITY.
#
#   "Let's look at collapsing all the s/sheets into one when we have multiple unit
#    quantities."                                            — James Gray, SDI, 15 Sep 2026
#   "For ease of process / check can all quantity breaks be on one sheet"
#                                                        — Howard Thurley, 0355255, 9 Sep
#
# The quantity sweep predates both. It recalculates the estimate at each quantity and SAVES
# EACH ONE AS ITS OWN FILE, which was the only way to see 10 off before the Material Price
# Break tab existed. Four quantities meant four workbooks open and the unit cost read out of
# each by eye — and each of those files looks exactly like a finished estimate, so the first
# thing that happens to one is somebody forwards it. That is why every variant opens on a
# READ THIS FIRST page disclaiming itself.
#
# The break tab answers the same question inside one workbook, on the estimators' own
# template, with the sheet's own LOOKUP against $D$6 — no disclaimer needed, because nothing
# has been recalculated behind anyone's back.
#
# None (the default) means: file the variants only where the one sheet CANNOT carry the
# breaks — a machine whose template has not been widened yet still gets its other quantities
# rather than silently getting none. True or False forces it either way.
#
# THE SWEEP ITSELF STILL RUNS EITHER WAY. It is what computes the figures the Quantity Breaks
# tab and the report both read; this setting governs only whether extra FILES are written.
QUANTITY_VARIANT_WORKBOOKS = None       # None | True | False

MATERIAL_PRICE_BREAK = {
    "enabled": True,
    "sheet": "Material Price Break",
    "estimate_sheet": "Estimate",
    "row_offset": -6,                 # break row = BOM row + this
    "first_bom_row": 11,
    # THE WHOLE BOM BLOCK, NOW THAT THE TABLE REACHES IT.
    #
    # James, 15 Sep: "we now have rows 5 to 49". At an offset of -6 that covers Estimate
    # rows 11 to 55, and the BOM block ends at 50 — so every slot has a break row, with
    # five spare. It was bounded at 25 for the hours the table was fifteen rows long;
    # anything past the table's last row would have been written into cells no LOOKUP reads.
    # The out-of-table report stays regardless, because the next template is not this one.
    "last_bom_row": 50,
    "qty_vector_first_cell": "F180",  # Estimate's own Qty Breaks column, 11 cells down
    "first_price_col": 4,             # D
    "last_price_col": 14,             # N
}

# --- Goods sold off a roll, priced by the length actually used ---------------------
#
# 0355255's tape line is the whole gap between our sheet and the estimator's: £19.50 a unit
# against £7.63, and £18.84 against £4.55 at a thousand off. TAPE113C is supplied on a 10
# METRE ROLL at £4.50. The drawing asks for three strips across the base, 200 mm each — six
# hundredths of a roll, twenty-eight pence. The line was costed 3 x £4.37, a PER-EACH default
# material rate, and came to £13.63. A per-each charge does not amortise either, which is why
# our column barely moved across the quantity breaks while the estimator's fell by a third.
#
# The record already knew enough to get it right: the description carries "LENGTH: 200.00" and
# the quantity is 3. What was missing is the only thing a roll needs — how long the roll is and
# what it costs. So that is what this table holds, keyed on the SDI code.
#
#   length_used = per-piece length x quantity;  price = length_used / roll_length x roll price
#
# A code NOT in this table is not guessed at: the line is withheld and says so, the same as a
# consumable with no quantity. Nothing here was inferred from a drawing.
# HOW IT IS SUPPLIED — NOT WHAT IT COSTS.
#
# James, 15 Sep: "we can't hard code prices. we can log hourly throughput rates but we need
# to start understanding if these change and why." He is right, and roll_price_gbp used to
# sit in this table. A price in source control cannot go stale visibly: nobody is told when
# it moves and the first person to notice is a customer.
#
# The roll LENGTH stays, because it is a packaging fact rather than money — TAPE113C comes on
# a 10 metre roll, which changes when the supplier changes the product and not before. The
# price is asked of SDI's own priced sources at run time (stated_prices.resolve), and where
# they cannot answer it falls to ESTIMATOR_STATED_PRICES below, dated and attributed.
ROLL_GOODS_CATALOGUE = {
    "TAPE113C": {
        "roll_length_mm": 10000.0,
        "label": "EPDM closed-cell tape 25 x 1 mm — 10 m roll",
        "source": "Howard Thurley (SDI estimating/buying), 0355255 review, 9 Sep 2026",
    },
}

# --- What an estimator told us a thing costs, with the date on it -----------------
#
# SECOND TO THE SYSTEM, ALWAYS. price_sources.get_best_price is asked first — the part system
# cost off Access Supply Chain, UDEF, historical quotes, the supplier catalogue. This is what
# answers when none of them can, and a line priced from here SAYS so on the sheet, with the
# name and the date, so an estimator can see he is reading his own six-week-old figure.
#
# WHY THE DATE IS THE POINT. PLAS534 already has three answers — £45.19 the supplier's current
# price per Howard, £47.21 what our sheet charged, £49.55 the material cost on Access Supply
# Chain which Howard reckons was migrated from the old system. Nothing in the engine can say
# which is right, and picking one silently is how the question stops being asked. Where this
# register and the system disagree by more than a penny in a pound, BOTH are reported.
ESTIMATOR_STATED_PRICES = {
    "TAPE113C": {
        "gbp": 4.50, "unit": "roll",
        "by": "Howard Thurley (SDI estimating/buying)",
        "on": "2026-09-09", "job": "0355255",
        "note": "10 m roll of EPDM closed-cell tape 25 x 1 mm",
    },
    # "Not all materials calculated no ABS edging Allowed" — Tony Ford's first finding on
    # 11908-21. The pack states no edging spec anywhere (his own line quotes the Egger
    # reference from the spec book, not from the drawing), so the engine could not mint the
    # material without inventing it. His sheet states both halves: the spec and the rate.
    #
    # THE RATE IS HERE. THE METREAGE IS NOT, AND MUST NOT BE. He bands 5 m a unit against a
    # much larger drawn perimeter, because only the VISIBLE edges are banded — which edges
    # those are is a judgement about the product, not a number on the drawing, and a rule
    # that banded every drawn edge would overcharge every joinery job by the difference.
    # So the engine measures what is drawn, holds this rate, and asks.
    "EDGE23X1ABS": {
        "gbp": 0.35, "unit": "metre",
        "by": "Tony Ford (SDI estimating)",
        "on": "2026-09-03", "job": "11908-21",
        "note": "23 x 1 mm ABS edging to match Egger W1001 ST9 laminate, Ostermann",
    },
}

# The edging code above, named once so the ask and the register cannot drift apart.
FACED_BOARD_EDGING_CODE = "EDGE23X1ABS"

# --- Which machine cuts a blank, when a part is charged two ways -------------------
#
# A part carrying BOTH a laser cut and a routed cut is the same profile paid for twice.
# 12349-02-69-06A, a 5 mm acrylic front cover, was in the 5 mm laser group AND had its own
# CNC line at £6.81.
#
# THE CUT FILE CANNOT ANSWER IT, AND THE MODEL THAT CLAIMED TO WAS GUESSING. The DXF
# interpreter returns a `recommended_process`, and the runner's own log shows the SAME
# unchanged file coming back
#
#     06A: laser · laser · laser · router · laser · router · laser · router · router · laser
#
# over ten runs. SDI's cut files cannot tell it either: the layer set is a fixed SolidWorks
# export template — SLD-0, BENDLINES, ETCHING, RIB, C_SNK, HIDDEN, REBATE, LANCEFORM — and
# not one layer names a machine. A rule keyed on that would strip the laser on some runs and
# the router on others, on one pack: a visible double charge turned into an invisible coin
# flip, which is worse than the double.
#
# So the decision is the SHOP'S, written down once and applied to every job. Keyed on
# normalised material, with an optional maximum gauge, first match wins:
#
#     {"material": "HIGH_IMPACT_ACRYLIC", "max_thickness_mm": 8, "method": "laser"}
#
# method is "laser", "punch" or "router". EMPTY ON PURPOSE: with no rule the two ops both
# stay and the line is flagged for a person, which is the honest answer to "which machine"
# when nobody has told us. Nothing here is guessed from a drawing.
#
# FILLED FROM THE SHOP, NOT FROM A DRAWING. These are SDI's own defaults as stated by James
# Gray (SDI estimating), 14 Sep 2026: acrylic is lasered unless the drawing or the issued CAM
# calls for CNC; board goes to the router; mild steel is lasered. A material NOT in this list
# still flags rather than guesses — nothing here was inferred from a pack.
CUT_METHOD_BY_MATERIAL: list = [
    {"material": "ACRYLIC", "method": "laser",
     "source": "SDI shop default, James Gray, 14 Sep 2026 — laser unless the drawing or the "
               "issued CAM calls for CNC"},
    {"material": "HIGH_IMPACT_ACRYLIC", "method": "laser",
     "source": "SDI shop default, James Gray, 14 Sep 2026 — laser unless the drawing or the "
               "issued CAM calls for CNC"},
    {"material": "MDF", "method": "router",
     "source": "SDI shop default, James Gray, 14 Sep 2026 — board is routed, not lasered"},
    {"material": "MILD_STEEL", "method": "laser",
     "source": "SDI shop default, James Gray, 14 Sep 2026"},
]

# --- ...and whether to ask the market when there is no house figure ---------------
#
# ONE PACK, THREE PRICES. 12349-02 was run three times at 7 off on an unchanged drawing pack
# and order-level packaging came back £424.97, then £175.00, then £74.97 — a 5.7x spread with
# nothing changed but the clock. Delivery moved £140.00 -> £68.11 -> £94.99 across the same
# three. Tim's manual estimate reaches £7.94 from a catalogue pack code and one pallet.
#
# The indication was defended on the grounds that "a zero sums as free and nobody argues with
# it; an indicative figure gets checked". That is true of a figure a person can sanity-check
# against something. It is not true of a figure that moves 5.7x between runs of the same job:
# an estimator cannot tell whether £75 or £425 is the one to argue with, and neither can the
# parity harness, which is why the same job cannot be compared with itself.
#
# So the COUNT is kept and the PRICE is withheld. plan_shipment still weighs the order, finds
# the largest panel, counts the cartons and the pallets, and writes the sentence a packer or a
# haulier would be asked; the line arrives at £0.00 carrying that whole description and its own
# entry on OUTSTANDING ESTIMATOR INPUTS. A zero that names the question it could not answer is
# not the same thing as a silent zero.
#
# Set this True to restore the market indication. Better: put SDI's real rates in
# COMMERCIAL_LINE_GBP_PER_ORDER above, and neither this flag nor the model is consulted.
COMMERCIAL_LINE_ASK_MARKET = False

# Standard bought-in COMMODITIES that appear on a BOM as a COMPONENT (not packaging) under a
# generic name — "PALLET", "STD PART" — with no SDI part code, so the purchasing DB has nothing
# to match and the line would otherwise fall to a per-run LLM guess or a £0. A stable, REPRODUCIBLE
# provisional holds the line still at a sensible figure until SDI adds the item to the purchasing
# catalogue, at which point the DB rate wins (this is only consulted on the fallback path, after
# the catalogue and history miss). This is the COMPONENT pallet the display is built on — distinct
# from PACKAGING_CONFIG["pallet"], which is the per-order SHIPPING pallet share. Confirm each price.
#   token -> {price_gbp, label}. A token is matched as an UPPER-CASE substring of the
#   description; join tokens with "+" ("PERFO+CLIP") to require that EVERY one is present,
#   which keeps a generic word from over-matching a part it does not name.
#
#   AND EVERY ENTRY SAYS WHERE ITS FIGURE CAME FROM. `source` is printed with the price, so an
#   estimator reading a provisional can see whose number it is without opening this file. A
#   provisional whose origin is unrecorded is indistinguishable from one somebody invented,
#   which is the difference between a figure worth confirming and a figure worth deleting.
STANDARD_COMMODITY_PRICE_GBP = {
    "PALLET": {
        "price_gbp": 12.00,
        "label": "standard 1200x1000 UK pallet (new) — PROVISIONAL, confirm new/recon and "
                 "whether an ISPM-15 heat-treated stamp is needed for export",
        "source": "market rate for a new 1200x1000 UK pallet — no supplier quote on file",
    },
    # 11762-17 item "STD PART / PERFO PLASTIC LOCKING CLIP" — the plastic clip that locks a
    # bottle-shelf into a perforated panel. No SDI part code, so the purchasing DB cannot
    # match it and the line read as £0.00. Both tokens are required so this prices the
    # perforated-panel clip only, not any part that merely says "CLIP". Per-each provisional.
    "PERFO+CLIP": {
        "price_gbp": 1.20,
        "label": "perforated-panel plastic locking clip — PROVISIONAL per-each, confirm "
                 "against a supplier quote or add the item to the purchasing catalogue",
        "source": "provisional set when 11762-17 surfaced the line — no supplier quote on file",
    },
    # 7332-01 item "P/P / BLACK FELT PAD, SELF-ADHESIVE, 25mm DIA" — the stick-on foot pad.
    # No SDI part code (the drawing prints the class word "P/P"), so the line read as £0.00 and
    # estimating bounces a zero. A 25mm self-adhesive felt pad is a stock commodity: a retail
    # pack is ~£3.50/16 -> ~£0.22 each, trade lower, so 20p is a fair INDICATIVE per-each hold.
    # Keyed FELT+PAD (both tokens), NOT "P/P" alone — "P/P" is a class word that would over-match
    # anything the drawing marks as a purchased part. No bench-fitting uplift: the assembly
    # labour already covers sticking them on. Tim confirms or overwrites.
    "FELT+PAD": {
        "price_gbp": 0.20,
        "label": "Self-adhesive felt pad 25 mm (INDICATIVE) — confirm against a supplier quote",
        "source": "derived from a retail pack (~£3.50 per 16 ≈ £0.22 each), held at £0.20 as a "
                  "trade indication — no supplier quote on file",
    },
    # 12349-02's two fasteners, and the reason they needed an entry at all.
    #
    # THE ONE TABLE THAT SHOULD HOLD A SCREW PRICE IS EMPTY. supplier_price_list.py's own audit
    # measures it: UDEF 93,837 rows, historical RAG 68,489, bought-in catalogue 0. So every
    # screw, castor, clip and lock falls past the rung meant for it. The market rung then finds
    # nothing either, because a generic fastener has no reference to search on — the bumpon on
    # the same bill of materials priced at 35p off its maker's code PD.2120, and "3.5x19mm WOOD
    # SCREW" carries no equivalent. Two lines an estimator prices in his sleep came back £0.00
    # on run after run, and a zero on a quote is a free part.
    #
    # KEYED ON THE FAMILY, PRICED AT THE SIZE WE WERE GIVEN. The rate is a small-gauge rate and
    # says so in its own label: a 3.5 x 19 wood screw is 3p and a 6 x 80 coach screw is not, so
    # a materially larger fastener carries the same line into review rather than being quietly
    # undercharged. Narrower keys would be safer still and would price nothing on the next job,
    # which is the failure this table exists to end.
    #
    # These go the moment a fastener price file is loaded — a real catalogue rate wins over a
    # provisional at every rung above this one.
    "WOOD+SCREW": {
        "price_gbp": 0.03,
        "label": "wood screw, small gauge — trade (rate given for 3.5 x 19 mm); confirm for "
                 "materially larger gauges",
        "source": "SDI trade rate, James Gray (SDI estimating), 14 Sep 2026",
    },
    "BUTTON+HEAD": {
        "price_gbp": 0.08,
        "label": "socket button head screw, small metric — trade (rate given for M4 x 10 mm, "
                 "black); confirm for materially larger sizes",
        "source": "SDI trade rate, James Gray (SDI estimating), 14 Sep 2026",
    },
}

# SUBCONTRACT PLATING — a PLATED weldment goes out to a plater, not through SDI's own powder
# booth, so its finish is a subcontract line priced on the plated MASS, not booth hours. This is
# distinct from POWDER_COSTING_POLICY (booth labour + consumable) and must never reuse it.
#
# gbp_per_kg is an INDICATIVE trade-zinc + passivate rate (Jackson-type card ~£2.50/kg); a
# decorative / named "Harrods" plate spec (nickel, etc.) is NOT this rate — the review flag says
# so and the line stays blocking until a plater quote confirms. vat_minimum_gbp is the plater's
# per-batch floor: a small order is charged the minimum however light it is, so the ORDER total
# is max(mass x rate x qty, vat_minimum); the per-unit line is that divided back by the order.
# Set gbp_per_kg to None to withhold the rate entirely (the line then reads "estimator to price").
#
# rate_covers IS THE HALF THE POLICY NEVER SAID OUT LOUD, and 7332-01 shipped £15.83
# because of it. The paragraph above states plainly that the £/kg card is zinc + passivate
# and that a decorative spec is not this rate — but the CODE had no way to tell the two
# apart, so every plate finish took the card, including a bare "PLATED" that names no
# process at all. A finish naming one of these words is a plating this rate actually
# prices. A finish naming none of them is a plating we cannot identify, and £2.50/kg is
# then not an indication of anything: brass, nickel and decorative specs run an order of
# magnitude above it, and the £250 Howard Thurley quoted for Brass Harrods 01 against the
# card's £15.83 is that order of magnitude on one line of one job.
#
# Widen this list ONLY with a process the £2.50 card genuinely covers. Anything else
# belongs in NAMED_PLATE_SPECS below as a quoted price, or stays blocking.
# WHEN ONE LABOUR ROW IS HIDING TWO VERY DIFFERENT PARTS.
#
# "Line 98 – Laser Rate Mild Steel 2.5mm – 2 Separate Components x 2 per each component one
# Labour Rate shown – Is AI linking both parts with average rate input?"
#                                       — Howard Thurley, SDI estimating, 9 Sep 2026
#
# Parts of one material and gauge share a laser set-up, so they share a row — that grouping
# is right and the set-up is genuinely booked once. What it costs is visibility: 7332-01's
# row is a 441 x 10 strap beside a 15.88 mm square cap, and his own figures for the two are
# 235/hr and 900/hr. A single blended number cannot be checked against either.
#
# The row rate is total pieces / total hours, which is the correct combination and NOT a
# mean — a mean of 235 and 900 is 567.5, the true combination of two at each is 372.7, and
# only one of those is a rate. That arithmetic is right and stays. The row now shows its
# members' own rates, and says so loudly when they are this far apart.
#
# The ratio at which "far apart" starts. 3x is a strap against a cap; 1.5x is two similar
# blanks and not worth a sentence.
LABOUR_GROUP_RATE_SPREAD_FLAG = 3.0

# ── DECISIONS AN ESTIMATOR MADE ONCE, APPLIED WHEREVER THEY ARE TRUE ────────────────────
#
#     "All changes we do should be worked to be inherited or it's a pointless one off hack
#      that we will be found out on with the next drawing with the same characteristics"
#                                                     — James Gray, SDI, 14 Sep 2026
#
# Brass Harrods 01 at £250 was put in 7332-01's own answers file, which governs 7332-01 and
# nothing else. That is correct for a decision about one stand and WRONG for this one: the
# next Harrods stand states the same bare "PLATED", blocks for the same reason, and somebody
# types the same £250 again. Same characteristics, same manual work, every time — which is
# the hack he is describing.
#
# THIS REVERSES A TEST I WROTE ON PURPOSE. test_the_customer_name_alone_buys_nothing pinned
# that a client called Harrods buys no plate spec, and the reasoning was sound: the ENGINE
# must never infer a price from a customer's name. It still must not. What changed is that
# this is not an inference. An estimator stated it, for stated conditions, and recording that
# is the opposite of guessing — it is the difference between "Harrods, so probably brass" and
# "Howard Thurley told us on 9 Sep that Harrods stands calling up a bare PLATED are Brass
# Harrods 01 at £250".
#
# WHAT MAKES INHERITANCE SAFE IS THAT IT ANNOUNCES ITSELF. Every entry carries who decided
# it, when, and on which job; every line it reaches says it was inherited and asks to be
# confirmed. An inherited decision that arrives silently is indistinguishable from a rate the
# engine invented, which is the whole thing this codebase refuses to do.
#
# `when` is ALL of its conditions — every key must match or the entry does not apply. An
# entry with no conditions is rejected rather than applied to everything.
# ══ REVOKED 16 SEP 2026 — HOWARD SAID PLATING DOES NOT INHERIT ══════════════════════════
#
# The entry that lived here bound £250 to any HARRODS job whose drawing said only "PLATED".
# We told Howard we had done it — "recorded as a standing decision, so any future Harrods job
# whose drawing only says Harrods01 prices at £250 rather than guessing zinc" — and he came
# back and corrected us:
#
#     "Plating would be as drawing specific, £250.00 is from supplier per unit and is
#      independent of any other job. Plating jobs priced independently."
#
# So the premise was wrong, not the implementation. Plating is quoted job by job; a price
# from one job is evidence about THAT job and about nothing else, and a customer's name buys
# nothing at all. test_the_customer_name_alone_buys_nothing was reversed to let this entry
# exist; it is restored, and it was right the first time.
#
# THE MECHANISM STAYS, EMPTY. A genuine standing decision — one an estimator states as a
# rule rather than as a price for a job — still belongs here, and the machinery around it
# (every condition must match, every entry names who decided it, every line it reaches says
# it was inherited) is what would make that safe. What it must not hold is a quoted price
# wearing a rule's clothes.
INHERITED_ESTIMATOR_DECISIONS: list = []

# ══ WHAT THE SHOP TOLD US, IN ONE PLACE ═════════════════════════════════════════════════
#
# James: "can we put these into a central area that is easy to identify and change if
# needed."
#
# Every figure below came out of a named person's mouth on a dated job. They were already
# in this file and they were in three places — brushing at one constant, the plater pack and
# freight at another, the weld and dress times at a third, each with its own `source` string
# in its own words. An estimator asked "what did Howard actually say" had to know which three
# constants to open, and a figure that needs correcting had to be found before it could be
# changed.
#
# THIS IS THE ONE HOME. The constants below READ from it rather than repeating it, so there
# is one number per fact and changing it here changes it everywhere. Adding a second copy
# anywhere else is the defect this whole file has been chasing: two readers of one fact,
# agreeing until the day they do not.
#
# ── AND THE WELD TIMES WERE DIVIDED BY A JOINT COUNT NOTHING MEASURED ────────────────────
#
# Howard stated 30 minutes to weld 7332-01-101 and 20 to dress it. That was turned into a
# per-joint rate by hand, against an ASSUMED three joints — the old comment says so: "a
# frame of four members — three joints — so it reads as 10 minutes a joint". The engine
# counts the joints itself, and for that part it counts FIVE. So it multiplied a rate
# derived from three by a count of five and printed 50 minutes where Howard said 30, and 33.5
# where he said 20 — about £28 a unit on every weldment job, from an arithmetic disagreement
# that nothing in the system could see, because the assumed count was in prose and the
# measured one was in code.
#
# So the count is stated HERE, beside the minutes it divides, and the per-joint rates are
# DERIVED. If the joint count for that frame is ever re-measured, one number changes and both
# rates follow. Nobody divides by hand again.
SHOP_STATED = {
    # Howard Thurley, SDI estimating — 7332-01 (Harrods A3 stand), 9 September 2026
    "weld_min_per_weldment": 30.0,
    "dress_min_per_weldment": 20.0,
    "weld_joints_measured_on": 5,          # joints the engine counts on 7332-01-101
    "weld_calibrated_on_part": "7332-01-101",
    # PER UNIT. Howard was asked directly — "is the 40 minutes per stand, or once for the
    # whole consignment? At 6 off that is the difference between about £3.50 and £21 a
    # unit" — and answered: "40 Minutes was given by production for one unit, rate was
    # priced based on experience and for similar size units, time would vary per unit /
    # size." So it is per unit, it is an experienced judgement rather than a measurement,
    # and it is scaled to SIMILAR-SIZED work. All three facts are in the provenance.
    "brush_before_plate_min": 40.0,        # per UNIT, before it goes to the platers
    "plater_pack_min": 4.0,                # packing to send
    "plater_final_pack_min": 8.0,          # packing again on the way back
    "plater_freight_gbp_per_order": 120.0,  # pallet network, round trip
    # Acrylic Dept via Howard Thurley — 0355255 (A4 table-top graphic holder), same date.
    # 60 parts/hour on the two-bend A01: one minute a part, half a minute a bend. Lived in
    # ACRYLIC_OP_DRIVERS with its own attribution comment, which was a second home for
    # exactly the kind of figure this register was built to hold in ONE — "can we put these
    # into a central area that is easy to identify and change if needed". ACRYLIC_OP_DRIVERS
    # now reads it from here, the way BRUSH_BEFORE_PLATE reads brush_before_plate_min.
    # WHAT THE SHOP STATED versus WHAT WE DERIVED FROM IT — kept apart on review advice
    # (16 Sep): Howard's workbook states 60 PARTS/HOUR on the two-bend A01; "0.5 minutes
    # per bend" is this engine's reading of that figure, generalised per bend so a
    # three-bend part books its real time. The stated fact and the derived driver are
    # both here, each labelled as what it is; if Howard confirms the per-bend figure
    # directly, its provenance upgrades from derived to stated.
    "linebend_parts_per_hour": 60.0,
    "linebend_min_per_bend": 0.5,
    # "Line 96 – Laser Rate Acrylic Comparison AI 252 p/hour Manual Estimate 95 p/hour."
    # The 252 was measured off THIRTEEN corpus lines — the thinnest sample in the
    # throughput table — against the estimator who runs the department. Third home found
    # for a stated shop figure (wb_populate._THROUGHPUT_DEFAULTS), now read from here.
    "laser_acrylic_parts_per_hour": 95.0,
    # PACP "Apply Tape, Bag, Bulk Pack" at 30 parts/hour, off Howard's own 0355255 sheet
    # (7 Sep 2026). The corpus-derived 99/hr was measured over 15 mixed lines and cannot
    # say what taping, bagging and boxing THIS kind of unit takes; the department figure
    # on his priced estimate can. This one line was most of the labour gap at volume
    # between his book and the engine's (~59p a unit at 10-off).
    "acrylic_assemble_pack_parts_per_hour": 30.0,
    # ── THE JOINERY DEPARTMENTS, OFF TONY FORD'S OWN 11908-21 SHEET (3 Sep 2026) ────────
    #
    # "No edge banding, no machining saw/spindle, no bench work time, CNC setup not
    # amortised" — Tony, reviewing the engine's book against his. Every joinery throughput
    # the engine held was a GUESS borrowed from a neighbouring department, because no
    # joinery job had ever been measured. His sheet is the first measurement, and the
    # guesses were not close:
    #
    #     dept   his hours   min/unit   parts/hour      the guess we held
    #     CNCJ      4.4167       5.30      11.3208      30   (2.6x too fast)
    #     EDGE      4.6667       5.60      10.7143      30   (2.8x too fast)
    #     MC J      4.6667       5.60      10.7143      no row at all
    #     BENC     25.5000      30.60       1.9608      79   (40.3x too fast)
    #     PACJ      2.7500       3.30      18.1818      99   (5.4x too fast)
    #
    # Bench work is 25.5 of his 42 hours, run 40x too fast — which is the whole of "no bench
    # work time" in one number, and most of the gap between his £57.09 and ours.
    #
    # DERIVED, AND SAID SO. His sheet states HOURS PER ORDER at a quantity of 50; the engine
    # needs parts/hour, so every figure here is his hours divided by his quantity. That is
    # arithmetic on a stated fact, not a stated fact — the same distinction linebend already
    # carries. Two things follow and are recorded in the provenance below: a per-order
    # element (a setup) would inflate the per-part figure, and one job is one job. Confirm
    # both with Tony and these upgrade from derived to stated.
    "joinery_cnc_parts_per_hour":          11.3208,
    "joinery_edge_banding_parts_per_hour": 10.7143,
    "joinery_machining_parts_per_hour":    10.7143,
    "joinery_bench_parts_per_hour":         1.9608,
    "joinery_pack_parts_per_hour":         18.1818,
    "joinery_rates_measured_on_job":       "11908-21",
    "joinery_rates_measured_at_quantity":  50,
    # SETUP CANNOT BE SEPARATED FROM ONE JOB, AND PRETENDING OTHERWISE IS THE DEFECT TONY
    # REPORTED. His hours per order contain a per-unit run time AND whatever setup each
    # department did once. One job is one equation in two unknowns: unsolvable, only
    # askable. None means UNKNOWN — not zero — and the figures above therefore carry the
    # setup inside them, which overstates the per-unit rate by however much it was. On his
    # own numbers, half an hour of setup a department moves the pack rate by 22%.
    "joinery_setup_min_per_department":    None,
    # Named here so the scope is a fact in the register rather than a sentence in a comment:
    # these figures apply to the family they were measured on and nothing else, until a
    # second job or the department itself widens them.
    "joinery_rates_scope":                 "faced/laminated board (MFMDF, MFC)",
    "joinery_rates_status":                "scoped pilot — provisional",
}

# EVERY FIGURE CARRIES ITS OWN PROVENANCE. The register used to close with one shared
# stated_by / stated_on / stated_for_job header, and the header lied the day the second
# job's figures arrived: linebend and the acrylic laser rate are 0355255's, and anything
# printing the shared source attributed them to 7332-01. James caught it in review.
#
# Values above stay plain numbers — every consumer and test reads them as numbers — and
# the who/when/which-job/what-unit lives here, one entry per figure, held complete by
# test_nobody_divides_by_hand_twice: a figure without provenance fails the suite.
_HOWARD_7332 = {"stated_by": "Howard Thurley (SDI estimating)", "stated_on": "9 Sep 2026",
                "source_job": "7332-01", "evidence": "estimator review of the 7332-01 book"}
_ACRYLIC_0355255 = {"stated_by": "Acrylic Dept via Howard Thurley (SDI estimating)",
                    "stated_on": "9 Sep 2026", "source_job": "0355255",
                    "evidence": "estimator review of the 0355255 book"}
_TONY_11908 = {"stated_by": "Tony Ford (SDI estimating)", "stated_on": "3 Sep 2026",
               "source_job": "11908-21",
               "evidence": "his own 11908-21 estimate sheet, Labour tab"}


def _joinery_derivation(code: str, hours: float, what: str) -> str:
    """The same sentence for every joinery figure, so none of them can overstate itself.

    Each one is his HOURS PER ORDER divided by his quantity. Saying that in the figure's own
    provenance is the difference between "the shop told us 1.96 parts an hour" — which
    nobody did — and "the shop told us 25.5 hours for fifty, and we divided"."""
    _qty = SHOP_STATED["joinery_rates_measured_at_quantity"]
    return (f"DERIVED by this engine: {what} — his Labour tab states {hours:g} hours for "
            f"{code} across a stated quantity of {_qty} ({hours * 60 / _qty:.2f} min a unit), "
            f"divided to parts/hour. Not itself a shop statement of a RATE: a per-order "
            f"element inside those hours (a setup) would inflate the per-part figure, and "
            f"this is one job. Confirm both with Tony to upgrade it from derived to stated.")
SHOP_STATED_PROVENANCE = {
    "weld_min_per_weldment":        dict(_HOWARD_7332, unit="minutes/weldment"),
    "dress_min_per_weldment":       dict(_HOWARD_7332, unit="minutes/weldment"),
    "weld_joints_measured_on":      dict(_HOWARD_7332, unit="joints",
                                         evidence="joints the engine counts on 7332-01-101"),
    "weld_calibrated_on_part":      dict(_HOWARD_7332, unit="part number"),
    "brush_before_plate_min":       dict(
        _HOWARD_7332, stated_on="16 Sep 2026", unit="minutes/unit",
        evidence="asked directly whether the 40 minutes was per stand or per "
                 "consignment, Howard answered per unit: \"40 Minutes was given by "
                 "production for one unit, rate was priced based on experience and for "
                 "similar size units, time would vary per unit / size\". An experienced "
                 "judgement scaled to similar-sized work, not a measurement — a much "
                 "larger or smaller stand should be asked about again"),
    "plater_pack_min":              dict(_HOWARD_7332, unit="minutes/consignment"),
    "plater_final_pack_min":        dict(_HOWARD_7332, unit="minutes/consignment"),
    "plater_freight_gbp_per_order": dict(_HOWARD_7332, unit="GBP/order",
                                         evidence="pallet network, round trip"),
    "linebend_parts_per_hour":      dict(_ACRYLIC_0355255, unit="parts/hour",
                                         evidence="stated on his sheet for the two-bend "
                                                  "A01 — the figure as he gave it"),
    "linebend_min_per_bend":        dict(_ACRYLIC_0355255, unit="minutes/bend",
                                         evidence="DERIVED by this engine from the stated "
                                                  "60 parts/hour on the two-bend A01 "
                                                  "(60/hr ÷ 2 bends); not itself a shop "
                                                  "statement — confirm per-bend generality "
                                                  "with Howard to upgrade it"),
    "laser_acrylic_parts_per_hour": dict(_ACRYLIC_0355255, unit="parts/hour",
                                         evidence="his manual estimate's own laser rate, "
                                                  "against 252 from 13 corpus lines"),
    "acrylic_assemble_pack_parts_per_hour": dict(
        _ACRYLIC_0355255, stated_by="Howard Thurley (SDI estimating)",
        stated_on="7 Sep 2026", unit="parts/hour",
        evidence="his own 0355255 sheet: PACP 30/hour, 'Apply Tape, Bag, Bulk Pack'"),
    "joinery_cnc_parts_per_hour":          dict(
        _TONY_11908, unit="parts/hour",
        evidence=_joinery_derivation("CNCJ", 4.4167, "the router pass on the board parts")),
    "joinery_edge_banding_parts_per_hour": dict(
        _TONY_11908, unit="parts/hour",
        evidence=_joinery_derivation("EDGE", 4.6667, "banding the 23 x 1mm ABS edge")),
    "joinery_machining_parts_per_hour":    dict(
        _TONY_11908, unit="parts/hour",
        evidence=_joinery_derivation("MC J", 4.6667, "saw and spindle — an operation the "
                                                     "engine does not yet emit at all")),
    "joinery_bench_parts_per_hour":        dict(
        _TONY_11908, unit="parts/hour",
        evidence=_joinery_derivation("BENC", 25.5, "bench assembly — 25.5 of his 42 hours, "
                                                   "and the figure to confirm first")),
    "joinery_pack_parts_per_hour":         dict(
        _TONY_11908, unit="parts/hour",
        evidence=_joinery_derivation("PACJ", 2.75, "boxing and palletising the tray")),
    "joinery_rates_measured_on_job":       dict(
        _TONY_11908, unit="job number",
        evidence="the one job these joinery figures are measured on"),
    "joinery_rates_measured_at_quantity":  dict(
        _TONY_11908, unit="units",
        evidence="the quantity his hours were stated at — the divisor behind every "
                 "joinery parts/hour figure above"),
    "joinery_setup_min_per_department":    dict(
        _TONY_11908, unit="minutes/department",
        evidence="UNKNOWN, and None says so rather than zero. His sheet states hours per "
                 "order, which contain a per-unit run time and whatever setup each "
                 "department did once; one job is one equation in two unknowns and cannot "
                 "be solved, only asked. Until it is asked, the run figures above carry "
                 "the setup inside them and overstate the per-unit rate by however much "
                 "of it was setup (on his numbers, 30 min a department moves the pack "
                 "rate by 22%). ASK TONY: of the hours on your Labour tab, how much is "
                 "set-up once and how much is per tray?"),
    "joinery_rates_scope":                 dict(
        _TONY_11908, unit="material family",
        evidence="the family the measurement was taken on — his colour-core laminated "
                 "tray. Outside it the engine keeps its UNMEASURED guesses, because an "
                 "honest 'we do not know' beats another department's number wearing "
                 "joinery's name. Widens on a second job or a department confirmation"),
    "joinery_rates_status":                dict(
        _TONY_11908, unit="status",
        evidence="a scoped pilot: one job, setup not separated, applied only inside its "
                 "own family. NOT a joinery constant and not to be quoted as one"),
}


def shop_stated_source(key: str) -> str:
    """Who stated this figure, when, and for which job — for THIS figure, never a shared
    header. The sentence every consumer prints beside the number."""
    p = SHOP_STATED_PROVENANCE.get(key) or {}
    if not p:
        return "an unrecorded source — add SHOP_STATED_PROVENANCE for this figure"
    return f"{p['stated_by']}, stated for {p['source_job']} on {p['stated_on']}"


# BRUSHED BEFORE IT GOES TO THE PLATERS — work the drawing never mentions.
#
# "Line 85 – Drawing doesn't annotate – material is brushed prior to sending to platers, op.
# for Manual Labour (Metal) 40 Minutes – Grey area as drawing only nominates a finish as
# Harrods01."   — Howard Thurley, SDI estimating, 9 Sep 2026
#
# It was carried as a flag for a while, on the reasoning that forty minutes nobody drew is an
# invention. That was half right: forty minutes nobody drew AND nobody mentioned would be an
# invention, but an estimator has mentioned it, with a duration, and leaving it off is simply
# under-charging — the direction nobody notices, because a quote that is too low is accepted.
#
# PER UNIT, ONCE PER WELDMENT. Two different questions, and the answers differ.
#
# WHICH PART: the weldment, never once per plated member — on 7332-01 that would be four
# hours of linishing on one stand.
#
# HOW OFTEN: per UNIT. This read "per consignment", which at 6 off understated the
# operation six-fold. Howard was asked outright and answered per unit (see the register
# above), so the minutes scale with the order like any other run time.
#
# Set enabled False to go back to naming it without costing it.
BRUSH_BEFORE_PLATE = {
    "enabled": True,
    # ONE NAME. An alias for the old per-consignment spelling was tempting and wrong:
    # two keys holding one figure is two places to edit and two chances to disagree, which
    # is the fault this whole register exists to stop.
    "minutes_per_unit": SHOP_STATED["brush_before_plate_min"],
    "setup_min": 0.0,
    "operation": "manual_labour_metal",
    "source": f"SDI shop practice via {shop_stated_source('brush_before_plate_min')}",
    # BOUNDED BY WHAT HOWARD ACTUALLY SPOKE FOR. His words: "rate was priced based on
    # experience and for similar size units, time would vary per unit / size." So this is
    # an INDICATIVE STATED METHOD calibrated on one stand, not a constant of the shop, and
    # the line says so wherever it lands.
    #
    # NO NUMERIC BAND, because inventing one would be worse than having none: nobody has
    # given us the size 7332-01-101 actually is, so any threshold here would be this
    # engine's guess wearing Howard's name — the exact fault the register exists to stop.
    # Instead the caveat travels with the line and the weldment's own measured size is
    # printed beside it, so the person who CAN judge it is given what they need to.
    "calibrated_on": SHOP_STATED["weld_calibrated_on_part"],
    "basis": "experience, for similar-sized units — varies with unit and size",
    "confirm_outside_similar_size": True,
}

PLATE_SUBCONTRACT_POLICY = {
    "gbp_per_kg": 2.50,
    "vat_minimum_gbp": 95.0,
    "label": "plating — INDICATIVE zinc/passivate, verify against plater quote",
    "rate_covers": ("ZINC", "PASSIVAT", "GALVAN", "ELECTRO-ZINC", "ELECTROZINC"),
}

# A NAMED PLATE SPEC IS A QUOTED PRICE, NOT A RATE PER KILO.
#
# The policy above says so itself — "a decorative / named 'Harrods' plate spec is NOT this
# rate … the line stays blocking until a plater quote confirms". 7332-01 is exactly that
# case and the quote has now arrived: the requirement is Brass Harrods 01 and the plater
# charges £250.00 per stand, against an indicative zinc line of a few pounds on mass. That
# is the largest single error on the sheet by an order of magnitude.
#
# Keyed on the FINISH the drawing names, so it can only ever price a job that calls that
# finish up: a spec not in this table falls through to the mass rate exactly as before, and
# a job with no plating never reaches either. Per UNIT, because that is how the plater
# quotes a decorative finish — the mass rate and its vat minimum do not apply.
#
# Matched on the finish text with spaces and punctuation removed, because a drawing writes
# "Harrods01", "HARRODS 01" and "Harrods-01" for one finish.
# A NAMED SPEC IS A METHOD WE LEARNED. IT IS NOT A PRICE WE HOLD.
#
# James Gray, 16 Sep 2026: "the engine must learn methods, conditions, and evidence, not copy
# a manual estimate's numbers into the next estimate… prices should live in a versioned,
# attributable price register or live system connector — not as numeric literals in Python
# configuration. Code should contain the pricing MECHANISM; data should contain approved
# rates, dates, scope, source, and expiry."
#
# £250 was a numeric literal in source. It was attributed and dated, which made it honest and
# did not make it right: a plater's quote for one stand in September is not a rate, and this
# file is not a price register. Scoping it to its own job (the previous fix) stopped it
# reaching other jobs and still left the engine charging from a hard-coded number.
#
# SO WHAT IS KEPT IS THE KNOWLEDGE, WHICH IS THE PART THAT COST A DAY TO GET:
#   * "Harrods 01" names a decorative plating requirement, not zinc — so the £/kg
#     zinc-and-passivate card must NOT price it (that was the original defect, an order of
#     magnitude out);
#   * a requirement of this kind is quoted per job by the plater.
#
# The price is asked of SDI's own sources at run time, exactly as the tape's roll price is.
# Where they cannot answer, the line asks for the plater's current figure and SHOWS the last
# quote we hold as dated context — evidence a person can act on, never money the engine
# charges. An estimator pricing THIS job puts the figure in this job's answers file, which is
# where a job-specific quote belongs.
NAMED_PLATE_SPECS = {
    "HARRODS01": {
        "label": "Brass — Harrods 01",
        # The learned facts: what it is, and how it is priced.
        "decorative": True,          # not zinc — the per-kilo card must not price it
        "requires_quote": True,      # the plater quotes it per job
        # Context for the person who has to get that quote. Dated, attributed, and never
        # charged: `gbp_per_unit` is deliberately NOT a key of this entry.
        "last_known_quote": {
            "gbp_per_unit": 250.00,
            "job": "7332-01",
            "on": "9 Sep 2026",
            "source": "plater quote via SDI estimating (Howard Thurley)",
        },
        "confirm": ("plating is quoted job by job (Howard Thurley, 16 Sep 2026) — get the "
                    "plater's price for THIS job, or enter it in this job's answers file"),
    },
}

# ── WORK A PLATED PART CAUSES THAT AN UNPLATED ONE DOES NOT ──────────────────────────────
#
# "There would be consideration for two ops for Packing — to and from Plater & Final
# Assembly / Pack. Manual Estimate for 4 Minutes Pack for Platers / 8 Minutes Final Assembly
# & Pack." The sheet booked ONE pack operation of 2 minutes for both. A part that leaves the
# building and comes back is packed twice, and the second pack is not the first one again.
#
# And it travels: "Delivery to & from Platers from Transport Dept. For Ref. £120.00 Pallet
# Network - £20.00 per Unit". Held as the ORDER figure with the per-unit share derived, which
# is the form that survives a quantity change — £120 over the six stands that quote was
# written against is the £20 a unit he quotes. Whether £120 is the round trip or each way is
# the one thing the note does not settle, so the line says which it assumed.
#
# EVERY FIGURE HERE IS KEYED ON PLATING BEING PRESENT, which is what makes it safe: a job
# with no plated part reaches none of it. 12349-02 has no plating and cannot be touched.
PLATING_LOGISTICS = {
    "pack_for_plater_min": float(os.getenv(
        "PLATER_PACK_MIN", SHOP_STATED["plater_pack_min"])),
    "final_pack_min": float(os.getenv(
        "PLATER_FINAL_PACK_MIN", SHOP_STATED["plater_final_pack_min"])),
    "freight_gbp_per_order": float(os.getenv(
        "PLATER_FREIGHT_GBP", SHOP_STATED["plater_freight_gbp_per_order"])),
    "freight_is_round_trip": True,
    "source": (f"SDI transport department, via "
               f"{shop_stated_source('plater_freight_gbp_per_order')} — £"
               f"{SHOP_STATED['plater_freight_gbp_per_order']:.0f} pallet network, "
               f"quoted as £20 a unit"),
}

# ── ESTIMATOR MANUAL-OVERRIDE OUTPUTS ────────────────────────────────────────────────
# Where the estimator-override loop (client_quote_regen) writes its two deliverables. The
# regenerated CLIENT QUOTE lands in the AISheets share so the portal can serve it; the amended
# workbook is saved as the manual-override record. Both default to the AISheets share so a pilot
# works out of the box; point OVERRIDE_XLSX_DIR at the job's Live Enquiry folder if the override
# sheet should live beside its pack instead. Env-overridable for a test box with no share mounted.
MANUAL_OVERRIDE_QUOTE_DIR = os.getenv(
    "SDI_AISHEETS_DIR",
    r"\\sdi-dc01\shareddata$\Shared\Estimating\Completed\AI Estimating\AISheets")
MANUAL_OVERRIDE_XLSX_DIR = os.getenv("SDI_OVERRIDE_XLSX_DIR", MANUAL_OVERRIDE_QUOTE_DIR)

# palletising.py counts an order into cartons and pallets from the blanks it already measured,
# so a shipment is described as "~3 cartons on 1 pallet" and can be priced against a carton /
# pallet catalogue. These are the limits it counts against; the module holds safe defaults, so
# every key here is OPTIONAL and overrides just that one. The only assumption the count carries
# is packing_factor (how much void a protective pack is) — declared on every plan, tuned here
# for every job at once. Leave empty to accept the module defaults.
#   e.g. {"pallet_max_weight_kg": 1000.0, "carton_internal_mm": [1150, 750, 550]}
PALLETISING_CONFIG = {
    # "packing_factor": 0.8,               # a pack treated as ~20% void
    # "carton_internal_mm": [1200, 800, 600],
    # "carton_max_weight_kg": 25.0,
    # "pallet_footprint_mm": [1200, 1000], # UK standard, matches PACKAGING_CONFIG["pallet"]
    # "pallet_max_height_mm": 1800.0,
    # "pallet_max_weight_kg": 500.0,
}

# A9: tokens that mark a "part number" as a title-block artifact, not a real part.
# Case-insensitive substring match. Inheritable — extend as new artifacts surface.
JUNK_PART_TOKENS = [
    "ENSURE", "CHECK", "SCALE", "METAL-TO-METAL", "METAL TO METAL",
    "DO NOT", "PLEASE", "TYPICAL", "ALL DIMENSIONS", "REF ONLY", "SEE NOTE",
    "THIS DRAWING", "TOLERANCE", "UNLESS STATED", "REMOVE BURRS",
]

# E3: optional overhead/downtime uplift. Default OFF so the engine reports true
# manufacturing cost; toggle on for an FD "sell" view. Inheritable.
OVERHEAD_POLICY = {
    "enabled": False,
    "pct": 15.0,          # Tim bakes ~15% into his unit price
    "label": "Overhead / downtime uplift",
}

# E2: assembly/pack labour. Minutes/bay are learned from historical_quote_operation;
# this default is only used when no history matches. Applied at HOURLY_RATES_GBP["assembly"] (PACM).
ASSEMBLY_LABOUR_POLICY = {
    "default_minutes_per_bay": None,   # None => flag "not costed" if history is empty
}

# FIX 2: description tokens that mark a part as a weldment/assembly PARENT whose
# material is carried by its child BOM lines (parent is labour-only). Tunable/inheritable.
WELDMENT_PARENT_DESC_TOKENS = [
    "WELDMENT", "WELD ASSEMBLY", "WELDED ASSEMBLY", "WELD ASSY",
    # SDI shorthands seen in title blocks (e.g. WA01 "BASE WELDED ASM").
    "WELDED ASM", "WELD ASM", "WELDED ASSY", "WELDED ASSEM",
]
# Part-number suffixes that denote a weld-assembly PARENT (material carried by
# child detail parts). WA = weld assembly, SA = sub-assembly. A part matching one
# of these AND carrying no flat DXF of its own is treated as a material-suppressed
# parent — this catches mislabelled title blocks (e.g. material "MDF" or a
# "SELDED" typo) without relying on the description spelling at all.
WELDMENT_PARENT_PN_SUFFIXES = [r"-WA\d*$", r"-SA\d*$"]

PROCESS_NOTE_PATTERNS = {
    "deburr": DEBURR_PATTERN,
    "break_sharp_edges": BREAK_EDGE_PATTERN,
    "powder_coating": r"\bPOWDER\s+COAT(?:ING)?\b",
    "welding": WELD_PATTERN,
    "tapping": TAP_PATTERN,
    "countersinking": CSK_PATTERN,
    "laser_cutting": LASER_PATTERN,
    "drilling": DRILL_PATTERN,
    "punching": PUNCH_PATTERN,
    "mirror_hand": MIRROR_PATTERN,
}

STANDARD_SHEET_SIZES_MM = {
    "MILD STEEL": [(2500, 1250), (3000, 1500)],
    "STAINLESS STEEL": [(2500, 1250), (3000, 1500)],
    "ALUMINIUM": [(2500, 1250), (3000, 1500)],
    "ALUMINUM": [(2500, 1250), (3000, 1500)],
    "ZINTEC": [(2500, 1250)],
    "ACRYLIC": [(2050, 1520), (3050, 2050)],
    "HIGH IMPACT ACRYLIC": [(2050, 1520), (3050, 2050)],
    "PERSPEX": [(2050, 1520), (3050, 2050)],
    "POLYCARBONATE": [(2050, 1520), (3050, 2050)],
    # THE PLASTICS THE ENGINE RECOGNISES BUT COULD NOT PRICE. _is_board classifies PETG,
    # HIPS, ABS, PVC and the rest as plastic sheet and routes them to Other Sheet Material
    # — and none of them existed in this table, in the density table, or in the price
    # table. 11650's PETG side panels were reported as "DIMS REQUIRED" when the real
    # blocker was that PETG is not a material this engine has ever been able to cost:
    # perfect dimensions would still have produced GBP 0.00.
    #
    # Sheet size and density are physical/stock facts and are stated here. THE PRICE IS
    # NOT — see MATERIAL_PRICE_GBP_PER_KG.
    "PETG": [(2050, 1520), (3050, 2050)],
    "HIPS": [(2050, 1520), (3050, 2050)],
    "ABS": [(2050, 1520), (3050, 2050)],
    "PVC": [(2050, 1520), (3050, 2050)],
    "FOAMEX": [(3050, 2030)],
    # Aluminium composite (ACM) — standard trade sheets. Physical stock fact, not a price.
    "DIBOND": [(3050, 1500), (2050, 3050), (4050, 2020)],
    "ALUPANEL": [(3050, 1500), (2050, 3050)],
    "REYNOBOND": [(3050, 1500), (2050, 3050)],
    "ETALBOND": [(3050, 1500), (2050, 3050)],
    "COMPOSITE": [(3050, 1500)],
    "POLYPROPYLENE": [(2050, 1520)],
    "POLYSTYRENE": [(2050, 1520)],
    "PMMA": [(2050, 1520), (3050, 2050)],
    "ACETAL": [(2000, 1000)],
    "DELRIN": [(2000, 1000)],
    "NYLON": [(2000, 1000)],
    "PET": [(2050, 1520)],
    "UHMW": [(2000, 1000)],
    # Timber-based sheet materials — standard UK board sizes
    "MDF": [(2440, 1220), (3050, 1525)],
    "MDF_BOARD": [(2440, 1220), (3050, 1525)],
    # FACED BOARD IS NOT NESTED ON A STEEL SHEET. Without an entry here, MFC fell through to
    # the sheet-metal default of 2500x1250 and yielded ONE panel per sheet; MDF, which has
    # board sizes, gets two of the same panel out of a 3050x1525. So the moment a sheet rate
    # is entered, 12422-24's end cap would be charged a whole sheet instead of half of one.
    #
    # These are STOCK SIZES, not prices: what the trade actually stocks, which is a physical
    # fact about the material and not a commercial number this engine may invent. 2800x2070
    # is the standard faced-board oversize sheet (Egger and equivalents); 2440x1220 is the
    # common trade size. Both are offered so the nester picks whichever yields more, exactly
    # as it does for MDF and ply. CONFIRM with the estimators which SDI actually buys.
    # 3080x1220 is the laminated-MDF sheet SDI actually buys from Lawcris — Tony Ford's own
    # estimate for 0359967 (11908-21, 16 Sep 2026) prices "3080 x 1220 x 9mm MDF laminated
    # both sides" by that sheet. A stock size is a physical fact about what the trade sells,
    # so it is recordable here; the PRICE of that sheet is not, and lives with its
    # provenance in BOARD_SHEET_PRICE_GBP below.
    "MFC": [(2800, 2070), (3080, 1220), (2440, 1220)],
    "MFMDF": [(2800, 2070), (3080, 1220), (2440, 1220)],
    "CHIPBOARD": [(2800, 2070), (2440, 1220)],
    "VENEERED MDF": [(2440, 1220), (3050, 1525)],
    "OAK_VENEER_MDF": [(2440, 1220), (3050, 1525)],
    "PLYWOOD": [(2440, 1220), (3050, 1525)],
    "BIRCH_PLYWOOD": [(2440, 1220), (3050, 1525)],
    "TIMBER": [(2400, 1200)],
    "DEFAULT": [(2500, 1250)],
}

MATERIAL_DENSITY_KG_PER_M3 = {
    "MILD STEEL": 7850,
    "MILD_STEEL": 7850,
    "GALVANISED STEEL": 7850,
    "GALVANIZED STEEL": 7850,
    "ZINTEC": 7850,
    "STAINLESS STEEL": 8000,
    "STAINLESS_STEEL": 8000,
    "ALUMINIUM": 2700,
    "ALUMINUM": 2700,
    "TIMBER": 600,
    "WOOD": 600,
    "MDF": 750,
    "MDF_BOARD": 750,
    "PLYWOOD": 680,
    "BIRCH_PLYWOOD": 680,
    "OAK_VENEER_MDF": 750,
    "HDPE_PLASTIC": 950,
    "SOFTWOOD": 500,
    "HIGH IMPACT ACRYLIC": 1190,
    "ACRYLIC": 1190,
    "PERSPEX": 1190,
    "POLYCARBONATE": 1200,
    # Physical constants, checkable against any materials datasheet.
    "PETG": 1270,
    "HIPS": 1050,
    "ABS": 1040,
    "PVC": 1400,
    "FOAMEX": 550,
    # ACM effective density: 3mm DIBOND is ~4.5 kg/m2 -> 4.5/0.003 = 1500 kg/m3. A composite,
    # so this is an EFFECTIVE figure for weight/handling — the material is priced by AREA
    # (BOARD_SHEET_PRICE_GBP), not by mass, because two ally skins on a plastic core do not
    # cost like a solid of any single density.
    "DIBOND": 1500,
    "ALUPANEL": 1500,
    "REYNOBOND": 1500,
    "ETALBOND": 1500,
    "COMPOSITE": 1500,
    "POLYPROPYLENE": 905,
    "POLYSTYRENE": 1050,
    "PMMA": 1190,
    # Found by test_every_plastic_the_router_recognises_has_a_density on its first run:
    # five more materials _is_board routes confidently and nothing could cost.
    "ACETAL": 1410,
    "DELRIN": 1410,
    "NYLON": 1140,
    "PET": 1380,
    "UHMW": 940,
}

MATERIAL_PRICE_GBP_PER_KG = {
    "MILD STEEL": 0.80,      # SDI rate £800/tonne inc. market movement buffer
    "MILD_STEEL": 0.80,
    "GALVANISED STEEL": 0.95,
    "GALVANIZED STEEL": 0.95,
    "ZINTEC": 0.90,          # Slightly above mild steel
    "STAINLESS STEEL": 3.10,
    "STAINLESS_STEEL": 3.10,
    "ALUMINIUM": 2.75,
    "ALUMINUM": 2.75,
    "TIMBER": 1.10,
    "WOOD": 1.10,
    "MDF": 1.35,
    "MDF_BOARD": 1.35,
    "PLYWOOD": 1.45,
    "BIRCH_PLYWOOD": 1.65,
    "OAK_VENEER_MDF": 2.20,
    "HDPE_PLASTIC": 2.85,
    "SOFTWOOD": 0.95,
    "HIGH IMPACT ACRYLIC": 3.26,
    "ACRYLIC": 3.26,
    "PERSPEX": 3.26,
    "POLYCARBONATE": 3.80,
    # ── PLASTICS THE ENGINE RECOGNISES AND STILL CANNOT PRICE ───────────────────────
    # PETG, HIPS, ABS, PVC, FOAMEX, PP and PS have a sheet size and a density above but
    # DELIBERATELY NO RATE HERE. A price is a commercial fact and SDI owns it; inventing
    # one would put a number on a quote that nobody has agreed to and that no supplier
    # would honour, which is worse than the gap it fills.
    #
    # The gap is not silent: a recognised plastic with no rate is reported as an ENGINE
    # gap (price_provenance.NO_VOCABULARY), which says the job is UNDER-CHARGED and that
    # no estimator input can fix it — it needs a rate here. Add one line each and every
    # job carrying that material prices itself from then on.
    #
    #   "PETG": <GBP per kg>,
}

WELD_TIME_POLICY = {
    "default_weld_minutes_per_weldment": 15.0,
    "default_dress_weld_minutes": 10.0,
    "weldment_complexity_max_multiplier": 4.0,
}

# ── DRES: dress welds after a structural (CO2/WELD) weld ──
# A CO2-welded fabrication is almost always linished/dressed (DRES dept, £28.68/hr)
# to clean the weld before finishing — Tim routes structural welds through DRES as a
# matter of course. When True, any part carrying a `welding` op chains a `dress_welds`
# op so the DRES labour lands on the route. Timing lives in the estimator (setup/run).
# Spot/resistance welds are NOT dressed (they leave no proud bead), so only the CO2
# `welding` op triggers this, not `spot_welding`/`resistance_welding`.
DRESS_AFTER_STRUCTURAL_WELD = True
# Per-unit dress RUN time. Tim's 12120 STAND ASSY "Dress (Minimal)" books 120/hr =
# 30s = 0.5 min/unit (Total Hours 104.67 at qty 12500). The engine previously used
# 2.0 min -> 30/hr, ~4x his cost (£0.96 vs his £0.24). 0.5 aligns to his number.
# Adjustable: a heavy multi-pass dress would take longer than this minimal rate.
DRESS_WELD_RUN_MINUTES = 0.5

# ── WELDING A FABRICATED ASSEMBLY: WHAT DRIVES THE TIME ──────────────────────────────────
#
# THE DEFECT THIS EXISTS TO CLOSE. Weld run-time was computed as
# `max(1.0, (pierces * 90 + cut_length_mm * 0.01) / 60)` — hole count and cut length, which
# are properties of a FLAT BLANK. A weld assembly has no flat of its own, so both drivers
# read zero on the only kind of part welding ever runs on, and every weldment took the
# 1-minute floor. On 7332-01 the sheet booked 2 minutes of welding and 1 of dressing where
# the welding department says 30 minutes and 20 — roughly £25-30 a unit missing on an £80
# stand. A timer with no valid input is not a low estimate, it is no estimate.
#
# THE PUBLISHED METHOD, which is not in dispute anywhere:
#     arc time   = weld length / travel speed
#     total time = arc time / operating factor      (MIG ~35%: the share of the hour the
#                                                    arc is actually burning, the rest being
#                                                    fit-up, clamping, repositioning,
#                                                    cleaning and inspection)
#     plus       handling per joint and set-up per weldment
# Sources: Miller Electric on arc-on time and operating factor; the Australian Steel
# Institute's hour-rates for continuous fillet welds (short welds under 250 mm: 0.3 h/m at a
# 6 mm leg). MIG production travel speeds run 10-25 in/min, i.e. 254-635 mm/min.
#
# WHAT WE CANNOT READ, AND SO DO NOT PRETEND TO. Nothing in a pack tells us weld LENGTH or
# JOINT COUNT: no drawing field, no model property, and on 7332-01 the weldment's members
# are siblings rather than children, so they cannot even be counted. The length-based model
# below is therefore live but dormant — it computes the moment a weld length reaches a
# record, and until then the allowance is used instead.
#
# THE ALLOWANCE IS THE SHOP'S OWN NUMBER, NOT OURS. 30 minutes to weld and 20 to dress are
# what SDI's welding department states for 7332-01 (Howard Thurley, 9 Sep 2026). It is one
# observation on one sheet-metal weldment and it is flagged as such on every line it prices,
# because whether it generalises to a small bracket is a question for the shop and not for
# this file. An over-statement that is flagged gets corrected by an estimator; the 1-minute
# floor it replaces was wrong by fifteen times and said nothing.
WELD_TIME_MODEL = {
    "travel_speed_mm_per_min": float(os.getenv("WELD_TRAVEL_SPEED_MM_PER_MIN", "300")),
    "operating_factor": float(os.getenv("WELD_OPERATING_FACTOR", "0.35")),
    "handling_min_per_joint": float(os.getenv("WELD_HANDLING_MIN_PER_JOINT", "2.0")),
    "setup_min_per_weldment": float(os.getenv("WELD_SETUP_MIN", "3.0")),
    # PER JOINT, BECAUSE ONE NUMBER FOR EVERY WELDMENT IS NOT A RULE, IT IS A BLANKET.
    # Scaling by joints reproduces the shop's own figure on the part the shop measured, and
    # it does not put a Harrods frame's time onto 12349-02-69-03M, which is two laser-cut
    # parts welded once. A weldment of N members has at least N-1 joints; where the members
    # can be counted, the count is used, and where they cannot the flat allowance stands.
    #
    # DERIVED, NOT DIVIDED BY HAND. These were 10.0 and 6.7 — Howard's 30 and 20 over an
    # ASSUMED three joints, while the engine counts five on the very part he timed. It then
    # multiplied a three-joint rate by a five-joint count and printed 50 minutes where he
    # said 30. The assumption lived in a comment and the measurement lived in code, so
    # nothing could compare them. Now the count sits in SHOP_STATED beside the minutes it
    # divides: correct the count and both rates follow.
    "weld_min_per_joint": float(os.getenv(
        "WELD_MIN_PER_JOINT",
        SHOP_STATED["weld_min_per_weldment"] / SHOP_STATED["weld_joints_measured_on"])),
    "dress_min_per_joint": float(os.getenv(
        "WELD_DRESS_MIN_PER_JOINT",
        SHOP_STATED["dress_min_per_weldment"] / SHOP_STATED["weld_joints_measured_on"])),
    # Used when the pack states no weld length, no joint count, and the members cannot even
    # be counted — 7332-01-101, whose members are siblings rather than children.
    "allowance_min_per_weldment": float(os.getenv(
        "WELD_ALLOWANCE_MIN", SHOP_STATED["weld_min_per_weldment"])),
    "dress_allowance_min_per_weldment": float(os.getenv(
        "WELD_DRESS_ALLOWANCE_MIN", SHOP_STATED["dress_min_per_weldment"])),
    "allowance_source": (f"SDI welding department, via {shop_stated_source('weld_min_per_weldment')} — one "
                         f"observation, pending confirmation that it generalises"),
    "method_source": ("arc time / operating factor, MIG ~35% (Miller Electric); fillet hour-"
                      "rates per metre (Australian Steel Institute)"),
}

# ── MANM: insert labour for pressed fasteners (self-clinch nuts, PEM studs) ──
# Tim books the press/insert time for pressed-in fasteners as MANM (Manual labour
# Metal, £31.18/hr, 15-min setup). His 12120 REV G manual estimate gives the rule
# TWICE, and both agree exactly:
#     Upstand   "Clinch x 4"  @ 60/hr  -> 3600/60  = 60s/part / 4 = 15 s/insert
#     Base plate "Pem x 2"    @ 120/hr -> 3600/120 = 30s/part / 2 = 15 s/insert
# So 15 s/insert is HIS number, derived from his own sheet — not an assumption.
# Knurled knobs and thumbscrews are HAND-ASSEMBLED (they go to Assemble/pack), not
# pressed, so only clinch/PEM parts count as inserts. wb_populate counts inserts from
# the reconciled BOM (self-clinch nuts + PEM/keyhole studs) and books one MANM row.
BOOK_MANM_INSERT_LABOUR = True
MANM_INSERT_SECONDS_EACH = 15.0            # from Tim's 12120 sheet (clinch x4 @60/hr, pem x2 @120/hr)
MANM_INSERT_PART_TOKENS = ["CLINCH", "PEM"]  # description/part-number tokens that mark a pressed insert

# ── Material total: tolerate not-yet-dimensioned rows ────────────────────────────
# When a fabricated part has no usable blank L/W (or gauge), the template's per-row material
# formula errors (#VALUE!/#DIV/0!) and the plain SUM in Total Material Cost (M92) propagates
# that error into Unit and Sell — so ONE missing dim blanks the whole sheet total. This is bad
# for a human-review deliverable: it hides the genuine labour/wire/BOM work below it.
# With this True, wb_populate rewrites M92's SUM(...) to AGGREGATE(9,6,...) (sum ignoring
# errors), so the sheet shows a PARTIAL total from the credible lines, marks the dim-less rows
# "⚠ DIMS REQUIRED", and self-completes as the estimator fills them in.
# NON-REGRESSIVE: AGGREGATE(9,6,range) == SUM(range) when the range has no errors, so fully
# dimensioned jobs (12120, 1282) are unchanged. Set False to restore the old #VALUE! wall.
MATERIAL_TOTAL_ERROR_TOLERANT = True

# ── Acrylic provisional pricing (PROVISIONAL — pending estimating/Tim confirmation) ──
# Bootstrap values from the M18 (10897) workbook so acrylic jobs get a sensible INFERRED
# cost today instead of flagging INSUFFICIENT / falling back to £/kg (which under-prices
# acrylic: a panel comes out ~£1.98 by mass vs ~£3.20 sheet-nested). Acrylic is bought and
# costed by the SHEET, so it is sheet-priced here, NOT £/kg. Every acrylic line costed from
# these values is stamped PROVISIONAL and is designed to be SWAPPED for canonical figures
# (sheet prices from purchasing, op time-drivers from estimating) by editing this block —
# no code change. Sheet SIZE comes from STANDARD_SHEET_SIZES_MM (acrylic = 2050x1520).
ACRYLIC_SHEET_PRICE_GBP = {
    2.0: 34.00,
    3.0: 46.20,    # 3mm high-impact @ 2050x1520 — confirmed from the M18 workbook
    5.0: 70.00,
    8.0: 112.00,
    10.0: 138.00,
    "default": 46.20,
}

# acrylic_area_pricing (2026-07-15): £/m2 by thickness, derived from UDEF (Access Supply Chain) —
# every priced acrylic line from Perspex Distribution / Plastics Plus / AMARI, isolated to
# Clear/standard XT stock. PROVEN LINEAR: for each thickness the £/m2 from a full sheet and a cut
# blank agree (2mm 7.8 vs 7.9/8.5; 3mm 11.5 vs 13.2), so a blank costs area × sheet-rate.
# Confidence: 1.8/2.0mm STRONG (3 lines each, tight); 3mm OK (2 lines); 4/5/6/8mm single-line
# (real current Perspex price, single-source). CLEAR/standard XT only — coloured / matt / cast /
# anti-reflective run ~1.5-2x higher and are NAMED on the drawing (separate tier, later).
# Used as: cost = blank_area_m2 × rate × (1+scrap), expressed through the WB's L/J. PROVISIONAL
# until estimating signs off these figures.
# ── WHICH MATERIALS THIS ENGINE CAN ACTUALLY PRICE ──────────────────────────────────
# The sheet-priced plastics. estimator's material branch tests membership of this set before
# taking the area x GBP/m2 path, and that path always resolves -- ACRYLIC_PRICE_GBP_PER_M2
# carries a "default" -- so a material IN this set always gets a rate.
#
# It lived as a set literal inside estimate_material, where nothing else could ask it. ABS is
# not in it and POLYCARBONATE is, so when SolidWorks (rank 90) beat the drawing text (rank 70)
# on 11650-01-05A DOOR, the winning material had no rate by ANY route -- not here, and no
# entry in MATERIAL_PRICE_GBP_PER_KG either -- while the losing one had both. The door costed
# GBP 0.00 material on a 1202 x 689 x 6mm panel and nothing said why.
#
# The tables live here, so the question "can we price this material at all" is answered here
# too. A second copy anywhere else would drift from the tables it describes.
PLASTIC_SHEET_PRICED_MATERIALS = frozenset({
    "ACRYLIC", "HIGH IMPACT ACRYLIC", "HIPS", "PERSPEX", "PMMA", "POLYCARBONATE",
})

# A BLANK MAY BE TURNED ON THE SHEET — unless something about it has a direction.
#
#   "Line 84 – AI Yield 24 Per Sheet – if Component, Exchange Length for Width and Vice
#    Versa   Yield is 26 Per Sheet"        — Howard Thurley, 0355255, 9 Sep 2026
#
# The workbook's own nesting formulas never rotate (K38 and J51 both nest length along
# length), so the ONLY way the sheet charges the better yield is for the blank to be
# WRITTEN turned. The engine tries both orientations and writes the better one — except
# where the material or finish runs one way, because a brushed panel nested sideways is a
# panel the customer rejects, and no yield pays for that. Tokens, not part numbers: a job
# nobody has seen yet is judged by the same rule, and estimating can extend the list.
DIRECTIONAL_FINISH_TOKENS = (
    "BRUSH", "GRAIN", "VENEER", "REEDED", "FLUTED", "RIBBED", "WOODGRAIN", "DIRECTIONAL",
)


# ── READING A MATERIAL CELL THAT CARRIES MORE THAN THE MATERIAL ──────────────────────
#
# 0359342's BOM states its materials the way a drawing office types them, not the way a rate
# table is keyed: "CR4, 2mm", "CR4,2mm", "Steel,Mild2mm", "Steel, Mild Wire", "MildSteel".
# Every one of those is mild steel and this engine holds a mild-steel rate, yet
# MATERIAL_PRICE_GBP_PER_KG.get("CR4, 2mm") is None — so the stated-weight costing path (the
# one that prices a part from its own printed weight) was skipped for want of a rate, and a
# 10 g backplate fell through to a generated market figure of GBP 55 each, GBP 3,203 the line.
# The price was never the problem. The KEY was.
#
# THE RULE THAT KEEPS THIS SAFE: resolution is only ever attempted for a name this engine
# CANNOT ALREADY PRICE. A name that resolves as written is returned untouched, so no job that
# prices today can move by a penny through this function — the structured lane cannot enter it.
#
# What it does is remove what is not the material and recognise what is:
#   - a gauge stated in the same cell ("2mm", and the glued "Mild2mm") is a thickness, and the
#     part already carries its thickness in its own field;
#   - a FORM ("wire", "sheet", "plate") is how the stock comes, not what it is made of;
#   - a GRADE is the material under another name, and CR4 is cold-reduced mild steel.
# Anything that still does not resolve returns None, exactly as before — an unknown material
# stays unknown and unpriced rather than being guessed into the nearest rate.
_MATERIAL_FORM_TOKENS = frozenset({
    "WIRE", "SHEET", "PLATE", "BAR", "ROD", "SECTION", "STRIP", "FLAT",
    "GRADE", "THK", "THICK", "GAUGE", "MM",
})

# Token sets, so word order and punctuation stop mattering: "Steel, Mild Wire", "MildSteel"
# and "Mild Steel CR4" all reduce to the same question. Values must be keys the tables above
# actually hold — this table renames, it never prices.
_MATERIAL_TOKEN_SYNONYMS = {
    frozenset({"CR4"}): "MILD STEEL",
    frozenset({"MS"}): "MILD STEEL",
    frozenset({"MILD", "STEEL"}): "MILD STEEL",
    frozenset({"CR4", "STEEL"}): "MILD STEEL",
    frozenset({"CR4", "MILD"}): "MILD STEEL",
    frozenset({"CR4", "MILD", "STEEL"}): "MILD STEEL",
    frozenset({"CR1", "STEEL"}): "MILD STEEL",
    frozenset({"HR4", "STEEL"}): "MILD STEEL",
    frozenset({"S275"}): "MILD STEEL",
    frozenset({"DC01"}): "MILD STEEL",
    frozenset({"FLEXI", "MDF"}): "MDF",
    frozenset({"MOISTURE", "RESISTANT", "MDF"}): "MDF",
    frozenset({"MR", "MDF"}): "MDF",
    frozenset({"BIRCH", "PLY"}): "BIRCH_PLYWOOD",
    frozenset({"BIRCH", "PLYWOOD"}): "BIRCH_PLYWOOD",
    frozenset({"PLY"}): "PLYWOOD",
    frozenset({"STAINLESS"}): "STAINLESS STEEL",
    frozenset({"SS", "STEEL"}): "STAINLESS STEEL",
    frozenset({"ALUMINIUM"}): "ALUMINIUM",
    frozenset({"ALUMINUM"}): "ALUMINIUM",
}


def _material_name_tokens(material) -> frozenset:
    """The material words in a cell, with gauges, forms and punctuation taken out."""
    import re as _re
    # Squashed table text arrives as one CamelCase word: extract_tables strips the spaces, so
    # "Mild Steel" reaches us as "MildSteel". Split on the case change FIRST, while the case is
    # still there to read, then upper-case.
    text = _re.sub(r"(?<=[a-z])(?=[A-Z])", " ", str(material or "").replace("_", " ")).upper()
    # Take the GAUGE out by name, not by splitting every letter/digit boundary — "Mild2mm" must
    # lose its 2mm while CR4 keeps its 4. A gauge is digits carrying a unit, so that is what is
    # matched; a grade is digits carrying nothing, and survives.
    text = _re.sub(r"\d+(?:\.\d+)?\s*MM\b", " ", text)
    words = _re.split(r"[^A-Z0-9]+", text)
    out = set()
    for w in words:
        if not w or w.isdigit():
            continue                           # a bare number is a gauge or a size, never a material
        if w in _MATERIAL_FORM_TOKENS:
            continue
        out.add(w)
    return frozenset(out)


def resolve_material_rate_key(material):
    """The rate-table key this material text prices under, or None if this engine holds none.

    Returns the name UNCHANGED whenever it already prices — see the rule above. Only a name
    with no rate of its own is reduced to its material words and looked up as a grade synonym.
    """
    name = str(material or "").strip()
    if not name:
        return None
    if material_has_a_rate(name):
        return name                            # already priceable: never rewritten
    tokens = _material_name_tokens(name)
    if not tokens:
        return None
    synonym = _MATERIAL_TOKEN_SYNONYMS.get(tokens)
    if synonym and material_has_a_rate(synonym):
        return synonym
    # No synonym entry, but the cell may simply have carried a gauge alongside a material this
    # engine already knows ("MDF, 18mm" -> MDF). Try the material words as written.
    for candidate in (" ".join(sorted(tokens)), " ".join(tokens)):
        if material_has_a_rate(candidate):
            return candidate
    if len(tokens) == 1:
        only = next(iter(tokens))
        if material_has_a_rate(only):
            return only
    return None


def material_has_a_rate(material) -> bool:
    """Can this engine put a price on this material by any route it has?

    Not "is it a sensible material" and not "did we price this part" -- only whether a rate
    exists to be found. Used by the costing to know when to look for a better-supported
    reading, and by the invariants to say that an unpriceable material is OUR gap and not
    the estimator's.
    """
    name = str(material or "").strip().upper().replace("_", " ")
    if not name:
        return False
    if name in PLASTIC_SHEET_PRICED_MATERIALS:
        return True
    for key in (name, name.replace(" ", "_")):
        if (MATERIAL_PRICE_GBP_PER_KG or {}).get(key) is not None:
            return True
    # BOARD PRICED BY THE SHEET IS STILL PRICED. MFC, chipboard and DIBOND/ACM carry a
    # per-sheet rate, not a GBP/kg — and without this a Dibond part that DOES price off
    # BOARD_SHEET_PRICE_GBP was still reported "no rate", so the sheet showed a real price and a
    # BLOCKING under-charge at once. The name may carry a gauge ("DIBOND 3.0MM"), so a board key
    # that is a substring of it counts too.
    _board = BOARD_SHEET_PRICE_GBP or {}
    for key in (name, name.replace(" ", "_")):
        if key in _board:
            return True
    if any(k in name for k in _board):
        return True
    return False


# ── APPLIED FINISHES, BY AREA ────────────────────────────────────────────────────────
#
# THE ONE PLACE A FINISH GAP IS CLOSED. Keyed on the finish codes applied_finish.py reads off
# the drawing, in GBP per square metre of coated face.
#
# EMPTY ON PURPOSE, AND THAT IS AN ANSWER RATHER THAN AN OVERSIGHT. Powder was the only finish
# this engine could cost, which is right for steel and wrong for everything else — vinyl,
# laminate, print, foil and paint go on MDF, acrylic and PETG every day. 11650-04's side panels
# state "1/2 INCH REEDED VINYL + UV OR CLEAR VINYL" and the vinyl was costed at nothing, on a
# panel where it is most of what the customer is buying.
#
# Until a rate is entered here, a stated finish produces an EXPLICIT estimator-input line
# carrying the code and the area — never a zero, because a finish costed at nothing and a
# finish nobody has priced read identically on a sheet and only one is an under-charge anybody
# can catch. Entering one line here prices that finish on every job that states it, for good;
# no enquiry should ever need code for this.
#
#   APPLIED_FINISH_RATES_GBP_PER_M2 = {"VINYL_REEDED": 14.50, "UV_COAT": 6.00}
#
APPLIED_FINISH_RATES_GBP_PER_M2: dict = {}


ACRYLIC_PRICE_GBP_PER_M2 = {
    1.5: 8.2,    # 1 line (full sheet clear XT) — single-source
    1.8: 7.8,    # 3 lines (blanks), £6.4-8.3 — STRONG
    2.0: 8.0,    # 3 lines (2 clear blank + 1 full sheet), £7.8-8.5 — STRONG
    3.0: 13.0,   # clear blank £13.2 + black full sheet £11.5 — OK
    4.0: 14.2,   # 1 line (full sheet clear XT) — single-source
    5.0: 19.5,   # 1 line (full sheet clear XT 3050x2050) — single-source
    6.0: 21.7,   # 1 line (full sheet clear XT) — single-source
    8.0: 30.9,   # 1 line (full sheet clear XT) — single-source
    "default": 8.0,   # thin-gauge standard (most display acrylic is 1.5-3mm)
}
ACRYLIC_OP_DRIVERS = {
    # CANONICAL — reverse-engineered from the M18 (10897) workbook acrylic cells; reproduces
    # the estimator's per-op costs (LASA, LINE, GLUE, MANA) to the penny. Laser time is the
    # SDI model: load/unload (per sheet, amortised over parts nested) + profile cut (perimeter
    # ÷ speed) + hole cutting. Linebend scales per bend; glue + flame-polish are ONE op per
    # bonded/display assembly, not per panel.
    "laser_cut_mm_per_sec": 50.0,             # 3mm acrylic profile speed (= 3000 mm/min)
    "laser_load_unload_sec_per_sheet": 300.0, # ÷ parts-per-sheet (300/15=20s; 300/192=1.56s)
    "laser_sec_per_hole": 3.0,                # non-profile (hole) cutting
    "laser_setup_min": 5.0,
    # THE ACRYLIC DEPARTMENT'S OWN FIGURE, which beats a number reverse-engineered from one
    # workbook. 0355255 line 97 booked Linebend at 30 parts/hr — 1.0 min per bend on a
    # two-bend part — and Howard Thurley relayed the department's timing as 60 parts/hour for
    # that part. Same class of evidence as the welding department's 30/20 on 7332-01: the
    # people who do the work, in writing, through the estimator who owns the job.
    #
    # READ AS PER PART, CONVERTED TO PER BEND. 60/hr on the two-bend A01 is one minute for the
    # part, so half a minute a bend — which is what scales honestly to a part with three. If
    # the department meant 60/hr whatever the bend count, that is a different rule and the
    # line's flag is where it gets corrected.
    # HELD IN SHOP_STATED, read here. One register for every figure the shop has stated,
    # so the next estimator to disagree finds them all in one place with the names on.
    "min_per_linebend": SHOP_STATED["linebend_min_per_bend"],
    "linebend_setup_min": 30.0,
    "glue_min_per_assembly": 2.4,             # GLUE: one op per bonded assembly (25 parts/hr)
    "glue_setup_min": 30.0,
    "flame_min_per_assembly": 1.2,            # MANA: one op per display assembly (50 parts/hr)
    "flame_setup_min": 15.0,
    # acrylic_rates_corpus (2026-07-15): the two ops every acrylic part needs and the engine
    # was omitting. Diamond Polish is the acrylic FINISH (not powder); Peel removes the
    # protective film. Throughputs are CORPUS MEDIANS from dbo.historical_quote_labour_line
    # (raw_line_json $.J.labels.left), NOT copied from any single estimator sheet - the same
    # source as the metal size-bands. Corpus: Diamond Polish 135/hr (n=147), Peel 100/hr
    # (n=230). (Tony's 12439 sheet books 120 for each; the corpus differs and wins - a single
    # sheet is not evidence.)
    "diamond_polish_min_per_part": 0.4444,    # DPOL: 135 parts/hr (corpus median, n=147)
    "diamond_polish_setup_min": 10.0,
    "peel_min_per_part": 0.6,                 # MANA/peel: 100 parts/hr (corpus median, n=230)
    "peel_setup_min": 15.0,
    # Other acrylic ops present in the SDI route (zero on M18, wire as needed): DPOL diamond
    # polish, DRIL drill-acrylic (£25.13/hr), OVEN oven-forming, EDGE edging, PACP assemble/pack.
}
# ── SET-UP MINUTES: ONE OWNER, KEYED ON THE DEPARTMENT ───────────────────────────────
#
# SET-UP IS A BATCH COST. It does not scale with quantity: one unit and a hundred pay the same
# ten or fifteen or thirty minutes per tooling group, and only the per-unit SHARE falls, as
# `setup_min / 60 / order_qty x rate`. That is already how the sheet behaves and it is the whole
# of the quantity-break story — on 12349-02 at 7 off, GBP 46.41 of GBP 83.77 labour is set-up
# against GBP 37.36 of run time, so the same job at 100 off sheds about GBP 43 a unit without a
# single rate changing.
#
# WHAT WAS MISSING WAS AN OWNER FOR THE MINUTES, and the drift had already started. The figure
# lived in three places — this file's ACRYLIC_OP_DRIVERS, sheet_steel_costing.RATE_CARD, and the
# Estimate template's own rate rows — and two of them disagreed: acrylic laser set-up read 5
# minutes here and 10 on the rate card. A department cannot have its rate on one book and its
# set-up invented somewhere else.
#
# THE LADDER IS THE SAME AS MATERIAL'S: the labour book wins where it carries a set-up column,
# this table is the offline fallback, and a department in neither is an explicit nil rather than
# a guessed number. Ask `sheet_steel_costing.setup_min_for()`; do not write minutes in code.
#
# Keyed on the DEPARTMENT CODE, because that is the tooling group — two 5 mm acrylic parts on
# CNC share one set-up, and a 6 mm MDF packer on CNCJ is a different machine and keeps its own.
#
# Values are the Estimate template's own rate rows, which is the book the sheet's LOOKUP reads.
# The eleven below the first group exist on the template and were absent from the engine's card
# entirely, so the engine could not cost or check them: two of them, Weld (CO2) and Wet Spray,
# are used on 12349-02.
OPERATION_SETUP_MIN = {
    "PACP": 15, "PACM": 15, "BENC": 30, "CNC": 10, "CNCJ": 15, "DPOL": 10,
    "DRES": 30, "DRIL": 30, "EDGE": 30, "FOLD": 30, "GLUE": 30, "GUIL": 15,
    "LASA": 10, "LASM": 10, "LINE": 30, "MC J": 30, "MANA": 15, "MANM": 15,
    "OVEN": 30, "P/C": 15, "PACJ": 15,
    # On the template, absent from the engine's rate card until now.
    "PINR": 30, "PUNC": 10, "ROBO": 15, "ROLL": 45, "SALV": 30, "SAW": 10,
    "SPOT": 30, "TUBE": 15, "TBEN": 45, "WELD": 30, "SPRY": 25,
}

# ── AND THE SECOND COPY IS RETIRED HERE ──────────────────────────────────────────────
#
# ACRYLIC_OP_DRIVERS above carried its own set-up minutes, which is precisely the "rate on one
# book, set-up invented in code" this table exists to stop. Five of the six already agreed with
# the rate card; the sixth did not.
#
#   laser_setup_min was 5.0 against the rate card's 10 for LASA
#
# COSTING CHANGE, DECLARED RATHER THAN SLIPPED IN. Acrylic laser set-up doubles, which on a
# GBP 41.21/hr department is about GBP 3.43 added to the ORDER — GBP 0.49 a unit at 7 off, GBP
# 0.03 at 100. The rate card is the book the sheet's own LOOKUP reads, so it wins; if 5 minutes
# is the true figure then the rate card row is what to correct, and it is now the only place to
# correct it.
for _k, _dept in (("laser_setup_min", "LASA"), ("linebend_setup_min", "LINE"),
                  ("glue_setup_min", "GLUE"), ("flame_setup_min", "MANA"),
                  ("diamond_polish_setup_min", "DPOL"), ("peel_setup_min", "MANA")):
    if _dept in OPERATION_SETUP_MIN:
        ACRYLIC_OP_DRIVERS[_k] = float(OPERATION_SETUP_MIN[_dept])
del _k, _dept

ACRYLIC_PROVISIONAL_FLAG = "acrylic_provisional_pending_estimating"

NESTING_RULES = {
    # Workbook rows 37-48: edge_margin = 80mm, inter-part gap = 5mm per side = 10mm pitch add.
    # select_sheet_size() uses: INT((sheet_dim - 80) / (part_dim + 10)) — matches workbook exactly.
    "edge_margin_mm": 80.0,
    "part_spacing_mm": 5.0,   # each side; select_sheet_size multiplies by 2 = 10mm pitch
    # Align with workbook scrap allowance (see SCRAP_PERCENTAGE / WORKBOOK_INPUT_DEFAULTS).
    "waste_factor_pct": 4.0,
}

LABOUR_RULES = {
    "laser_cutting": {
        "setup_min": 3.0,
        "load_unload_sec": 30.0,
        "pierce_sec_each": 1.2,
        "cutting_speeds_mm_per_sec": {
            0.7: 118.0,
            1.0: 105.0,
            1.2: 100.0,
            1.5: 91.0,
            2.0: 75.0,
            2.5: 60.0,
            3.0: 55.0,
            4.0: 45.0,
            5.0: 28.0,
        },
    },
    # Punch press / CNC turret: holes are single HITS (fast), not laser pierces.
    # Dense identical-hole parts (peg panels, perforated/slotted/mesh) route here.
    # sec_per_hit is a PLACEHOLDER pending Tim's punch cycle time — turret punches
    # run ~1-2 hits/sec; 0.7s is deliberately conservative. profile = outline nibble.
    "punch": {
        "setup_min": 3.0,
        "load_unload_sec": 30.0,
        "sec_per_hit": 0.7,
        "profile_speed_mm_per_sec": 60.0,
    },
    "hole_machining": {
        "setup_min": 1.5,
        "sec_per_hole": 8.0,
    },
    "folding": {
        "setup_min": 2.0,
        "sec_per_bend": 18.0,
        "sec_per_mm_bend_length": 0.01,
    },
    # Booth labour: setup + (coated m² / throughput). Rate £/h from HOURLY_RATES_GBP["powder_coating"] / SQL (P/C).
    "powder_coating": {
        "setup_min_per_part": 0.75,
        # Calibrated to Tim's P/C line: 2.5 m/min (=150 m/hr) track, 319 hanging bars/hr
        # at HOURLY_RATES_GBP["powder_coating"]=£355.43/hr -> ~£1.11/bar. With both coated
        # faces counted in coated_m2, that line throughput is ~180 m2/hr, NOT 15. The old
        # 15 over-stated powder labour ~12x. Confirm against a closed works order.
        "throughput_m2_per_hour": 180.0,
        "min_run_min": 0.25,
    },
    # Wet spray / line paint: same coated-area model as powder; higher throughput, lower booth rate in HOURLY_RATES_GBP.
    "wet_spray": {
        "setup_min_per_part": 0.75,
        "throughput_m2_per_hour": 22.0,
        "min_run_min": 0.25,
    },
    # CNC routing (workbook CNCJ): light heuristic until cycle times are fed from CAM.
    "cnc": {
        "setup_min": 4.0,
        "min_run_min": 1.0,
        "sec_per_mm_contour": 0.04,
    },
    "cnc_routing": {
        "setup_min": 4.0,
        "min_run_min": 8.0,
        "sec_per_mm_contour": 0.04,
    },
    "edge_banding": {
        "setup_min": 3.0,
        "min_run_min": 4.0,
        "sec_per_mm_edge": 0.08,
    },
    # Bench fitting / manual assembly cells (workbook BENC).
    "bench_work": {
        "min_per_part": 2.0,
    },
    "handling": {
        "min_per_part": 0.8,
    },
    # Wire / spot / deburr (times largely set in estimator.estimate_process_times)
    "wire_forming": {
        "setup_min": 5.0,
        "mm_per_min": 500.0,
    },
    "deburring": {
        "setup_min": 1.0,
        "sec_per_point": 30.0,
    },
    "resistance_welding": {
        "setup_min": 2.0,
        "sec_per_point": 45.0,
    },
}

# Department labour rates (£/hr). DEFAULTS are Tim's ACTUAL card values, ingested
# from his 1282 estimate and cross-checked against his labour lines (dept code in
# the comment). These are OVERLAID at import by tim_rate_card.json when present, so
# re-running tim_rate_card_ingest.py on ANY SDI estimate refreshes them with no code edit.
HOURLY_RATES_GBP = {
    "laser_cutting": 68.19,          # LASM
    "laser_cutting_acrylic": 41.21,  # LASA
    "hole_machining": 25.13,         # DRIL
    "folding": 40.47,                # FOLD
    "powder_coating": 355.43,        # P/C (applied with throughput divisor)
    "handling": 31.18,               # MANM (manual metal handling)
    "assembly": 28.56,               # PACM (Assemble/pack metal)
    "assembly_acrylic": 25.43,       # PACP
    "welding": 41.77,                # WELD (CO2)
    "tube": 31.98,                   # TUBE
    # TWO SPELLINGS, ONE LETTER, AND THE TUBE-BENDER WORKED FOR NOTHING.
    #
    # The estimator emits the operation "tube_bending". This table held only "tube_bend", so
    # the rate lookup missed, the op landed in missing_rate_operations, and NO hours were
    # written for it at all — after which wb_populate had nothing to derive from and fell
    # back to its UNMEASURED 30/hr department default. 7332-01 has carried that default on
    # every book ever produced for it.
    #
    # The template prices Tubebend at £32.84/hr with a 45-minute set-up (TBEN) and always
    # has. Nothing was missing but the spelling.
    #
    # Both keys are kept: "tube_bend" is referenced elsewhere and removing it would be the
    # same defect in the other direction. test_every_operation_has_an_hourly_rate now fails
    # the suite if any op the estimator can time is missing from this table.
    "tube_bending": 32.84,           # TBEN — the name the engine actually emits
    "tube_bend": 32.84,              # TBEN — kept as an alias
    "wire_forming": 39.84,           # engine default (no single Tim wire-labour dept)
    "spot_welding": 32.90,           # SPOT
    "resistance_welding": 32.90,     # SPOT (resistance = spot)
    "deburring": 31.18,              # engine default
    "guillotine": 31.29,             # GUIL
    "diamond_polish": 31.60,         # DPOL
    "dress_welds": 28.68,            # DRES
    "glue": 25.43,                   # GLUE
    "punch": 43.77,                  # PUNC
    "roll": 30.84,                   # ROLL
    "saw": 31.89,                    # SAW
    "linisher": 25.43,               # engine default
    "manual_labour_metal": 31.18,    # MANM
    "manual_labour_acrylic": 25.43,  # MANA
    "cnc": 43.36,                    # CNC
    "cnc_routing": 64.07,            # CNCJ
    "cnc_joinery": 64.07,            # CNCJ
    "wet_spray": 33.54,              # SPRY
    "bench_work": 28.74,             # BENC
    "edge_banding": 39.03,           # EDGE
    "linebend": 25.43,               # LINE
    "pin_router": 25.43,             # PINR
    "robomac": 31.45,                # ROBO
    "salvagnini": 39.43,             # SALV
    "oven": 25.43,                   # OVEN
    "packing_joinery": 28.74,        # PACJ
    "machines_joinery": 28.74,       # MC J
}

# Learn from Tim: overlay the ingested rate card (tim_rate_card.json beside this file).
# Source of truth = Tim's sheet; defaults above are the fallback when the JSON is absent.
TIM_RATE_CARD_LOADED = None
try:
    import os as _os_rc, json as _json_rc
    _rc_path = _os_rc.path.join(_os_rc.path.dirname(_os_rc.path.abspath(__file__)), "tim_rate_card.json")
    if _os_rc.path.exists(_rc_path):
        with open(_rc_path) as _fh_rc:
            _rc = _json_rc.load(_fh_rc)
        for _op, _rate in (_rc.get("by_op") or {}).items():
            HOURLY_RATES_GBP[_op] = float(_rate)
        TIM_RATE_CARD_LOADED = _rc.get("source")
except Exception:
    TIM_RATE_CARD_LOADED = None

# Max unit cost applied silently to auto-detected bought-in lines (fuzzy catalogue match).
# Above this → reject match and flag for manual pricing (prevents "BRACKET" -> £13k hits).
BOUGHT_IN_MAX_PLAUSIBLE_GBP = 750.0

# Data sufficiency — suppress headline total when auto-estimate is not DXF-backed enough.
# credible_cost_ratio: share of document £ from parts with part-level DXF (not PDF/inferred).
# dxf_part_ratio: share of fabricated parts that have a matched part DXF.
DATA_SUFFICIENCY_MIN_CREDIBLE_COST_RATIO = 0.50
DATA_SUFFICIENCY_MIN_DXF_PART_RATIO = 0.25

CSV_HEADERS = [
    "source_file",
    "part_number",
    "description",
    "quantity",
    "page_roles",
    "material",
    "thickness_mm",
    "finish",
    "colour",
    "revision",
    "dates",
    "overall_length_mm",
    "overall_width_mm",
    "overall_sizes_mm",
    "dimensions_mm",
    "angles_deg",
    "hole_sizes_mm",
    "slot_sizes_mm",
    "manufacturing_features",
    "operations",
    "process_notes",
    "estimated_cut_length_mm",
    "estimated_hole_count",
    "estimated_slot_like_features",
    "estimated_bend_line_count",
    "blank_length_mm",
    "blank_width_mm",
    "material_cost_gbp",
    "total_time_min",
    "unit_labour_cost_gbp",
    "unit_total_cost_gbp",
    "extended_total_cost_gbp",
]

HISTORY_CSV_HEADERS = [
    "job_key",
    "spreadsheet_file",
    "drawing_file",
    "part_numbers",
    "materials",
    "thicknesses_mm",
    "operations",
    "estimated_total_cost_gbp",
    "document_total_estimated_cost_gbp",
    "spreadsheet_numeric_total",
    "text_snippet",
]

# WHICH MATERIAL CLASSES HAVE A FIRM-CAPABLE PRICING SOURCE YET.
#
# Firm pricing arrives one supplier at a time, not all at once, so this is a per-class switch
# rather than a single global flag. Turning sheet steel on when the Uptonsteel feed lands must
# not imply that plastic, timber and MRO are also integrated.
#
# Set a class True once a connector for it can supply an agreed rate or account feed carrying
# a validity date. Until then a firm customer quote on that class is refused with "no firm
# pricing source configured", which is the truth rather than a shrug.
#
# Classes come from price_provenance.material_class_of, which keys on material family and
# stock form — never on a part code — so a job nobody has seen yet is routed by the same rule.
FIRM_PRICING_COVERAGE = {
    "sheet_steel":   {"firm_capable": False, "intended_source": "Uptonsteel account feed"},
    "plastic_sheet": {"firm_capable": False, "intended_source": "Eagle Plastics account feed"},
    "timber_board":  {"firm_capable": False, "intended_source": "Cashmores account feed"},
    "fasteners_mro": {"firm_capable": False, "intended_source": "RS eProcurement / Farnell"},
    "other":         {"firm_capable": False, "intended_source": "UDEF contract price"},
}

# Whether an estimate is being produced to inform, or to be sent to a customer as a price we
# will honour. Nothing is firm by default: a job becomes firm-intent only when someone says so.
QUOTE_INTENT_INDICATIVE = "indicative"
QUOTE_INTENT_FIRM = "firm"
DEFAULT_QUOTE_INTENT = QUOTE_INTENT_INDICATIVE

PRICE_SOURCE_PRIORITY = [
    "udef_sqlserver",
    "sqlserver",
    "spreadsheet",
    "access",
    "web",
]

# ── SDILive credentials ───────────────────────────────────────────────────────
#
# THE PASSWORD HAS NO DEFAULT, AND THAT IS THE ENTIRE POINT OF THIS BLOCK.
#
# These four values were literals inside PRICE_SOURCE_CONFIG, so changing the SDILive password
# meant editing source — which means committing it, which means it is in git history for ever.
# It had been committed, in a repository that was public for four months. The engine's config
# never read SDI_DB_PASSWORD at all; only the backend service did, so the two halves of the same
# system disagreed about where the credential lived.
#
# Server, database and user DO keep defaults. An internal IP and a service-account name are not
# secrets, and defaulting them means an existing machine keeps working. The password defaults to
# NOTHING: an unset password must fail loudly and by name, because the alternative is a fallback
# literal, and a fallback literal is the thing being removed.
#
# SDILive is Access Supply Chain's primary database. Sage X3 is not live.
DB_SERVER   = os.getenv("SDI_DB_SERVER",   "10.0.0.200")
DB_NAME     = os.getenv("SDI_DB_NAME",     "SDILive")
DB_USER     = os.getenv("SDI_DB_USER",     "AIBot")
DB_PASSWORD = os.getenv("SDI_DB_PASSWORD", "")
# Driver 18 is the laptop's; SDI-APP01 carries only 17, and a missing driver reports IM002 —
# a client-side error that reads like the server is unreachable. Settable per machine.
DB_DRIVER   = os.getenv("SDI_DB_DRIVER",   "ODBC Driver 18 for SQL Server")


# Characters that break the connection string this password is pasted into, or the .env parser
# it is read from. The string is built as "...UID={user};PWD={password};Encrypt=yes..." so a
# semicolon ENDS THE PASSWORD AND STARTS A NEW KEYWORD -- the server is handed a truncated
# password and answers "Login failed for user 'AIBot'", which reads as a wrong password rather
# than a badly-chosen one. Braces delimit ODBC values; a quote or a hash can be eaten by dotenv.
#
# Checked rather than escaped, because a service password is generated once and never typed. The
# fix is to pick a different one, and being told that costs a minute, where diagnosing a
# truncated connection string costs an afternoon.
_PASSWORD_HOSTILE = ";{}\"'#"


def require_db_password() -> str:
    """The one place the absence of a password becomes a sentence somebody can act on."""
    bad = sorted({c for c in DB_PASSWORD if c in _PASSWORD_HOSTILE})
    if bad:
        where = str(_DOT_ENV_PATH) if _DOT_ENV_PATH else str(BASE_DIR / ".env")
        raise RuntimeError(
            f"SDI_DB_PASSWORD in {where} contains {' '.join(repr(c) for c in bad)}, which cannot "
            f"survive the ODBC connection string it is pasted into.\n"
            f"A semicolon in particular ends the password and starts a new keyword, so the server "
            f"is handed a truncated one and answers 'Login failed' -- which reads as the wrong "
            f"password rather than an unusable one.\n"
            f"Choose a letters-and-digits password instead; it is generated once and never typed, "
            f"so make it long rather than clever.")
    if not DB_PASSWORD:
        where = str(_DOT_ENV_PATH) if _DOT_ENV_PATH else str(BASE_DIR / ".env")
        raise RuntimeError(
            f"SDI_DB_PASSWORD is not set, so SDILive cannot be reached. Add it to {where} "
            f"as SDI_DB_PASSWORD=<the password for the SDILive login>.\n"
            f"That is the .env this process actually loaded -- the repo root is tried before "
            f"src/, and only the first one found is read, so editing the other has no effect.\n"
            f"It is deliberately not defaulted in source: a password in a source file is in git "
            f"history the moment it is pushed, and deleting it later does not remove it.")
    return DB_PASSWORD


PRICE_SOURCE_CONFIG = {
    "udef_sqlserver": {
        "enabled": True,
        "server": DB_SERVER,
        "database": DB_NAME,
        "username": DB_USER,
        "password": DB_PASSWORD,
        "driver": DB_DRIVER,
        "encrypt": True,
        "trust_server_certificate": True,
        # UDEF-first anchor for part/bought-in system cost lookups.
        # UDEF collation is Latin1_General_BIN (binary, case-sensitive) — use exact column name casing.
        # [Supplier name] exists directly on UDEF — SUP_TBL join not needed.
        # [WO Est lab cost], [WO Actual lab cost] etc. available for parity comparison.
        # Expected params: (part_code, description, part_code, description, part_code)
        "part_system_cost_query": """
SELECT TOP (1) * FROM (
    SELECT
        u.[Part code]      COLLATE Latin1_General_CI_AS AS part_code,
        u.[Description]    COLLATE Latin1_General_CI_AS AS description,
        u.[System cost per]                              AS system_cost_per,
        CAST(u.[System cost per] AS decimal(18,4))       AS price,
        u.[Supplier code]  COLLATE Latin1_General_CI_AS AS supplier_code,
        u.[Supplier name]  COLLATE Latin1_General_CI_AS AS supplier_name,
        'GBP'              AS currency,
        u.[UOM]            COLLATE Latin1_General_CI_AS AS unit,
        0.98               AS confidence,
        GETDATE()          AS price_date,
        0                  AS source_rank,
        u.[WO Est lab cost]     AS wo_est_lab_cost,
        u.[WO Est mat cost]     AS wo_est_mat_cost,
        u.[WO Actual lab cost]  AS wo_actual_lab_cost,
        u.[WO Actual mat cost]  AS wo_actual_mat_cost
    FROM dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING u
    WHERE
        LTRIM(RTRIM(u.[Part code] COLLATE Latin1_General_CI_AS)) = LTRIM(RTRIM(?))
        OR u.[Description] COLLATE Latin1_General_CI_AS LIKE '%' + LTRIM(RTRIM(?)) + '%'
    UNION ALL
    SELECT
        b.part_code        COLLATE Latin1_General_CI_AS,
        b.description      COLLATE Latin1_General_CI_AS,
        b.unit_price_gbp   AS system_cost_per,
        CAST(b.unit_price_gbp AS decimal(18,4)) AS price,
        b.supplier_code    COLLATE Latin1_General_CI_AS,
        b.supplier_name    COLLATE Latin1_General_CI_AS,
        'GBP'              AS currency,
        b.uom              COLLATE Latin1_General_CI_AS AS unit,
        0.93               AS confidence,
        b.effective_date   AS price_date,
        1                  AS source_rank,
        NULL AS wo_est_lab_cost,
        NULL AS wo_est_mat_cost,
        NULL AS wo_actual_lab_cost,
        NULL AS wo_actual_mat_cost
    FROM dbo.bought_in_parts b
    WHERE b.is_active = 1
      AND (
          LTRIM(RTRIM(b.part_code)) = LTRIM(RTRIM(?))
          OR b.description LIKE '%' + LTRIM(RTRIM(?)) + '%'
      )
) combined
ORDER BY
    CASE WHEN LTRIM(RTRIM(combined.part_code)) = LTRIM(RTRIM(?)) THEN 0 ELSE 1 END,
    source_rank,
    combined.price DESC
""",
        # Sargable fast-path: exact part-code seek only, NO description LIKE scan.
        # Tried first in get_part_system_cost; a code match already outranks any
        # description match in the full query above, so when this returns a row the
        # result is identical — it just skips the 91k-row table scan (~5.7s → ~ms).
        # The full query above is used only as a fallback when this returns nothing.
        # Expected params: (part_code, part_code, part_code)
        "part_system_cost_query_by_code": """
SELECT TOP (1) * FROM (
    SELECT
        u.[Part code]      COLLATE Latin1_General_CI_AS AS part_code,
        u.[Description]    COLLATE Latin1_General_CI_AS AS description,
        u.[System cost per]                              AS system_cost_per,
        CAST(u.[System cost per] AS decimal(18,4))       AS price,
        u.[Supplier code]  COLLATE Latin1_General_CI_AS AS supplier_code,
        u.[Supplier name]  COLLATE Latin1_General_CI_AS AS supplier_name,
        'GBP'              AS currency,
        u.[UOM]            COLLATE Latin1_General_CI_AS AS unit,
        0.98               AS confidence,
        GETDATE()          AS price_date,
        0                  AS source_rank,
        u.[WO Est lab cost]     AS wo_est_lab_cost,
        u.[WO Est mat cost]     AS wo_est_mat_cost,
        u.[WO Actual lab cost]  AS wo_actual_lab_cost,
        u.[WO Actual mat cost]  AS wo_actual_mat_cost
    FROM dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING u
    WHERE LTRIM(RTRIM(u.[Part code] COLLATE Latin1_General_CI_AS)) = LTRIM(RTRIM(?))
    UNION ALL
    SELECT
        b.part_code        COLLATE Latin1_General_CI_AS,
        b.description      COLLATE Latin1_General_CI_AS,
        b.unit_price_gbp   AS system_cost_per,
        CAST(b.unit_price_gbp AS decimal(18,4)) AS price,
        b.supplier_code    COLLATE Latin1_General_CI_AS,
        b.supplier_name    COLLATE Latin1_General_CI_AS,
        'GBP'              AS currency,
        b.uom              COLLATE Latin1_General_CI_AS AS unit,
        0.93               AS confidence,
        b.effective_date   AS price_date,
        1                  AS source_rank,
        NULL AS wo_est_lab_cost,
        NULL AS wo_est_mat_cost,
        NULL AS wo_actual_lab_cost,
        NULL AS wo_actual_mat_cost
    FROM dbo.bought_in_parts b
    WHERE b.is_active = 1
      AND LTRIM(RTRIM(b.part_code)) = LTRIM(RTRIM(?))
) combined
ORDER BY
    CASE WHEN LTRIM(RTRIM(combined.part_code)) = LTRIM(RTRIM(?)) THEN 0 ELSE 1 END,
    source_rank,
    combined.price DESC
""",
    },
    "sqlserver": {
        "enabled": True,
        "server": DB_SERVER,
        "database": DB_NAME,
        "username": DB_USER,
        "password": DB_PASSWORD,
        "driver": DB_DRIVER,
        "encrypt": True,
        "trust_server_certificate": True,
        # TODO: replace with your real material table query when ready.
        # Expected params: (normalized_material, thickness_mm, quantity)
        "material_price_query": """
SELECT TOP (1)
    material_code AS material,
    thickness_mm,
    price_gbp_per_kg AS price,
    'GBP' AS currency,
    'GBP_per_kg' AS unit,
    0.92 AS confidence,
    supplier_name AS supplier_source,
    effective_date AS price_date
FROM dbo.material_prices
WHERE UPPER(LTRIM(RTRIM(material_code))) = UPPER(LTRIM(RTRIM(?)))
  AND (thickness_mm IS NULL OR ABS(thickness_mm - ?) <= 0.15)
ORDER BY effective_date DESC
""",
        # TODO: replace with your real labour table query when ready.
        # Expected params: (operation)
        "labour_rate_query": """
SELECT TOP (1)
    operation_code AS rate_code,
    hourly_rate_gbp AS price,
    'GBP' AS currency,
    'GBP_per_hour' AS unit,
    0.92 AS confidence,
    effective_date AS price_date
FROM dbo.labour_rates
WHERE LOWER(LTRIM(RTRIM(operation_code))) = LOWER(LTRIM(RTRIM(?)))
ORDER BY effective_date DESC
""",
        # Historical quote RAG — material_line is a real table with quote_id (not quote_part_id).
        # Used by pricing_service._get_historical_rag and get_top_historical_matches.
        # Expected params: (search_term)
        "historical_rag_query": """
SELECT TOP 1
    hml.line_description,
    hml.unit_price_gbp,
    hml.line_total_gbp,
    hml.part_code,
    hh.drawing_number,
    hh.quote_date,
    hh.customer_name
FROM dbo.historical_quote_material_line hml
LEFT JOIN dbo.historical_quote_header hh
    ON hml.quote_id = hh.quote_id
WHERE hml.unit_price_gbp IS NOT NULL
  AND hml.unit_price_gbp > 0
  AND UPPER(hml.line_description) LIKE '%' + UPPER(LTRIM(RTRIM(?))) + '%'
ORDER BY
    CASE WHEN hh.quote_date IS NOT NULL THEN 0 ELSE 1 END,
    hh.quote_date DESC,
    COALESCE(hml.line_total_gbp, 0) DESC
""",
        # Supplier catalogue URL + indicative price.
        # Expected params: (material_hint)
        "supplier_catalog_query": """
SELECT TOP 1
    catalog_url,
    material_hint,
    unit_price_gbp,
    sort_order
FROM dbo.estimating_supplier_catalog_url
WHERE UPPER(material_hint) LIKE '%' + UPPER(LTRIM(RTRIM(?))) + '%'
ORDER BY sort_order ASC
""",
        # Historical operation lookup for labour parity.
        # Expected params: (k, normalized_description)
        "historical_operations_query": """
SELECT TOP (?)
    hqo.operation_code,
    hqo.department_code,
    hqo.run_min_per_unit,
    hqo.hourly_rate_gbp,
    hqo.operation_cost_gbp,
    hqo.setup_min,
    hh.drawing_number,
    hh.quote_date
FROM dbo.historical_quote_operation hqo
JOIN dbo.historical_quote_part hqp ON hqo.quote_part_id = hqp.quote_part_id
JOIN dbo.historical_quote_header hh ON hqp.quote_id = hh.quote_id
WHERE UPPER(hqp.normalized_description) LIKE '%' + UPPER(LTRIM(RTRIM(?))) + '%'
  AND hqo.operation_cost_gbp IS NOT NULL
ORDER BY hh.quote_date DESC, hqo.operation_cost_gbp DESC
""",
        # Active now: System Cost Per + bought-in parts lookup from SDILive.
        # UDEF collation Latin1_General_BIN — exact casing required on column names.
        # [Supplier name] is on UDEF directly — no SUP_TBL join needed.
        # WO columns included for parity reporting.
        # Expected params: (part_code, description, part_code, description, part_code)
        "part_system_cost_query": """
SELECT TOP (1) * FROM (
    SELECT
        u.[Part code]      COLLATE Latin1_General_CI_AS AS part_code,
        u.[Description]    COLLATE Latin1_General_CI_AS AS description,
        u.[System cost per]                              AS system_cost_per,
        CAST(u.[System cost per] AS decimal(18,4))       AS price,
        u.[Supplier code]  COLLATE Latin1_General_CI_AS AS supplier_code,
        u.[Supplier name]  COLLATE Latin1_General_CI_AS AS supplier_name,
        'GBP'              AS currency,
        u.[UOM]            COLLATE Latin1_General_CI_AS AS unit,
        0.95               AS confidence,
        GETDATE()          AS price_date,
        0                  AS source_rank,
        u.[WO Est lab cost]     AS wo_est_lab_cost,
        u.[WO Est mat cost]     AS wo_est_mat_cost,
        u.[WO Actual lab cost]  AS wo_actual_lab_cost,
        u.[WO Actual mat cost]  AS wo_actual_mat_cost
    FROM dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING u
    WHERE
        LTRIM(RTRIM(u.[Part code] COLLATE Latin1_General_CI_AS)) = LTRIM(RTRIM(?))
        OR u.[Description] COLLATE Latin1_General_CI_AS LIKE '%' + LTRIM(RTRIM(?)) + '%'
    UNION ALL
    SELECT
        b.part_code        COLLATE Latin1_General_CI_AS,
        b.description      COLLATE Latin1_General_CI_AS,
        b.unit_price_gbp   AS system_cost_per,
        CAST(b.unit_price_gbp AS decimal(18,4)) AS price,
        b.supplier_code    COLLATE Latin1_General_CI_AS,
        b.supplier_name    COLLATE Latin1_General_CI_AS,
        'GBP'              AS currency,
        b.uom              COLLATE Latin1_General_CI_AS AS unit,
        0.93               AS confidence,
        b.effective_date   AS price_date,
        1                  AS source_rank,
        NULL AS wo_est_lab_cost,
        NULL AS wo_est_mat_cost,
        NULL AS wo_actual_lab_cost,
        NULL AS wo_actual_mat_cost
    FROM dbo.bought_in_parts b
    WHERE b.is_active = 1
      AND (
          LTRIM(RTRIM(b.part_code)) = LTRIM(RTRIM(?))
          OR b.description LIKE '%' + LTRIM(RTRIM(?)) + '%'
      )
) combined
ORDER BY
    CASE WHEN LTRIM(RTRIM(combined.part_code)) = LTRIM(RTRIM(?)) THEN 0 ELSE 1 END,
    source_rank,
    combined.price DESC
""",
        # Sargable fast-path: exact part-code seek only, NO description LIKE scan.
        # Tried first in get_part_system_cost; identical TOP(1) result to the full
        # query above whenever a code match exists (code outranks description), but
        # skips the 91k-row scan. Full query used only as fallback on a code miss.
        # Expected params: (part_code, part_code, part_code)
        "part_system_cost_query_by_code": """
SELECT TOP (1) * FROM (
    SELECT
        u.[Part code]      COLLATE Latin1_General_CI_AS AS part_code,
        u.[Description]    COLLATE Latin1_General_CI_AS AS description,
        u.[System cost per]                              AS system_cost_per,
        CAST(u.[System cost per] AS decimal(18,4))       AS price,
        u.[Supplier code]  COLLATE Latin1_General_CI_AS AS supplier_code,
        u.[Supplier name]  COLLATE Latin1_General_CI_AS AS supplier_name,
        'GBP'              AS currency,
        u.[UOM]            COLLATE Latin1_General_CI_AS AS unit,
        0.95               AS confidence,
        GETDATE()          AS price_date,
        0                  AS source_rank,
        u.[WO Est lab cost]     AS wo_est_lab_cost,
        u.[WO Est mat cost]     AS wo_est_mat_cost,
        u.[WO Actual lab cost]  AS wo_actual_lab_cost,
        u.[WO Actual mat cost]  AS wo_actual_mat_cost
    FROM dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING u
    WHERE LTRIM(RTRIM(u.[Part code] COLLATE Latin1_General_CI_AS)) = LTRIM(RTRIM(?))
    UNION ALL
    SELECT
        b.part_code        COLLATE Latin1_General_CI_AS,
        b.description      COLLATE Latin1_General_CI_AS,
        b.unit_price_gbp   AS system_cost_per,
        CAST(b.unit_price_gbp AS decimal(18,4)) AS price,
        b.supplier_code    COLLATE Latin1_General_CI_AS,
        b.supplier_name    COLLATE Latin1_General_CI_AS,
        'GBP'              AS currency,
        b.uom              COLLATE Latin1_General_CI_AS AS unit,
        0.93               AS confidence,
        b.effective_date   AS price_date,
        1                  AS source_rank,
        NULL AS wo_est_lab_cost,
        NULL AS wo_est_mat_cost,
        NULL AS wo_actual_lab_cost,
        NULL AS wo_actual_mat_cost
    FROM dbo.bought_in_parts b
    WHERE b.is_active = 1
      AND LTRIM(RTRIM(b.part_code)) = LTRIM(RTRIM(?))
) combined
ORDER BY
    CASE WHEN LTRIM(RTRIM(combined.part_code)) = LTRIM(RTRIM(?)) THEN 0 ELSE 1 END,
    source_rank,
    combined.price DESC
""",
    },
    "spreadsheet": {
        "enabled": True,
        "template_workbook": str(SPREADSHEETS_DIR / "EmptyEstimating" / "Blank Estimate Sheet 2026.xls"),
    },
    "access": {
        "enabled": False,
        "database_path": "",
        "material_price_query": "",
    },
    "web": {
        "enabled": True,
        # Each source item can be a supplier/catalog row, for example:
        # {"name": "FH Brundle wire mesh", "url": "https://www.fhbrundle.co.uk/mesh/welded-wire-mesh", "material_hint": "WIRE MESH", "unit": "GBP_per_m2"}
        "sources": [],
        "user_agent": "CodexPriceCollector/1.0",
        # Optional LLM helpers for parsing web/catalog pages into numeric prices.
        # API keys are read from environment variables:
        #   XAI_API_KEY   for Grok / xAI SDK
        #   OPENAI_API_KEY for OpenAI
        "llm_provider": "xai",  # "xai", "openai", or "none"
        "xai_model": "grok-4.3",
        "openai_model": "gpt-4.1-mini",
        # When enable_web_ai_fallback is True, call LLM for indicative prices if catalog URLs miss or are absent.
        "llm_market_estimate_fallback": True,
        # Programmatic search before Anthropic web search (requires API keys — not fully free).
        # SerpAPI: SERPAPI_API_KEY — https://serpapi.com (limited free tier, then paid).
        # Google: GOOGLE_CSE_API_KEY + GOOGLE_CSE_CX — 100 queries/day free, then billed.
        "search": {
            "enabled": True,
            "provider": "auto",  # auto | serpapi | google_cse | anthropic | none
            "top_n": 5,
            "max_urls_to_scrape": 3,
            "region": "uk",
            "google_gl": "uk",
            "google_hl": "en",
            "allowed_domains": [
                "fhbrundle.co.uk",
                "essentracomponents.com",
                "rs-online.com",
                "screwfix.com",
                "toolstation.com",
                "metals4u.co.uk",
                "metalssupermarkets.co.uk",
                "acmefix.com",
                "mcmaster.com",
            ],
        },
    },
}

# Optional: when internal DB / spreadsheet return no price, WebPriceConnector can ask an LLM for an indicative
# UK-trade reference (mirrors a human web search). Requires PRICE_SOURCE_CONFIG["web"]["enabled"] True and
# XAI_API_KEY and/or OPENAI_API_KEY. Costs API tokens — enable deliberately (CLI or here).
FALLBACK_PRICING_POLICY = {
    "enable_web_ai_fallback": True,
    "fallback_confidence": 0.65,
    "fallback_confidence_cap": 0.72,
    # ── Bounds so the (valuable) web/LLM fallback can never HANG a run ──────────────
    # The fallback prices bought-ins/non-catalogue parts (needed for a good estimate), but it
    # runs per-part with serial network+LLM calls. Unbounded, a job with many unpriced parts
    # stalls for tens of minutes. These caps keep the pricing while guaranteeing the run finishes:
    #   - a hard wall-clock timeout per part (a slow/blocked call is abandoned -> part flagged),
    #   - a per-job budget (price the first N via fallback; flag the rest 'estimator to confirm'),
    #   - skip rollup/assembly parents (they carry no own price; web-searching them is wasted time).
    #
    # THE BUDGET IS A SAFETY CEILING, NOT A ROUTINE GATE. The policy is that every unpriced real
    # line gets a number — a catalogue rate, else an LLM indication, never a bare zero that reads
    # as free. At 25 a bought-in-heavy pack (8352's stand: castors, clips, graphic, trays, bungs,
    # nutserts, hank bushes) spent the budget on the metal and left everyday hardware at zero. The
    # per-part timeout is what actually bounds the run; the budget only guards a pathological pack,
    # so it is set high enough that a normal pack prices ALL its lines.
    "web_ai_call_timeout_s": 25,
    "max_web_ai_lookups_per_job": 80,
    "skip_rollup_parents": True,
    # SQL query-execution timeout (seconds). The pyodbc CONNECT timeout does not bound a running
    # query, so a slow/locked query on SDILive would hang the whole estimate at 0 CPU. This bounds
    # each query: on overrun it degrades to 'no price' for that part (flagged) and the run finishes.
    "sql_query_timeout_s": 30,
}

# openpyxl cannot save .xls; use an .xlsx copy of the blank estimate for --generate-ai-spreadsheet / write-back.
AI_ESTIMATE_XLSX_TEMPLATE = SPREADSHEETS_DIR / "EmptyEstimating" / "Blank Estimate Sheet 2026.xlsx"

WORKBOOK_EQUIVALENT_PRICING = {
    # overhead_absorption_factor: the divisor in the workbook's M105 formula.
    # =((M59+M103)/(1-M107))/<factor>  — machine downtime, rework, indirect costs.
    #
    # THE TEMPLATE MOVED AND THIS CONSTANT DID NOT. It read 0.92 while the live workbook divides
    # by 0.93, so the engine's workbook-equivalent parity figure disagreed with the sheet it
    # exists to reconcile against — about £0.91 a unit on 7332-01, silently, in the engine's
    # favour. Two runs settle it beyond argument:
    #     05:33  49.87/0.92 = 54.21   49.87/0.93 = 53.62   sheet: 53.62
    #     12:37  77.48/0.92 = 84.22   77.48/0.93 = 83.31   sheet: 83.31
    # The WORKBOOK is authoritative — wep_readback_from_xlsx parses the divisor out of the live
    # formula and reports it ("absorption divisor 0.93 written into the formula"). This value is
    # only the fallback for a path with no workbook to read, so it must track the template.
    "overhead_absorption_factor": 0.93,
    # M107: rebate fraction. TTI default 0.066 (6.6%). Grossed into unit cost before margin.
    "default_m107": 0.066,
    # M109: sell margin fraction. 0.0 in blank template; estimator fills this in.
    # Sell price = M105 / (1 - M109). NOT M105 × (1 + margin%) — workbook uses margin-on-sell.
    "default_m109": 0.0,
    "sell_markup_options_pct": {
        "low": 10.0,
        "standard": 20.0,
        "premium": 35.0,
    },
    # 11-band qty break table — matches Material Price Break sheet columns D4:N4.
    # Thresholds: 1, 10, 25, 50, 100, 250, 500, 600, 700, 800, 900.
    "quantity_breaks": [
        {"min_qty": 1,   "max_qty": 9,    "multiplier": 1.000},
        {"min_qty": 10,  "max_qty": 24,   "multiplier": 0.970},
        {"min_qty": 25,  "max_qty": 49,   "multiplier": 0.960},
        {"min_qty": 50,  "max_qty": 99,   "multiplier": 0.940},
        {"min_qty": 100, "max_qty": 249,  "multiplier": 0.920},
        {"min_qty": 250, "max_qty": 499,  "multiplier": 0.910},
        {"min_qty": 500, "max_qty": 599,  "multiplier": 0.900},
        {"min_qty": 600, "max_qty": 699,  "multiplier": 0.895},
        {"min_qty": 700, "max_qty": 799,  "multiplier": 0.890},
        {"min_qty": 800, "max_qty": 899,  "multiplier": 0.885},
        {"min_qty": 900, "max_qty": None, "multiplier": 0.880},
    ],
    "variance_thresholds_pct": {
        "match": 3.0,
        "warning": 10.0,
    },
}

# Explicit freshness and ranking rules for connector selection.
PRICE_FRESHNESS_RULES = {
    "default_days_fresh": 30,
    "default_days_stale": 120,
    "source_priority": {
        "udef_sqlserver": 110,
        "sqlserver": 100,
        "spreadsheet": 80,
        "access": 60,
        "web": 40,
    },
    # Penalty values are added to a candidate score before sorting; lower is better.
    "freshness_penalty": {
        "fresh": 0.0,
        "stale": 12.0,
        "unknown": 20.0,
    },
}

# PricingService policy (explicit so production runs do not rely on hidden defaults).
# Tuned via calibration / variance reports; see pricing_service._resolve_effective_material_cost.
PRICING_SERVICE_POLICY = {
    # Minimum anchor confidence required to override workbook material cost.
    "anchor_override_min_confidence": 0.90,
    # Material scrap factor used when anchor pricing overrides workbook material.
    "anchor_override_scrap_factor": 1.04,
    # PMA_TBL: PMA_PROC_CODE='P' → PMA_COST_MAT is per-unit purchased material (not per kg).
    # Wired in pricing_service._get_pma_purchased (tier 1.5, after UDEF, before bought_in_parts).
}

# Section / tube stock costing policy for workbook parity gaps.
# SECTION STOCK IS NOT PRICED LIKE SHEET, AND THIS ENGINE HAS BEEN PRICING IT LIKE SHEET.
#
# The section/tube path costs by mass x MATERIAL_PRICE_GBP_PER_KG, which is the flat-product
# rate: GBP 0.80/kg, matching the sheet's own GBP 900/tonne. Small-diameter tube is not sold
# on that basis. A 12.7 x 1.2mm mild steel tube retails around GBP 2.48/m at 0.34 kg/m --
# GBP 7.29/kg, roughly EIGHT TIMES the flat rate. On M&S 2085 that is the difference between
# GBP 0.05 and GBP 0.37 for the two tubes; on a job built from section it is the difference
# between a quote and a loss.
#
# Left as None deliberately. Inventing a rate is how "Salvage / Rework" happened. While it is
# None the engine prices section at the flat rate AND FLAGS EVERY LINE saying so, which is
# visible and wrong rather than invisible and wrong. Set it to the real trade rate -- or to a
# dict keyed by material family -- and the flag goes away.
# AN ASSEMBLY-LEVEL OPERATION HAPPENS ONCE, NOT ONCE PER PART IT TOUCHES.
#
# The workbook sums a per-part quantity across every part a route line names. On M&S 2085
# that charged Weld, Dress Welds and P.Coat at qty 3 across three components -- GBP 6.85 of
# an GBP 11.14 labour figure -- for work done once on one bracket.
#
# Whether that is wrong depends on what the throughput rates MEAN. If Weld's 29/hr is
# assemblies per hour, qty 3 triple-charges. If it is parts welded per hour, qty 3 is right.
# That is an estimator's ruling about their own rate table, not a decision this engine can
# make from a drawing, so the default changes nothing: assembly-scoped rows are FLAGGED with
# both quantities and charged exactly as they are today.
#
# Set True once the rates are confirmed as per-assembly, and a route line the extract marks
# scope="assembly" is charged once per product.
ASSEMBLY_SCOPED_OPS_CHARGE_ONCE = False

# Canonical BOM/route cutover.
#
# On the route-compiler cutover branch the hierarchy-aware OperationDecision graph is the
# authority for which labour rows exist and where they belong. The workbook still owns rates
# and formulas; it no longer unions raw route words back into costed records.
#
# Set SDI_CANONICAL_ROUTE_WORKBOOK=0 for an emergency comparison with the legacy renderer.
# The rollback is explicit and visible in the workbook flags; it is not an automatic fallback
# from a compiler failure, because silently returning to the resurrection path would recreate
# the defect this switch closes.
CANONICAL_ROUTE_WORKBOOK_CUTOVER = (
    str(os.getenv("SDI_CANONICAL_ROUTE_WORKBOOK", "1")).strip().lower()
    not in {"0", "false", "no", "off"}
)

# Section / tube stock is NOT sold at the flat-product £/kg — small thin tube is several times
# dearer per kilo. Left unset, a section falls to the flat rate (~£0.80/kg) and under-reads
# badly: 7332-01-002's 12.7×1.2 leg came out £0.64 against a real ~£7.29/kg. This is an
# INDICATIVE global trade hold (the engine's own cited figure for that tube) so no section ships
# under-read; it is flagged for verify on the line, because one scalar over-reads a LARGE
# section as much as it rescues a small one. Tim replaces it with a size-aware rate/table. May
# also be a dict keyed by UPPER-CASE material name.
SECTION_STOCK_PRICE_GBP_PER_KG = 7.29

SECTION_STOCK_POLICY = {
    "enabled": True,
    # Applied after raw mass*price calculation for cut loss / trim waste.
    "waste_factor_pct": 4.0,
    # Regex-hint tokens to classify section-like bought-in fabricated stock.
    "section_keywords": ["TUBE", "RHS", "SHS", "BOX SECTION", "ANGLE", "CHANNEL", "WIRE MESH"],
}

# --- Spreadsheet parity (Estimate / Material Price Break). Refresh via extract_workbook_constants.py ---
# Default assumed order quantity for unit-cost roll-ups (Estimate!D6).
# Override without code edits: ESTIMATE_DEFAULT_JOB_QUANTITY=400
DEFAULT_JOB_QUANTITY = int(float(os.getenv("ESTIMATE_DEFAULT_JOB_QUANTITY", "180")))

# Global scrap factor as a fraction (4% = 0.04). Used with nesting / anchor policies.
SCRAP_PERCENTAGE = 0.04

# ── FACED BOARD IS BOUGHT BY THE SHEET, NOT BY THE KILO ──────────────────────────────
#
# Every price below is one SDI has actually PAID, read out of the historical corpus built
# from the estimators' own workbooks. Nothing here is a web price or a list price: a list
# price repeats perfectly and commits nobody, and a consumer price for a pre-cut B&Q strip
# is not what this shop buys.
#
# WHAT THE CORPUS SHOWS (src/corpus.jsonl, cost_per_sheet_gbp on MFC046 rows):
#   MFC046 = "Egger H3131 ST12 Natural Davos Oak FSC MFC 2800x2070x19mm sheet"
#     18/19mm   GBP 55.00 (2025, 11641-02 Half Shelf), 58.55 (2024, Mannequin Plinth),
#               61.64 (2024 and 2025, 11141-04 Tiered Riser)   -> median 58.55
#     36mm      GBP 84.54 (2024, 11416-GA Low Level Basket)
#
# Two observed thicknesses of the same board, eighteen months apart, from priced jobs.
# Thickness in between is INTERPOLATED between them — an estimator's own arithmetic on the
# shop's own purchases — and outside them is refused rather than extrapolated, because
# nothing in the history says what a 50mm board costs.
#
# These are indicative and dated, not firm. The price_not_firm invariant already says so on
# every sheet, and it should keep saying so until Tim confirms the current rate.
BOARD_SHEET_PRICE_GBP = {
    # material -> {thickness_mm: GBP per full sheet}
    "MFC":       {18.0: 58.55, 36.0: 84.54},
    # 9mm: £172.00 a 3080x1220 sheet of "MDF laminated both sides" (colour core), Lawcris,
    # stated by Tony Ford in his own estimate for 0359967 (11908-21 Sunglasses Tray,
    # 16 Sep 2026) at the 50-off rate. His sheet carries the supplier's own quantity breaks
    # — 173 / 172 / 168 / 165 / 163 at 1 / 50 / 100 / 250 / 500 — which this table cannot
    # yet hold; the register records them until a per-line supplier-break mechanism exists.
    # CAUTION ON INTERPOLATION: the 9mm point is a PREMIUM colour-core laminate and the
    # 18/36mm points are the Egger Davos Oak MFC — a thickness between 9 and 18 would
    # interpolate DOWNWARD across two different products. The label _board_sheet_rate
    # prints quotes both ends, so a falling curve is visible, INDICATIVE, and Tony's to
    # overrule — but treat any 10-17mm faced-board price from this table with suspicion.
    # The dict form carries the SHEET SIZE the price was paid for: £172 buys a
    # 3080x1220, and dividing it by a 2800x2070's yield would understate every part.
    "MFMDF":     {9.0: {"gbp": 172.00, "sheet_mm": (3080, 1220)},
                  18.0: 58.55, 36.0: 84.54},
    "CHIPBOARD": {18.0: 58.55, 36.0: 84.54},
    # DIBOND / ACM — PROVISIONAL, per full 3050x1500 (4.575 m2) sheet, ~£36/m2 at 3mm and
    # ~£46/m2 at 4mm (mid trade). CONFIRM against SDI's own Dibond buy price and replace these
    # two lines — then every Dibond job prices itself from the real number. Priced by the sheet
    # and nested like any board, so a small panel is charged its share, not a whole sheet.
    "DIBOND":    {3.0: 165.0, 4.0: 210.0},
    "ALUPANEL":  {3.0: 165.0, 4.0: 210.0},
    "REYNOBOND":  {3.0: 165.0, 4.0: 210.0},
    "ETALBOND":  {3.0: 165.0, 4.0: 210.0},
}

# ── WHAT EACH CUSTOMER'S SHEET CHARGES ON TOP, BY NAME ───────────────────────────────
#
# The Estimate's own totals formula is  M170 = ((material + labour)/(100% − M172)) / 0.93
# — M172 is the customer REBATE and the trailing divisor is the overhead ABSORPTION. The
# blank template ships with rebate 0 and /0.93, and nothing ever set them, so every M&S
# job went out missing the 1.8% uplift the office applies and using the wrong divisor.
#
# The table below is the office's own, read off Tony Ford's estimate for 0359967
# (11908-21, 16 Sep 2026), whose Labour tab prints it verbatim:
#
#     "All Except M&S /0.93 · Tesco - 2.7% /0.93 · TTI - 6.6% /0.93
#      · M&S - 1.8% /0.92 · Boots 2.7% /0.93"
#
# These are COMMERCIAL TERMS, not prices: which fraction a customer contract rebates and
# which absorption the office books against it. They change when contracts change, so
# they live here with their source, and an estimator's own typed rebate on the sheet is
# never overwritten.
CUSTOMER_COMMERCIAL_TERMS = {
    "M&S":             {"rebate_fraction": 0.018, "absorption_divisor": 0.92},
    "MARKS & SPENCER": {"rebate_fraction": 0.018, "absorption_divisor": 0.92},
    "MARKS AND SPENCER": {"rebate_fraction": 0.018, "absorption_divisor": 0.92},
    "TESCO":           {"rebate_fraction": 0.027, "absorption_divisor": 0.93},
    "TTI":             {"rebate_fraction": 0.066, "absorption_divisor": 0.93},
    "BOOTS":           {"rebate_fraction": 0.027, "absorption_divisor": 0.93},
}


def customer_commercial_terms(customer):
    """The stated terms for this customer name, or None. Matched on the normalised name —
    "M&S", "M and S Ltd" and "Marks & Spencer PLC" are one customer — and NEVER guessed:
    an unlisted customer gets the template's own defaults, not the nearest neighbour's."""
    import re as _re
    text = str(customer or "").upper().replace(".", "").strip()
    if not text:
        return None
    squashed = text.replace(" AND ", " & ")
    for name, terms in CUSTOMER_COMMERCIAL_TERMS.items():
        # Bounded, so TTI never matches inside another word — a rebate applied to the
        # wrong customer is worse than the default it replaced.
        if _re.search(rf"(?<![A-Z0-9]){_re.escape(name)}(?![A-Z0-9])", squashed):
            return dict(terms, customer=name)
    return None


# A6: any "thickness" above this (mm) is treated as a dimension misparse and rejected.
MAX_SHEET_THICKNESS_MM = 25.0
# A BOARD IS NOT A GAUGE, AND THE CEILING HAS TO KNOW WHICH IT IS LOOKING AT.
#
# The bound above exists to stop a product LENGTH being read as a thickness — "Left Arm
# 200mm_flat.dxf" came back as a 200mm steel gauge. 25mm is generous for sheet metal and
# simply wrong for board: shop-fitting board runs 18/22/25/28/30 and beyond, and 12422-24's
# MFC end cap panel is 28mm.
#
# The ceiling lives here, not in the module that first needed it. drawing_job_merge widened
# its own filename bound for board and estimator kept a hard 25.0 in three places, so a
# genuine "28MM_MFC" filename was read by one module and thrown away by the next — the same
# shape as the MFC vocabulary being in four modules and missing from the authoritative one.
MAX_BOARD_THICKNESS_MM = 75.0

# THE BOARD FAMILIES, IN ONE PLACE.
#
# Four modules carried their own answer to "is this board?" — wb_populate._is_board,
# _TIMBER_TOKENS, estimator's thickness tokens and the SolidWorks connector's family table —
# and the faced-board family was missing from three of them at different times. Each gap cost
# a different thing: a refused 28mm gauge, a melamine panel measured against a sheet-metal
# bound, and a chipboard sheet resolving to MDF.
#
# SHEET board and SOLID timber are separate because their thickness FLOORS differ (3mm MDF is
# a stocked item; a 3mm pine panel is not), and both are separate from the faced family
# because the facing changes the price and the machining, not the substrate.
FACED_BOARD_TOKENS = ("MFC", "MFMDF", "MELAMINE", "PRE LAM", "PRELAM", "PRE-LAM")
SHEET_BOARD_TOKENS = ("MDF", "PLYWOOD", "PLY", "CHIPBOARD", "OSB", "HARDBOARD")
SOLID_TIMBER_TOKENS = ("TIMBER", "WOOD", "PINE", "SOFTWOOD", "HARDWOOD", "OAK",
                       "SPRUCE", "BEECH", "BIRCH", "REDWOOD", "WHITEWOOD", "ASH")
# Thinnest stock we will accept as a real thickness on a joinery part. Below this the value
# is tolerance-table text, not a gauge (0.5mm "TIMBER" reached the Horti Crate sheet this
# way). Metal is unaffected — 0.5mm sheet steel is ordinary stock.
#
# Two floors, because the stock differs: sheet board is made thin (3mm MDF and 3mm ply are
# stocked items), solid timber is not — nobody machines a 3mm pine panel, the thinnest
# practical section is around 6mm. A single floor either lets solid-timber noise through or
# rejects real thin board. Tune to what SDI actually buys.
MIN_BOARD_THICKNESS_MM = 3.0          # MDF / plywood / chipboard / OSB — sheet goods
MIN_SOLID_TIMBER_THICKNESS_MM = 6.0   # pine / oak / spruce etc — solid section

# A7: filenames matching these (case-insensitive substring) are NOT part drawings —
# setup/route/manufacturing-order sheets that must never be ingested as parts.
EXCLUDE_DOC_FILENAME_PATTERNS = [
    "SETUPPLAN", "SETUP PLAN", "SETUP_PLAN",
    "MANUFACTURING ORDER", "MANUFACTURING_ORDER", "MO SHEET",
    "ROUTE CARD", "ROUTE_CARD", "ROUTE IMPORT", "ROUTING SHEET",
    "WORKS ORDER", "JOB CARD",
]

# Mild steel: kg/m² per mm thickness (7850 kg/m³ × thickness_m).
MILD_STEEL_DENSITY_KG_PER_MM_M2 = 7.85

# Material Price Break sheet column semantics (D4:N4 style layout).
MATERIAL_PRICE_BREAK_HEADERS = {
    "gauge": "Gauge",
    "thickness_mm": "Thickness mm",
    "sheet_type": "Sheet Type",
    "material_grade": "Material Grade",
    "price_per_tonne": "Price per Tonne (£)",
    "price_date": "Price Date",
    "supplier": "Supplier",
    "currency": "Currency",
    "notes": "Notes",
    "effective_from": "Effective From",
    "scrap_override": "Scrap % Override",
}

# Manual Estimate-tab inputs (override via env or extract_workbook_constants.py).
WORKBOOK_INPUT_DEFAULTS = {
    "default_job_quantity": DEFAULT_JOB_QUANTITY,
    # L3 in workbook: Wire Cost Per Tonne. Blank sheet = £1600. Override via env or workbook scan.
    "wire_cost_per_tonne_gbp": float(os.getenv("WORKBOOK_WIRE_COST_PER_TONNE_GBP", "1500.0")),  # SDI rate £1500/tonne
    # L5 in workbook: Sheet Steel Cost Per Tonne. Blank sheet = £900. Override via env or workbook scan.
    "sheet_steel_cost_per_tonne_gbp": float(os.getenv("WORKBOOK_SHEET_STEEL_COST_PER_TONNE_GBP", "950.0")),  # F: Tim rate £950/tonne
    "scrap_pct": SCRAP_PERCENTAGE * 100.0,
}

# Wire gauge lookup table — workbook rows 151-159: H=gauge_mm, I=metres_per_tonne.
# Used by estimate_material() wire path: price_per_metre = wire_£_per_tonne / metres_per_tonne.
WIRE_GAUGE_TABLE = {
    2.0:  40550.0,
    2.5:  25950.0,
    3.0:  18020.0,
    4.0:  10140.0,
    4.5:   8010.0,
    5.0:   6488.0,
    6.0:   4505.0,
    8.0:   2534.0,
    10.0:  1622.0,
}

# Powder: material (kg = coated_m² / coverage) + labour (see LABOUR_RULES["powder_coating"]).
# Typical standard epoxy-polyester £8–12/kg; metallics / effects often £14–18/kg — see special_finish_keywords.
# Calibrate throughput_m2_per_hour (LABOUR_RULES) from one works order: booth_hours / coated_m².
# Punch vs laser recognition. Derived from the 2023 manual-estimate corpus
# (3,055 records): peg panels punch at 5.9x baseline lift, slot/perf/mesh ~2-3x;
# brackets/uprights/bases show no lift (stay laser). A dense field of holes is
# uneconomic to laser-pierce and is the punch-press's job.
PUNCH_RECOGNITION = {
    "enabled": True,
    # Hole-count alone is enough above this threshold (e.g. a 386-hole peg panel).
    "min_holes_for_punch": int(os.getenv("PUNCH_MIN_HOLES", "40")),
    # Corpus-validated descriptive terms; require a modest hole count alongside.
    "punch_keywords": ["PEG", "SLOT", "PERFORAT", "PERF", "MESH", "GRILLE", "VENT"],
    "min_holes_with_keyword": int(os.getenv("PUNCH_MIN_HOLES_KEYWORD", "8")),
}

POWDER_COSTING_POLICY = {
    "enabled": True,
    # Workbook AB:AC:AD formula (cols AB-AD, rows 38-48):
    #   AB = (part_length_m × part_width_m) × 2   [both faces, m²]
    #   AC = 6 / AB                                [qty per kg — coverage = 6 m²/kg hard-coded]
    #   AD = (1/AC) × qty_per_unit                 [kg of powder per unit]
    # Simplified: powder_kg_per_unit = (blank_area_m2 × 2) / 6
    "coverage_m2_per_kg": 6.0,
    "kg_per_m2": round(1.0 / 6.0, 6),   # = 0.166667 — inverse of coverage
    # Total blank face area multiplier (2.0 = both sides, matching workbook × 2 in AB formula).
    "coated_faces_multiplier": 2.0,
    "single_face_keywords": [
        "SINGLE FACE",
        "SINGLE-FACE",
        "EXTERNAL ONLY",
        "VISIBLE FACE ONLY",
        "ONE SIDE",
        "ONE SIDE ONLY",
        "OUTSIDE FACE ONLY",
    ],
    "coated_faces_multiplier_single_face": 1.0,
    # When only visible exterior + lip / partial second surface (e.g. channel outer spec).
    "partial_exterior_keywords": [
        "VISIBLE FACE AND LIP",
        "EXTERNAL AND FLANGE",
        "OUTSIDE ONLY PLUS EDGE",
    ],
    "coated_faces_multiplier_partial_exterior": 1.3,
    # Approximate strip width (mm) along bend lines for extra coated area.
    "bend_coating_strip_mm": 40.0,
    "powder_material_gbp_per_kg": float(os.getenv("POWDER_MATERIAL_GBP_PER_KG", "4.0")),  # £4/kg standard powder, confirmed by estimating (Tim, POWDER5 on job 1282). Was 12.5 (~3x too high).
    # WHO SAYS SO, IN A FIELD AND NOT A COMMENT. "Where did the price come from for Powder
    # (Per Kilo)?" was the estimator's first question, about a line that stated its area and
    # not its rate — and the rate's provenance existed only here, in a comment no sheet can
    # read. A figure whose source cannot travel with it reads as invented, however well
    # evidenced it is. The BOM line prints this.
    "powder_material_gbp_per_kg_source": os.getenv(
        "POWDER_MATERIAL_GBP_PER_KG_SOURCE",
        "SDI standard powder rate, confirmed by estimating — POWDER5, job 1282"),
    "special_finish_keywords": [
        "METALLIC",
        "PEARLESCENT",
        "TEXTURED",
        "WRINKLE",
        "HAMMER",
        "ANTIQUE",
    ],
    "powder_material_gbp_per_kg_special": float(os.getenv("POWDER_MATERIAL_SPECIAL_GBP_PER_KG", "16.0")),  # Metallic/textured/wrinkle specials
    # Include global SCRAP_PERCENTAGE on powder kg (overspray); sheet scrap handled separately.
    "apply_global_scrap_to_powder_kg": True,
}

# When True, JSON/API outputs emphasize manufacturing cost; omit sales sell-price uplift from summary.
OUTPUT_MANUFACTURING_COST_ONLY = os.getenv("OUTPUT_MANUFACTURING_COST_ONLY", "1").lower() in {"1", "true", "yes"}

# Human-facing label for costing rule sets; bumped when defaults materially change. Emitted on every estimate JSON.
ESTIMATE_POLICY_VERSION = (os.getenv("ESTIMATE_POLICY_VERSION", "1.1.0").strip() or "1.1.0")

# Standard enquiry quantity breaks — used when presenting JSON-only quantity ladders (parity exports include these).
JOB_QUOTE_QUANTITY_BREAKS = [1, 2, 4, 6, 10, 20, 30, 40, 50]

# Full workbook ↔ JSON parity (see estimate_full_parity_report.build_full_parity_report).
ESTIMATE_FULL_PARITY = {
    "estimate_sheet_name": "Estimate",
    "labour_route_row_start": 117,
    "labour_route_row_end": 148,
    # When True (and labour_row_start/end are not passed to build_full_parity_report), find SDI codes in column B.
    "labour_route_discover": True,
    "labour_route_pad_rows": 2,
    "labour_route_operation_column": "B",
    # Route & BOM sheets often put qty breaks in B; scan these columns for LASM/FOLD/…
    "labour_route_scan_columns": ["B", "C", "D", "E", "A", "I"],
    "quantity_break_rows_start": 115,
    "quantity_break_rows_end": 125,
    # Optional overrides for money_cells: list of {"cell","path","label"} — omit to use sheet discovery + quantity cell.
    "money_cells": None,
}

# Label-scan discovery for Estimate totals (rows move when the BOM block grows).
# Rules are evaluated in order; ``match_policy`` ``last`` prefers the lowest matching row (typical rollup).
ESTIMATE_SHEET_TOTAL_DISCOVERY = {
    "enabled": True,
    "row_min": 1,
    "row_max": 320,
    "label_columns": ["I", "J", "K", "L"],
    "match_policy": "last",
    # If a rule matches no row, optionally fill that path from ESTIMATE_TEMPLATE_WRITEBACK.output_cells when set.
    "merge_static_fallback": True,
    # If discovery finds no cells at all, use the full static output_cells map (set False to surface gaps only).
    "use_static_when_empty": False,
    "rules": [
        {
            # M59 — all material sections sum into col M only. L59 is empty.
            "summary_path": "estimate_summary.workbook_equivalent_pricing.m59_material_subtotal_gbp",
            "label_regex": r"(?is).*(?:material|sheet|plate|bought[\s-]*in|boughtins).*(?:sub\s*total|subtotal)|(?:sub\s*total|subtotal).{0,48}(?:material|bought)",
            "value_columns": ["M"],
        },
        {
            # M103 — labour route totals sum into col M only. L103 is empty.
            "summary_path": "estimate_summary.workbook_equivalent_pricing.m103_labour_subtotal_gbp",
            "label_regex": r"(?is).*(?:labou?r|labor|operations?).*(?:sub\s*total|subtotal)|(?:sub\s*total|subtotal).{0,48}(?:labou?r|operations?)|production\s*time.{0,40}(?:sub\s*total|subtotal|total)",
            "value_columns": ["M"],
        },
        {
            # M105 — total unit cost price. Only in col M; L105 is empty.
            "summary_path": "estimate_summary.workbook_equivalent_pricing.l105_total_unit_cost_gbp",
            "label_regex": r"(?is).*(?:total\s*unit\s*cost|unit\s*cost\s*price|manufacturing\s*cost)",
            "value_columns": ["M"],
        },
        {
            # M105 duplicate path for legacy compatibility
            "summary_path": "estimate_summary.workbook_equivalent_pricing.m105_total_unit_cost_gbp",
            "label_regex": r"(?is).*(?:total\s*unit\s*cost|unit\s*cost\s*price|manufacturing\s*cost)",
            "value_columns": ["M"],
        },
        {
            # M111 — sell price. Only in col M; L111 is empty.
            "summary_path": "estimate_summary.workbook_equivalent_pricing.l111_sell_price_gbp",
            "label_regex": r"(?is).*(?:sell(?:ing)?\s*price|sell\s*price)",
            "value_columns": ["M"],
        },
    ],
}

# Reference job quantity cell (parity uses this vs JSON assumed quantity).
ESTIMATE_QUANTITY_CELL_DISCOVERY = {
    "enabled": True,
    "default_cell": "D6",
    "row_min": 1,
    "row_max": 50,
    "label_columns": ["A", "B", "C", "D", "E", "F"],
    "label_regex": r"(?is)\b(?:qty|quantity|parts\s*per\s*assembly|assembly\s*qty|order\s*qty)\b",
    "value_column_preference": ["D", "E", "G"],
}

# Manual £/tonne rows on the Estimate tab (labels in I:K, values often in L) — read at estimate time, not hardcoded L3/L5.
ESTIMATE_WORKBOOK_RATE_DISCOVERY = {
    "enabled": True,
    "row_min": 1,
    "row_max": 35,
    "label_columns": ["I", "J", "K"],
    "match_policy": "first",
    "rates": [
        {
            "key": "wire_cost_per_tonne_gbp",
            "label_regex": r"(?is)\bwire\b",
            "value_column": "L",
        },
        {
            "key": "sheet_steel_cost_per_tonne_gbp",
            "label_regex": r"(?is)(?:sheet|plate).{0,24}(?:steel|tonne|ton)|(?:steel|sheet).{0,20}(?:\/|per)\s*tonne",
            "value_column": "L",
        },
    ],
}

# Estimate route codes (Estimate ~B117:B148) ↔ internal LABOUR_RULES keys in estimator.
SDI_OPERATION_CODES = [
    {"code": "LASM", "title": "Laser Metal", "internal_estimator_op": "laser_cutting"},
    {"code": "FOLD", "title": "Folding / Press Brake", "internal_estimator_op": "folding"},
    {"code": "SPOT", "title": "Spot Welding", "internal_estimator_op": None},
    {"code": "WELD", "title": "Welding (MIG/TIG)", "internal_estimator_op": "welding"},
    {"code": "PC", "title": "Powder Coating (line)", "internal_estimator_op": "powder_coating"},
    {"code": "P/C", "title": "Powder Coating (line)", "internal_estimator_op": "powder_coating"},
    {"code": "SPRY", "title": "Spray / Wet Paint", "internal_estimator_op": "wet_spray"},
    {"code": "CNCJ", "title": "CNC / Joinery machining", "internal_estimator_op": "cnc"},
    {"code": "BENC", "title": "Bench work / fitting", "internal_estimator_op": "bench_work"},
    {"code": "PACP", "title": "Packaging – Carton", "internal_estimator_op": None},
    {"code": "PACM", "title": "Packaging – Manual / Assembly", "internal_estimator_op": "assembly"},
    {"code": "HAND", "title": "Handling / Logistics", "internal_estimator_op": "handling"},
    {"code": "MANM", "title": "Manual handling / assembly", "internal_estimator_op": "handling"},
    {"code": "DRIL", "title": "Drilling / Tapping", "internal_estimator_op": "drilling"},
    {"code": "COUN", "title": "Countersink", "internal_estimator_op": "countersinking"},
    {"code": "TAP", "title": "Tapping", "internal_estimator_op": "tapping"},
    {"code": "GRIN", "title": "Grinding / Deburr", "internal_estimator_op": None},
    {"code": "DPOL", "title": "Diamond Polish", "internal_estimator_op": "diamond_polish"},
    {"code": "GLUE", "title": "Gluing / Bonding", "internal_estimator_op": "glue"},
]

# Labour route parity columns (~K–O) — documentation + future extractors.

ESTIMATE_LABOUR_ROUTE_COLUMNS = {
    "B": "operation_code",
    "K": "setup_hours",
    "L": "run_hours",
    "M": "total_hours",
    "N": "hourly_rate_gbp",
    "O": "line_cost_gbp",
}

# Map config keys to workbook locations for the next reverse-engineer pass.
WORKBOOK_SOURCE_MAP = {
    "default_job_quantity": {"sheet": "Estimate", "cell": "D6", "notes": "Typical location; live scans use ESTIMATE_QUANTITY_CELL_DISCOVERY + read_estimate_workbook_inputs"},
    "wire_cost_per_tonne_gbp": {"sheet": "Estimate", "cell": "L3", "notes": "Manual wire £/tonne"},
    "sheet_steel_cost_per_tonne_gbp": {"sheet": "Estimate", "cell": "L5", "notes": "Manual sheet steel £/tonne"},
    "material_price_break_headers_row": {"sheet": "Material Price Break", "row": 4, "cols": "D:N"},
    "ignored_sales_markup": {"cells": ["M109", "M111"], "notes": "Sales markup — excluded from manufacturing-only output"},
}

# Rounding policy:
# - final_total_only: preserve precision through lines; round final rollups/output fields.
# - per_line: round line-level costs before aggregation.
# - per_section: round material/labour section totals before document total.
ROUNDING_POLICY = {
    "mode": "final_total_only",
    "money_decimals": 2,
}

# Cells kept for historical parity context but excluded from manufacturing-cost output.
WORKBOOK_IGNORED_MARKUP_CELLS = ["M109", "M111"]

# Write-back uses ``estimate_sheet_discovery`` on the template (see ESTIMATE_SHEET_TOTAL_DISCOVERY).
# Optional static cell map used only when discovery sets ``merge_static_fallback`` / ``use_static_when_empty``.
ESTIMATE_TEMPLATE_WRITEBACK = {
    "output_cells": {},
}

# BOM + labour line export (AI side complete; manual columns reserved for workbook / ERP bridge).
BOM_COMPARISON_COLUMNS = [
    "part_number",
    "description",
    "quantity",
    "ai_material",
    "ai_thickness_mm",
    "ai_bought_in_flag",
    "ai_material_cost_gbp",
    "ai_labour_cost_gbp",
    "ai_total_cost_gbp",
    "manual_material_cost_gbp",
    "manual_labour_cost_gbp",
    "manual_total_cost_gbp",
    "variance_pct",
    "operations",
    "notes",
]


def ensure_directories() -> None:
    for path in [
        DRAWINGS_DIR,
        SPREADSHEETS_DIR,
        HISTORY_DIR,
        OUTPUT_DIR,
        JSON_DIR,
        LOG_DIR,
        TEXT_DIR,
        CSV_DIR,
        SQL_DIR,
        PAGE_IMAGES_DIR,
        HISTORY_JSON_DIR,
        HISTORY_CSV_DIR,
        ARCHIVE_DIR,
        ARCHIVE_JSON_DIR,
        ARCHIVE_TEXT_DIR,
        ARCHIVE_LOG_DIR,
        ARCHIVE_CSV_DIR,
        ARCHIVE_SQL_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)


def get_connection(timeout: int = 30):
    """SDILive (SQL Server) connection for the ingest / maintenance tools.

    The tim_*_ingest.py tools call config.get_connection() with --write-db, but this
    helper never existed — so every --write-db silently skipped with
    "module 'config' has no attribute 'get_connection'", writing JSON/SQL but never
    landing the figures in the database the engine reads. This mirrors
    PricingService._get_db_connection so the tools write to the same place.

    pyodbc is imported lazily so config stays importable in contexts without it,
    and the call RAISES on failure rather than silently skipping — a write you think
    happened but didn't is worse than a loud error.
    """
    import pyodbc
    require_db_password()
    c = PRICE_SOURCE_CONFIG.get("sqlserver", {})
    conn_str = (
        f"DRIVER={{{c.get('driver', 'ODBC Driver 18 for SQL Server')}}};"
        f"SERVER={c.get('server')};DATABASE={c.get('database')};"
        f"UID={c.get('username')};PWD={c.get('password')};"
        "Encrypt=yes;TrustServerCertificate=yes;"
    )
    _conn = pyodbc.connect(conn_str, timeout=timeout)   # login/connect timeout
    # QUERY-execution timeout — the connect timeout does NOT bound a running query. This shared
    # connection is used by the tube-catalogue lookup, board-rate resolver and drawing-facts; a
    # slow/locked query on any of them would hang the whole estimate at 0 CPU. Bound query
    # execution so it raises (caller degrades to no-match) instead of blocking forever.
    try:
        _qt = int((FALLBACK_PRICING_POLICY or {}).get("sql_query_timeout_s", 30))
        _conn.timeout = _qt
    except Exception:
        pass
    return _conn

# ── Powder coating material rate ────────────────────────────────────────────
# £ per kg of powder. The Estimate workbook computes powder MATERIAL kg per part
# from geometry (area -> 6 m2/kg coverage -> kg), sums it (AD57 'Total Powder Per
# Unit'), and multiplies by this rate (cell AF57) into the material total M67.
# THIS SAID IT WAS THE SINGLE SOURCE OF TRUTH AND WAS THE SECOND OF TWO.
#
# POWDER_COSTING_POLICY["powder_material_gbp_per_kg"] is the other, and they disagreed by
# 2.4x: the estimator costed powder at GBP 4.00/kg and the workbook charged GBP 9.73/kg for
# the same powder on the same part. Two records of one fact, each calling itself the rate.
#
# The evidence is all on one side. The policy's own note says "GBP 4/kg standard powder,
# confirmed by estimating (Tim, POWDER5 on job 1282)". THIS constant's own note said it was
# "reconciled to ~GBP 4/kg" while holding 9.73 — a comment contradicting the value beneath it.
# And Tim's 12349-02 sheet buys POWDER40 at GBP 3.48/kg. Nothing anywhere evidences 9.73.
#
# What it cost: 12349-02's powder came out at GBP 2.14 against Tim's GBP 0.72. At the policy
# rate the same calculation gives GBP 0.88, and the rest of that gap is the quantity and the
# area, both fixed separately. Every powder-coated job carried the same 2.4x.
#
# ONE NUMBER NOW, and it is the policy's — the one with a name against it. Change it there
# and both the estimator and the workbook move together, which is the property that was
# missing. POWDER_MATERIAL_GBP_PER_KG in the environment still overrides it.
POWDER_COST_PER_KG = float(
    POWDER_COSTING_POLICY.get("powder_material_gbp_per_kg") or 4.0)


# ── POWDER COVERAGE ─────────────────────────────────────────────────────────────
# Kilograms of powder per square metre of coated surface.
#
# The Excel template's Powder Qty Calculator uses 6 m2 per kilo = 0.1667 kg/m2. That is
# 100% TRANSFER EFFICIENCY — every particle lands on the part. Nothing coats at 100%.
#
# What the manual sheets actually book:
#
#     1298  bracket      0.45 kg/m2      2.7x the template
#     1310  hook plate   0.82 kg/m2      4.9x     <- we shipped 1310 5x under on 2026-07-13
#     7670  wire frame   1.70 kg/m2     10.2x     <- open frame: most of the cloud misses
#     template           0.167 kg/m2     1x
#
# The rate rises as the part gets more OPEN. That is real transfer loss, and it means this
# constant is wrong on EVERY job — not just wire.
#
# LEFT AT THE TEMPLATE'S VALUE ON PURPOSE. Setting it to 1.70 would put 7670 exactly on
# Tim's number, but that is fitting to a single data point and the next wire job would be
# wrong invisibly. powder_rule_v2.sql (query 5) measures it across the corpus. Set it from
# that, and it corrects every job at once.
# ASSUMPTION (2026-07-14) — estimator to confirm; see POWDER_MIN_KG_PER_PIECE below.
#
# The template's own calculator uses 0.1667 kg/m2 = 6 m2 per kilo = 100% TRANSFER
# EFFICIENCY. Nothing coats at 100%: most of the cloud misses the part and falls in the
# booth.
#
# A powder film is ~70 microns at ~1.5 g/cm3, so ~0.105 kg/m2 lands ON the part. At a
# realistic ~50% transfer efficiency you CONSUME ~0.20 kg/m2. That is a derivation from
# the physics, not a fit to our benchmark sheets.
POWDER_KG_PER_M2 = 0.20

# ASSUMPTION (2026-07-14) — estimator to confirm.
#
# Tim's sheets do not behave like a coverage model:
#     1298 bracket     0.025 kg
#     1310 hook plate  0.030 kg   (area 0.039 m2 -> implies 0.76 kg/m2)
#     7670 wire frame  0.040 kg   (area 0.023 m2 -> implies 1.70 kg/m2)
# The parts get SMALLER as the powder goes UP. That is backwards for coverage — so he is
# not computing from area on small parts. He is booking a nominal MINIMUM per piece.
#
# Which is right: you cannot coat a 40mm hook with six grams of powder. The gun does not
# care how small the part is, and there is overspray, sweep and colour-change loss on
# every piece regardless of its size.
#
# So:   powder_kg = max( area x POWDER_KG_PER_M2 , pieces x POWDER_MIN_KG_PER_PIECE )
#
# On a small part the floor binds and we land on Tim (1310: 0.030 kg, GBP 0.30, exact).
# On a big part the area term takes over and the floor never binds (1282: 1.09 kg) — which
# is why a floor is safe where a fitted coverage constant would NOT have been. Fitting
# 0.8 kg/m2 to the small parts would have put GBP 42 of powder on one wall bay.
POWDER_MIN_KG_PER_PIECE = 0.03

# Size-banded throughput (pieces/hour). Medians MEASURED 2026-07-14 from 1,982 historical jobs
# (throughput recovered from raw_line_json $.J.labels.left), banded by product size. Fold,
# measured the same way, matched the estimator to 4% (93.76 vs 90), so the measurement holds.
#
# ONLY operations where SIZE is genuinely the driver belong here. Fold/Laser are derived from
# the drawing/template and must not be banded; Robomac (driver: wire length + bends) and Weld
# (driver: weld count, on no drawing) are not size-driven and are deliberately absent.
#
# KEYED ON PART AREA, not job cost: area is known when the labour block runs; unit cost is an
# unresolved workbook formula at that point. Boundaries reproduce the original cost bands and
# are confirmed against known parts (1310 hook 0.019 m2 -> A; 1282 bay panel 0.30 m2 -> D).
THROUGHPUT_SIZE_BANDS = {
    "Assemble/pack (Metal)":   {"A": 90, "B": 30, "C": 20, "D": 15},
    "Assemble/pack (Acrylic)": {"A": 90, "B": 30, "C": 20, "D": 15},
    "P.Coat":                  {"A": 638, "B": 319, "C": 319, "D": 319},
}
# m2 boundaries: A < 0.05 <= B < 0.15 <= C < 0.40 <= D
THROUGHPUT_AREA_EDGES = (0.05, 0.15, 0.40)
