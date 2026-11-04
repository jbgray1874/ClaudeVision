"""YA00408BOM - bills of materials, from the run's extract (the BOM grid of extract_products.sql).

The BOM grid is every parent - component line in ASC_BOM_TBL, nothing filtered in SQL. The rules
(runbook 3 and 6.2, as the 27 Oct file):
  * a BOM goes in when its parent is in the product file and is made (FGML or PHANT); X3 builds
    manufactured products only. A BOM on a bought-in parent (RAWML / FGSL) is held back.
  * a line goes in when it has a quantity (vw_BOMP's rule; a 0 quantity is held back) and is not
    an exact repeat of another line on the same parent.
  * a component not in the product file can't load: the line is held back and listed. products.py
    puts every component of a migrated BOM in the product file, so this should be none.
  * BOM code 10, use status 2, base quantity 1, management unit 1, component type 1 (the file
    loaded in Run 2). Valid from / to are Access's dates, blank where Access has none.
  * sequence 10, 20, 30 ... per parent, in Access's own line order (BOM_UNIQUE).
  * a BOM whose parent isn't migrated is listed on 'Not migrated' with the reason, so nothing is
    dropped silently.
Codes go through the same code map as the product file (common.product_codes).
"""
from collections import Counter, defaultdict
from pathlib import Path

from openpyxl import Workbook

from common import add_sheet, ensure_dir, notes, read_grids, write_load

HEAD = ["ITMREF", "BOMALT", "USESTA", "BOHSTRDAT", "BOHENDDAT", "BASQTY", "QTYCOD", "BOMSEQ", "CPNITMREF",
        "CPNTYP", "LIKQTY"]
TITLES = ["Parent Product", "BOM Code", "Use Status", "Valid from", "Valid to", "Base Quantity", "Management Unit",
          "Sequence", "Component", "Component Type", "Link Quantity"]
MADE = {"FGML", "PHANT"}


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def qty(v):
    f = num(v)
    return int(f) if f.is_integer() else round(f, 6)


def date(v):
    v = (v or "").strip()
    return int(v) if v.isdigit() and len(v) == 8 else None


def build(run_dir, rows, code):
    """rows: {x3 code: ZSDIITM row} from products.build (column 0 = category); code: {Access code: x3}."""
    run_dir = Path(run_dir)
    grids, _ = read_grids(run_dir / "extract" / "extract_products.txt")
    if "BOM" not in grids:
        raise SystemExit("extract_products.txt has no BOM grid - was the whole of extract_products.sql saved?")
    cat = {x: r[0] for x, r in rows.items()}
    lines = defaultdict(list)                                   # x3 parent -> [(line_id, component, raw row)]
    for r in grids["BOM"]:
        p, c = r[0].strip(), r[1].strip()
        lines[code.get(p, p)].append((int(num(r[5])) if len(r) > 5 else 0, code.get(c, c), r, p, c))

    data, held, not_mig, missing = [], [], [], []
    why = Counter()
    for parent in sorted(lines):
        ls = sorted(lines[parent], key=lambda t: t[0])
        if parent not in rows:
            not_mig.append([parent, ", ".join(sorted({t[3] for t in ls})), len(ls),
                            "parent is not in the product file (not live - see the product file's 'Not migrated')"])
            why["parent not migrated"] += len(ls)
            continue
        seen, seq = set(), 0
        for line_id, comp, r, p_raw, c_raw in ls:
            row = [parent, 10, 2, date(r[3]), date(r[4]), 1, 1, None, comp, 1, qty(r[2])]
            reason = None
            if cat[parent] not in MADE:
                reason = f"BOM on a bought-in product ({cat[parent]}) - X3 builds manufactured products only"
            elif num(r[2]) <= 0:
                reason = "no quantity in Access"
            elif comp not in rows:
                reason = "component is not in the product file"
                missing.append([parent, comp])
            elif (comp, row[10], row[3], row[4]) in seen:
                reason = "exact repeat of another line on this BOM"
            if reason:
                held.append(row[:7] + [None] + row[8:] + [reason, line_id])
                why[reason.split(" (")[0]] += 1
                continue
            seen.add((comp, row[10], row[3], row[4]))
            seq += 10
            row[7] = seq
            data.append(row)

    keys = Counter((r[0], r[1], r[7]) for r in data)
    assert max(keys.values(), default=1) == 1, "parent / BOM code / sequence not unique"
    assert all(r[8] in rows and r[0] in rows for r in data)

    out = ensure_dir(run_dir / "out") / "YA00408BOM_boms_MAPPED.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Data with Headings"
    ws.append(HEAD)
    ws.append(TITLES)
    for r in data:
        ws.append(r)
    ws.freeze_panes = "A3"
    add_sheet(wb, "Held back", TITLES + ["Why", "Access line (BOM_UNIQUE)"], held, [18, 8, 8, 10, 10, 8, 8, 8, 18, 8, 10, 60, 12])
    add_sheet(wb, "Missing components", ["Parent (loads)", "Component not in the product file"], missing, [22, 30])
    add_sheet(wb, "Not migrated", ["Parent", "Access code(s)", "Lines", "Why"], not_mig, [22, 22, 8, 70])
    parents = len({r[0] for r in data})
    notes(wb, [["YA00408BOM - bills of materials"], [],
               ["Source", "ASC_BOM_TBL, every line (BOM grid of extract_products.sql), this run's extract"],
               ["Rows", f"{len(data):,} lines on {parents:,} BOMs"],
               ["Rules", "Parent in the product file and made (FGML / PHANT); a quantity; component in the product "
                         "file; exact repeats out. BOM code 10, use status 2, sequence 10, 20 ... in Access's line order"],
               ["Held back", f"{len(held):,}: " + ", ".join(f"{k} {v:,}" for k, v in why.items() if k != 'parent not migrated')],
               ["Not migrated", f"{len(not_mig):,} BOMs ({why['parent not migrated']:,} lines) whose parent is not live"]],
          index=0)
    wb.save(out)
    txt, n, lost = write_load(out, "Data with Headings", 3)
    assert n == len(data), (n, len(data))
    return out, dict(lines=len(data), boms=parents, held=len(held),
                     held_why={k: v for k, v in why.items() if k != "parent not migrated"},
                     missing_components=len(missing), not_migrated_boms=len(not_mig),
                     load_file=f"{txt.name} ({n:,} lines)")
