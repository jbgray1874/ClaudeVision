"""ZSDIROU2 - routes, from the run's extract (the ROU grid of sql/extract_routes.sql).

ROU is migration.vw_ROU, a live view over Access's route table ASC_PLN_TBL. The file loaded so
far came from migration.LOAD_ROU, a one-off copy of that view (31,326 of 65,158 operations); the
rules below reproduce that file exactly from LOAD_ROU (checked 5 Nov on all 31,253 lines):
  * one route per product: BOM code 10, site S01A, use status 1, time unit 2 (minutes), work
    order mode 4. Access's few extra route numbers on a product are merged into it, in order.
  * operations numbered 5, 10, 15 ... in Access's order (route, operation, sub-operation)
  * work centre: Access's -> X3's, from work_centres.csv (the mapping the loaded file used)
  * setup time as Access; run time per unit = Access run time / its 'per' quantity, 4 places
  * description: Access's, through Ethan's character rule, 30 characters; blank -> the work
    centre's usual text (work_centres.csv)
  * routes only on made products (FGML / PHANT); a route on a bought-in product is held back
  * an operation on a work centre with no X3 mapping is held back and listed, for Marc
  * a route whose product isn't in the product file is listed on 'Not migrated'
Codes go through the product file's code map.
"""
import csv
from collections import Counter, defaultdict
from pathlib import Path

from openpyxl import Workbook

from common import add_sheet, ensure_dir, notes, read_grids, write_load, x3_text

HERE = Path(__file__).resolve().parent
H1 = ["ROUTING"] * 6 + ["ROUOPE"] * 5
H2 = ["ITMREF", "ROUALT", "FCY", "USESTA", "TIMUOMCOD", "WORTYP", "OPENUM", "WST", "ROODES", "SETTIM", "OPETIM"]
H3 = ["Routing", "Routing Code", "Site", "Use Status", "Time Unit", "Work Order Management Mode", "Operation",
      "Main Work Centre", "Operation Description", "Setup Time", "Run Time"]
MADE = {"FGML", "PHANT"}


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def clean_num(f):
    return int(f) if float(f).is_integer() else f


def work_centres():
    with open(HERE / "work_centres.csv", newline="") as f:
        return {r["access_work_centre"]: r for r in csv.DictReader(f)}


def build(run_dir, rows, code):
    """rows: {x3 code: ZSDIITM row} (column 0 = category); code: {Access code: x3 code}."""
    run_dir = Path(run_dir)
    path = run_dir / "extract" / "extract_routes.txt"
    if not path.exists():
        return None, {"skipped": f"no {path.name} - run sql/extract_routes.sql (rule 1d)"}
    g, _ = read_grids(path)
    if "ROU" not in g:
        raise SystemExit("extract_routes.txt has no ROU grid - was the whole of extract_routes.sql saved?")
    wc = work_centres()
    ops = defaultdict(list)
    for r in g["ROU"]:
        raw = r[0].strip()
        ops[code.get(raw, raw)].append(r)

    data, held, not_mig = [], [], []
    why = Counter()
    for p in sorted(ops):
        ls = sorted(ops[p], key=lambda r: (int(num(r[1])), int(num(r[3])), int(num(r[4]))))
        if p not in rows:
            not_mig.append([p, len(ls), "product is not in the product file (not live)"])
            why["product not migrated"] += len(ls)
            continue
        n = 0
        for r in ls:
            w = wc.get(r[6].strip())
            desc = x3_text(r[5]).strip()[:30].rstrip() or (w and w["description_when_blank"]) or x3_text(r[14]).strip()[:30]
            per = num(r[10]) or 1
            line = [p, 10, "S01A", 1, 2, 4, None, w["x3_work_centre"] if w else r[6].strip(), desc,
                    clean_num(num(r[8])), clean_num(round(num(r[9]) / per, 4))]
            reason = None
            if rows[p][0] not in MADE:
                reason = f"route on a bought-in product ({rows[p][0]}) - X3 routes manufactured products only"
            elif not w:
                reason = f"Access work centre {r[6].strip() or '(blank)'} has no X3 work centre - Marc to map"
            if reason:
                held.append(line + [reason])
                why[reason.split(" (")[0] if "bought-in" in reason else reason] += 1
                continue
            n += 5
            line[6] = n
            data.append(line)

    assert len({(r[0], r[1], r[6]) for r in data}) == len(data), "product / route / operation not unique"
    assert all(r[0] in rows for r in data)

    out = ensure_dir(run_dir / "out") / "ZSDIROU2_routes_MAPPED.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "ZSDROU2"
    for h in (H1, H2, H3):
        ws.append(h)
    for r in data:
        ws.append(r)
    ws.freeze_panes = "A4"
    add_sheet(wb, "Held back", H3 + ["Why"], held, [18, 8, 6, 6, 6, 8, 8, 10, 30, 8, 8, 60])
    add_sheet(wb, "Not migrated", ["Product", "Operations", "Why"], not_mig, [22, 10, 50])
    long = sorted((c, p) for p, c in Counter(r[0] for r in data).items() if c > 150)
    notes(wb, [["ZSDIROU2 - routes"], [],
               ["Source", "migration.vw_ROU (live, over ASC_PLN_TBL), this run's extract_routes.sql"],
               ["Rows", f"{len(data):,} operations on {len({r[0] for r in data}):,} products"],
               ["Rules", "Route 10, site S01A, use status 1, minutes, mode 4; operations 5, 10, 15 in Access order; "
                         "run time per unit = run time / per quantity; Access work centres mapped as the 27 Oct file"],
               ["Held back", f"{len(held):,}: " + "; ".join(f"{k} {v:,}" for k, v in why.items() if k != "product not migrated")],
               ["Not migrated", f"{len(not_mig):,} products ({why['product not migrated']:,} operations) not in the product file"],
               ["Over 150 operations", ", ".join(f"{p} ({c})" for c, p in long) or "none"
                + " - X3's screen holds 150 (Run 2: 'Table is full 150')"]], index=0)
    wb.save(out)
    txt, n, _ = write_load(out, "ZSDROU2", 4)
    assert n == len(data), (n, len(data))
    return out, dict(operations=len(data), products=len({r[0] for r in data}), held=len(held),
                     held_why={k: v for k, v in why.items() if k != "product not migrated"},
                     not_migrated_products=len(not_mig), over_150=len(long), load_file=f"{txt.name} ({n:,} lines)")
