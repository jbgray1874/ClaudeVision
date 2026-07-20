import fitz  # PyMuPDF
import re
from pathlib import Path

# --- DIRECTORY SETUP ---
# This ensures the script knows where to find your 'input' folder
BASE_DIR = Path(__file__).resolve().parent.parent
DRAWINGS_DIR = BASE_DIR / "input" / "drawings"

def sdi_smart_extract(filename):
    file_path = DRAWINGS_DIR / filename
    
    if not file_path.exists():
        print(f"❌ Error: Could not find {file_path}")
        return

    doc = fitz.open(str(file_path))
    page = doc[0]
    text = page.get_text("text")

    # --- EXTRACTION LOGIC ---
    # Hunting for Revision, Material Gauge, and Quantity
    rev_match = re.search(r"REV[:\s]*(\d+)", text, re.I)
    mat_match = re.search(r"(\d+\.?\d*)mm\s+([A-Z\s]+(?:STEEL|ALU|ZINTEC))", text, re.I)
    qty_match = re.search(r"QTY[:\s]*(\d+)", text, re.I)

    print(f"\n{'='*50}")
    print(f"🔍 ANALYSING: {filename}")
    print(f"{'='*50}")
    
    print(f"📍 Revision:     {rev_match.group(1) if rev_match else 'Not Detected'}")
    
    if mat_match:
        print(f"🛠️  Material:     {mat_match.group(2).strip()}")
        print(f"📏 Thickness:    {mat_match.group(1)}mm")
    else:
        print("🛠️  Material:     Check Title Block (OCR may be needed)")

    print(f"🔢 Quantity:     {qty_match.group(1) if qty_match else '1 (Default)'}")
    
    # Check for CAD vectors - important for laser timing
    drawings = page.get_drawings()
    print(f"⚡ Vector Paths: {len(drawings)} (CAD integrity check)")
    print(f"{'='*50}\n")
    
    doc.close()

# --- EXECUTION ---
# Running it on your specific file from the folder
if __name__ == "__main__":
    sdi_smart_extract("1315-1000x300mm Shelf Assembly REV11.PDF")