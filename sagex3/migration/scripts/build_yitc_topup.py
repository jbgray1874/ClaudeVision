"""YITC - a standard cost for every product in the product file (James, 30 Oct).

The cost source only held products with a non-zero Access standard cost, so 6,902 of the 16,499
products had no cost and X3 stops the stock load on them. No product is left without a cost on
an assumption now. Each product without one gets the best value Access has, in this order:
  1. the average lot cost of its stock in the stock file (quantity-weighted)  - "stock lot cost"
  2. the price on its last purchase order line; a EUR / USD price converted at Access's own
     ledger rate (the GBP / currency ratio on the supplier open items)       - "last purchase price"
  3. for a made product (FGML / PHANT): its BOM material cost - the sum of each component's
     cost x link quantity / base quantity, using costs 1 to 3, worked out recursively
                                                                              - "BOM material roll-up"
Anything still without a value is listed on the Check tab for SDI to supply - never a made-up
figure. Costs are per unit, the same scale as the existing YITC (checked: median ratio 1.0
against lot cost on 2,528 products).

Writes YITC_product_costs_TOPUP_MAPPED.xlsx (the new rows only, to load now) and rebuilds
YITC_product_costs_MAPPED.xlsx with the existing rows unchanged plus the new ones.

Usage:
    python build_yitc_topup.py
"""
import csv
import re
import sys
from collections import Counter, defaultdict

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

BASE = "/tmp/claude-0/-home-user-ClaudeVision/e9ffe9d9-c7dd-5e34-8a16-6cb3c65dadea/scratchpad"
V8, OUT = f"{BASE}/out_v8", f"{BASE}/out_sheets"
PURCHASES = [f"{BASE}/psup3/out.txt",                         # product_suppliers_v3 grid 2
             "/root/.claude/uploads/e9ffe9d9-c7dd-5e34-8a16-6cb3c65dadea/ba9c5378-productsql.txt"]  # new suppliers
FULL_MARK = "Costs for every product (30 Oct)"
YITC = [("Line Indicator", "Line Indicator"), ("STOFCY", "Site"), ("ITMREF", "Product"), ("CSTTYP", "Cost Type"),
        ("ITCSEQ", "Sequence no."), ("ITCDAT", "Date Calculated"), ("ITCSTRDAT", "To"), ("ITCENDDAT", "To"),
        ("FIYNUM", "Fiscal year"), ("MATCST", "Material Cost"), ("CLCQTY", "Calculation Quantity"),
        ("MATLEVCST", "Material Cost Level")]


def read(p):
    with open(p, newline="", encoding="cp850") as f:
        return [r for r in csv.reader(f, delimiter=";") if r and r[0].strip()]


def clean(c):
    """The V7 product code rule."""
    return re.sub(r"[^A-Z0-9\-]", "", c.strip().upper().replace("/", "-").replace("_", "-"))


def main():
    prods = read(f"{V8}/ZSDIITM_load8_products.txt")
    cat = {r[1]: r[0] for r in prods}
    desc = {r[1]: (r[4] or r[2]) for r in prods}
    existing = read(f"{V8}/YITC_load8_product_costs.txt")
    have = {r[2] for r in existing}

    lot = defaultdict(lambda: [0.0, 0.0])
    for r in read(f"{BASE}/out_v7/YA004SMR_load7_clean_run.txt"):
        q = float(r[11])
        lot[r[7]][0] += q
        lot[r[7]][1] += q * float(r[12])
    buy = {}
    for f in PURCHASES:
        for line in open(f, encoding="utf-8", errors="replace").read().splitlines():
            x = line.split("\t")
            if len(x) != 16 or x[2] != "1":
                continue
            try:
                price = float(x[8])
            except ValueError:
                continue
            p = clean(x[0])
            if price > 0 and (p not in buy or x[15] > buy[p][1]):
                buy[p] = (price, x[15], x[6] or "GBP")
    bom = defaultdict(list)
    for r in read(f"{V8}/YA00408BOM_load8_boms.txt"):
        bom[r[0]].append((r[8], float(r[9 + 1]) / (float(r[5]) or 1)))

    # Access's own exchange rates: GBP / currency on the supplier ledger items (one fixed rate a
    # currency - EUR 0.8643, USD 0.7484 on 30 Oct), so a foreign purchase price isn't left out
    rates = defaultdict(list)
    for r in read(f"{BASE}/out_mapped/load_files/YA004BISX_load1.txt"):
        if r[5] not in ("GBP", "") and float(r[8]) > 0:
            rates[r[5]].append(float(r[7]) / float(r[8]))
    rate = {k: sorted(v)[len(v) // 2] for k, v in rates.items()}
    stocked_zero = {c for c, (q, v) in lot.items() if q > 0 and v <= 0}

    cost = {r[2]: float(r[9]) for r in existing}
    source = {}

    def direct(c):
        if c in cost:
            return cost[c]
        q, v = lot.get(c, (0, 0))
        if q > 0 and v > 0:
            cost[c], source[c] = v / q, "stock lot cost"
            return cost[c]
        b = buy.get(c)
        if b and b[2] in ("GBP", ""):
            cost[c], source[c] = b[0], f"last purchase price ({b[1]})"
            return cost[c]
        if b and b[2] in rate:
            cost[c] = b[0] * rate[b[2]]
            source[c] = f"last purchase price ({b[1]}), {b[2]} {b[0]} at the Access ledger rate {rate[b[2]]:.4f}"
            return cost[c]
        return None

    def rolled(c, seen=()):
        v = direct(c)
        if v is not None or c not in bom or c in seen:
            return v
        total, gaps = 0.0, 0
        for comp, qty in bom[c]:
            cv = rolled(comp, seen + (c,))
            if cv is None:
                gaps += 1
            else:
                total += cv * qty
        if total > 0:
            cost[c] = total
            source[c] = "BOM material roll-up" + (f" ({gaps} component(s) with no cost)" if gaps else "")
            return total
        return None

    new, check = [], []
    for c in sorted(cat):
        if c in have:
            continue
        v = rolled(c)
        if v is None:
            b = buy.get(c)
            why = ("HOLDS STOCK at zero cost in Access - needs a cost before the stock load" if c in stocked_zero else
                   f"last purchase price is in {b[2]} ({b[0]}) - no exchange rate in the data" if b else
                   "no standard cost, stock, purchase or costed BOM in Access")
            check.append([c, desc[c], cat[c], why])
            continue
        v = round(v, 5) if v >= 0.0001 else 0.0001
        new.append(["I", "S01A", c, 1, 1, 20260101, 20260101, 20261231, 3, v, 100, v, source[c]])

    hf, fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="44546A")
    counts = Counter(r[12].split(" (")[0] for r in new)

    def book(rows, title, extra_note):
        wb = Workbook()
        ws = wb.active
        ws.title = "YITC"
        ws.append([c for c, _ in YITC])
        ws.append([h for _, h in YITC])
        for r in rows:
            ws.append([float(x) if i in (9, 11) else x for i, x in enumerate(r[:12])])
        ws.freeze_panes = "A3"
        src = wb.create_sheet("Cost source")
        src.append(["Product", "Description", "Category", "Material cost", "Where the cost came from"])
        for r in new:
            src.append([r[2], desc[r[2]], cat[r[2]], float(r[9]), r[12]])
        ck = wb.create_sheet("Check")
        ck.append(["Product", "Description", "Category", "Why there is no cost"])
        for r in check:
            ck.append(r)
        for s_, w in ((src, (20, 32, 9, 13, 60)), (ck, (20, 32, 9, 70))):
            for c in s_[1]:
                c.font, c.fill = hf, fill
            for i, x in enumerate(w, 1):
                s_.column_dimensions[get_column_letter(i)].width = x
            s_.freeze_panes = "A2"
            s_.auto_filter.ref = s_.dimensions
        n = wb.create_sheet("Notes", 0)
        for line in [[title], [],
                     ["Why", "The original cost file only held products with an Access standard cost, so 6,902 products had "
                             "no cost and X3 would not take their stock. Every product now gets the best cost Access has."],
                     ["New costs", f"{len(new)}: " + ", ".join(f"{k} {v}" for k, v in counts.most_common())],
                     ["Order of sources", "1 stock lot cost (average of the product's stock lots), 2 last purchase price "
                                          "(GBP), 3 for made products the BOM material roll-up of their components"],
                     ["Check tab", f"{len(check)} products with no cost anywhere in Access - SDI to supply"],
                     ["Layout", "As YITC: cost type 1, the whole cost as Material Cost, per unit"], extra_note]:
            n.append(line)
        n["A1"].font = Font(bold=True, size=13)
        n.column_dimensions["A"].width, n.column_dimensions["B"].width = 18, 110
        for r in n.iter_rows(min_row=3):
            for c in r:
                c.alignment = Alignment(wrap_text=True, vertical="top")
        return wb

    top = f"{OUT}/YITC_product_costs_TOPUP_MAPPED.xlsx"
    book(new, "YITC - costs for products that had none (top-up, 30 Oct)",
         ["Load", "Into UAT now, on top of the 9,597 costs already loaded. Then reload the stock file"]).save(top)
    # The full clean-run file: the existing workbook (its Guide and Held back tabs kept), with the
    # new rows added under the existing ones and the two new tabs.
    from openpyxl import load_workbook
    full = f"{OUT}/YITC_product_costs_MAPPED.xlsx"
    wb = load_workbook(full)
    ws = wb["YITC"]
    before = [list(r) for r in ws.iter_rows(min_row=3, values_only=True) if r[0] is not None]
    assert len(before) == len(existing), (len(before), len(existing))
    if FULL_MARK not in [c.value for c in wb["Notes"]["A"]]:
        for r in new:
            ws.append([float(x) if i in (9, 11) else x for i, x in enumerate(r[:12])])
        t = book(new, "", ["", ""])
        for name in ("Cost source", "Check"):
            src, dst = t[name], wb.create_sheet(name)
            for r in src.iter_rows(values_only=True):
                dst.append(list(r))
            for c in dst[1]:
                c.font, c.fill = hf, fill
            dst.freeze_panes = "A2"
            dst.auto_filter.ref = dst.dimensions
        n = wb["Notes"]
        n.insert_rows(3, 3)
        n.cell(3, 1, FULL_MARK).font = Font(bold=True)
        n.cell(4, 1, f"{len(new)} costs added for products that had none ("
                     + ", ".join(f"{k} {v}" for k, v in counts.most_common())
                     + f"). {len(check)} products still without a cost are on the Check tab. The {len(existing)} "
                       "costs from the cost source are unchanged.")
        wb.save(full)
    after = [list(r) for r in load_workbook(full, read_only=True)["YITC"].iter_rows(min_row=3, values_only=True)
             if r[0] is not None]
    assert after[:len(before)] == before and len(after) == len(existing) + len(new)
    print(len(new), "new costs", dict(counts), "|", len(check), "on Check |", len(after), "in the full file")
    return new, check


if __name__ == "__main__":
    main()
