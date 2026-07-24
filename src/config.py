import os
from pathlib import Path

# Canonical hand-edited source for this project lives in this repo's `src/`.
# After changes here, copy/sync the same files to your runtime tree (e.g. C:\ClaudeVision\src) before running scans.

BASE_DIR = Path(__file__).resolve().parents[1]
INPUT_DIR = BASE_DIR / "input"
DRAWINGS_DIR = INPUT_DIR / "drawings"
SPREADSHEETS_DIR = INPUT_DIR / "spreadsheets"
HISTORY_DIR = INPUT_DIR / "history"

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

# PDF GA + flat DXF per part: DXF augments geometry on the PDF scan JSON (see drawing_job_merge.py).
DRAWING_JOB_DISCOVERY = {
    "enabled": True,
    "auto_discover_on_pdf_scan": True,
    "exclude_flat_dxf_from_batch": True,
    "dxf_subdir": "DXF",
    # All DXFs in job folder — GA sheets filtered by is_ignored_ga_dxf()
    "flat_dxf_glob": "*.[Dd][Xx][Ff]",
    "ignore_dxf_name_tokens": ["-GA_", "_GA_", "-GA.", "_GA."],
    "part_number_from_dxf_patterns": [
        # 2–3 digit suffix, optional letter  e.g. 9376-01-001  12242-01-01M  11367-09-08A
        r"(?P<pn>\d{4,5}-\d{2}-\d{2,3}[A-Z]?)",
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

PART_NUMBER_PATTERN = r"\b(?:\d{4,5}[A-Z]?|[A-Z]{1,6}\d{0,4}|FIXING\d*)(?:-[A-Z0-9_]{1,12}|\s-\s[A-Z0-9_]{1,12}){1,4}\b"
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

MATERIAL_PATTERN = r"\b(MILD\s+STEEL|STAINLESS\s+STEEL|ALUMINIUM|ALUMINUM|ALU|ZINTEC|GALVANISED\s+STEEL|GALVANIZED\s+STEEL|TIMBER|WOOD|MDF|PLYWOOD|SOFTWOOD|HIGH\s+IMPACT\s+ACRYLIC|ACRYLIC|PERSPEX|POLYCARBONATE)\b"
FINISH_PATTERN = r"(?:SURFACE\s+FINISH|FINISH)\s*[:\-]?\s*([A-Z0-9\s\-\[\]/,]+)"
COLOUR_PATTERN = r"(?:COLOUR|COLOR)\s*[:\-]?\s*([A-Z0-9\s\-,\[\]/]+)"
WEIGHT_PATTERN = r"WEIGHT\s*[:\-]?\s*([0-9.]+\s*(?:KG|kg|g|G))"
QUANTITY_PATTERN = r"\b(?:QTY|QUANTITY)\s*[:\-]?\s*(\d+)\b"
THICKNESS_PATTERN = r"\b(?:THK|THICKNESS|GAUGE)\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*(?:MM|mm)?\b"

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
MIRROR_PATTERN = r"\bMIRROR(?:ED)?\b"
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
    # Timber-based sheet materials — standard UK board sizes
    "MDF": [(2440, 1220), (3050, 1525)],
    "MDF_BOARD": [(2440, 1220), (3050, 1525)],
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
    "min_per_linebend": 1.0,                  # FRONT/TOP/BACK 2 bends -> 30 parts/hr
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
    "tube_bend": 32.84,              # TBEN
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

PRICE_SOURCE_PRIORITY = [
    "udef_sqlserver",
    "sqlserver",
    "spreadsheet",
    "access",
    "web",
]

PRICE_SOURCE_CONFIG = {
    "udef_sqlserver": {
        "enabled": True,
        "server": "10.0.0.200",
        "database": "SDILive",
        "username": "AIBot",
        "password": "AIAgentPW2026",
        "driver": "ODBC Driver 18 for SQL Server",
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
    },
    "sqlserver": {
        "enabled": True,
        "server": "10.0.0.200",
        "database": "SDILive",
        "username": "AIBot",
        "password": "AIAgentPW2026",
        "driver": "ODBC Driver 18 for SQL Server",
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
    "web_ai_call_timeout_s": 25,
    "max_web_ai_lookups_per_job": 25,
    "skip_rollup_parents": True,
}

# openpyxl cannot save .xls; use an .xlsx copy of the blank estimate for --generate-ai-spreadsheet / write-back.
AI_ESTIMATE_XLSX_TEMPLATE = SPREADSHEETS_DIR / "EmptyEstimating" / "Blank Estimate Sheet 2026.xlsx"

WORKBOOK_EQUIVALENT_PRICING = {
    # overhead_absorption_factor: the hard-coded 0.92 divisor in workbook M105 formula.
    # =((M59+M103)/(1-M107))/0.92  — covers machine downtime, rework, indirect costs (~8.7% uplift).
    "overhead_absorption_factor": 0.92,
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

# A6: any "thickness" above this (mm) is treated as a dimension misparse and rejected.
MAX_SHEET_THICKNESS_MM = 25.0

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
    c = PRICE_SOURCE_CONFIG.get("sqlserver", {})
    conn_str = (
        f"DRIVER={{{c.get('driver', 'ODBC Driver 18 for SQL Server')}}};"
        f"SERVER={c.get('server')};DATABASE={c.get('database')};"
        f"UID={c.get('username')};PWD={c.get('password')};"
        "Encrypt=yes;TrustServerCertificate=yes;"
    )
    return pyodbc.connect(conn_str, timeout=timeout)

# ── Powder coating material rate ────────────────────────────────────────────
# £ per kg of powder. The Estimate workbook computes powder MATERIAL kg per part
# from geometry (area -> 6 m2/kg coverage -> kg), sums it (AD57 'Total Powder Per
# Unit'), and multiplies by this rate (cell AF57) into the material total M67.
# This is the single source of truth for the powder price; change it here.
# Provisional rate from Tim's manual sheet (POWDER5 line reconciled to ~£4/kg).
POWDER_COST_PER_KG = 9.73


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
