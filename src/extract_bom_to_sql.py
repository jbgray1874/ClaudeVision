import argparse
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from pypdf import PdfReader

# ========================== HARD-CODED DB CREDENTIALS ==========================
# Kept here to match the current standalone script style.
# If you want, we should move these to environment variables next.
DB_CONFIG = {
    "driver": "ODBC Driver 18 for SQL Server",
    "server": "10.0.0.200",
    "database": "SDILive",
    "username": "AIBot",
    "password": "AIAgentPW2026",
}

TABLE_NAME = "dbo.drawing_bom_items"

HEADER_DWG_QTY = "ITEM DWG NO. DESCRIPTION QTY"
HEADER_DWG_DESC_UPC_QTY = "ITEM DWG NO. DESCRIPTION UPC QTY"
HEADER_QTY_DESC_LENGTH = "ITEM QTY DESCRIPTION LENGTH"

DATE_LINE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}\b")
ITEM_LINE_RE = re.compile(r"^\d+\s+")
UPC_RE = re.compile(r"\b0\d{6}\b")
USER_UPC_RE = re.compile(r"\bUSER\s+(0\d{6})\b", re.IGNORECASE)
FILE_UPC_RE = re.compile(r"\b(0\d{6})\b")
PAGE_DRAWING_RE = re.compile(r"CONSULTANT\s+([A-Z0-9_-]+(?:-[A-Z0-9_-]+)*)", re.IGNORECASE)
ROW_DWG_QTY_RE = re.compile(r"^(\d+)\s+(.+?)\s+(\d+)$")
ROW_DWG_UPC_QTY_RE = re.compile(r"^(\d+)\s+(.+?)\s+(0\d{6})\s+(\d+)$")
ROW_DWG_OPTIONAL_UPC_QTY_RE = re.compile(r"^(\d+)\s+(.+?)\s+(\d+)$")
ROW_QTY_DESC_LENGTH_RE = re.compile(r"^(\d+)\s+(\d+)\s+(.+?)\s+([-+]?\d+(?:\.\d+)?)$")
CODE_TOKEN_RE = re.compile(
    r"^(?:\d{5}-[A-Z0-9-]+|[A-Z]*\d[A-Z0-9_-]*|[A-Z0-9_-]*\d[A-Z0-9_-]*)$",
    re.IGNORECASE,
)


# ========================== DB HELPERS ==========================
def get_db_connection():
    import pyodbc

    conn_str = (
        f"DRIVER={{{DB_CONFIG['driver']}}};"
        f"SERVER={DB_CONFIG['server']};"
        f"DATABASE={DB_CONFIG['database']};"
        f"UID={DB_CONFIG['username']};"
        f"PWD={DB_CONFIG['password']};"
        "Encrypt=yes;TrustServerCertificate=yes;"
    )
    return pyodbc.connect(conn_str, timeout=30)


def get_text_column_lengths(cursor) -> Dict[str, Optional[int]]:
    cursor.execute(
        """
        SELECT COLUMN_NAME, CHARACTER_MAXIMUM_LENGTH
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = 'dbo'
          AND TABLE_NAME = 'drawing_bom_items'
          AND DATA_TYPE IN ('varchar', 'nvarchar', 'char', 'nchar')
        """
    )
    lengths: Dict[str, Optional[int]] = {}
    for col, max_len in cursor.fetchall():
        lengths[str(col).lower()] = None if int(max_len) == -1 else int(max_len)
    return lengths


def trim_to_max(value: Any, max_len: Optional[int]) -> str:
    text = "" if value is None else str(value)
    if max_len is None:
        return text
    return text[:max_len]


def column_exists(cursor, column_name: str) -> bool:
    cursor.execute(
        """
        SELECT 1
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = 'dbo'
          AND TABLE_NAME = 'drawing_bom_items'
          AND COLUMN_NAME = ?
        """,
        column_name,
    )
    return cursor.fetchone() is not None


def delete_existing_rows(cursor, drawing_number: str) -> int:
    cursor.execute(
        f"DELETE FROM {TABLE_NAME} WHERE drawing_number = ?",
        drawing_number,
    )
    return int(cursor.rowcount or 0)


# ========================== PARSING HELPERS ==========================
def extract_upc_from_text(text: str, pdf_path: Optional[Path] = None) -> Optional[str]:
    text = text or ""

    # Best signal on these drawings: the footer line like "... USER 0351808".
    match = USER_UPC_RE.search(text)
    if match:
        return match.group(1)

    # Next best: the filename usually starts with the UPC.
    if pdf_path is not None:
        file_match = FILE_UPC_RE.search(pdf_path.stem.upper())
        if file_match:
            return file_match.group(1)

    # Fallback: any 7-digit 0-prefixed token in the text.
    match = UPC_RE.search(text)
    return match.group(0) if match else None


def clean_line(line: str) -> str:
    return " ".join((line or "").split())


def is_footer_start(line: str) -> bool:
    upper = line.upper()
    if DATE_LINE_RE.match(line):
        return True
    if "WEIGHT:" in upper or line.endswith("WEIGHT:"):
        return True
    if upper.startswith("COLOUR:") or upper.startswith("FINISH:") or upper.startswith("MATERIAL:"):
        return True
    return False


def extract_page_drawing_number(page_text: str) -> Optional[str]:
    match = PAGE_DRAWING_RE.search(page_text or "")
    return match.group(1).strip().upper() if match else None


def split_code_and_description(body: str) -> Tuple[str, str]:
    body = clean_line(body)
    if not body:
        return "", ""

    for prefix in ("STD PART ", "UPC STICKERWHITE ", "FIXING "):
        if body.upper().startswith(prefix):
            return body[: len(prefix) - 1], body[len(prefix) :].strip()

    tokens = body.split()
    code_idx: Optional[int] = None
    for idx, token in enumerate(tokens):
        if CODE_TOKEN_RE.match(token) and any(char.isdigit() for char in token):
            code_idx = idx
            break

    if code_idx is None:
        return "", body

    token = tokens[code_idx]
    trailing_tokens = tokens[code_idx + 1 :]

    # Supplier/catalog style rows sometimes look like:
    # "Tente Linea Castor 5925UAP050L51_10 CASTOR115"
    # In the drawing table, everything up to and including the code belongs in
    # DWG NO, with the final commercial short name in DESCRIPTION.
    if code_idx > 0 and trailing_tokens:
        trailing_text = " ".join(trailing_tokens).upper()
        if any(keyword in trailing_text for keyword in ("CASTOR", "WHEEL", "GLIDE")):
            return " ".join(tokens[: code_idx + 1]).strip(), " ".join(trailing_tokens).strip()

    if code_idx == 0:
        return token, " ".join(trailing_tokens).strip()

    description = " ".join(tokens[:code_idx] + trailing_tokens).strip()
    return token, description


def parse_quantity(text: str) -> int:
    try:
        return int(round(float(text)))
    except Exception:
        return 0


def parse_length_mm(text: str) -> Optional[float]:
    try:
        return float(text)
    except Exception:
        return None


def is_tube_description(description: str) -> bool:
    return "TUBE" in (description or "").upper()


def length_label_for_description(length_raw: str, length_mm: Optional[float]) -> str:
    if length_raw:
        return clean_line(length_raw)
    if length_mm is None:
        return ""
    if float(length_mm).is_integer():
        return str(int(length_mm))
    return f"{length_mm:g}"


def iter_bom_lines(lines: Sequence[str]) -> Iterable[Tuple[str, str]]:
    mode: Optional[str] = None
    pending: Optional[str] = None

    for raw_line in lines:
        line = clean_line(raw_line)
        if not line:
            continue

        upper = line.upper()
        if HEADER_DWG_DESC_UPC_QTY in upper:
            if pending and mode:
                yield mode, pending
            mode = "dwg_upc_qty"
            pending = None
            continue
        if HEADER_DWG_QTY in upper:
            if pending and mode:
                yield mode, pending
            mode = "dwg_qty"
            pending = None
            continue
        if HEADER_QTY_DESC_LENGTH in upper:
            if pending and mode:
                yield mode, pending
            mode = "qty_desc_length"
            pending = None
            continue

        if mode and is_footer_start(line):
            if pending:
                yield mode, pending
            mode = None
            pending = None
            continue

        if not mode:
            continue

        if ITEM_LINE_RE.match(line):
            if pending:
                yield mode, pending
            pending = line
        elif pending:
            # Continuation line: common when PDF text extraction splits vendor name / code.
            pending = f"{pending} {line}"

    if pending and mode:
        yield mode, pending


def extract_bom_rows_from_page(
    drawing_number: str,
    page_number: int,
    page_text: str,
    upc: str,
) -> List[Dict[str, Any]]:
    page_rows: List[Dict[str, Any]] = []
    page_drawing_number = extract_page_drawing_number(page_text)
    lines = [line for line in (page_text or "").splitlines() if line.strip()]

    for mode, line in iter_bom_lines(lines):
        if mode == "dwg_qty":
            match = ROW_DWG_QTY_RE.match(line)
            if not match:
                continue
            item_number, body, quantity_text = match.groups()
            dwg_no, description = split_code_and_description(body)
            page_rows.append(
                {
                    "drawing_number": drawing_number,
                    "upc": upc,
                    "page_number": page_number,
                    "page_drawing_number": page_drawing_number,
                    "item_number": item_number,
                    "dwg_no": dwg_no,
                    "description": description,
                    "quantity": parse_quantity(quantity_text),
                    "length_mm": None,
                    "length_raw": "",
                }
            )
            continue

        if mode == "dwg_upc_qty":
            match = ROW_DWG_UPC_QTY_RE.match(line)
            row_upc: Optional[str]
            if match:
                item_number, body, row_upc, quantity_text = match.groups()
            else:
                fallback_match = ROW_DWG_OPTIONAL_UPC_QTY_RE.match(line)
                if not fallback_match:
                    continue
                item_number, body, quantity_text = fallback_match.groups()
                row_upc = None
            dwg_no, description = split_code_and_description(body)
            page_rows.append(
                {
                    "drawing_number": drawing_number,
                    "upc": row_upc or "",
                    "page_number": page_number,
                    "page_drawing_number": page_drawing_number,
                    "item_number": item_number,
                    "dwg_no": dwg_no,
                    "description": description,
                    "quantity": parse_quantity(quantity_text),
                    "length_mm": None,
                    "length_raw": "",
                }
            )
            continue

        match = ROW_QTY_DESC_LENGTH_RE.match(line)
        if not match:
            continue
        item_number, quantity_text, description, length_text = match.groups()
        page_rows.append(
            {
                "drawing_number": drawing_number,
                "upc": upc,
                "page_number": page_number,
                "page_drawing_number": page_drawing_number,
                "item_number": item_number,
                # For cut-length pages there is no row-level drawing number, so
                # use the current page drawing number to preserve parent context.
                "dwg_no": page_drawing_number or "",
                "description": clean_line(description),
                "quantity": parse_quantity(quantity_text),
                "length_mm": parse_length_mm(length_text),
                "length_raw": length_text,
            }
        )

    return page_rows


def extract_bom_tables(pdf_path: str) -> List[Dict[str, Any]]:
    pdf_file = Path(pdf_path)
    drawing_number = pdf_file.stem.upper()
    reader = PdfReader(str(pdf_file))

    full_text = "\n".join((page.extract_text() or "") for page in reader.pages)
    upc = extract_upc_from_text(full_text, pdf_file) or "UNKNOWN"

    raw_rows: List[Dict[str, Any]] = []
    seen_keys = set()

    tube_counters: Dict[str, int] = {}

    for page_number, page in enumerate(reader.pages, 1):
        page_text = page.extract_text() or ""
        for row in extract_bom_rows_from_page(drawing_number, page_number, page_text, upc):
            row["description3"] = ""
            if is_tube_description(row["description"]):
                tube_context = row.get("page_drawing_number") or row["dwg_no"] or drawing_number
                tube_counters[tube_context] = tube_counters.get(tube_context, 0) + 1
                tube_counter = tube_counters[tube_context]
                base_dwg_no = row["dwg_no"]
                row["dwg_no"] = f"T{tube_counter}-{base_dwg_no}"
                length_label = length_label_for_description(row.get("length_raw", ""), row.get("length_mm"))
                if length_label:
                    row["description3"] = f"{base_dwg_no} {row['description']} {length_label}mm"

            dedupe_key = (
                row["page_number"],
                row.get("page_drawing_number") or "",
                row["item_number"],
                row["dwg_no"],
                row["description"],
                row["quantity"],
                row["length_mm"],
            )
            # Keep duplicate protection within the same page extraction pass, but
            # preserve repeated BOM tables that genuinely appear on different pages.
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            raw_rows.append(row)

    return raw_rows


# ========================== MAIN ==========================
def main():
    parser = argparse.ArgumentParser(description="Extract BOM tables from PDFs to SQL")
    parser.add_argument("input_path", help="PDF file or folder containing PDF drawings")
    parser.add_argument(
        "--replace-existing",
        action="store_true",
        help="Delete existing rows for the same drawing_number/upc before inserting.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and print counts without inserting into SQL.",
    )
    args = parser.parse_args()

    input_path = Path(args.input_path)
    if not input_path.exists():
        print(f"ERROR: Path not found: {input_path}")
        return

    if input_path.is_file():
        pdf_files = [input_path]
    else:
        pdf_files = sorted(
            file_path
            for file_path in input_path.rglob("*")
            if file_path.is_file() and file_path.suffix.lower() == ".pdf"
        )
    if not pdf_files:
        print(f"ERROR: No PDFs found in {input_path}")
        return

    conn = None
    cursor = None
    col_lengths: Dict[str, Optional[int]] = {}
    has_description3 = False
    total_inserted = 0
    total_trimmed = 0
    total_deleted = 0

    if not args.dry_run:
        conn = get_db_connection()
        cursor = conn.cursor()
        col_lengths = get_text_column_lengths(cursor)
        has_description3 = column_exists(cursor, "description3")

    print(f"Scanning {len(pdf_files)} PDF(s) from: {input_path}\n")

    for pdf_file in pdf_files:
        print(f"Processing: {pdf_file.name}")
        bom_rows = extract_bom_tables(str(pdf_file))
        print(f"   -> parsed {len(bom_rows)} BOM row(s)")

        if args.dry_run:
            for sample in bom_rows[:10]:
                print(
                    "      ",
                    sample["page_number"],
                    sample["item_number"],
                    sample["dwg_no"],
                    sample["description"],
                    sample["quantity"],
                    sample["length_mm"],
                )
            continue

        if args.replace_existing and bom_rows:
            drawing_number = trim_to_max(
                bom_rows[0]["drawing_number"],
                col_lengths.get("drawing_number"),
            )
            deleted = delete_existing_rows(cursor, drawing_number)
            total_deleted += deleted

        for row in bom_rows:
            cleaned = {
                "drawing_number": trim_to_max(row["drawing_number"], col_lengths.get("drawing_number")),
                "upc": trim_to_max(row["upc"], col_lengths.get("upc")),
                "item_number": trim_to_max(row["item_number"], col_lengths.get("item_number")),
                "dwg_no": trim_to_max(row["dwg_no"], col_lengths.get("dwg_no")),
                "description": trim_to_max(row["description"], col_lengths.get("description")),
                "length_raw": trim_to_max(row["length_raw"], col_lengths.get("length_raw")),
                "description3": trim_to_max(row.get("description3", ""), col_lengths.get("description3")),
            }

            if (
                cleaned["drawing_number"] != row["drawing_number"]
                or cleaned["upc"] != row["upc"]
                or cleaned["item_number"] != row["item_number"]
                or cleaned["dwg_no"] != row["dwg_no"]
                or cleaned["description"] != row["description"]
                or cleaned["length_raw"] != row["length_raw"]
                or cleaned["description3"] != row.get("description3", "")
            ):
                total_trimmed += 1

            if has_description3:
                cursor.execute(
                    f"""
                    INSERT INTO {TABLE_NAME}
                    (drawing_number, upc, page_number, item_number, dwg_no, description, quantity, length_mm, length_raw, description3)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    cleaned["drawing_number"],
                    cleaned["upc"],
                    row["page_number"],
                    cleaned["item_number"],
                    cleaned["dwg_no"],
                    cleaned["description"],
                    row["quantity"],
                    row["length_mm"],
                    cleaned["length_raw"],
                    cleaned["description3"],
                )
            else:
                cursor.execute(
                    f"""
                    INSERT INTO {TABLE_NAME}
                    (drawing_number, upc, page_number, item_number, dwg_no, description, quantity, length_mm, length_raw)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    cleaned["drawing_number"],
                    cleaned["upc"],
                    row["page_number"],
                    cleaned["item_number"],
                    cleaned["dwg_no"],
                    cleaned["description"],
                    row["quantity"],
                    row["length_mm"],
                    cleaned["length_raw"],
                )
            total_inserted += 1

        conn.commit()
        print(f"   -> inserted {len(bom_rows)} row(s)")

    if conn is not None:
        conn.close()

    if args.dry_run:
        print("\nDONE: Dry run completed.")
        return

    print(f"\nDONE: {total_inserted} BOM row(s) saved to {TABLE_NAME}")
    if args.replace_existing:
        print(f"Deleted existing rows first: {total_deleted}")
    if not has_description3:
        print("NOTE: SQL column description3 was not found, so description3 values were not inserted.")
    if total_trimmed:
        print(f"WARNING: {total_trimmed} row(s) had text trimmed to fit SQL column lengths")


if __name__ == "__main__":
    main()
