"""YITC - a standard cost line for every product in the product file, from extract_products.sql.

Every product gets a line (runbook 1a, register 1 and 16). A product already costed in the
previous YITC keeps that cost, so a loaded cost never moves without a reason. Every other
product, the ones the product build has just brought in among them, takes the best value Access has:
  1. Access material cost, PMA_COST_MAT per unit (divided by PMA_COST_MAT_PER where Access
     holds the cost per N units)
  2. the average lot cost of its stock (stock value / quantity, full lot cost as in SMR)
  3. the price on its last priced purchase line; EUR / USD at Access's own ledger rate (RATE grid)
  4. for a product with a BOM: the material roll-up of its components, using costs 1 to 3
  5. nothing in Access: loaded at 0 and listed on Check, never left out (James, 2 Nov)
Costs are per unit: MATCST = MATLEVCST, CLCQTY 100, as the loaded file.

Usage: called by run.py after products.py. Writes <run>/out/YITC_product_costs_MAPPED.xlsx and .txt.
"""
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

from openpyxl import Workbook, load_workbook

from common import add_sheet, ensure_dir, notes, read_grids, write_load
from products import load, num, val

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from build_yitc import GUIDE, YITC  # noqa: E402  the template layout, one copy


FALLBACK_RATES = {"EUR": 0.8643, "USD": 0.7484}     # GBP per unit, Access's ledger rates on 30 Oct


def previous_costs(path):
    """{product: (cost, source)} from a previous YITC spreadsheet, if there is one."""
    if not path or not Path(path).exists():
        return {}
    wb = load_workbook(path, read_only=True)
    src = {}
    if "Cost source" in wb.sheetnames:
        src = {r[0]: r[4] for r in wb["Cost source"].iter_rows(min_row=2, values_only=True) if r[0]}
    return {r[2]: (float(r[9] or 0), src.get(r[2], "as loaded"))
            for r in wb["YITC"].iter_rows(min_row=3, values_only=True) if r and r[2]}


def build(run_dir, rows, code, previous=None):
    """rows: {x3 code: ZSDIITM row} from products.build; code: {Access code: x3 code}."""
    run_dir = Path(run_dir)
    extract = run_dir / "extract" / "extract_products.txt"
    _, _, use, _, rate = load(extract)
    rate_note = "Access's own rate from the purchase ledger (RATE grid)"
    if not rate:
        # the RATE grid comes back empty when no open purchase-ledger item is in a foreign
        # currency; then the rates Access held on 30 Oct (runbook register 1) are used
        rate = {k: (v, v, v, "30 Oct") for k, v in FALLBACK_RATES.items()}
        rate_note = "no RATE grid in this extract: Access's ledger rates of 30 Oct used (EUR 0.8643, USD 0.7484)"
    grids, _ = read_grids(extract)
    prev = previous_costs(previous)

    # what Access holds, per X3 code
    mat, lot, buy = {}, defaultdict(lambda: [0.0, 0.0]), {}
    for c, u in use.items():
        x = code.get(c)
        if x not in rows:
            continue
        per = num(u[16]) or 1
        if num(u[12]) > 0:
            mat[x] = max(mat.get(x, 0), num(u[12]) / per)
        if num(u[1]) > 0:
            lot[x][0] += num(u[1])
            lot[x][1] += num(u[2])
        if num(u[13]) > 0 and (x not in buy or u[15] > buy[x][2]):
            buy[x] = (num(u[13]), u[14] or "GBP", u[15])
    bom = defaultdict(list)
    for r in grids["BOM"]:
        p, c, q = code.get(val(r[0])), code.get(val(r[1])), num(r[2]) if len(r) > 2 else 1
        if p in rows and c in rows and q > 0 and p != c:
            bom[p].append((c, q))

    cost, source = {}, {}

    def direct(x):
        if x in cost:
            return cost[x]
        if x in mat:
            cost[x], source[x] = mat[x], "Access material cost"
        elif lot[x][0] > 0 and lot[x][1] > 0:
            cost[x], source[x] = lot[x][1] / lot[x][0], "stock lot cost"
        elif x in buy and buy[x][1] in ("GBP", ""):
            cost[x], source[x] = buy[x][0], f"last purchase price ({buy[x][2]})"
        elif x in buy and buy[x][1] in rate and rate[buy[x][1]][0] > 0:
            p, cur, d = buy[x]
            cost[x] = p * rate[cur][0]
            source[x] = f"last purchase price ({d}), {cur} {p:g} at the Access ledger rate {rate[cur][0]:.4f}"
        return cost.get(x)

    def rolled(x, seen=()):
        v = direct(x)
        if v is not None or x not in bom or x in seen:
            return v
        total, gaps = 0.0, 0
        for c, q in bom[x]:
            cv = rolled(c, seen + (x,))
            gaps += cv is None
            total += (cv or 0) * q
        if total > 0:
            cost[x] = total
            source[x] = "BOM material roll-up" + (f" ({gaps} component(s) with no cost)" if gaps else "")
            return total
        return None

    out, check = [], []
    for x in sorted(rows):
        if x in prev and prev[x][0] > 0:
            v, why = prev[x]
            why = f"{why} (kept from the previous file)" if "kept" not in why else why
        else:
            v = rolled(x)
            why = source.get(x)
            if v is None:
                stocked = lot[x][0] > 0
                why = "no cost in Access - loaded at 0, SDI to supply"
                check.append([x, rows[x][2], rows[x][0], ("HOLDS STOCK at zero cost in Access" if stocked else
                              "no standard cost, stock, purchase or costed BOM in Access") + " - loaded at 0"])
                v = 0
        v = round(v, 5) if v == 0 or v >= 0.0001 else 0.0001
        out.append(["I", "S01A", x, 1, 1, 20260101, 20260101, 20261231, 3, v, 100, v, why])
    assert {r[2] for r in out} == set(rows), "a product without a cost line"

    path = ensure_dir(run_dir / "out") / "YITC_product_costs_MAPPED.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "YITC"
    ws.append([c for c, _ in YITC])
    ws.append([h for _, h in YITC])
    for r in out:
        ws.append(r[:12])
    ws.freeze_panes = "A3"
    g = wb.create_sheet("Guide")
    for row in GUIDE:
        g.append(list(row))
    kinds = Counter("kept from the previous file" if "kept" in r[12] else
                    "last purchase price, converted" if "ledger rate" in r[12] else r[12].split(" (")[0] for r in out)
    add_sheet(wb, "Cost source", ["Product", "Description", "Category", "Material cost", "Where the cost came from"],
              [[r[2], rows[r[2]][2], rows[r[2]][0], r[9], r[12]] for r in out], [20, 32, 9, 13, 70])
    add_sheet(wb, "Check", ["Product", "Description", "Category", "Why the cost is 0"], check, [20, 32, 9, 70])
    notes(wb, [["YITC - product standard costs, complete file"], [],
               ["Rows", f"{len(out):,}: one cost line for every product in the product file. A complete file, not a "
                        "top-up (rule 1b)"],
               ["Where costs come from", ", ".join(f"{k} {v:,}" for k, v in kinds.most_common())],
               ["Order of sources", "A cost already in the previous file is kept. Otherwise: 1 Access material cost "
                                    "(per unit); 2 the average cost of the stock lots; 3 the last purchase price (EUR / "
                                    "USD at Access's own ledger rate); 4 the BOM material roll-up; 5 loaded at 0"],
               ["Check tab", f"{len(check):,} products with no cost anywhere in Access, loaded at 0 - SDI to supply. "
                             f"{sum(1 for r in check if r[3].startswith('HOLDS')):,} of them hold stock"],
               ["Exchange rates", rate_note],
               ["Layout", "Cost type 1, the whole cost as Material Cost, per unit"]], index=0)
    wb.save(path)
    got = [r for r in load_workbook(path, read_only=True)["YITC"].iter_rows(min_row=3, values_only=True) if r[0]]
    assert len(got) == len(out) and all(g[2] == r[2] and float(g[9]) == float(r[9]) for g, r in zip(got, out))
    txt, n, _ = write_load(path, "YITC", 3)
    assert n == len(out)
    return path, dict(costs=len(out), sources=dict(kinds), at_zero=len(check),
                      at_zero_stocked=sum(1 for r in check if r[3].startswith("HOLDS")), load_file=txt.name)


if __name__ == "__main__":
    print("Run through run.py: costs need the product build first.", file=sys.stderr)
    sys.exit(2)
