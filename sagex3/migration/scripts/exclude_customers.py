"""The customer and delivery-address files with one client taken out (James, 4 Nov: Tesco).

Removes, from YA004BPC and YA004BPCDL together (a delivery address whose customer address is
missing would be rejected):
  * every account whose name holds the word, with all its addresses
  * on other customers' accounts, any address that names the word - unless it is that customer's
    main (default) address, which the record needs; those are kept and listed
Everything else is the current file unchanged. Writes both spreadsheets with a 'Taken out' tab
and their load files.

Usage:
    python exclude_customers.py [WORD]          (default TESCO)
"""
import os
import re
import shutil
import sys

from openpyxl import load_workbook

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "rebuild"))
from common import add_sheet, write_load  # noqa: E402

BASE = "/tmp/claude-0/-home-user-ClaudeVision/e9ffe9d9-c7dd-5e34-8a16-6cb3c65dadea/scratchpad"
SET = os.environ.get("SET_DIR", f"{BASE}/Current_mapped_set_2026-11-04")
OUT = os.environ.get("OUT_DIR", f"{BASE}/out_without")


def rewrite(ws, first, keep):
    """Replace the data rows in one go (deleting rows one by one is far too slow on 6,000 rows)."""
    ws.delete_rows(first, ws.max_row - first + 1)
    for v in keep:
        ws.append(v)


def main(word="TESCO"):
    hit = re.compile(re.escape(word), re.I)
    tag = word.upper()
    os.makedirs(OUT, exist_ok=True)

    bpc_path = f"{OUT}/YA004BPC_customers_MAPPED_without_{tag}.xlsx"
    shutil.copy(f"{SET}/YA004BPC_customers_MAPPED.xlsx", bpc_path)
    wb = load_workbook(bpc_path)
    ws = wb["Data with Headings"]
    rows = [(r, [c.value for c in ws[r]]) for r in range(3, ws.max_row + 1) if ws.cell(r, 2).value]
    accounts = sorted({v[1] for _, v in rows if hit.search(str(v[2] or ""))})
    drop, kept, out_rows = [], [], []
    for r, v in rows:
        site = " ".join(str(v[i] or "") for i in (18, 19, 20, 21))
        if v[1] in accounts:
            drop.append(r)
            out_rows.append([v[1], v[2], v[17], v[18], "the account is " + word.title()])
        elif hit.search(site):
            if v[17] == v[7]:                       # the customer's main address: the record needs it
                kept.append([v[1], v[2], v[17], v[18], f"kept - names {word.title()} but it is the main address"])
            else:
                drop.append(r)
                out_rows.append([v[1], v[2], v[17], v[18], f"a {word.title()} site on another customer's account"])
    before = len(rows)
    rewrite(ws, 3, [v for r, v in rows if r not in set(drop)])
    gone = {(o[0], o[2]) for o in out_rows}
    add_sheet(wb, "Taken out", ["Customer", "Name", "Address code", "Description", "Why"], out_rows + kept,
              [10, 32, 8, 34, 60])
    n = wb["Notes"]
    n.append([])
    n.append([f"Without {word.title()} (4 Nov)", f"{len(accounts)} accounts ({', '.join(accounts)}) and their addresses "
              f"taken out, and {sum(1 for o in out_rows if o[0] not in accounts)} {word.title()} sites on other "
              f"customers' accounts. {len(kept)} kept because they are the customer's main address. "
              f"{before - len(drop):,} of {before:,} address rows remain"])
    wb.save(bpc_path)
    write_load(bpc_path, "Data with Headings", 3)

    dl_path = f"{OUT}/YA004BPCDL_delivery_addresses_MAPPED_without_{tag}.xlsx"
    shutil.copy(f"{SET}/YA004BPCDL_delivery_addresses_MAPPED.xlsx", dl_path)
    wb = load_workbook(dl_path)
    ws = wb["Data with headings"]
    dl_drop = [r for r in range(3, ws.max_row + 1)
               if ws.cell(r, 1).value and (ws.cell(r, 1).value, str(ws.cell(r, 2).value).zfill(3)) in
               {(a, str(c).zfill(3)) for a, c in gone}]
    dl_before = sum(1 for r in range(3, ws.max_row + 1) if ws.cell(r, 1).value)
    dl_drop = set(dl_drop)
    rewrite(ws, 3, [[c.value for c in ws[r]] for r in range(3, ws.max_row + 1)
                    if ws.cell(r, 1).value and r not in dl_drop])
    wb.save(dl_path)
    write_load(dl_path, "Data with headings", 3)

    # every delivery address still has its customer address, and none of the removed ones is left
    bpc_keys = {(r[1], str(r[17]).zfill(3)) for r in load_workbook(bpc_path, read_only=True)["Data with Headings"]
                .iter_rows(min_row=3, values_only=True) if r[1]}
    dl_keys = [(r[0], str(r[1]).zfill(3)) for r in load_workbook(dl_path, read_only=True)["Data with headings"]
               .iter_rows(min_row=3, values_only=True) if r[0]]
    assert all(k in bpc_keys for k in dl_keys), "a delivery address without its customer address"
    assert not any(a in accounts for a, _ in bpc_keys)
    print(bpc_path, f"\n  accounts out: {accounts} | address rows {before:,} -> {before - len(drop):,} "
          f"({len(drop):,} out; {len(kept)} kept as main addresses)")
    print(dl_path, f"\n  delivery addresses {dl_before:,} -> {dl_before - len(dl_drop):,} ({len(dl_drop):,} out)")
    for k in kept:
        print("  kept:", k)


if __name__ == "__main__":
    main(*(sys.argv[1:2] or ["TESCO"]))
