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
    "MILD STEEL": 0.90,
    "GALVANISED STEEL": 1.05,
    "GALVANIZED STEEL": 1.05,
    "ZINTEC": 1.00,
    "STAINLESS STEEL": 3.10,
    "ALUMINIUM": 2.75,
    "ALUMINUM": 2.75,
}

NESTING_RULES = {
    "edge_margin_mm": 10.0,
    "part_spacing_mm": 5.0,
    "waste_factor_pct": 8.0,
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
    "laser_cutting": 68.19,
    "hole_machining": 43.77,
    "folding": 40.47,
    "powder_coating": 355.43,
    "handling": 31.18,
    "assembly": 28.56,
    "welding": 41.77,
    "guillotine": 31.29,
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
    "sqlserver",
    "spreadsheet",
    "access",
    "web",
]

PRICE_SOURCE_CONFIG = {
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
        # Active now: System Cost Per + supplier lookup from SDILive.
        # Expected params: (part_code, description, part_code)
        "part_system_cost_query": """
SELECT TOP (1)
    u.[Part ref] AS part_code,
    u.[Description] AS description,
    u.[System cost per] AS system_cost_per,
    CAST(u.[System cost per] AS decimal(18,4)) AS price,
    u.[Cus code] AS supplier_code,
    s.[SUP_NAME] AS supplier_name,
    'GBP' AS currency,
    'each' AS unit,
    0.95 AS confidence,
    GETDATE() AS price_date
FROM UDEF_PARTS_TABLE_FOR_ESTIMATING u
LEFT JOIN SUP_TBL s
    ON s.[SUP_CODE] = u.[Cus code]
WHERE
    UPPER(LTRIM(RTRIM(u.[Part ref]))) = UPPER(LTRIM(RTRIM(?)))
    OR UPPER(u.[Description]) LIKE '%' + UPPER(?) + '%'
ORDER BY
    CASE WHEN UPPER(LTRIM(RTRIM(u.[Part ref]))) = UPPER(LTRIM(RTRIM(?))) THEN 0 ELSE 1 END,
    u.[System cost per] DESC
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
        "enabled": False,
        "sources": [],
        "user_agent": "CodexPriceCollector/1.0",
    },
}

WORKBOOK_EQUIVALENT_PRICING = {
    "fixed_factor": 0.95,
    "default_m107": 0.0,
    "default_m109": 0.0,
    "sell_markup_options_pct": {
        "low": 10.0,
        "standard": 20.0,
        "premium": 35.0,
    },
    # Workbook parity helper: quantity uplift/discount multipliers.
    # Applied to computed totals when no direct system_cost_per_part is used.
    "quantity_breaks": [
        {"min_qty": 1, "max_qty": 4, "multiplier": 1.00},
        {"min_qty": 5, "max_qty": 24, "multiplier": 0.97},
        {"min_qty": 25, "max_qty": 99, "multiplier": 0.94},
        {"min_qty": 100, "max_qty": None, "multiplier": 0.91},
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

# Minimal write-back map for Blank Estimate template.
# Keep this conservative: write to visible totals/output cells only.
ESTIMATE_TEMPLATE_WRITEBACK = {
    "output_cells": {
        "L59": "estimate_summary.workbook_equivalent_pricing.m59_material_subtotal_gbp",
        "L101": "estimate_summary.workbook_equivalent_pricing.m103_labour_subtotal_gbp",
        "L105": "estimate_summary.workbook_equivalent_pricing.l105_total_unit_cost_gbp",
        "L111": "estimate_summary.workbook_equivalent_pricing.l111_sell_price_gbp",
    }
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
