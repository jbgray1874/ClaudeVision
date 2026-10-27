"""V8: Track 2 master data, for a clean run. Builds on V7 (codes already cleaned).

  Ethan's character rule on every text field: letters, numbers, spaces, - _ . only.
      & -> AND, / -> -, accents dropped, anything else removed, nothing longer than
      the longest value the field already holds. Emails, phones and websites untouched.
  Products     a code on two products keeps one row (the manufactured one if the code has
               a BOM or route); blank first descriptions filled from description 3, then 2
  Costs        one cost per product
  BOMs         exact duplicate lines dropped, a clashing sequence moved to the next free one,
               BOMs on bought-in (FGSL) products held back
  Routes       routes on bought-in (RAWML, FGSL) products held back
  Suppliers    tax rule EU -> ROWS (X3 has no EU rule)
  Customers    EU -> ROW / ROWC, as UNI100 which loaded; ROL100's 8-digit VAT number blanked
  Then the delivery addresses, product-suppliers and works orders are rebuilt to agree.
Every row held back is listed with its reason in V8_track2_report.xlsx.
"""
import csv
import re
import unicodedata
import zipfile
from collections import Counter, defaultdict

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

BASE = "/tmp/claude-0/-home-user-ClaudeVision/e9ffe9d9-c7dd-5e34-8a16-6cb3c65dadea/scratchpad"
V7 = f"{BASE}/out_v7"
OUT = f"{BASE}/out_v8"
ENC = "cp850"
MAKE = {"FGML", "PHANT"}                  # categories X3 manufactures


def read(p):
    with open(p, newline="", encoding=ENC) as f:
        return [r for r in csv.reader(f, delimiter=";") if r and r[0].strip()]


def write(p, rows):
    with open(p, "w", newline="", encoding=ENC) as f:
        csv.writer(f, delimiter=";", lineterminator="\r\n").writerows(rows)


def x3(v):
    # spelled out the same way as in the Track 1 files
    for x, y in (("Ø", "DIA "), ("ø", "dia "), ("°", " deg"), ("½", "1/2"),
                 ("¼", "1/4"), ("–", "-"), ("—", "-"), ("’", "'")):
        v = v.replace(x, y)
    v = re.sub("(?<=[A-Za-z])£(?=s\\b)", "", v)    # Dowel£s: an apostrophe Access lost
    v = re.sub("£s\\b", " GBP", v).replace("£", " GBP ")
    v = v.replace(" ? ", " - ")
    v = unicodedata.normalize("NFKD", v)
    v = "".join(ch for ch in v if not unicodedata.combining(ch))
    v = v.replace("&", " AND ").replace("/", "-")
    return " ".join(re.sub(r"[^A-Za-z0-9._\- ]", "", v).split())


log, held = Counter(), defaultdict(list)


def clean_cols(rows, cols, name):
    for c in cols:
        limit = max(len(r[c]) for r in rows)
        for r in rows:
            v = x3(r[c])[:limit].rstrip()
            if v != r[c]:
                r[c] = v
                log[f"{name}: text cells cleaned"] += 1


# ---- products ------------------------------------------------------------------------
itm = read(f"{V7}/ZSDIITM_load7_products.txt")
bom = read(f"{V7}/YA00408BOM_load7_loadable.txt")
rou = read(f"{V7}/ZSDIROU2_load7_routes.txt")
yitc = read(f"{V7}/YITC_load7_product_prices.txt")
made = {r[0] for r in bom} | {r[0] for r in rou}
keep, seen = [], {}
for r in itm:
    c = r[1]
    if c not in seen:
        seen[c] = len(keep)
        keep.append(r)
        continue
    first = keep[seen[c]]
    # the manufactured version wins when the code has a BOM or route
    if c in made and r[0] in MAKE and first[0] not in MAKE:
        held["Products"].append(first + ["code on two products - the bought-in version, the code has a BOM"])
        keep[seen[c]] = r
    else:
        held["Products"].append(r + ["code on two products - second row, X3 keeps one product per code"])
itm = keep
for r in itm:
    if not r[2].strip():
        r[2] = (r[4].strip() or r[3].strip() or r[1])[:30]
        log["Products: blank description filled from description 3, 2 or the code"] += 1
clean_cols(itm, [2, 3, 4], "Products")
cat = {r[1]: r[0] for r in itm}

# ---- costs ---------------------------------------------------------------------------
seen = set()
out = []
for r in yitc:
    if r[2] in seen:
        held["Costs"].append(r + ["second cost for a product code that was on two products"])
    else:
        seen.add(r[2])
        out.append(r)
yitc = out

# ---- BOMs ----------------------------------------------------------------------------
out, lines, seqs = [], set(), defaultdict(set)
for r in bom:
    if cat.get(r[0]) not in MAKE:
        held["BOMs"].append(r + [f"BOM on a bought-in product ({cat.get(r[0])}) - X3 builds manufactured products only"])
        continue
    if tuple(r) in lines:
        held["BOMs"].append(r + ["exact duplicate of another line"])
        continue
    lines.add(tuple(r))
    seqs[(r[0], r[1])].add(int(r[7]))
    out.append(r)
fixed = Counter()
for r in out:                                        # a sequence used twice: second moves on
    k = (r[0], r[1], r[7])
    fixed[k] += 1
    if fixed[k] > 1:
        nxt = max(seqs[(r[0], r[1])]) + 10
        seqs[(r[0], r[1])].add(nxt)
        r[7] = str(nxt)
        log["BOMs: clashing sequence moved to the next free number"] += 1
bom = out
bom_held = read(f"{V7}/YA00408BOM_load7_held_back.txt")

# ---- routes --------------------------------------------------------------------------
out = []
for r in rou:
    if cat.get(r[0]) not in MAKE:
        held["Routes"].append(r + [f"route on a bought-in product ({cat.get(r[0])}) - X3 routes manufactured products only"])
    else:
        out.append(r)
rou = out
clean_cols(rou, [8], "Routes")

# ---- suppliers -----------------------------------------------------------------------
bps = read(f"{V7}/YA004BPS_load5_suppliers.txt")
for r in bps:
    if r[7] == "EU":
        r[7] = "ROWS"
        log["Suppliers: tax rule EU set to ROWS"] += 1
    if r[6].upper().startswith("TEMP"):                 # a placeholder, not a VAT number
        r[6] = ""
        log[f"Suppliers: placeholder VAT number blanked ({r[1]})"] += 1
clean_cols(bps, [2, 11, 12, 13, 14, 15], "Suppliers")

# ---- customers -----------------------------------------------------------------------
bpc = read(f"{V7}/YA004BPC_load5_customers.txt")
for r in bpc:
    if r[0] == "EU" or r[14] == "EU":
        r[0], r[14] = "ROW", "ROWC"
        log["Customers: EU address rows set to ROW / ROWC"] += 1
    for c in (10, 12):
        v = r[c].replace(" ", "")
        if v.startswith("GB") and not re.fullmatch(r"GB(\d{9}|\d{12})", v):
            r[c] = ""
            log[f"Customers: invalid GB VAT number blanked ({r[1]})"] += 1
clean_cols(bpc, [2, 4, 18, 19, 20, 21, 23, 33], "Customers")

# ---- delivery addresses, from the cleaned customers --------------------------------
multi = Counter(r[1] for r in bpc)


def short(name):
    w = [x for x in name.upper().split() if x != "THE"]
    return " ".join(w[:2]) if w and len(w[0]) <= 3 else (w[0] if w else name.upper())


def dname(r):
    if multi[r[1]] == 1:
        return r[18].strip()[:30].rstrip()
    who, pc = short(r[18]), r[22].strip().upper()
    room = 30 - len(who) - len(pc) - 2
    line = " ".join(r[19].upper().split())[:max(room, 0)].rstrip()
    return " ".join(" ".join(x for x in (who, line, pc) if x).split())[:30].rstrip()


bpcdl = [[r[1], r[17], x3(dname(r))] for r in bpc]

# ---- product-suppliers and works orders, re-checked against the final files ----------
products = set(cat)
sup_codes = {r[1] for r in bps}
itmsup = []
for r in read(f"{V7}/ZSDIITMSUP_load7_clean_run.txt"):
    if r[0] in products and r[1] in sup_codes:
        itmsup.append(r)
    else:
        held["Product-suppliers"].append(r + ["product or supplier not in the final files"])
bom_parents, rou_products = {r[0] for r in bom}, {r[0] for r in rou}
mfg = []
for r in read(f"{BASE}/out_mfg/YA004MFG_load7_clean_run.txt"):
    if r[2] in bom_parents and r[2] in rou_products:
        mfg.append(r)
    else:
        held["Works orders"].append(r + ["product's BOM or route is not in the final files"])

# ---- checks: nothing goes out that X3 would reject on structure ----------------------
assert len({r[1] for r in itm}) == len(itm)
assert len({r[2] for r in yitc}) == len(yitc) and all(r[2] in products for r in yitc)
assert len({(r[0], r[1], r[7]) for r in bom}) == len(bom)
assert all(r[0] in products and r[8] in products for r in bom)
assert len({(r[0], r[1], r[6]) for r in rou}) == len(rou) and all(r[0] in products for r in rou)
assert len({r[1] for r in bps}) == len(bps)
assert len({(r[1], r[17]) for r in bpc}) == len(bpc)
assert len({(r[0], r[1]) for r in bpcdl}) == len(bpcdl)
assert all(r[7] in ("DOM", "ROWS", "XVRS") for r in bps) and all(r[14] in ("DOM", "ROWC") for r in bpc)
bad = re.compile(r"[^A-Za-z0-9._\- ]")
for rows, cols in ((itm, [1, 2, 3, 4]), (rou, [0, 8]), (bom, [0, 8]), (yitc, [2]),
                   (bps, [2, 11, 12, 13, 14, 15]), (bpc, [2, 4, 18, 19, 20, 21, 23, 33]), (bpcdl, [2])):
    assert not any(bad.search(r[c]) for r in rows for c in cols)

FILES = {
    "YA004BPS_load6_suppliers.txt": bps,
    "YA004BPC_load6_customers.txt": bpc,
    "YA004BPCDL_load2_delivery_addresses.txt": bpcdl,
    "ZSDIITM_load8_products.txt": itm,
    "ZSDIITMSUP_load8_product_suppliers.txt": itmsup,
    "YA00408BOM_load8_boms.txt": bom,
    "ZSDIROU2_load8_routes.txt": rou,
    "YITC_load8_product_costs.txt": yitc,
    "YA004MFG_load8_works_orders.txt": mfg,
}
for n, rows in FILES.items():
    write(f"{OUT}/{n}", rows)
with zipfile.ZipFile(f"{OUT}/Track2_V8_clean_run_load_files.zip", "w", zipfile.ZIP_DEFLATED) as z:
    for n in FILES:
        z.write(f"{OUT}/{n}", n)

# ---- report --------------------------------------------------------------------------
HF, FILL = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="44546A")
wb = Workbook()
s = wb.active
s.title = "Summary"
s.append(["Track 2 - master data V8, for the clean run"])
s["A1"].font = Font(bold=True, size=13)
s.append([])
s.append(["Load order", "File", "Rows", "Held back"])
for c in s[3]:
    c.font, c.fill = HF, FILL
ORDER = [("Suppliers", "YA004BPS_load6_suppliers.txt", None), ("Customers", "YA004BPC_load6_customers.txt", None),
         ("Delivery addresses", "YA004BPCDL_load2_delivery_addresses.txt", None),
         ("Products", "ZSDIITM_load8_products.txt", "Products"),
         ("Product-suppliers", "ZSDIITMSUP_load8_product_suppliers.txt", "Product-suppliers"),
         ("BOMs", "YA00408BOM_load8_boms.txt", "BOMs"), ("Routes", "ZSDIROU2_load8_routes.txt", "Routes"),
         ("Product costs", "YITC_load8_product_costs.txt", "Costs"),
         ("Works orders", "YA004MFG_load8_works_orders.txt", "Works orders")]
for i, (what, n, h) in enumerate(ORDER, 1):
    s.append([f"{i}. {what}", n, len(FILES[n]), len(held.get(h, [])) if h else 0])
s.append([])
s.append(["Changes", "Count"])
for c in s[s.max_row]:
    c.font = Font(bold=True)
for k, v in sorted(log.items()):
    s.append([k, v])
s.append([])
s.append(["BOM lines held back in V7 (parent or component not a product)", len(bom_held)])
s.append(["Parents whose BOM loads without a missing component", len({r[0] for r in bom_held if r[0] in products})])
s.append([])
s.append(["For the next run - mocked for UAT"])
s.append(["EU customers ROWC, EU suppliers ROWS", "X3 has no EU tax rule. Finance to confirm the right rule for EU trade"])
s.append(["ROL100 VAT number", "GB76361992 is 8 digits, blanked. Finance to supply the real one"])
s.append(["Codes on two products", "One row loaded, the other held back. SDI to decide which product keeps each code"])
for c, w in zip("ABCD", (62, 44, 10, 10)):
    s.column_dimensions[c].width = w
for name, rows in held.items():
    ws = wb.create_sheet(f"Held - {name}"[:31])
    for r in rows:
        ws.append(r)
    ws.freeze_panes = "A1"
ws = wb.create_sheet("BOM missing components")
ws.append(["Parent (loads)", "Missing component"])
for r in bom_held:
    if r[0] in products:
        ws.append([r[0], r[8]])
wb.save(f"{OUT}/V8_track2_report.xlsx")

for i, (what, n, h) in enumerate(ORDER, 1):
    print(f"{i}. {what:20} {n:44} {len(FILES[n]):7} held {len(held.get(h, [])) if h else 0}")
for k, v in sorted(log.items()):
    print("  ", k, v)
