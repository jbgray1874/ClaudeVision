from pathlib import Path
import re

BASE_DIR = Path(__file__).resolve().parents[1]
INPUT_DIR = BASE_DIR / "input"
DRAWINGS_DIR = INPUT_DIR / "drawings"
SPREADSHEETS_DIR = INPUT_DIR / "spreadsheets"

OUTPUT_DIR = BASE_DIR / "output"
JSON_DIR = OUTPUT_DIR / "json"
LOG_DIR = OUTPUT_DIR / "logs"
TEXT_DIR = OUTPUT_DIR / "text"
PAGE_IMAGES_DIR = OUTPUT_DIR / "page_images"

SUPPORTED_EXTENSIONS = {".pdf"}

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
    "WEIGHT",
    "SCALE",
    "CLIENT REF",
]

DIMENSION_PATTERN = r"(?<!\d)(\d+(?:\.\d+)?)\s*(?:MM|mm|°|X|EXT|INT|PITCH)?"
PART_NUMBER_PATTERN = r"\b\d{4}\s*-\s*\d{2}\b"
REVISION_PATTERN = r"\bREV(?:ISION)?\s*[:.-]?\s*(\d+)\b"
DATE_PATTERN = r"\b\d{2}/\d{2}/\d{4}\b"


def ensure_directories() -> None:
    for path in [
        DRAWINGS_DIR,
        SPREADSHEETS_DIR,
        JSON_DIR,
        LOG_DIR,
        TEXT_DIR,
        PAGE_IMAGES_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)