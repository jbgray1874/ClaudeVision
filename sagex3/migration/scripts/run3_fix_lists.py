"""Run 3 (4 Nov): the master-data fixes Acuity's Run 2 notes ask for, as one workbook.

Each list says what is wrong, what it needs and what else fails because of it, so the fix can
be made before the opening transactions go in:
  * Suppliers   - the FR suppliers X3 rejected (EECNUM and CRN blank), and the POH lines and
                  BISY items that fail with them (BAL500, SOG500)
  * Customers   - the six customers X3 rejected (postcode format, missing State/Region), and the
                  delivery addresses that fail with them (1,425 of the "1,400+")
  * FGSL stock  - FGSL products holding stock: X3 rejects stock on a product that isn't
                  stock-managed (SMR, 1,500+ errors)
  * PHANT sold  - PHANT products on open sales orders (SOHPJ "Sales product missing")
Names are SDI data: the workbook is written to the working folder, never to git.

Usage:
    python run3_fix_lists.py
"""
import os
import re
import sys
from collections import Counter, defaultdict

from openpyxl import Workbook, load_workbook

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "rebuild"))
from common import add_sheet, notes  # noqa: E402

BASE = "/tmp/claude-0/-home-user-ClaudeVision/e9ffe9d9-c7dd-5e34-8a16-6cb3c65dadea/scratchpad"
SHEETS = os.environ.get("SHEETS_DIR", f"{BASE}/out_sheets")
OPEN_ITEMS = os.environ.get("OPEN_ITEMS_DIR", f"{BASE}/out_run3")
OUT = os.environ.get("OUT_DIR", f"{BASE}/out_run3")

# from Ethan's Run 2 notes (28 Oct)
FAILED_SUPPLIERS = ["AMG500", "AGE500", "GAL500", "GRO500", "ICE500", "PLS500", "VUS500", "SOG500", "BAL500",
                    "BUR500", "ECO500"]
POSTCODE_ERRORS = ["TEC100", "TEC105", "UNI103"]       # XPOSCOD
STATE_ERRORS = ["DRE100", "MAR101", "PER101"]          # XSAT

# postcode formats, for the countries in the failing customers' addresses
POSTCODE = {
    "GB": r"[A-Z]{1,2}\d[A-Z\d]? ?\d[A-Z]{2}", "JE": r"JE\d[A-Z\d]? ?\d[A-Z]{2}", "GG": r"GY\d[A-Z\d]? ?\d[A-Z]{2}",
    "IM": r"IM\d[A-Z\d]? ?\d[A-Z]{2}", "IE": r"[A-Z]\d[\dW] ?[A-Z\d]{4}", "ES": r"\d{5}", "FR": r"\d{5}",
    "DE": r"\d{5}", "IT": r"\d{5}", "FI": r"\d{5}", "PT": r"\d{4}-\d{3}", "NL": r"\d{4} ?[A-Z]{2}",
    "BE": r"\d{4}", "DK": r"\d{4}", "AT": r"\d{4}", "NO": r"\d{4}", "AU": r"\d{4}", "SE": r"\d{3} ?\d{2}",
    "PL": r"\d{2}-\d{3}", "CZ": r"\d{3} ?\d{2}", "SG": r"\d{6}", "CA": r"[A-Z]\d[A-Z] ?\d[A-Z]\d",
    "US": r"\d{5}(-\d{4})?",
}
NO_POSTCODE = {"HK", "AE"}                              # countries with no postcodes
NEEDS_STATE = {"CA", "AU", "AE", "US"}                  # X3 asks for State/Region (XSAT in Run 2)


def data(name, sheet, first):
    ws = load_workbook(f"{SHEETS}/{name}", read_only=True)[sheet]
    rows = list(ws.iter_rows(values_only=True))
    return rows[0], rows[first - 1:]


def main():
    # ---- suppliers -------------------------------------------------------------------------
    codes, bps = data("YA004BPS_suppliers_MAPPED.xlsx", "Data with Headings", 3)
    c = {k: i for i, k in enumerate(codes) if k}
    poh_head, poh = data("YA004POH_guide_MAPPED_clean_run.xlsx", "Data with Headings", 3)
    poh_sup = Counter(r[poh_head.index("BPSNUM")] for r in poh if r[0])
    bisy = [r for r in load_workbook(f"{OPEN_ITEMS}/YA004BISY_guide_MAPPED.xlsx", read_only=True)
            ["Data with Headings"].iter_rows(min_row=2, values_only=True) if r[0]]
    bisy_sup, bisy_gbp = Counter(r[2] for r in bisy), defaultdict(float)
    for r in bisy:
        bisy_gbp[r[2]] += float(r[7] or 0)
    sup = []
    for r in bps:
        if r[1] not in FAILED_SUPPLIERS:
            continue
        need = [f for f, i in (("EECNUM (intra-EU VAT number)", c["EECNUM"]), ("CRN (SIRET / company number)", c["CRN"]))
                if not r[i]]
        if r[3] != "FR":
            need.append(f"country {r[3]} with a {str(r[c['EECNUM']])[:2]} VAT number - check the country and number")
        if r[3] == "FR" and r[c["VACBPR"]] == "DOM":
            need.append("tax rule DOM on an FR supplier - ROWS like the other FR suppliers?")
        sup.append([r[1], r[2], r[3], r[c["VACBPR"]], r[c["EECNUM"]] or "", r[c["CRN"]] or "", "; ".join(need),
                    poh_sup.get(r[1], 0), bisy_sup.get(r[1], 0), round(bisy_gbp.get(r[1], 0), 2)])

    # ---- customers -------------------------------------------------------------------------
    _, bpc = data("YA004BPC_customers_MAPPED.xlsx", "Data with Headings", 3)
    _, bpcdl = data("YA004BPCDL_delivery_addresses_MAPPED.xlsx", "Data with headings", 3)
    dl = Counter(r[0] for r in bpcdl if r[0])
    cus = []
    for r in bpc:
        if r[1] not in POSTCODE_ERRORS + STATE_ERRORS:
            continue
        cry, pc, state = r[24] or "", str(r[22] or "").strip().upper(), r[23]
        issue = []
        if cry in NO_POSTCODE and pc:
            issue.append(f"{cry} has no postcodes - postcode '{pc}' should be blank (a PO box goes in the address)")
        elif cry in POSTCODE and pc and not re.fullmatch(POSTCODE[cry], pc):
            issue.append(f"postcode '{pc}' is not a {cry} format")
        elif cry in POSTCODE and not pc:
            issue.append(f"no postcode for a {cry} address")
        if cry in NEEDS_STATE and not state:
            issue.append(f"{cry} address needs a State/Region")
        if issue:
            cus.append([r[1], r[2], r[17], cry, pc, state or "", " ".join(str(x) for x in r[19:22] if x),
                        "; ".join(issue), "XPOSCOD" if r[1] in POSTCODE_ERRORS else "XSAT"])
    per_customer = Counter(x[0] for x in cus)
    cus_summary = [[k, dl.get(k, 0), per_customer.get(k, 0),
                    "postcode format (XPOSCOD)" if k in POSTCODE_ERRORS else "State/Region (XSAT)"]
                   for k in POSTCODE_ERRORS + STATE_ERRORS]

    # ---- FGSL stock and PHANT sold -----------------------------------------------------------
    _, itm = data("ZSDIITM_products_MAPPED.xlsx", "Data with Headings", 4)
    cat = {r[1]: r[0] for r in itm if r[1]}
    desc = {r[1]: r[2] for r in itm if r[1]}
    _, smr = data("YA004SMR_guide_MAPPED_clean_run.xlsx", "Data with Headings", 3)
    stock = defaultdict(lambda: [0, 0.0, 0.0])
    for r in smr:
        if r[0] and cat.get(r[7]) == "FGSL":
            s = stock[r[7]]
            s[0] += 1
            s[1] += float(r[11] or 0)
            s[2] += float(r[11] or 0) * float(r[12] or 0)
    fgsl = sorted(([p, desc.get(p, ""), n, round(q, 4), round(v, 2)] for p, (n, q, v) in stock.items()),
                  key=lambda x: -x[4])
    so_head, so = data("YA004SOHPJ_guide_MAPPED_clean_run.xlsx", "Data with Headings", 3)
    pi = so_head.index("ITMREF")
    sold = Counter(r[pi] for r in so if r[0] and cat.get(r[pi]) == "PHANT")
    raw_sold = Counter(r[pi] for r in so if r[0] and cat.get(r[pi]) == "RAWML")
    phant = [[p, desc.get(p, ""), n, "PHANT", "FGML - sold on its own, so not a true phantom (usage test, group A)"]
             for p, n in sold.most_common()]
    phant += [[p, desc.get(p, ""), n, "RAWML", "watch - a raw material on an open sales order; check it has sales data"]
              for p, n in raw_sold.most_common()]

    # ---- workbook ------------------------------------------------------------------------------
    wb = Workbook()
    wb.remove(wb.active)
    add_sheet(wb, "Suppliers", ["Supplier", "Name", "Country", "Tax rule", "EECNUM", "CRN", "What it needs",
                                "POH lines that fail with it", "BISY items that fail with it", "BISY GBP"], sup,
              [10, 32, 8, 8, 16, 16, 70, 12, 12, 12])
    add_sheet(wb, "Customers", ["Customer", "Delivery addresses that fail with it", "Addresses to fix", "Run 2 error"],
              cus_summary, [12, 16, 12, 30])
    add_sheet(wb, "Customer addresses", ["Customer", "Name", "Address code", "Country", "Postcode", "State/Region",
                                         "Address", "What's wrong", "Run 2 error"], cus,
              [10, 30, 8, 8, 12, 12, 50, 70, 10])
    add_sheet(wb, "FGSL with stock", ["Product", "Description", "Lots", "Quantity", "Value GBP"], fgsl,
              [22, 32, 8, 12, 14])
    add_sheet(wb, "On open sales orders", ["Product", "Description", "Open SO lines", "Category", "What to do"], phant,
              [22, 32, 10, 9, 80])
    fgsl_value = sum(x[4] for x in fgsl)
    notes(wb, [
        ["Run 3 - master-data fixes before the opening transactions"], [],
        ["Source", "Acuity's Run 2 notes (28 Oct) and the files loaded in Run 2. Each list says what's wrong, what it "
                   "needs, and what else fails because of it"],
        ["Suppliers", f"{len(sup)} suppliers rejected. X3 needs EECNUM and CRN for FR suppliers - Finance to supply "
                      "(never a dummy value). BAL500 and SOG500 are why 3 POH lines and 12 BISY items failed"],
        ["Customers", f"6 customers rejected, taking {sum(x[1] for x in cus_summary):,} delivery addresses with them. "
                      f"{len(cus)} addresses to fix: postcode format, or a State/Region X3 requires (CA, AU, AE, US). "
                      "The template's County / region column has never been filled - it has no X3 field code"],
        ["FGSL with stock", f"{len(fgsl):,} FGSL products hold stock: {sum(x[2] for x in fgsl):,} lots, "
                            f"GBP {fgsl_value:,.0f}. X3 rejects stock on a product that isn't stock-managed. Decision for "
                            "Marc / Ethan: make FGSL stock-managed in X3 (these are bought-in goods SDI really stocks), "
                            "or the stock can't load"],
        ["On open sales orders", f"{len(sold)} PHANT products on {sum(sold.values())} open sales order lines - sold, "
                                 "so not true phantoms: FGML. Also listed: "
                                 f"{len(raw_sold)} RAWML products on {sum(raw_sold.values())} lines, to check they "
                                 "have sales data"],
    ], index=0)
    os.makedirs(OUT, exist_ok=True)
    path = f"{OUT}/Run3_master_data_fixes.xlsx"
    wb.save(path)
    print(path)
    print(f"suppliers {len(sup)} | customers 6 ({len(cus)} addresses, {sum(x[1] for x in cus_summary)} delivery "
          f"addresses depend) | FGSL with stock {len(fgsl)} (GBP {fgsl_value:,.0f}) | PHANT sold {len(sold)} "
          f"({sum(sold.values())} lines) | RAWML sold {len(raw_sold)} ({sum(raw_sold.values())} lines)")


if __name__ == "__main__":
    main()
