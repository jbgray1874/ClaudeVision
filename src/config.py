from pathlib import Path

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

SUPPORTED_EXTENSIONS = {".pdf"}
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

PART_NUMBER_PATTERN = r"\b(?:\d{4,5}[A-Z]?|[A-Z]{1,6}\d{0,4}|FIXING\d*)\s*(?:-\s*[A-Z0-9_]{1,12}){1,4}\b"
PART_NUMBER_PATTERNS = [
    PART_NUMBER_PATTERN,
    r"\b[A-Z]{1,4}\s*-\s*\d{2,}\b",
]
DATE_PATTERN = r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b"
REVISION_PATTERN = r"\bREV(?:ISION)?\s*[:.\-]?\s*([A-Z0-9]+)\b"
SHEET_PATTERN = r"\b(\d+\s*/\s*\d+)\b"
SHEET_SIZE_PATTERN = r"\b(A[0-4])\b"
SCALE_PATTERN = r"\bSCALE\s*[:\-]?\s*([A-Z0-9:./\- ]+)"
DWG_NO_PATTERN = r"(?:DWG\s*NO|DRAWING\s*NO)\s*[:\-]?\s*([A-Z0-9\s\-_]+)"
DRAWING_NUMBER_PATTERN = DWG_NO_PATTERN
DESCRIPTION_PATTERN = r"DESCRIPTION\s*[:\-]?\s*(.+)"
DRAWN_BY_PATTERN = r"DRAWN\s*BY\s*[:\-]?\s*([A-Z0-9.\-_ ]+)"
MODIFIED_BY_PATTERN = r"MODIFIED\s*BY\s*[:\-]?\s*([A-Z0-9.\-_ ]+)"
CLIENT_PATTERN = r"CLIENT\s*[:\-]?\s*([A-Z0-9.\-_ ]+)"
PROJECT_TITLE_PATTERN = r"PROJECT\s*TITLE\s*[:\-]?\s*(.+)"

MATERIAL_PATTERN = r"\b(MILD\s+STEEL|STAINLESS\s+STEEL|ALUMINIUM|ALUMINUM|ALU|ZINTEC|GALVANISED\s+STEEL|GALVANIZED\s+STEEL|TIMBER|WOOD|MDF|PLYWOOD)\b"
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
FOLD_PATTERN = r"\b(?:EXT\s+FOLD|INT\s+FOLD|FOLD|BEND)\b"
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

QTY_TABLE_ROW_PATTERN = r"(\d+)\s+([A-Z0-9_]+(?:\s*-\s*[A-Z0-9_]+){1,4})\s+(.+?)\s+(\d+)"

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
    "DEFAULT": [(2500, 1250)],
}

MATERIAL_DENSITY_KG_PER_M3 = {
    "MILD STEEL": 7850,
    "GALVANISED STEEL": 7850,
    "GALVANIZED STEEL": 7850,
    "ZINTEC": 7850,
    "STAINLESS STEEL": 8000,
    "ALUMINIUM": 2700,
    "ALUMINUM": 2700,
}

MATERIAL_PRICE_GBP_PER_KG = {
    "MILD STEEL": 2.25,
    "GALVANISED STEEL": 2.55,
    "GALVANIZED STEEL": 2.55,
    "ZINTEC": 2.45,
    "STAINLESS STEEL": 5.80,
    "ALUMINIUM": 4.20,
    "ALUMINUM": 4.20,
}

NESTING_RULES = {
    "edge_margin_mm": 10.0,
    "part_spacing_mm": 5.0,
    "waste_factor_pct": 8.0,
}

LABOUR_RULES = {
    "laser_cutting": {
        "setup_min": 3.0,
        "pierce_sec_each": 1.2,
        "cut_sec_per_mm": 0.015,
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
    "powder_coating": {
        "min_per_part": 1.2,
    },
    "handling": {
        "min_per_part": 0.8,
    },
}

HOURLY_RATES_GBP = {
    "laser_cutting": 48.0,
    "hole_machining": 42.0,
    "folding": 45.0,
    "powder_coating": 38.0,
    "handling": 35.0,
}

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
    "spreadsheet",
    "access",
    "web",
]

PRICE_SOURCE_CONFIG = {
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
        "enabled": False,
        "sources": [],
        "user_agent": "CodexPriceCollector/1.0",
    },
}


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
