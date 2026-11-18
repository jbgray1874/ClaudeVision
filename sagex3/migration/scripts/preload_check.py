"""Pre-load check: test a hand-over set against every rule X3 has rejected on, before Ethan loads it.

    python preload_check.py <hand-over folder> <out .xlsx> [--bank <YA004BPSC .txt>]

Reads the .txt load files (; separated, cp850) in the folder and writes one workbook:
  Summary        every check, the file, how many records fail, PASS / FIX / NOTE
  Placeholders   every value that is provisional or a placeholder, with its owner
  one tab per check that found something, listing the records

FIX   = would be rejected or load wrong: fix before the load.
NOTE  = loads, but is a known gap (a placeholder, a held record) - listed so nobody forgets it.
NOTE* = data quality X3 ACCEPTED in Run 4 (the same patterns are on customers / suppliers that loaded):
        odd or missing GB postcodes, several emails in a field, regions on US / AU / AE addresses.
        Calibrated 18 Nov against Run 4's results - X3 rejected only the six customers and the FR / ES
        suppliers. Worth tidying in Access; not a reason to stop a load.

Rules, from Runs 2-4 and Ethan's notes:
  customers   one default address per customer; postcode format for the country; GB has a postcode;
              State/Region for AE, CA, AU, US (X3's XSAT); ACCCOD is ID / EU / STD; tax rule set;
              one email per field; every customer's addresses are in the delivery-address file
  suppliers   unique codes; FR suppliers have a valid VAT (key + SIREN) and SIRET (Luhn), ES a VAT;
              tax rule set; GB postcode format; no placeholder (MOCK) left unflagged
  bank        every bank row's supplier is in the supplier file; BIDNUM = XXXX + 6 + 8 digits
  products    unique codes; category FGML / FGSL / PHANT / RAWML; every BOM parent / component,
              route product, cost and product-supplier link points at a product in the file;
              every route work centre is an X3 work centre we map to; every product-supplier
              link's supplier is in the supplier file
"""
import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "rebuild"))
from apply_supplier_ids import fr_vat, is_mock, luhn  # noqa: E402
from fix_customer_addresses import valid  # noqa: E402
from run3_fix_lists import POSTCODE  # noqa: E402

CATEGORIES = {"FGML", "FGSL", "PHANT", "RAWML"}
ACCCODES = {"ID", "EU", "STD"}
REGION = {"AE", "CA", "AU", "US"}
GREEN, AMBER, RED = (PatternFill("solid", fgColor=c) for c in ("C6EFCE", "FFEB9C", "FFC7CE"))


def read(path):
    if not path.exists():
        return []
    with open(path, encoding="cp850", newline="") as f:
        return [r for r in csv.reader(f, delimiter=";") if len(r) > 1]


def main(folder, out, bank_path=None):
    d = Path(folder)
    f = lambda name: read(d / f"{name}_MAPPED.txt")
    bpc, dl, bps = f("YA004BPC_customers"), f("YA004BPCDL_delivery_addresses"), f("YA004BPS_suppliers")
    itm, cost, bom = f("ZSDIITM_products"), f("YITC_product_costs"), f("YA00408BOM_boms")
    rou, sup = f("ZSDIROU2_routes"), f("ZSDIITMSUP_product_suppliers")
    bank = read(Path(bank_path)) if bank_path else []
    wcs = {r["x3_work_centre"] for r in csv.DictReader(open(HERE.parent / "rebuild" / "work_centres.csv"))}

    checks = []   # (file, check, level, rows, head)

    def add(file, name, level, rows, head):
        checks.append((file, name, level, rows, head))

    # ---- customers -----------------------------------------------------------------------------
    by_cust = defaultdict(list)
    for r in bpc:
        by_cust[r[1]].append(r)
    add("YA004BPC", "Exactly one default address (BPAADDFLG 2) per customer", "FIX",
        [[c, sum(1 for r in rs if r[32] == "2")] for c, rs in by_cust.items() if sum(1 for r in rs if r[32] == "2") != 1],
        ["Customer", "Default addresses"])
    add("YA004BPC", "Postcode matches the country's format (XPOSCOD)", "NOTE*",
        [[r[1], r[17], r[24], r[22]] for r in bpc if r[22] and r[24] in POSTCODE and not valid(r[24], r[22].upper())],
        ["Customer", "Address", "Country", "Postcode"])
    add("YA004BPC", "GB address has a postcode", "NOTE*",
        [[r[1], r[17], r[19]] for r in bpc if r[24] == "GB" and not r[22].strip()],
        ["Customer", "Address", "Line 1"])
    add("YA004BPC", "State/Region for AE, CA, AU, US (XSAT) - the region column has no X3 field code yet", "NOTE*",
        [[r[1], r[17], r[24], r[23], "default" if r[32] == "2" else ""] for r in bpc if r[24] in REGION],
        ["Customer", "Address", "Country", "Region (not received by X3)", "Default?"])
    add("YA004BPC", "ACCCOD is ID / EU / STD", "FIX",
        [[c, rs[0][16]] for c, rs in by_cust.items() if rs[0][16] not in ACCCODES], ["Customer", "ACCCOD"])
    add("YA004BPC", "Tax rule (VACBPR) set", "FIX",
        [[c] for c, rs in by_cust.items() if not rs[0][14].strip()], ["Customer"])
    add("YA004BPC", "One email per field (a ';' shifts the row)", "NOTE*",
        [[r[1], r[17], r[27], r[28]] for r in bpc if ";" in (r[27] + r[28]) or r[27].count("@") > 1 or r[28].count("@") > 1],
        ["Customer", "Address", "Email", "Email"])
    dl_keys = {(r[0], r[1]) for r in dl}
    bpc_keys = {(r[1], r[17]) for r in bpc}
    add("YA004BPCDL", "Delivery-address file matches the customer file, address for address", "FIX",
        [[a, b, "in customers, not delivery addresses"] for a, b in sorted(bpc_keys - dl_keys)] +
        [[a, b, "in delivery addresses, not customers"] for a, b in sorted(dl_keys - bpc_keys)],
        ["Customer", "Address", "Where"])

    # ---- suppliers -----------------------------------------------------------------------------
    codes = Counter(r[1] for r in bps)
    add("YA004BPS", "Supplier codes unique", "FIX", [[c, n] for c, n in codes.items() if n > 1], ["Supplier", "Rows"])
    bad_ids, mocks = [], []
    for r in bps:
        cry, crn, vat = r[3], r[5].strip(), r[6].strip().upper()
        if is_mock(vat) or is_mock(crn):
            mocks.append([r[1], cry, vat, crn])
        if cry == "FR":
            why = []
            if not re.fullmatch(r"FR\d{11}", vat) or fr_vat(vat[4:]) != vat:
                why.append("VAT missing or key wrong")
            if not (len(crn) == 14 and crn.isdigit() and luhn(crn) and crn[:9] == vat[4:]):
                why.append("SIRET missing, fails Luhn, or not this VAT's SIREN")
            if why:
                bad_ids.append([r[1], cry, vat, crn, "; ".join(why)])
        elif cry == "ES" and not re.fullmatch(r"ES[A-Z0-9]\d{7}[A-Z0-9]", vat):
            bad_ids.append([r[1], cry, vat, crn, "ES VAT missing or wrong format"])
    add("YA004BPS", "FR suppliers: VAT (key + SIREN) and SIRET; ES suppliers: VAT", "FIX", bad_ids,
        ["Supplier", "Country", "VAT", "SIRET", "Why"])
    add("YA004BPS", "Tax rule (VACBPR) set", "FIX", [[r[1]] for r in bps if not r[7].strip()], ["Supplier"])
    add("YA004BPS", "GB postcode format", "NOTE*",
        [[r[1], r[17]] for r in bps if r[18] == "GB" and r[17].strip() and not valid("GB", r[17].upper())],
        ["Supplier", "Postcode"])

    # ---- bank ----------------------------------------------------------------------------------
    if bank:
        sups = set(codes)
        add("YA004BPSC", "Bank row's supplier is in the supplier file", "FIX",
            [[r[0]] for r in bank if r[0] not in sups], ["Supplier"])
        add("YA004BPSC", "Bank account = XXXX + 6-digit sort code + 8-digit account", "FIX",
            [[r[0], "format wrong"] for r in bank if not re.fullmatch(r"XXXX\d{14}", r[3])], ["Supplier", "Why"])

    # ---- products and their links --------------------------------------------------------------
    prod = Counter(r[1] for r in itm)
    pset = set(prod)
    add("ZSDIITM", "Product codes unique", "FIX", [[c, n] for c, n in prod.items() if n > 1], ["Product", "Rows"])
    add("ZSDIITM", "Category is FGML / FGSL / PHANT / RAWML", "FIX",
        [[r[1], r[0]] for r in itm if r[0] not in CATEGORIES], ["Product", "Category"])
    add("YITC", "Cost's product is in the product file", "FIX",
        [[r[2]] for r in cost if r[2] not in pset], ["Product"])
    add("YA00408BOM", "BOM parent and component are in the product file", "FIX",
        [[r[0], r[8], "parent" if r[0] not in pset else "component"] for r in bom if r[0] not in pset or r[8] not in pset],
        ["Parent", "Component", "Missing"])
    add("ZSDIROU2", "Route product is in the product file", "FIX",
        sorted({(r[0],) for r in rou if r[0] not in pset}), ["Product"])
    add("ZSDIROU2", "Route work centre is one we map to", "FIX",
        sorted({(r[7],) for r in rou if r[7] not in wcs}), ["Work centre"])
    add("ZSDIITMSUP", "Product-supplier link: product and supplier both in the files", "FIX",
        [[r[0], r[1], "product" if r[0] not in pset else "supplier"] for r in sup if r[0] not in pset or r[1] not in codes],
        ["Product", "Supplier", "Missing"])

    # ---- placeholders (NOTE) -------------------------------------------------------------------
    zero = [r[2] for r in cost if r[9] in ("0", "0.0", "")]
    held = d / "Held_addresses_for_later.xlsx"
    ph = ([["YA004BPS", r[0], f"VAT {r[2]} / SIRET {r[3]}", "MOCK - real number from the French register / Finance"] for r in mocks]
          + [["YITC", p, "cost 0", "no cost in Access - SDI to price"] for p in zero])
    add("Placeholders", "Placeholder values in the files (load, but must be replaced)", "NOTE", ph,
        ["File", "Record", "Value", "Owner / action"])
    if held.exists():
        add("Held_addresses_for_later.xlsx", "Addresses held back until X3's country set-up is fixed", "NOTE",
            [["see the file", "", "", "Ethan: region field / country set-up"]], ["", "", "", ""])

    # ---- workbook ------------------------------------------------------------------------------
    wb = Workbook()
    s = wb.active
    s.title = "Summary"
    s.append([f"Pre-load check - {d.name}"])
    s["A1"].font = Font(bold=True, size=13)
    s.append(["FIX = would be rejected or load wrong: fix first.  NOTE = loads, a known gap / placeholder.  "
              "NOTE* = data quality X3 accepted in Run 4."])
    s.append([])
    s.append(["File", "Check", "Records", "Result"])
    for c in s[4]:
        c.font = Font(bold=True)
    for i, (file, name, level, rows, head) in enumerate(checks, 1):
        result = "PASS" if not rows else level
        s.append([file, name, len(rows), result])
        s.cell(s.max_row, 4).fill = GREEN if result == "PASS" else AMBER if result.startswith("NOTE") else RED
        if rows:
            t = wb.create_sheet(f"{i:02d} {file}"[:31])
            t.append([name])
            t["A1"].font = Font(bold=True)
            t.append(head)
            for r in rows:
                t.append(list(r))
    for col, w in zip("ABCD", (16, 90, 10, 8)):
        s.column_dimensions[col].width = w
    wb.save(out)
    fails = [(c[0], c[1], len(c[3])) for c in checks if c[3] and c[2] == "FIX"]
    notes = [(c[2], c[0], c[1], len(c[3])) for c in checks if c[3] and c[2] != "FIX"]
    print(f"{len(checks)} checks: {sum(1 for c in checks if not c[3])} pass, {len(fails)} to fix, {len(notes)} notes")
    for x in fails:
        print("  FIX ", x)
    for x in notes:
        print("  NOTE", x)
    print("written", out)


if __name__ == "__main__":
    a = sys.argv[1:]
    b = None
    if "--bank" in a:
        i = a.index("--bank")
        b = a[i + 1]
        del a[i:i + 2]
    main(a[0], a[1], b)
