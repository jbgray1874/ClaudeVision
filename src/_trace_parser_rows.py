r"""READ-ONLY. Run the parser's EXACT _manual_bom_lines logic against Tim's real sheet, row by
row, printing for each row: the cells it scanned (cols 1-6), whether a skip-word fired, what it
picked as code_val/desc_val, and the cost. Shows precisely which rows produce the garbage
(code=0.0, description=100.0) and which real BOM rows it MISSES. Pure trace — replicates the
live logic, no import needed, no edits."""
import re
import xlrd

MANUAL = r"K:\Estimating\Completed\Manual Estimates\2026\TTI\1282- MILWAUKEE RED 50cm PEG\1282-MILWAUKEE 50CM PEG WALL BAY(ISS 7)-.xls"

# replicate the wrapper (1-indexed -> xlrd 0-indexed)
bk = xlrd.open_workbook(MANUAL)
sh = bk.sheet_by_name("Estimate")
def cell(row, col):
    try: return sh.cell_value(row-1, col-1)
    except IndexError: return None

max_row, max_col = sh.nrows, sh.ncols

# replicate parser constants
code_re = re.compile(r"^[A-Z0-9][A-Z0-9 ./_-]{1,30}$", re.IGNORECASE)
skip_words = ("TOTAL","SUBTOTAL","DESCRIPTION","ITEM","QTY","SHEET STEEL",
              "BILL OF MATERIALS","PART CODE","SUPPLIER","STANDARD MATERIALS",
              "QUANTITY","MATERIAL","LABOUR","OVERHEAD","MARGIN","SELL")
def norm(raw):
    s=str(raw or "").strip().upper(); s=re.sub(r"\s+","",s); s=re.sub(r"-+$","",s); return s
def safe_float(v):
    try:
        if v is None or v=="" : return None
        return float(v)
    except: return None

print("Row-by-row parser decision on Tim's Estimate sheet (rows 8..60):\n")
picked=[]
for row in range(8, min(max_row,60)+1):
    code_val=None; desc_val=""; fired=None
    scanned=[]
    for col in range(1, min(7, max_col+1)):
        v=cell(row,col)
        if v is None: continue
        txt=str(v).strip()
        if not txt: continue
        scanned.append(f"c{col}={txt[:18]}")
        up=txt.upper()
        if any(sw in up for sw in skip_words):
            fired=[sw for sw in skip_words if sw in up][0]; code_val=None; break
        if code_val is None and code_re.match(txt) and any(c.isdigit() for c in txt):
            code_val=txt
        elif code_val is not None and not desc_val and len(txt)>3:
            desc_val=txt
    cost=None
    for col in range(2, max_col+1):
        f=safe_float(cell(row,col))
        if f is not None and f>0: cost=f
    verdict=""
    if fired: verdict=f"SKIP({fired})"
    elif code_val and len(norm(code_val))>=3: 
        verdict=f"PICK code={norm(code_val)!r} desc={desc_val[:20]!r} cost={cost}"
        picked.append(norm(code_val))
    else: verdict="(no code)"
    if scanned:
        print(f" r{row}: {' '.join(scanned[:4]):<58} -> {verdict}")

print(f"\nTOTAL picked codes: {len(picked)}")
print("picked:", picked)
