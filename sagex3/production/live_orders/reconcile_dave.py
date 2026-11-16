"""Live Orders: reconcile Production's own sheet (Dave Wright's Live_Orders.xlsx, a Crystal export edited by hand)
against the Access data, column by column, and map every column onto the Sage X3 import templates.

Purpose (James, 16 Nov): show Acuity exactly where each of Production's columns comes from and where it lands in
Sage X3, proved automatically against Production's sheet - without the manual steps - so the mapping is 100%
identified before asking Acuity whether Sage X3 can provide the report today.

    python reconcile_dave.py <Live_Orders.xlsx> <extract .txt/.rpt> <out.xlsx>
        --products <ZSDIITM .xlsx> --boms <YA00408BOM .txt> --routes <ZSDIROU2 .txt>

Read-only: reads the files, writes one workbook. Use the extract nearest the date Production's sheet was saved.
"""
import argparse
import datetime as dt
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import build_live_orders as lo  # noqa: E402

INK = PatternFill("solid", fgColor="282928")
Y = Font(bold=True, color="F5D947")
B = Font(bold=True)
OK = PatternFill("solid", fgColor="E6F4EA")
NO = PatternFill("solid", fgColor="FDE2E1")
INFO = PatternFill("solid", fgColor="FFF4C2")
WRAP = Alignment(wrap_text=True, vertical="top")

# Dave's column -> (meaning, Access source, how the board works it out, X3 template / field, X3 position)
COLUMNS = [
    ("Due date", "When the works order must be finished", "ASC_WOR_TBL.WOR_DATE_SCHED",
     "Works order scheduled date", "YA004MFG ENDDAT (End date)", "Loaded"),
    ("Customer Date", "The customer's date for the order behind the works order",
     "WOR_SALORD → sales-order line due date (vw_SOH_V2)", "The works order's sales-order line date (Dave's own formula is broken: #REF!)",
     "YA004SOHPJ DEMDLVDAT / SHIDAT on the SO line - but YA004MFG carries NO link from the works order to its sales order",
     "GAP: needs the WO → SO link in X3"),
    ("WO Num", "Works order number", "ASC_WOR_TBL.WOR_ORDER (e.g. 70020969, sub-assemblies 70020969/01)",
     "Access works order", "YA004MFG MFGNUM is left blank: X3 gives its own number (Access number kept on the 'Access reference' tab only)",
     "GAP: Access WO number not on the X3 order"),
    ("SO Num", "The sales order (and line) the works order is for", "ASC_WOR_TBL.WOR_SALORD",
     "Access works order", "YA004SOHPJ SOHNUM / SOPLIN - not linked to the works order in YA004MFG", "GAP: same as Customer Date"),
    ("Part code", "What is being made", "WOR_ITEM_ONLY", "Product, X3 code rule", "YA004MFG ITMREF (and ZSDIITM ITMREF)", "Loaded"),
    ("Description", "Product description", "Product master (PMA)", "Product description", "ZSDIITM ITMDES1", "Loaded"),
    ("DRAWING NUMBER", "Drawing the part is made to", "Part code (typed on the sheet)", "Part code less the customer prefix",
     "ZSDIITM ITMREF / ITMDES2", "Loaded (derived)"),
    ("REV", "Drawing revision", "WOR_ITEM_REV - but it is blank on almost every open works order: Production type the rev from the drawing",
     "Works order revision (mostly blank in Access)", "ZSDIITM ITMDES2 (revision text, as migrated) - not per works order",
     "GAP: rev is typed by Production; in X3 it sits on the product only"),
    ("MATERIAL STATUS", "Is everything in to make it? Typed by hand today",
     "Not held - typed", "Worked out: BOM × balance against stock, POs and works orders → green / amber / red",
     "X3 WO material lines (allocated / short) + PO lines: YA004POH EXTRCPDAT; stock: YA004SMR", "X3 standard (WO materials / shortages) - to confirm"),
    ("QTY", "Quantity ordered", "WOR_AMD_QTY / WOR_ORIG_QTY", "Ordered (amended if set)",
     "YA004MFG EXTQTY = still to make (ordered − made), not the original", "Partly: X3 order starts at the remaining quantity"),
    ("Booked in", "Quantity made so far", "WOR_GOOD_QTY", "Good quantity", "Not loaded: EXTQTY is the remaining quantity", "GAP: made-to-date not carried"),
    ("Balance", "Still to make", "QTY − Booked in", "Ordered − good", "YA004MFG EXTQTY (Planned)", "Loaded"),
    ("Metal / Joinery / Acrylics", "Which shop it goes through (typed Y by Production)", "Typed on the sheet", "Board: families of every work centre on the route",
     "ZSDIROU2 WST (work centre) on the routing", "Loaded (derived) - definition to agree with Production"),
    ("LASM … PACP (23 dept columns)", "Hours still to do in each department",
     "Crystal report: the works order's OWN operations still open (finished operations drop off)",
     "Board: route run time × balance (+ set-up if nothing made). Matches the sheet where no operation has been finished; differs where some have (see Dept hours)",
     "X3 WO operations (created from ZSDIROU2 when the WO is created); YA004MFG loads the WO at the remaining quantity with ALL operations open",
     "GAP: operations already finished in Access are not marked done in X3"),
    ("Tube req / Comments / Prog", "Production's own notes", "Not held - typed", "Carried forward by WO from last week's sheet",
     "Not in any template", "GAP: X3 user fields on the WO?"),
]


def d(v):
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    return None


def same_num(a, b, tol=1e-6):
    try:
        return abs(float(a or 0) - float(b or 0)) <= tol
    except (TypeError, ValueError):
        return False


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("dave")
    ap.add_argument("extract")
    ap.add_argument("out")
    ap.add_argument("--products", required=True)
    ap.add_argument("--boms", required=True)
    ap.add_argument("--routes", required=True)
    a = ap.parse_args()

    tmp = Path(tempfile.mkdtemp())
    res = lo.build(a.extract, tmp, a.products, a.boms, a.routes)
    wos, wcnames = res["wos"], res["wcnames"]
    as_at = res["meta"]["as_at"]
    by = {w["wo"]: w for w in wos}
    import csv
    wc_csv = HERE.parent.parent / "migration" / "rebuild" / "work_centres.csv"
    with open(wc_csv) as f:
        dept_to_wc = {r["access_work_centre"].strip(): r["x3_work_centre"].strip() for r in csv.DictReader(f)
                      if r["x3_work_centre"].strip() and r["x3_work_centre"] != "x3_work_centre"}

    dw = load_workbook(a.dave, data_only=True)
    ws = dw.worksheets[0]
    props = dw.properties
    head = [str(c.value or "").strip() for c in ws[1]]
    col = {h: i for i, h in enumerate(head)}
    depts = [h for h in head[18:41] if h]

    stats = defaultdict(lambda: [0, 0])        # column -> [same, compared]
    rows, hours_rows, not_open, dave_rows = [], [], [], 0
    due_later, rev_typed_only = 0, 0
    for r in ws.iter_rows(min_row=2, values_only=True):
        if not r[col["WO Num"]]:
            continue
        dave_rows += 1
        wo = str(r[col["WO Num"]]).strip()
        w = by.get(wo)
        if not w:
            not_open.append([wo, r[col["Part code"]], r[col["Description"]], r[col["Balance"]],
                             "Not open in Access on the extract date (completed or closed since the sheet was saved)"])
            continue
        checks = []

        def cmp(name, dave_v, acc_v, same):
            stats[name][1] += 1
            stats[name][0] += 1 if same else 0
            checks.extend([dave_v, acc_v, "✓" if same else "✗"])

        dp = str(r[col["Part code"]] or "").strip()
        cmp("Part code", dp, w["code"], lo.product_code(dp) == w["code"])
        dd, ad = d(r[col["Due date"]]), w["due"]
        cmp("Due date", dd, ad, dd == ad)
        due_later += 1 if dd and ad and ad > dd else 0
        ds = str(r[col["SO Num"]] or "").strip()
        so_d = "" if ds.upper() in ("", "STOCK") else ds.lstrip("0")
        cmp("SO Num", ds, w["so"], so_d == str(w["so"] or "").strip().lstrip("0"))
        drev = str(r[col["REV"]] or "").strip()
        cmp("REV", drev, w["rev"], drev.upper() == str(w["rev"] or "").strip().upper())
        rev_typed_only += 1 if drev and not str(w["rev"] or "").strip() else 0
        cmp("QTY", r[col["QTY"]], w["qty"], same_num(r[col["QTY"]], w["qty"]))
        cmp("Booked in", r[col["Booked in"]], w["done"], same_num(r[col["Booked in"]], w["done"]))
        cmp("Balance", r[col["Balance"]], w["bal"], same_num(r[col["Balance"]], w["bal"]))
        fam = [f for f in ("Metal", "Joinery", "Acrylics") if str(r[col[f]] or "").strip().upper() == "Y"]
        cmp("Metal / Joinery / Acrylics", "/".join(fam), "/".join(w["families"]), set(fam) == set(w["families"]))
        # department hours: Dave's depts summed onto X3 work centres, against the board's hours per work centre
        dave_wc = defaultdict(float)
        for dep in depts:
            v = r[col[dep]]
            if isinstance(v, (int, float)) and v:
                dave_wc[dept_to_wc.get(dep, dep)] += float(v)
        acc_wc = {k: v for k, v in w["hours"].items() if v}
        all_wc = sorted(set(dave_wc) | set(acc_wc))
        hrs_same = all(abs(dave_wc.get(k, 0) - acc_wc.get(k, 0)) <= max(0.05, 0.02 * max(dave_wc.get(k, 0), acc_wc.get(k, 0)))
                       for k in all_wc)
        cmp("Dept hours", round(sum(dave_wc.values()), 2), round(sum(acc_wc.values()), 2), hrs_same)
        for k in all_wc:
            hours_rows.append([wo, w["code"], k, ", ".join(wcnames.get(k, [])) if isinstance(wcnames.get(k), (list, tuple)) else str(wcnames.get(k, "")), round(dave_wc.get(k, 0), 3), round(acc_wc.get(k, 0), 3),
                               round(acc_wc.get(k, 0) - dave_wc.get(k, 0), 3)])
        rows.append([wo, w["level"]] + checks + [str(r[col["MATERIAL STATUS"]] or "")[:120], w["status"], w["mat_text"][:120]])

    # ------------------------------------------------------------------ workbook
    wb = Workbook()
    rm = wb.active
    rm.title = "Read me"
    matched = len(rows)
    for line in [
        ("Live Orders – Production's sheet reconciled to the Access data and mapped onto Sage X3", None),
        (None, None),
        ("Production's sheet", f"Live_Orders.xlsx - a Crystal Reports export ('{props.creator}'), last saved by {props.lastModifiedBy} "
                               f"on {props.modified:%d %b %Y %H:%M}, then edited by hand. {dave_rows} works-order rows."),
        ("Access data", f"Extract as at {as_at} (read-only), the nearest to the sheet's date. {res['meta']['wos']} open works orders."),
        ("How", "No manual steps: the sheet and the Access data are read by a program and compared works order by works order, "
                "column by column. Every column is then traced to its Access source and to the Sage X3 import template it was loaded with."),
        ("Result", f"{matched} of the sheet's {dave_rows} works orders were still open in Access on the extract date and are compared; "
                   f"{len(not_open)} had been completed since the sheet was saved."),
        (None, None),
        ("Tab", "What it shows"),
        ("Findings", "START HERE: what the reconciliation shows, and the gaps between Production's sheet and the Sage X3 data as loaded."),
        ("Column map", "Every column of the sheet: what it means, the Access source, how it is worked out, the Sage X3 template "
                       "and field it lands in, whether it reaches X3, and how well it reconciles."),
        ("By works order", "Each matched works order: the sheet's value, the Access value and ✓ / ✗ for every column."),
        ("Dept hours", "The sheet's department hours (summed onto Sage X3 work centres) against the hours worked out from the route."),
        ("Not open", "Works orders on the sheet that were no longer open in Access on the extract date."),
    ]:
        rm.append(line)
    rm["A1"].font = Font(bold=True, size=14)
    for row in rm.iter_rows(min_row=3):
        row[0].font = B
        for c in row:
            c.alignment = WRAP
    rm["A8"].fill = rm["B8"].fill = INK
    rm["A8"].font = rm["B8"].font = Y
    rm.column_dimensions["A"].width, rm.column_dimensions["B"].width = 20, 120

    # ------------------------------------------------------------------ findings (worked out from the comparison)
    def st(k):
        return stats[k][0], stats[k][1]
    both = [h for h in hours_rows if h[4] and h[5]]
    close = sum(1 for h in both if abs(h[6]) <= max(0.05, 0.02 * max(h[4], h[5])))
    sheet_only = sum(1 for h in hours_rows if h[4] and not h[5])
    board_only = sum(1 for h in hours_rows if h[5] and not h[4])
    all_wor = lo.read_extract(a.extract)[0]["WOR"]          # every open works order in Access (incl. nothing left to make)
    acc_rev = sum(1 for w in all_wor if str(w["rev"] or "").strip())
    due_s, due_n = st("Due date")
    fw = wb.create_sheet("Findings")
    for line in [
        (f"What the reconciliation shows (Production's sheet against Access as at {as_at}, {matched} works orders still open in both)", None),
        (None, None),
        ("Finding", "Detail"),
        ("Part, quantity, balance – the same",
         f"Part code {'%d / %d' % st('Part code')}, quantity ordered {'%d / %d' % st('QTY')}, balance {'%d / %d' % st('Balance')} and "
         f"booked-in {'%d / %d' % st('Booked in')}. Differences are works orders where more was made after the sheet was saved."),
        ("Sales order – the same",
         f"{'%d / %d' % st('SO Num')} once 'Stock' on the sheet is read as 'no sales order' (as in Access). Those left are mostly "
         "sub-assembly orders where the sheet leaves the sales order blank."),
        ("Due date – moved, not wrong",
         f"{due_s} / {due_n} the same. {due_later} of the {due_n - due_s} that differ have a LATER date in Access: "
         "orders were rescheduled after the sheet was saved."),
        ("REV – typed by Production",
         f"Access holds a revision on only {acc_rev} of {len(all_wor)} open works orders. Production type the rev from the drawing "
         f"(the sheet has it where Access has none on {rev_typed_only} more). In Sage X3 the rev is migrated onto the product "
         "(Description 2), not the works order."),
        ("Metal / Joinery / Acrylics – a definition to agree",
         f"{'%d / %d' % st('Metal / Joinery / Acrylics')} the same. The sheet marks the shops still to come; working it out from the "
         "route gives every shop the part ever goes through."),
        ("Department hours – the important one",
         f"Per work centre: {close} of {len(both)} lines where both have hours agree. {sheet_only} lines have hours only on the sheet "
         f"and {board_only} only from the route. The sheet's hours come from each works order's OWN operations, with finished "
         "operations dropping off; the route can't know what is finished. In Sage X3 the migrated works orders (YA004MFG) are "
         "loaded at the remaining quantity with ALL operations open, so hours already done in Access would show as still to do."),
        ("Customer date – broken today",
         "The sheet's formula shows #REF!. Access has the date on the sales-order line; Sage X3 needs the works order linked to its "
         "sales order to show it, and YA004MFG doesn't load that link."),
        ("Material status, comments, Prog, tube – typed",
         "Not held in Access or the templates. Material status can be worked out from Sage X3 (WO materials, stock, POs); the notes "
         "need user fields on the works order or a separate store."),
        ("WO number – not carried",
         "YA004MFG leaves the order number blank, so Sage X3 gives each works order a new number. Production's sheet is keyed on "
         "the Access number."),
    ]:
        fw.append(line)
    fw["A1"].font = Font(bold=True, size=13)
    fw["A3"].fill = fw["B3"].fill = INK
    fw["A3"].font = fw["B3"].font = Y
    for row in fw.iter_rows(min_row=4):
        row[0].font = B
        for c in row:
            c.alignment = WRAP
    fw.column_dimensions["A"].width, fw.column_dimensions["B"].width = 36, 120

    cm = wb.create_sheet("Column map")
    cm.append(["Production's column", "What it means", "Access source", "How it is worked out", "Sage X3 template / field",
               "Reaches Sage X3?", "Reconciles with the sheet"])
    for c in cm[1]:
        c.fill, c.font, c.alignment = INK, Y, WRAP
    key = {"Due date": "Due date", "SO Num": "SO Num", "Part code": "Part code", "REV": "REV", "QTY": "QTY",
           "Booked in": "Booked in", "Balance": "Balance", "Metal / Joinery / Acrylics": "Metal / Joinery / Acrylics",
           "LASM … PACP (23 dept columns)": "Dept hours"}
    for c_ in COLUMNS:
        k = key.get(c_[0])
        if k:
            s, n = stats[k]
            rec = f"{s} of {n} ({100 * s / n:.0f}%)" if n else "–"
        elif c_[0] == "Customer Date":
            rec = "Not comparable: the sheet's formula shows #REF!"
        elif c_[0] in ("MATERIAL STATUS", "Tube req / Comments / Prog"):
            rec = "Typed text: not comparable (the board works material status out)"
        else:
            rec = "Derived from the part code"
        cm.append(list(c_) + [rec])
        cm.cell(cm.max_row, 6).fill = OK if c_[5].startswith("Loaded") else (NO if c_[5].startswith("GAP") else INFO)
        for c in cm[cm.max_row]:
            c.alignment = WRAP
    for colw, w_ in zip("ABCDEFG", (22, 30, 34, 38, 46, 30, 26)):
        cm.column_dimensions[colw].width = w_
    cm.freeze_panes = "B2"

    bw = wb.create_sheet("By works order")
    hdr = ["WO", "Level"]
    for name in ("Part code", "Due date", "SO Num", "REV", "QTY", "Booked in", "Balance", "Metal/Joinery/Acrylics", "Dept hours (total)"):
        hdr += [f"{name}: sheet", f"{name}: Access", "✓/✗"]
    hdr += ["Material status (typed on the sheet)", "Board status", "Board material detail"]
    bw.append(hdr)
    for c in bw[1]:
        c.fill, c.font, c.alignment = INK, Y, WRAP
    for r in rows:
        bw.append([x.strftime("%d/%m/%y") if isinstance(x, dt.date) else x for x in r])
        for i, v in enumerate(r, 1):
            if v in ("✓", "✗"):
                bw.cell(bw.max_row, i).fill = OK if v == "✓" else NO
    bw.freeze_panes = "C2"
    bw.column_dimensions["A"].width = 14

    hw = wb.create_sheet("Dept hours")
    hw.append(["WO", "Part", "X3 work centre", "Access dept(s)", "Sheet hours", "Board hours", "Difference"])
    for c in hw[1]:
        c.fill, c.font = INK, Y
    for r in hours_rows:
        hw.append(r)
    hw.freeze_panes = "A2"

    nw = wb.create_sheet("Not open")
    nw.append(["WO", "Part code", "Description", "Balance on the sheet", "Why not compared"])
    for c in nw[1]:
        c.fill, c.font = INK, Y
    for r in not_open:
        nw.append(r)
    wb.save(a.out)
    print(f"sheet {dave_rows} rows, compared {matched}, not open {len(not_open)}")
    for k, (s, n) in stats.items():
        print(f"  {k}: {s}/{n}")


if __name__ == "__main__":
    main()
