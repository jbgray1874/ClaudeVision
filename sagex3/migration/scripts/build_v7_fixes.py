"""V7: the fixes from Ethan's import error review, plus the two new templates.

  Products, routes, prices, BOMs   every symbol out of product codes (Ethan: % and ? and
                                   the rest), upper case, applied to all four files alike
  Suppliers                        the 179 rejected on VAT: dummy VAT numbers blanked
  Customers                        TEC100 postcodes, two rows split by a ';' in the email
  ZSDIITMSUP                       product-supplier, Ethan's template, main supplier only
  YA004BPCDL                       customer delivery addresses, Ethan's template

Nothing is invented: a code is only cleaned, never renamed, and anything that needs a
decision is listed in V7_fix_report.xlsx rather than guessed.
"""
import csv
import io
import re
import zipfile
from collections import Counter, defaultdict

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

BASE = "/tmp/claude-0/-home-user-ClaudeVision/e9ffe9d9-c7dd-5e34-8a16-6cb3c65dadea/scratchpad"
V6 = f"{BASE}/out_std6"
OUT = f"{BASE}/out_v7"
ENC = "cp850"


def read(path):
    with open(path, newline="", encoding=ENC) as f:
        return [r for r in csv.reader(f, delimiter=";") if r and r[0].strip()]


def write(path, rows):
    with open(path, "w", newline="", encoding=ENC) as f:
        csv.writer(f, delimiter=";", lineterminator="\r\n").writerows(rows)


# ---- 1. product codes ----------------------------------------------------------
def clean(code, slash="-"):
    """Upper case; / and _ become hyphens; every other symbol goes."""
    s = code.strip().upper().replace("/", slash).replace("_", "-")
    return re.sub(r"[^A-Z0-9\-]", "", s)


itm = read(f"{V6}/ZSDIITM_load6_products.txt")
codes = list(dict.fromkeys(r[1] for r in itm))
newcode, taken = {}, Counter(clean(c) for c in codes)
for c in codes:
    n = clean(c)
    # a slash turned hyphen would land on a code that already exists: drop it instead
    if taken[n] > 1 and n != c and "/" in c and clean(c, "") not in taken:
        n = clean(c, "")
    newcode[c] = n
dup_before = {c: n for c, n in Counter(r[1] for r in itm).items() if n > 1}
after = Counter(newcode[r[1]] for r in itm)
new_dups = [c for c, n in after.items() if n > 1 and not any(newcode.get(o) == c for o in dup_before)]
assert not new_dups, new_dups
changes = [(c, newcode[c]) for c in codes if newcode[c] != c]


def recode(rows, cols):
    for r in rows:
        for i in cols:
            if r[i] in newcode:
                r[i] = newcode[r[i]]
    return rows


for r in itm:
    r[1] = newcode[r[1]]
rou = recode(read(f"{V6}/ZSDIROU2_load6_routes.txt"), [0])
yitc = recode(read(f"{V6}/YITC_load6_product_prices.txt"), [2])
bom = recode(read(f"{V6}/YA00408BOM_load6_loadable.txt"), [0, 8])
held = read(f"{V6}/YA00408BOM_load6_held_back.txt")
known = set(after)
recovered, still = [], []
for r in held:
    p, c = clean(r[0]), clean(r[8])
    if p in known and c in known:
        recovered.append((r[0], r[8], p, c))
        r[0], r[8] = p, c
        bom.append(r)
    else:
        still.append(r)

# ---- 2. suppliers ------------------------------------------------------------------
err = load_workbook(f"{BASE}/upl_1026/a7040949-Import_Error_Troubleshooting_Guide.xlsx")
sup_err = [r for r in err["Customers Troubleshooting List"].iter_rows(min_row=2, values_only=True) if r[0]]
cus_err = [r for r in err["Customers Troubleshooting Guide"].iter_rows(min_row=2, values_only=True) if r[0] and r[1] and r[0] != "Field Error"]
rejected = {r[0] for r in sup_err}
bps = read(f"{BASE}/upl2/bps.txt")
bps_codes = {r[1] for r in bps}
VAT = 6


def uk_dummy(r):
    """A UK supplier whose VAT number is a placeholder or another company's. Blank loads."""
    v = r[VAT].replace(" ", "").upper()
    return r[3] == "GB" and bool(v) and (v.startswith("TEMP") or v in ("PL5252230498", "PL7617501413")
                                         or not re.fullmatch(r"GB(\d{9}|\d{12})", v))


# Rejected suppliers are fixed whatever their country. Overseas ones that loaded are left
# alone: X3 took them, and a blank may not pass the EU tax rule.
sup_fix = []
for r in bps:
    if r[1] in rejected or uk_dummy(r):
        sup_fix.append([r[1], r[2], r[3], r[7], r[VAT], "rejected in UAT" if r[1] in rejected else "loaded",
                        "real VAT number needed - EU/overseas" if r[3] != "GB" else "blank is accepted for UK"])
        r[VAT] = ""
fixed_codes = {f[0] for f in sup_fix}
write(f"{OUT}/YA004BPS_load5_suppliers.txt", bps)
write(f"{OUT}/YA004BPS_reload_{len(rejected & bps_codes)}_rejected_suppliers.txt",
      [r for r in bps if r[1] in rejected])

# ---- 3. customers ------------------------------------------------------------------
bpc = read(f"{BASE}/upl2/bpc.txt")
cus_notes = []
for r in bpc:
    if len(r) == 35:                       # two emails split by ';' shifted every later field
        cus_notes.append([r[1], r[17], "two email addresses separated by ';' pushed the row out by "
                          f"one field. Kept {r[28]}; second address {r[29].strip()} left out"])
        del r[29]
    if r[1] == "TEC100" and r[17] == "001":      # postcode was in address line 2
        r[19], r[20], r[21], r[22], r[23] = r[19], r[21], "", r[20], ""
        cus_notes.append(["TEC100", "001", "postcode 28823 moved from address line 2 to the postcode field"])
    if r[1] == "TEC100" and r[17] == "002":      # postcode, town and country run together
        r[20] = r[20].replace("CostaRUA", "Costa, RUA")
        r[21], r[22] = "TROFA", "4785-598"
        cus_notes.append(["TEC100", "002", "'4785-598TROFAPORTUGAL' split into postcode 4785-598 and town TROFA"])
assert all(len(r) == 34 for r in bpc)
write(f"{OUT}/YA004BPC_load5_customers.txt", bpc)

# ---- 4. delivery addresses (YA004BPCDL) ---------------------------------------------
multi = Counter(r[1] for r in bpc)


def short(name):
    w = [x for x in name.upper().split() if x != "THE"]
    return " ".join(w[:2]) if w and len(w[0]) <= 3 else (w[0] if w else name.upper())


def dname(r):
    """Company, store line, postcode in 30 characters - the store line gives way, never the postcode."""
    if multi[r[1]] == 1:
        return r[18].strip()[:30].rstrip()
    who, pc = short(r[18]), r[22].strip().upper()
    room = 30 - len(who) - len(pc) - 2
    line = re.sub(r"\s+", " ", r[19].strip().upper())[:max(room, 0)].rstrip()
    return re.sub(r"\s+", " ", " ".join(x for x in (who, line, pc) if x))[:30].rstrip()


bpcdl = [[r[1], r[17], dname(r)] for r in bpc]
write(f"{OUT}/YA004BPCDL_load1_delivery_addresses.txt", bpcdl)

# ---- 5. product-supplier (ZSDIITMSUP) -----------------------------------------------
ps = load_workbook(f"{BASE}/out_psup/Product_supplier_list_V2.xlsx", read_only=True)
cand = [r for s in ("For UAT now", "Next run (V6)") for r in ps[s].iter_rows(min_row=2, values_only=True) if r[0]]
uat_codes = {r[1] for r in read(f"{BASE}/uploads_final/ZSDIITM_Cleansing.txt")}
main = {}
alts = []
for r in sorted(cand, key=lambda r: (r[0], r[4])):
    if r[0] in main:
        if r[2] != main[r[0]][2]:
            alts.append(r)
        continue
    main[r[0]] = r
sup_now = [[p, r[2], p] for p, r in sorted(main.items()) if p in uat_codes]
sup_v7 = [[newcode.get(p, p), r[2], newcode.get(p, p)] for p, r in sorted(main.items())]
write(f"{OUT}/ZSDIITMSUP_load1_UAT_now.txt", sup_now)
write(f"{OUT}/ZSDIITMSUP_load7_clean_run.txt", sup_v7)
wait_sup = sum(1 for r in sup_now if r[1] in fixed_codes and r[1] in rejected)

# ---- the zip -------------------------------------------------------------------------
write(f"{OUT}/ZSDIITM_load7_products.txt", itm)
write(f"{OUT}/ZSDIROU2_load7_routes.txt", rou)
write(f"{OUT}/YITC_load7_product_prices.txt", yitc)
write(f"{OUT}/YA00408BOM_load7_loadable.txt", bom)
write(f"{OUT}/YA00408BOM_load7_held_back.txt", still)

# ---- workbooks ----------------------------------------------------------------------
HF, FILL = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="44546A")


def sheet(wb, title, head, data, widths, first=False):
    ws = wb.active if first else wb.create_sheet(title)
    ws.title = title
    ws.append(head)
    for c in ws[1]:
        c.font, c.fill = HF, FILL
        c.alignment = Alignment(wrap_text=True, vertical="top")
    for d in data:
        ws.append(list(d))
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"
    return ws


def guide(name, title, fields, data, held_rows, held_head, notes):
    """Same tabs as the other mapped guides; Data with Headings is what Marc's macro reads."""
    wb = Workbook()
    m = sheet(wb, "Mapping", ["#", "Sage field", "X3 column", "Template example", "Guide note", "Source", "Status"],
              [[i, f[1], f[0], f[2], f[3], f[4], f[5]] for i, f in enumerate(fields, 1)],
              [4, 18, 12, 18, 40, 60, 12], first=True)
    m.insert_rows(1, 2)
    m["A1"] = f"{name}  -  {title}"
    m["A1"].font = Font(bold=True, size=13)
    n = wb.create_sheet("Notes")
    for r in notes:
        n.append(r)
    n["A1"].font = Font(bold=True, size=13)
    n.column_dimensions["A"].width = 44
    n.column_dimensions["B"].width = 100
    d = wb.create_sheet("Data with Headings")
    d.append([f[0] for f in fields])
    d.append([f[1] for f in fields])
    for c in d[2]:
        c.font = Font(bold=True)
    for r in data:
        d.append(r)
    for i in range(1, len(fields) + 1):
        d.column_dimensions[get_column_letter(i)].width = 24
    d.freeze_panes = "A3"
    g = wb.create_sheet("Guide")
    g.append(["Field", "Description", "Example 1", "Notes"])
    for c in g[1]:
        c.font = Font(bold=True)
    for f in fields:
        g.append([f[0], f[1], f[2], f[3]])
    for i, w in enumerate([12, 20, 22, 50], 1):
        g.column_dimensions[get_column_letter(i)].width = w
    if held_rows:
        sheet(wb, "Held back", held_head, held_rows, [24] * len(held_head))
    wb.save(f"{OUT}/{name}_guide_MAPPED.xlsx")


guide("ZSDIITMSUP", "Products-suppliers",
      [("ITMREF", "Product", "0-5MODMIRROR", "Sage Product Code", "Product code exactly as loaded in UAT", "Dynamic"),
       ("BPSNUM", "Supplier", "ABC100", "Sage Supplier Code", "Supplier last bought from, via XREF_SAGE_BPS", "Dynamic"),
       ("ITMREFBPS", "Supplier Product", "0-5MODMIRROR", "Sage Product Code again", "= ITMREF", "Dynamic")],
      sup_now,
      [[r[0], r[2], r[0], f"alternative supplier, priority {r[4]} - the template has no priority column"]
       for r in alts if r[0] in uat_codes],
      ["ITMREF", "BPSNUM", "ITMREFBPS", "Reason"],
      [["ZSDIITMSUP  -  what the data says, and what is still open"], [],
       ["Rows in the UAT load", len(sup_now)],
       ["   whose supplier was rejected in UAT", f"{wait_sup} - load YA004BPS_reload first"],
       ["Rows in the clean-run load (V7 codes)", len(sup_v7)],
       ["Alternative suppliers held back", len([a for a in alts if a[0] in uat_codes])],
       [],
       ["Built from", "Access purchase orders since September 2022. One row per product: the supplier "
                      "it was last bought from. Access holds no supplier against the part itself."],
       ["Open with Ethan", "The template has no priority column, so only the main supplier is in the load. "
                           "Add PIO if you want the alternatives loaded as priority 2, 3 ..."]])

guide("YA004BPCDL", "Customer delivery addresses",
      [("BPCNUM", "Customer Code", "TES101", "Customer Code", "Customer file (YA004BPC_load5)", "Dynamic"),
       ("BPAADD", "Ship-to Address", "001", "Address code matches the customer import", "Same file, address code", "Dynamic"),
       ("BPDNAM", "Company Name", "TESCO Cardiff Central", "Recognisable name for the address",
        "One address: the address name. Several: first word of the name, address line 1, postcode, 30 characters", "Dynamic")],
      bpcdl, [], [],
      [["YA004BPCDL  -  what the data says, and what is still open"], [],
       ["Rows", len(bpcdl)], ["Customers", len(multi)],
       ["Customers with more than one address", sum(1 for v in multi.values() if v > 1)],
       [],
       ["Name", "The address name in Access is the company for every address (all 1,399 Tesco addresses are "
                "TESCO STORES LIMITED), so the name is built from the store line and postcode, e.g. "
                "TESCO PITTODRIE EXPRESS AB24 3DF."],
       ["Load after", "the customer file, which creates the addresses these point to."]])

rep = Workbook()
s = rep.active
s.title = "Summary"
for line in [
    ["V7 - fixes from Ethan's import error review"], [],
    ["Products, routes, prices, BOMs"],
    ["Product codes cleaned", len(changes), "upper case, / and _ to hyphens, every other symbol out"],
    ["   of which had a symbol", sum(1 for o, n in changes if o.upper() != n)],
    ["   of which upper case only", sum(1 for o, n in changes if o.upper() == n)],
    ["New duplicate codes created", 0],
    ["Duplicate codes ALREADY in the product file", len(dup_before), "two products on one code - needs a decision, see tab"],
    ["BOM lines recovered from held back", len(recovered)],
    ["BOM lines still held back", len(still), "parent or component is not in the product file at all"],
    [],
    ["Suppliers"],
    ["Rejected in UAT (Ethan's list)", len(rejected), f"{len(rejected - bps_codes)} not in the loaded file: "
                                                       + ", ".join(sorted(rejected - bps_codes))],
    ["Dummy VAT numbers blanked", len(sup_fix)],
    ["   UK - blank is accepted (9 loaded with none)", sum(1 for f in sup_fix if f[2] == "GB")],
    ["   EU and overseas - real VAT number needed", sum(1 for f in sup_fix if f[2] != "GB")],
    [],
    ["Customers"],
    ["Customers rejected in UAT", len({r[1] for r in cus_err if r[1]}), f"{sum(1 for r in cus_err if r[1])} errors"],
    ["   VACBPR - all 10 EU customers", "tax rule EU was rejected on every EU customer, so it does not look like a customer tax "
                                         "rule in UAT. The one ROW customer uses ROWC and loaded. What is the EU customer code?"],
    ["   POSCOD - TEC100", "fixed, see Customer fixes"],
    [],
    ["Product-supplier rows (ZSDIITMSUP)", len(sup_now)],
    ["Delivery addresses (YA004BPCDL)", len(bpcdl)],
]:
    s.append(line)
s["A1"].font = Font(bold=True, size=13)
for c, w in zip("ABC", (46, 14, 80)):
    s.column_dimensions[c].width = w
sheet(rep, "Product code changes", ["Old code", "New code", "Why"],
      [[o, n, "symbol removed" if o.upper() != n else "upper case"] for o, n in changes], [26, 26, 16])
sheet(rep, "Duplicate product codes", ["Product code", "Category", "Description", "Description 3"],
      [[r[1], r[0], r[2], r[4]] for r in itm if any(newcode[c] == r[1] for c in dup_before)], [22, 8, 34, 34])
sheet(rep, "BOM lines recovered", ["Parent was", "Component was", "Parent", "Component"], recovered, [24] * 4)
sheet(rep, "Supplier VAT fixes", ["Supplier", "Name", "Country", "Tax rule", "VAT number removed", "UAT", "Action"],
      sup_fix, [10, 32, 8, 8, 16, 14, 34])
sheet(rep, "Customer errors", ["Field", "Customer", "Line in log"], cus_err, [10, 10, 10])
sheet(rep, "Customer fixes", ["Customer", "Address", "Fix"], cus_notes, [10, 8, 90])
rep.save(f"{OUT}/V7_fix_report.xlsx")

with zipfile.ZipFile(f"{OUT}/V7_load_files.zip", "w", zipfile.ZIP_DEFLATED) as z:
    for n in ["ZSDIITM_load7_products.txt", "ZSDIROU2_load7_routes.txt", "YITC_load7_product_prices.txt",
              "YA00408BOM_load7_loadable.txt", "YA00408BOM_load7_held_back.txt", "ZSDIITMSUP_load7_clean_run.txt",
              "ZSDIITMSUP_load1_UAT_now.txt", "YA004BPS_load5_suppliers.txt",
              f"YA004BPS_reload_{len(rejected & bps_codes)}_rejected_suppliers.txt",
              "YA004BPC_load5_customers.txt", "YA004BPCDL_load1_delivery_addresses.txt"]:
        z.write(f"{OUT}/{n}", n)

print("codes changed", len(changes), "dups before", len(dup_before), "recovered", len(recovered), "still", len(still))
print("suppliers fixed", len(sup_fix), "rejected in file", len(rejected & bps_codes), "sup_now", len(sup_now),
      "wait", wait_sup, "v7", len(sup_v7), "alts", len(alts), "bpcdl", len(bpcdl))
