"""A customer pack: everything in the mapped files to do with one client, in one workbook.

Searches the current mapped set for a word (default TESCO) and collects:
  * Accounts           - customer accounts whose name holds the word, with their Access code,
                         terms, VAT, tax rule and totals
  * Addresses          - every address on those accounts, and any other customer's address that
                         names the word (a store or site billed through someone else)
  * Delivery addresses - the YA004BPCDL rows for the accounts
  * Open sales orders  - the YA004SOHPJ lines for the accounts
  * Open items         - the YA004BICY invoices, credits and receipts for the accounts
  * Products           - product codes or descriptions with the word or its code prefix, plus
                         every product on the accounts' open orders, with category, price and cost
  * Address fixes      - the 4 Nov address fixes made to these accounts
Names and addresses are SDI data: the workbook is written to the working folder, never git.

Usage:
    python build_customer_pack.py [WORD] [CODE PREFIX]     e.g.  python build_customer_pack.py TESCO TES-
"""
import os
import re
import sys
from collections import Counter, defaultdict

from openpyxl import load_workbook

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "rebuild"))
from common import add_sheet, notes  # noqa: E402
from openpyxl import Workbook  # noqa: E402

BASE = "/tmp/claude-0/-home-user-ClaudeVision/e9ffe9d9-c7dd-5e34-8a16-6cb3c65dadea/scratchpad"
SET = os.environ.get("SET_DIR", f"{BASE}/Current_mapped_set_2026-11-04")
MAPPING = os.environ.get("MAPPING", f"{BASE}/out_sue/Customer_mapping_old_to_new_v2.xlsx")
OUT = os.environ.get("OUT_DIR", f"{BASE}/out_packs")


def tab(name, sheet, first):
    ws = load_workbook(f"{SET}/{name}", read_only=True)[sheet]
    rows = list(ws.iter_rows(values_only=True))
    return rows[:first - 1], [r for r in rows[first - 1:] if r and r[0] is not None]


def main(word="TESCO", prefix="TES-"):
    hit = re.compile(re.escape(word), re.I)
    text = lambda r, cols: " ".join(str(r[i] or "") for i in cols)

    _, bpc = tab("YA004BPC_customers_MAPPED.xlsx", "Data with Headings", 3)
    accounts = sorted({r[1] for r in bpc if hit.search(str(r[2] or ""))})
    old = {}
    for r in load_workbook(MAPPING, read_only=True)["Old to new"].iter_rows(min_row=2, values_only=True):
        if r and len(r) > 2 and r[2]:
            old[r[2]] = r[0]

    # ---- open orders and open items --------------------------------------------------------
    sh, so = tab("YA004SOHPJ_guide_MAPPED_clean_run.xlsx", "Data with Headings", 3)
    soc = {c: i for i, c in enumerate(sh[0]) if c}
    so = [r for r in so if r[soc["BPCORD"]] in accounts]
    _, bicy = tab("YA004BICY_guide_MAPPED.xlsx", "Data with Headings", 2)
    bicy = [r for r in bicy if r[2] in accounts]
    so_val, so_lines, so_orders = defaultdict(float), Counter(), defaultdict(set)
    for r in so:
        a = r[soc["BPCORD"]]
        so_lines[a] += 1
        so_orders[a].add(r[soc["CUSORDREF"]])        # X3 numbers the order, so the customer's reference
        so_val[a] += float(r[soc["QTY"]] or 0) * float(r[soc["GROPRI"]] or 0)
    sign = {"MCRN": -1, "MREC": -1, "MJCT": -1}
    oi_val, oi_n = defaultdict(float), Counter()
    for r in bicy:
        oi_n[r[2]] += 1
        oi_val[r[2]] += sign.get(r[0], 1) * float(r[7] or 0)

    # ---- accounts and addresses ----------------------------------------------------------------
    main_adr = {r[1]: r for r in bpc if r[1] in accounts and r[17] == r[7]}
    n_adr = Counter(r[1] for r in bpc if r[1] in accounts)
    acc_rows = []
    for a in accounts:
        m = main_adr.get(a) or next(r for r in bpc if r[1] == a)
        acc_rows.append([a, old.get(a, ""), m[2], m[0], m[9], m[12] or "", m[14], m[15], n_adr[a], so_lines[a],
                         len(so_orders[a]), round(so_val[a], 2), oi_n[a], round(oi_val[a], 2)])
    adr_rows = []
    for r in bpc:
        own = r[1] in accounts
        if own or hit.search(text(r, (18, 19, 20, 21))):
            adr_rows.append([r[1], r[2], r[17], r[18], r[19], r[20], r[21], r[22], r[23], r[24], r[25], r[28],
                             "account" if own else f"a {word.title()} site on another customer's account"])
    _, bpcdl = tab("YA004BPCDL_delivery_addresses_MAPPED.xlsx", "Data with headings", 3)
    dl_rows = [list(r[:3]) for r in bpcdl if r[0] in accounts]

    # ---- products -------------------------------------------------------------------------------
    _, itm = tab("ZSDIITM_products_MAPPED.xlsx", "Data with Headings", 4)
    _, yitc = tab("YITC_product_costs_MAPPED.xlsx", "YITC", 3)
    cost = {r[2]: r[9] for r in yitc}
    on_order = Counter(r[soc["ITMREF"]] for r in so)
    prod_rows = []
    for r in itm:
        why = []
        if prefix and str(r[1]).startswith(prefix):
            why.append(f"code starts {prefix}")
        if hit.search(text(r, (2, 3, 4))):
            why.append(f"description names {word.title()}")
        if on_order[r[1]]:
            why.append(f"on {on_order[r[1]]} open {word.title()} order line(s)")
        if why:
            prod_rows.append([r[1], r[2], r[3], r[4], r[0], r[12], cost.get(r[1], ""), on_order[r[1]], "; ".join(why)])

    # ---- the 4 Nov address fixes on these accounts --------------------------------------------
    wb_bpc = load_workbook(f"{SET}/YA004BPC_customers_MAPPED.xlsx", read_only=True)
    fixes = ([list(r) for r in wb_bpc["Address fixes"].iter_rows(min_row=2, values_only=True) if r[0] in accounts]
             if "Address fixes" in wb_bpc.sheetnames else [])

    wb = Workbook()
    wb.remove(wb.active)
    add_sheet(wb, "Accounts", ["X3 code", "Access code", "Name", "Category", "Currency", "VAT number", "Tax rule",
                               "Payment terms", "Addresses", "Open SO lines", "Open orders (customer refs)", "Open SO value",
                               "Open items", "Open items GBP (net)"], acc_rows,
              [9, 10, 36, 9, 8, 16, 8, 14, 9, 9, 9, 13, 9, 14])
    add_sheet(wb, "Addresses", ["Customer", "Customer name", "Address code", "Description", "Line 1", "Line 2",
                                "Line 3", "Postcode", "State/Region", "Country", "Telephone", "Email", "Whose"],
              adr_rows, [9, 30, 8, 30, 30, 26, 22, 10, 8, 7, 16, 26, 36])
    add_sheet(wb, "Delivery addresses", ["Customer", "Address code", "Delivery address name"], dl_rows, [9, 8, 40])
    add_sheet(wb, "Open sales orders", [sh[1][i] or sh[0][i] for i in range(len(sh[0]))], [list(r) for r in so])
    add_sheet(wb, "Open items", ["Type", "Document (NUM)", "Customer", "Company", "Site", "Accounting date", "Currency",
                                 "GBP amount", "Transaction amount", "Source date", "Paying customer", "Due date",
                                 "Payment terms", "Access invoice no. (BPRVCR)", "Comment"],
              [list(r[:15]) for r in bicy], [7, 14, 9, 8, 6, 10, 7, 12, 12, 10, 9, 10, 10, 16, 30])
    add_sheet(wb, "Products", ["Product", "Description", "Description 2", "Description 3", "Category", "Base price",
                               "Standard cost", f"Open {word.title()} SO lines", "Why listed"], prod_rows,
              [20, 30, 26, 30, 9, 10, 11, 10, 50])
    if fixes:
        add_sheet(wb, "Address fixes", ["Customer", "Address", "Field", "Was", "Now", "Rule"], fixes,
                  [9, 8, 14, 30, 30, 50])
    others = Counter(r[0] for r in adr_rows if r[0] not in accounts)
    notes(wb, [[f"{word.title()} - customer pack"], [],
               ["Accounts", ", ".join(f"{a[0]} {a[2]} (Access {a[1]})" for a in acc_rows)],
               ["Addresses", f"{sum(1 for r in adr_rows if r[0] in accounts):,} on these accounts; "
                             f"{sum(others.values()):,} {word.title()} sites on other customers' accounts ("
                             + ", ".join(f"{k} {v}" for k, v in others.most_common(6)) + ")"],
               ["Open sales orders", f"{len(so):,} lines on {sum(len(v) for v in so_orders.values()):,} orders, "
                                     f"GBP {sum(so_val.values()):,.2f}"],
               ["Open items", f"{len(bicy):,} items, net GBP {sum(oi_val.values()):,.2f} (credits and receipts negative)"],
               ["Products", f"{len(prod_rows):,}: codes starting {prefix}, descriptions naming {word.title()}, and "
                            "everything on the open orders"],
               ["Data as at", "Accounts, addresses and products: the current mapped set (products from the 4 Nov "
                              "extract). Open orders and open items: the 21 Oct extract plus the 27 Oct new accounts - "
                              "refreshed with the Run 3 transaction extract"],
               ["Confidential", "Customer names, addresses and balances - SDI data, keep inside SDI"]], index=0)
    os.makedirs(OUT, exist_ok=True)
    path = f"{OUT}/{word.title()}_customer_pack.xlsx"
    wb.save(path)
    print(path)
    for a in acc_rows:
        print(f"  {a[0]} {a[2]} (Access {a[1]}): {a[8]} addresses, {a[9]} SO lines / {a[10]} orders GBP {a[11]:,.2f}, "
              f"{a[12]} open items GBP {a[13]:,.2f}")
    print(f"  other customers' {word.title()} sites: {sum(others.values())} {dict(others.most_common(8))}")
    print(f"  products: {len(prod_rows)} | address fixes on these accounts: {len(fixes)}")


if __name__ == "__main__":
    main(*(sys.argv[1:3] or ["TESCO", "TES-"]))
