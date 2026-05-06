"""
STANDALONE BOM Extractor → SQL
- Scans a folder of PDF drawings
- Extracts every BOM table (Item / DWG No. / Description / QTY)
- Detects UPC from footer
- Saves everything to dbo.drawing_bom_items
- Uses secure keyring for DB password
"""

import pdfplumber
import re
import argparse
from pathlib import Path
from datetime import datetime
import keyring
import pyodbc
from typing import List, Dict

# ========================== CONFIG ==========================
SERVICE_NAME = "SDI_AI_Estimating"
USERNAME = "AIBot"
TABLE_NAME = "dbo.drawing_bom_items"

# ========================== HELPERS ==========================
def get_db_connection():
    """Secure connection using Windows Credential Manager"""
    password = keyring.get_password(SERVICE_NAME, USERNAME)
    if not password:
        raise RuntimeError("❌ AIBot password not found. Run the one-line storage command first.")

    conn_str = (
        f"DRIVER={{{'ODBC Driver 18 for SQL Server'}}};"
        f"SERVER=10.0.0.200;DATABASE=SDILive;"
        f"UID={USERNAME};PWD={password};"
        f"Encrypt=yes;TrustServerCertificate=yes;"
    )
    return pyodbc.connect(conn_str, timeout=30)

def extract_upc_from_text(text: str) -> str | None:
    """Find UPC number (e.g. 0351808) from footer"""
    match = re.search(r'\b0\d{6}\b', text)
    return match.group(0) if match else None

def extract_bom_tables(pdf_path: str) -> List[Dict]:
    """Extract all BOM tables from PDF"""
    results = []
    upc = None

    with pdfplumber.open(pdf_path) as pdf:
        drawing_number = Path(pdf_path).stem.upper()

        for page_num, page in enumerate(pdf.pages, 1):
            # Extract raw text for UPC detection
            text = page.extract_text() or ""
            if not upc:
                upc = extract_upc_from_text(text)

            # Try to extract tables
            tables = page.extract_tables()
            for table in tables:
                if len(table) < 2:
                    continue

                # Look for BOM header row
                header = [str(col or "").strip().upper() for col in table[0]]
                if any("ITEM" in h or "DWG" in h for h in header) and any("QTY" in h or "QUANTITY" in h for h in header):
                    for row in table[1:]:  # skip header
                        if len(row) < 4:
                            continue
                        item_num = str(row[0] or "").strip()
                        dwg_no = str(row[1] or "").strip()
                        description = str(row[2] or "").strip()
                        qty_str = str(row[3] or "").strip()

                        try:
                            qty = int(float(qty_str)) if qty_str else 0
                        except:
                            qty = 0

                        if item_num or description:  # only save meaningful rows
                            results.append({
                                "drawing_number": drawing_number,
                                "upc": upc or "UNKNOWN",
                                "page_number": page_num,
                                "item_number": item_num,
                                "dwg_no": dwg_no,
                                "description": description,
                                "quantity": qty
                            })
    return results

# ========================== MAIN ==========================
def main():
    parser = argparse.ArgumentParser(description="Extract BOM tables from PDFs and save to SQL")
    parser.add_argument("folder", help="Folder containing PDF drawings")
    args = parser.parse_args()

    folder = Path(args.folder)
    if not folder.exists():
        print(f"❌ Folder not found: {folder}")
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    total_inserted = 0

    for pdf_file in folder.glob("*.pdf"):
        print(f"Processing: {pdf_file.name}")
        bom_rows = extract_bom_tables(str(pdf_file))

        for row in bom_rows:
            cursor.execute(f"""
                INSERT INTO {TABLE_NAME}
                (drawing_number, upc, page_number, item_number, dwg_no, description, quantity)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, 
                row["drawing_number"],
                row["upc"],
                row["page_number"],
                row["item_number"],
                row["dwg_no"],
                row["description"],
                row["quantity"]
            )
            total_inserted += 1

        conn.commit()
        print(f"   → {len(bom_rows)} rows inserted")

    conn.close()
    print(f"\n✅ Done! {total_inserted} BOM rows saved to {TABLE_NAME}")

if __name__ == "__main__":
    main()