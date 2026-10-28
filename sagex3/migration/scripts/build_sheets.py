"""The mapped spreadsheets for the clean run - what James loads from.

Track 1, the three files whose product codes changed for the clean run:
    YA004SMR, YA004POH, YA004SOHPJ - the existing guides with the V7 product codes
Track 2, each template filled with the V8 data:
    ZSDIITM, ZSDIROU2, ZSDIITMSUP, YA004BPCDL  - the templates as issued
    YA00408BOM, YITC                           - laid out exactly as the templates seen earlier
    YA004MFG                                   - our mapped guide, on the V7 codes
Every sheet's data is checked against the load data cell by cell before it is saved.
"""
import csv
import os
import shutil

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

BASE = "/tmp/claude-0/-home-user-ClaudeVision/e9ffe9d9-c7dd-5e34-8a16-6cb3c65dadea/scratchpad"
V8, OUT, T = f"{BASE}/out_v8", f"{BASE}/out_sheets", f"{BASE}/tmpl_t2"
os.makedirs(OUT, exist_ok=True)
HF, FILL = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="44546A")


def read(p):
    with open(p, newline="", encoding="cp850") as f:
        return [r for r in csv.reader(f, delimiter=";") if r and r[0].strip()]


def cell(v, numeric):
    if numeric and v != "":
        f = float(v)
        return int(f) if f.is_integer() and "." not in v else f
    return v if v != "" else None


def as_text(v):
    if v is None:
        return ""
    if isinstance(v, float):
        return repr(v).rstrip("0").rstrip(".") if "e" not in repr(v) else str(v)
    return str(v)


def same(a, b):
    """A cell read back equals the load value: numbers compared as numbers."""
    if a == b:
        return True
    try:
        return float(a) == float(b)
    except ValueError:
        return False


def fill(ws, first_row, rows, numeric):
    if ws.max_row >= first_row:
        ws.delete_rows(first_row, ws.max_row)
    for r in rows:
        ws.append([cell(v, i in numeric) for i, v in enumerate(r)])
    ws.freeze_panes = ws.cell(first_row, 1)


def check(path, sheet, first_row, rows):
    ws = load_workbook(path, read_only=True)[sheet]
    got = [[as_text(v) for v in r] for r in ws.iter_rows(min_row=first_row, values_only=True)]
    got = [g for g in got if any(g)]
    assert len(got) == len(rows), (path, len(got), len(rows))
    for g, r in zip(got, rows):
        g = g[:len(r)] + [""] * (len(r) - len(g))
        assert all(same(a, b) for a, b in zip(g, r)), (path, g, r)
    return len(got)


def add_sheet(wb, title, head, rows, widths=None):
    ws = wb.create_sheet(title)
    ws.append(head)
    for c in ws[1]:
        c.font, c.fill = HF, FILL
        c.alignment = Alignment(wrap_text=True, vertical="top")
    for r in rows:
        ws.append(list(r))
    for i, w in enumerate(widths or [18] * len(head), 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"
    return ws


def notes(wb, lines):
    ws = wb.create_sheet("Notes")
    for l in lines:
        ws.append(l)
    ws["A1"].font = Font(bold=True, size=13)
    ws.column_dimensions["A"].width = 46
    ws.column_dimensions["B"].width = 100


rep = load_workbook(f"{V8}/V8_track2_report.xlsx", read_only=True)


def held(name):
    s = f"Held - {name}"[:31]
    return [list(r) for r in rep[s].iter_rows(values_only=True)] if s in rep.sheetnames else []


made = []

# ---- Track 1: the three guides, product codes on the clean-run file --------------------
for name, col, src in (("YA004SMR", 7, "YA004SMR_load7_clean_run.txt"), ("YA004POH", 7, "YA004POH_load7_clean_run.txt"),
                       ("YA004SOHPJ", 16, "YA004SOHPJ_load7_clean_run.txt")):
    rows = read(f"{BASE}/out_v7/{src}")
    path = f"{OUT}/{name}_guide_MAPPED_clean_run.xlsx"
    shutil.copy(f"{BASE}/out_mapped/{name}_guide_MAPPED.xlsx", path)
    wb = load_workbook(path)
    ws = wb["Data with Headings"]
    changed = 0
    for i, r in enumerate(rows):
        c = ws.cell(3 + i, col + 1)
        if c.value != r[col]:
            c.value = r[col]
            changed += 1
        if name == "YA004SMR":                # Description (column E) is the product key
            ws.cell(3 + i, 5).value = r[4]
    n = wb["Notes"]
    n.insert_rows(3, 2)
    n.cell(3, 1, "Clean run").font = Font(bold=True)
    n.cell(4, 1, f"Product codes on {changed} lines changed to the cleaned codes in the clean-run product "
                 "file (ZSDIITM). Nothing else differs from the UAT guide.")
    wb.save(path)
    made.append((path, check(path, "Data with Headings", 3, rows), changed))

# ---- Track 2 ---------------------------------------------------------------------------
# products: the ZSDIITM template as issued
rows = read(f"{V8}/ZSDIITM_load8_products.txt")
path = f"{OUT}/ZSDIITM_products_MAPPED.xlsx"
wb = load_workbook(f"{T}/ZSDIITM.xlsx")
fill(wb["Data with Headings"], 4, rows, {7, 9, 11, 12})
add_sheet(wb, "Held back", ["Category", "Product", "Description", "Description 2", "Description 3"] + [""] * 13 + ["Why"],
          held("Products"))
notes(wb, [["ZSDIITM - products, clean run"], [], ["Rows", len(rows)],
           ["Codes", "Upper case, letters, numbers and hyphens only - the same codes in every other file"],
           ["Descriptions", "Ethan's character rule: & as AND, / as -, other symbols removed, within 30 characters. "
                            "68 blank first descriptions filled from description 3, then 2, then the code"],
           ["Held back", "33 rows - a code on two different products. X3 keeps one product per code: the "
                         "manufactured version is kept where the code has a BOM. SDI to decide which product keeps each code"]])
wb.save(path)
made.append((path, check(path, "Data with Headings", 4, rows), 0))

# routes: the ZSDIROU2 template as issued
rows = read(f"{V8}/ZSDIROU2_load8_routes.txt")
path = f"{OUT}/ZSDIROU2_routes_MAPPED.xlsx"
wb = load_workbook(f"{T}/ZSDIROU2.xlsx")
fill(wb["ZSDROU2"], 4, rows, {1, 3, 4, 5, 6, 9, 10})
add_sheet(wb, "Held back", ["Routing", "Routing Code", "Site", "Use Status", "Time Unit", "WO Mode", "Operation",
                            "Main Work Centre", "Operation Description", "Setup Time", "Run Time", "Why"], held("Routes"))
notes(wb, [["ZSDIROU2 - routes, clean run"], [], ["Rows", len(rows)],
           ["Work centres", "All 31 used are on X3's work centre list - no Access names"],
           ["Operation descriptions", "Ethan's character rule applied - P/C becomes P-C, & becomes AND"],
           ["Held back", "71 lines on 36 bought-in products (RAWML, FGSL) - X3 routes manufactured products only"]])
wb.save(path)
made.append((path, check(path, "ZSDROU2", 4, rows), 0))

# BOMs: the YA00408BOM layout seen earlier
BOM = [("ITMREF", "Parent Product"), ("BOMALT", "BOM Code"), ("USESTA", "Use Status"), ("BOHSTRDAT", "Valid from"),
       ("BOHENDDAT", "Valid to"), ("BASQTY", "Base Quantity"), ("QTYCOD", "Management Unit"), ("BOMSEQ", "Sequence"),
       ("CPNITMREF", "Component"), ("CPNTYP", "Component Type"), ("LIKQTY", "Link Quantity")]
rows = read(f"{V8}/YA00408BOM_load8_boms.txt")
path = f"{OUT}/YA00408BOM_boms_MAPPED.xlsx"
wb = Workbook()
ws = wb.active
ws.title = "Data with Headings"
ws.append([c for c, _ in BOM])
ws.append([h for _, h in BOM])
for c in ws[2]:
    c.font = Font(bold=True)
fill(ws, 3, rows, {1, 2, 3, 4, 5, 6, 7, 9, 10})
add_sheet(wb, "Held back", [h for _, h in BOM] + ["Why"], held("BOMs"))
add_sheet(wb, "Missing components", ["Parent (loads)", "Component not in the product file"],
          [list(r) for r in rep["BOM missing components"].iter_rows(min_row=2, values_only=True)], [24, 30])
notes(wb, [["YA00408BOM - bills of materials, clean run"], [], ["Rows", len(rows)],
           ["Every parent and component", "is in the clean-run product file, and parent/BOM code/sequence is unique"],
           ["Held back", "11 lines on 3 bought-in (FGSL) products, 1 exact duplicate. One clashing sequence moved on"],
           ["Missing components", "92 parents load with one or more components missing (215 lines) - the components "
                                  "are not in the product load. SDI decision on the 14,304 products BOMs use but the load leaves out"]])
wb.save(path)
made.append((path, check(path, "Data with Headings", 3, rows), 0))

# product costs: the YITC layout seen earlier
YITC = [("Line Indicator", "Line Indicator", "I", "Hard code to letter I"), ("STOFCY", "Site", "S01A", "Hardcode to S01A"),
        ("ITMREF", "Product", "SHEETMETAL305", "Product code for this cost record"),
        ("CSTTYP", "Cost Type", 1, "Hard code to 1"), ("ITCSEQ", "Sequence no.", 1, "Hard code to 1"),
        ("ITCDAT", "Date Calculated", 20260101, "First day of financial year"),
        ("ITCSTRDAT", "To", 20260101, "First day of financial year"), ("ITCENDDAT", "To", 20261231, "Last day of financial year"),
        ("FIYNUM", "Fiscal year", 3, "Hard code to 3"), ("MATCST", "Material Cost", 9, "Total cost of product"),
        ("CLCQTY", "Calculation Quantity", 100, "Calculation quantity"), ("MATLEVCST", "Material Cost Level", 9, "Same as Material Cost")]
rows = read(f"{V8}/YITC_load8_product_costs.txt")
path = f"{OUT}/YITC_product_costs_MAPPED.xlsx"
wb = Workbook()
ws = wb.active
ws.title = "YITC"
ws.append([c for c, *_ in YITC])
ws.append([h for _, h, *_ in YITC])
fill(ws, 3, rows, {3, 4, 5, 6, 7, 8, 9, 10, 11})
g = wb.create_sheet("Guide")
for r in YITC:
    g.append(list(r))
add_sheet(wb, "Held back", [h for _, h, *_ in YITC] + ["Why"], held("Costs"))
notes(wb, [["YITC - product standard costs, clean run"], [], ["Rows", len(rows)],
           ["All under material", "Cost type 1, the whole cost in Material Cost - as Ethan's notes ask"],
           ["Held back", "28 second costs for codes that were on two products - one cost per product"]])
wb.save(path)
made.append((path, check(path, "YITC", 3, rows), 0))

# product-suppliers: the ZSDIITMSUP template as issued
rows = read(f"{V8}/ZSDIITMSUP_load8_product_suppliers.txt")
path = f"{OUT}/ZSDIITMSUP_product_suppliers_MAPPED.xlsx"
wb = load_workbook(f"{T}/ZSDIITMSUP.xlsx")
fill(wb["Template"], 3, rows, set())
notes(wb, [["ZSDIITMSUP - product-suppliers, clean run"], [], ["Rows", len(rows)],
           ["Built from", "Access purchase orders since September 2022: the supplier each product was last bought from"],
           ["Not loaded", "3,150 alternative suppliers - the template has no priority column. Ethan to add PIO if wanted"]])
wb.save(path)
made.append((path, check(path, "Template", 3, rows), 0))

# delivery addresses: the YA004BPCDL template as issued
rows = read(f"{V8}/YA004BPCDL_load2_delivery_addresses.txt")
path = f"{OUT}/YA004BPCDL_delivery_addresses_MAPPED.xlsx"
wb = load_workbook(f"{T}/YA004BPCDL.xlsx")
fill(wb["Data with headings"], 3, rows, set())
notes(wb, [["YA004BPCDL - customer delivery addresses, clean run"], [], ["Rows", len(rows)],
           ["Load after", "the customer file - every customer and address code matches it"],
           ["Company Name", "Access names every address after the company, so it is built from the store line and "
                            "postcode (TESCO PITTODRIE EXPRE AB24 3DF), 30 characters, Ethan's character rule"]])
wb.save(path)
made.append((path, check(path, "Data with headings", 3, rows), 0))

# works orders: our mapped guide, on the clean-run codes
rows = read(f"{V8}/YA004MFG_load8_works_orders.txt")
path = f"{OUT}/YA004MFG_works_orders_MAPPED_clean_run.xlsx"
shutil.copy(f"{BASE}/out_mfg/YA004MFG_guide_MAPPED.xlsx", path)
wb = load_workbook(path)
fill(wb["Data With Headings"], 3, rows, set())
wb.save(path)
made.append((path, check(path, "Data With Headings", 3, rows), 0))

for p, n, c in made:
    print(f"{os.path.basename(p):52} {n:6} rows checked" + (f"   {c} codes changed" if c else ""))
