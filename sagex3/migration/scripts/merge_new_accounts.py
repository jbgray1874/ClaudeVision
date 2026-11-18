"""Add the new accounts' rows (build_new_customers.py / build_new_suppliers.py) to the run's customer,
delivery-address and supplier files, then rewrite each load file.

    python merge_new_accounts.py <run folder> <new_accounts folder> <Customer_List_master.xlsx> [--skip CODE,...]

<run folder>       holds YA004BPC_customers_MAPPED.xlsx, YA004BPCDL_delivery_addresses_MAPPED.xlsx and
                   YA004BPS_suppliers_MAPPED.xlsx (rewritten in place)
<new_accounts>     cust/YA004BPC_new_customers.txt, cust/YA004BPCDL_new_delivery_addresses.txt,
                   sup/YA004BPS_new_suppliers.txt (; separated, cp850), Customers_to_add.xlsx
Customer_List_master.xlsx  Finance's list: column T (User Sort 2) gives ACCCOD - ASSIGNED -> ID,
                   EURO -> EU, NON-ASSIGNED -> STD; blank -> EU for a euro account, else STD (provisional)
--skip             new codes to leave out (e.g. ISO100: no address, nothing open)

A code already in a file is never added twice (the run stops), so it's safe to see what a re-run would do.
Each file gets a "New accounts" tab listing what was added.
"""
import csv
import sys
from pathlib import Path

from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "rebuild"))
from common import add_sheet, write_load  # noqa: E402

T_TO_CODE = {"ASSIGNED": "ID", "EURO": "EU", "NON-ASSIGNED": "STD", "NON ASSIGNED": "STD"}
ACCCOD, CUR = 16, 9          # 0-based, YA004BPC


def read(path):
    with open(path, encoding="cp850", newline="") as f:
        return [r for r in csv.reader(f, delimiter=";") if len(r) > 1]


def append(xlsx, sheet, rows, label):
    wb = load_workbook(xlsx)
    ws = wb[sheet]
    have = {ws.cell(r, 1).value if sheet == "Data with headings" else ws.cell(r, 2).value
            for r in range(3, ws.max_row + 1)}
    key = 0 if sheet == "Data with headings" else 1
    clash = sorted({r[key] for r in rows} & have)
    if clash:
        raise SystemExit(f"{Path(xlsx).name}: already holds {clash} - not added twice")
    width = ws.max_column
    for r in rows:
        ws.append([(v if v != "" else None) for v in (r + [""] * width)[:width]])
    if "New accounts" in wb.sheetnames:
        del wb["New accounts"]
    add_sheet(wb, "New accounts", ["Code", "Rows added", "Why"],
              [[c, sum(1 for r in rows if r[key] == c), label] for c in sorted({r[key] for r in rows})], [12, 10, 90])
    wb.save(xlsx)
    write_load(xlsx, sheet, 3)
    return len(rows)


def main(run, new, finance, skip):
    run, new = Path(run), Path(new)
    old_of = {r[6]: r[0] for r in load_workbook(new / "Customers_to_add.xlsx")["Customers to add"].iter_rows(
        min_row=2, values_only=True) if r[6]}
    fin = {}
    for r in load_workbook(finance, read_only=True).worksheets[0].iter_rows(min_row=2, values_only=True):
        if r and r[1]:
            fin[str(r[1]).strip()] = str(r[19] or "").strip().upper()

    bpc = [r for r in read(new / "cust" / "YA004BPC_new_customers.txt") if r[1] not in skip]
    provisional = []
    for r in bpc:
        code = T_TO_CODE.get(fin.get(old_of.get(r[1], ""), ""))
        if not code:
            code = "EU" if r[CUR] == "EUR" else "STD"
            provisional.append(r[1])
        r[ACCCOD] = code
    dl = [r for r in read(new / "cust" / "YA004BPCDL_new_delivery_addresses.txt") if r[0] not in skip]
    bps = [r for r in read(new / "sup" / "YA004BPS_new_suppliers.txt") if r[1] not in skip]

    why = "new account 18 Nov: trading in Access with no Sage code (extract_accounts.sql NEWC / NEWS)"
    n1 = append(run / "YA004BPC_customers_MAPPED.xlsx", "Data with Headings", bpc, why)
    n2 = append(run / "YA004BPCDL_delivery_addresses_MAPPED.xlsx", "Data with headings", dl, why)
    n3 = append(run / "YA004BPS_suppliers_MAPPED.xlsx", "Data with Headings", bps, why)
    print(f"customers +{len({r[1] for r in bpc})} ({n1} rows), delivery addresses +{n2}, "
          f"suppliers +{len({r[1] for r in bps})} ({n3} rows); ACCCOD provisional: {provisional}")


if __name__ == "__main__":
    a = sys.argv[1:]
    skip = set()
    if "--skip" in a:
        i = a.index("--skip")
        skip = set(a[i + 1].split(","))
        del a[i:i + 2]
    main(*a[:3], skip)
