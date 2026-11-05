"""ZSDIITMSUP - every supplier of every product, with its priority, from product_suppliers_v4.sql.

Run 2 loaded the main supplier only (8,644), because the template has no priority column, and
left 3,150 alternatives out. That is too many to lose (James, 4 Nov). This file carries every
product-supplier pair Access has bought since September 2022, with a priority from Access's own
purchase history: 1 = the supplier last bought from, then 2, 3 ... (grid 2 of the query). No
value is invented. The load has the template's three columns only (Ethan, 5 Nov: an added PIO
column made Run 3 reject the file), main supplier first per product; the priority is kept on the
'Supplier priority' tab, not loaded.

Usage: called by run.py after products.py, when <run>/extract/product_suppliers.txt exists.
"""
import re
import shutil
from collections import defaultdict
from pathlib import Path

from openpyxl import load_workbook

from common import add_sheet, ensure_dir, notes, read_grids, write_load
from products import val

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "templates" / "ZSDIITMSUP.xlsx"


def old_clean(c):
    """The cleansing product_suppliers_v4.sql applies to POR_PART_ONLY, so its codes can be matched
    to the Access codes the product build decided on: upper case; NBSP, spaces, &, ( ) removed;
    . to -. The / is left in."""
    s = c.replace("\xa0", "").strip().upper()
    return re.sub(r"[ &()]", "", s).replace(".", "-")


def suppliers_in(path):
    ws = load_workbook(path, read_only=True)["Data with Headings"]
    return {r[1] for r in ws.iter_rows(min_row=3, values_only=True) if r and r[1]}


def build(run_dir, rows, code, suppliers_file):
    run_dir = Path(run_dir)
    labelled, plain = read_grids(run_dir / "extract" / "product_suppliers.txt")
    pairs = [[val(x) for x in r] for g in plain for r in g if len(r) == 16 and val(r[2]).isdigit()]
    if not pairs:
        raise SystemExit("product_suppliers.txt: no grid 2 - was the whole of product_suppliers_v4.sql saved?")
    to_x3 = {}
    for raw, x in code.items():
        to_x3.setdefault(old_clean(raw), x)
    sups = suppliers_in(suppliers_file)

    keep, held = defaultdict(list), []
    for p in pairs:
        prod, sup, prio = p[0], p[1], int(p[2])
        x = to_x3.get(prod)
        why = ("product not in the product file" if x not in rows else
               "supplier not in the supplier file" if sup not in sups else "")
        if why:
            held.append([x or prod, sup, prio, p[3], p[12], p[15], why])
        else:
            keep[x].append((prio, sup, p))
    data, alt = [], []
    for x in sorted(keep):
        seen = set()
        for n, (_, sup, p) in enumerate(sorted(keep[x]), 1):
            if sup in seen:
                continue
            seen.add(sup)
            data.append([x, sup, x, len(seen)])
            if len(seen) > 1:
                alt.append([x, rows[x][2], sup, len(seen), p[12], p[13], p[15]])

    out = ensure_dir(run_dir / "out") / "ZSDIITMSUP_product_suppliers_MAPPED.xlsx"
    shutil.copy(TEMPLATE, out)
    wb = load_workbook(out)
    ws = wb["Template"]
    # The template's three columns only: Ethan (5 Nov) - the added PIO column made Run 3 reject the
    # file. Main supplier first per product; the priority is kept on its own tab, not loaded.
    for r in data:
        ws.append(r[:3])
    ws.freeze_panes = "A3"
    add_sheet(wb, "Supplier priority", ["Product", "Supplier", "Supplier product", "Priority (not loaded)"], data,
              [20, 10, 20, 12])
    add_sheet(wb, "Alternative suppliers", ["Product", "Description", "Supplier", "Priority", "Order lines",
                                            "Quantity ordered", "Last ordered"], alt, [20, 32, 10, 8, 10, 12, 10])
    add_sheet(wb, "Held back", ["Product", "Supplier", "Access priority", "Supplier name", "Order lines",
                                "Last ordered", "Why"], held, [20, 10, 8, 30, 10, 10, 50])
    main = sum(1 for r in data if r[3] == 1)
    notes(wb, [["ZSDIITMSUP - product-suppliers, complete file"], [],
               ["Rows", f"{len(data):,}: {main:,} products with their main supplier (priority 1) and {len(alt):,} "
                        "alternative suppliers (priority 2, 3 ...). Run 2 loaded the main supplier only"],
               ["Priority", "Not in the load (Ethan, 5 Nov: the extra PIO column made the import fail). The three "
                            "template columns load every pair, main supplier first. The priority (1 = the supplier last "
                            "bought from, then by last order date and order lines) is on the 'Supplier priority' tab"],
               ["Source", "Access purchase orders since September 2022 (product_suppliers_v4.sql, grid 2)"],
               ["Held back", f"{len(held):,} pairs: a product not in the product file, or a supplier not in the "
                             "supplier file - each with its reason"]], index=0)
    wb.save(out)
    got = [r for r in load_workbook(out, read_only=True)["Template"].iter_rows(min_row=3, values_only=True) if r[0]]
    assert [list(g[:3]) for g in got] == [r[:3] for r in data]
    assert all(len([v for v in g if v is not None]) == 3 for g in got)
    assert len({(r[0], r[1]) for r in data}) == len(data)
    txt, n, _ = write_load(out, "Template", 3)
    assert n == len(data)
    return out, dict(pairs=len(data), main=main, alternatives=len(alt), held=len(held), load_file=txt.name)
