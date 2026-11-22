"""Year-end product-line report for one customer, from customer_year_end.sql's output. Written 22 Nov 2026.

    python customer_year_end_xlsx.py --run --customer "<name>" --name "%<NAME>%" --prefix "<PFX>-%"
        one command (22 Nov, James: SSMS Results-to-File "is very unorthodox"): runs customer_year_end.sql against
        SDILive itself - read only, with your own Windows login, no password anywhere - and saves the workbook to your
        Desktop. [--server 10.0.0.200] [--database SDILive] [--out <file.xlsx>]
    python customer_year_end_xlsx.py <customer_year_end.txt> <out.xlsx> --customer "<name>"   (from an SSMS file)
    [--target-margin 25]

A record of every product line the customer bought from SDI this year (with last year beside it) before the move to
Sage X3, and a first look at where manufacturing could cost less: margins, batch sizes, scrap, prices. Read-only
data from Access; nothing is changed anywhere. The customer's name is given on the command line and appears only in
the workbook (never in git).

Tabs: Read me (period, accounts, ASSUMPTIONS), Summary, By part, Opportunities, Order lines, Works orders, Accounts.
"""
import argparse
import collections
import datetime as dt
import os
import re
import statistics
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

INK, YELLOW, SOFT = "282928", "F5D947", "F4F4F0"
RED, AMBER, GREEN = "FDE2E1", "FFF1C7", "E3F4E8"
NOT_PRODUCT = re.compile(r"^(CARRIAGE.*|DELIVERY.*|REWORK.*|ADDITIONAL COST.*|SDI-PROTO|MISC PRINT|SAMPLE.*|POSTAGE.*)$|"
                         r"INSTALLATION|RESPRAY|CARRIAGE", re.I)


# ---------------------------------------------------------------- reading SSMS "Results to File" output
def read(path):
    """Grids by label: {'LINE': [dict, ...], ...}. Each grid's header row starts with 'grid'."""
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            text = raw.decode(enc)
            if "grid" in text:
                break
        except UnicodeDecodeError:
            continue
    grids, head = collections.defaultdict(list), None
    for ln in text.splitlines():
        cells = ln.rstrip("\r").split("\t")
        if not cells or not cells[0].strip():
            continue
        if cells[0].strip() == "grid":
            head = [c.strip() for c in cells]
            continue
        if head and cells[0].strip() in ("CHECK", "ACCOUNT", "LINE", "WO", "PART") and len(cells) >= len(head) - 1:
            grids[cells[0].strip()].append({h: (cells[i].strip() if i < len(cells) else "") for i, h in enumerate(head)})
    return grids


def num(v):
    try:
        return float(str(v).replace(",", "")) if v not in (None, "", "NULL") else 0.0
    except ValueError:
        return 0.0


def day(v):
    m = re.match(r"(\d{4})-(\d\d)-(\d\d)", str(v or ""))
    return dt.date(int(m[1]), int(m[2]), int(m[3])) if m else None


def run_sql(server, database, name_like, part_like, login=""):
    """Run customer_year_end.sql (beside this file) on SDILive and return its grids, as read() would from a file.
    Windows authentication only; the SQL only reads (temp tables in tempdb). The two placeholders are filled in
    memory - the file on disk keeps them."""
    import pyodbc                                     # pip install pyodbc (and Microsoft's ODBC Driver 17/18)
    sql = (Path(__file__).with_name("customer_year_end.sql")).read_text(encoding="utf-8")
    q = lambda v: v.replace("'", "''")
    sql, n1 = re.subn(r"DECLARE @name_like varchar\(60\) = '[^']*';", f"DECLARE @name_like varchar(60) = '{q(name_like)}';", sql)
    sql, n2 = re.subn(r"DECLARE @part_like varchar\(30\) = '[^']*';", f"DECLARE @part_like varchar(30) = '{q(part_like)}';", sql)
    if not (n1 and n2):
        sys.exit("customer_year_end.sql has changed: can't find the @name_like / @part_like lines")
    sql = re.sub(r"(?im)^\s*USE \w+;\s*$", "", sql)  # the database comes from the connection
    drivers = [d for d in ("ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server", "SQL Server")
               if d in pyodbc.drivers()]
    if not drivers:
        sys.exit("No SQL Server ODBC driver on this PC: install Microsoft's 'ODBC Driver 18 for SQL Server'")
    if login:                                         # a SQL Server login, as SSMS's "SQL Server Authentication":
        import getpass                                # the password is typed (hidden), used once, never stored
        auth = f"UID={login};PWD={{{getpass.getpass(f'Password for {login} on {server} (hidden): ').replace('}', '}}')}}};"
    else:
        auth = "Trusted_Connection=yes;"              # Windows login, as SSMS's "Windows Authentication"
    conn = pyodbc.connect(f"DRIVER={{{drivers[0]}}};SERVER={server};DATABASE={database};{auth}"
                          "TrustServerCertificate=yes;Encrypt=yes;ApplicationIntent=ReadOnly;", timeout=20,
                          autocommit=True)
    cur = conn.cursor()
    cur.execute(sql)
    grids = collections.defaultdict(list)
    txt = lambda v: "" if v is None else (v.isoformat() if hasattr(v, "isoformat") else str(v))
    while True:
        if cur.description:
            cols = [c[0] for c in cur.description]
            for row in cur.fetchall():
                rec = {c: txt(v) for c, v in zip(cols, row)}
                grids[rec.get("grid", "")].append(rec)
        if not cur.nextset():
            break
    conn.close()
    return grids


# ---------------------------------------------------------------- the analysis
def analyse(g, target):
    chk = (g.get("CHECK") or [{}])[0]
    y0 = day(chk.get("this_year_from")) or dt.date(dt.date.today().year, 1, 1)
    p0 = day(chk.get("last_year_from")) or dt.date(y0.year - 1, 1, 1)
    to = day(chk.get("to_date")) or dt.date.today()
    parts = {r["part"]: r for r in g.get("PART", [])}
    lines = []
    for r in g.get("LINE", []):
        d = day(r["order_date"])
        if not d:
            continue
        q, price = num(r["qty_ordered"]), num(r["unit_price"])
        lines.append(dict(r, d=d, yr="this" if d >= y0 else "last", qty=q, dq=num(r["qty_delivered"]), price=price,
                          value=round(q * price, 2), product=not NOT_PRODUCT.search(r["part"])))
    wos = []
    for r in g.get("WO", []):
        fin = day(r["done"]) or day(r["scheduled"])
        good, rej, scr = num(r["qty_good"]), num(r["qty_rejected"]), num(r["qty_scrap"])
        cost = num(r["booked_mat"]) + num(r["booked_lab"]) + num(r["booked_subcon"])
        wos.append(dict(r, fin=fin, open=r["status"].strip() == "", good=good, rej=rej, scr=scr, batch=good + rej + scr,
                        mat=num(r["booked_mat"]), lab=num(r["booked_lab"]), sc=num(r["booked_subcon"]), cost=cost,
                        yr=None if r["status"].strip() == "" else ("this" if fin and fin >= y0 else "last")))

    rows = []
    for part in sorted({l["part"] for l in lines}):
        L = [l for l in lines if l["part"] == part]
        ty, ly = [l for l in L if l["yr"] == "this"], [l for l in L if l["yr"] == "last"]
        P = parts.get(part, {})
        qty, val = sum(l["qty"] for l in ty), sum(l["value"] for l in ty)
        lqty, lval = sum(l["qty"] for l in ly), sum(l["value"] for l in ly)
        prices = [l["price"] for l in ty if l["price"] > 0] or [l["price"] for l in ly if l["price"] > 0]
        avg = (val / qty) if qty else ((lval / lqty) if lqty else 0)
        W = [w for w in wos if w["part"] == part]
        done_ty = [w for w in W if w["yr"] == "this" and w["good"] > 0]
        done_ly = [w for w in W if w["yr"] == "last" and w["good"] > 0]
        basis_w = done_ty or done_ly
        good = sum(w["good"] for w in basis_w)
        cost_w = sum(w["cost"] for w in basis_w)
        std = num(P.get("cost")) / (num(P.get("cost_per")) or 1) if num(P.get("cost")) else 0
        if good and cost_w > 0:
            unit_cost = cost_w / good
            basis = "works orders this year" if done_ty else "works orders last year"
        elif std:
            unit_cost, basis = std, "Access standard cost"
        else:
            unit_cost, basis = None, "no cost found"
        mat_u = sum(w["mat"] for w in basis_w) / good if good else None
        lab_u = sum(w["lab"] for w in basis_w) / good if good else None
        margin = (avg - unit_cost) if unit_cost is not None and avg else None
        mpct = (margin / avg) if margin is not None and avg else None
        made = sum(w["batch"] for w in done_ty)
        lost = sum(w["rej"] + w["scr"] for w in done_ty)
        scrap = lost / made if made else None
        batches = [w["batch"] for w in done_ty]
        # batch size and labour per unit: the smaller half of this year's works orders against the larger half
        small_u = large_u = saving = None
        bw = [w for w in (done_ty if len(done_ty) >= 2 else done_ty + done_ly) if w["good"] > 0 and w["lab"] > 0]
        if len(bw) >= 2:
            med = statistics.median(w["batch"] for w in bw)
            sm = [w for w in bw if w["batch"] <= med]
            lg = [w for w in bw if w["batch"] > med] or [max(bw, key=lambda w: w["batch"])]
            small_u = sum(w["lab"] for w in sm) / sum(w["good"] for w in sm)
            large_u = sum(w["lab"] for w in lg) / sum(w["good"] for w in lg)
            if large_u and small_u > large_u:
                saving = (small_u - large_u) * sum(w["good"] for w in sm if w in done_ty or not done_ty)
        by_price = collections.Counter()                          # the usual price: the one most units sold at
        for l in ty:
            by_price[round(l["price"], 4)] += l["qty"]
        usual = by_price.most_common(1)[0][0] if by_price else 0
        below = sum((usual - l["price"]) * l["qty"] for l in ty if 0 < l["price"] < usual)
        open_w = [w for w in W if w["open"]]
        open_ord = sum(max(l["qty"] - l["dq"], 0) for l in L if l["line_status"] in ("", "B", "H"))
        flags = []
        if L and not L[0]["product"]:
            flags.append("Not a product (carriage, rework etc.)")
        else:
            if mpct is not None and mpct < 0:
                flags.append("LOSS")
            elif mpct is not None and mpct < target:
                flags.append(f"Margin under {target:.0%}")
            if scrap is not None and scrap >= 0.03:
                flags.append(f"Scrap / rejects {scrap:.0%}")
            if small_u and large_u and small_u >= 1.5 * large_u:
                flags.append(f"Small batches cost {small_u / large_u:.1f}x the labour per unit")
            if len(prices) >= 2 and avg and (max(prices) - min(prices)) / avg > 0.05:
                flags.append(f"Price varies {min(prices):.2f} - {max(prices):.2f}")
            if unit_cost is None:
                flags.append("No cost found")
        rows.append(dict(part=part, description=P.get("description") or P.get("description_full") or "",
                         product=bool(L[0]["product"]), accounts=", ".join(sorted({l["account"] for l in L})),
                         lines=len(ty), orders=len({l["order_no"] for l in ty}), qty=qty,
                         delivered=sum(l["dq"] for l in ty), value=val, avg=avg,
                         pmin=min(prices) if prices else None, pmax=max(prices) if prices else None,
                         lqty=lqty, lval=lval, chg=((qty - lqty) / lqty) if lqty else None,
                         first=min((l["d"] for l in ty), default=None), last=max((l["d"] for l in L), default=None),
                         wos=len(done_ty), made=made, good=sum(w["good"] for w in done_ty), lost=lost, scrap=scrap,
                         bavg=(sum(batches) / len(batches)) if batches else None, bmin=min(batches) if batches else None,
                         bmax=max(batches) if batches else None, mat_u=mat_u, lab_u=lab_u, unit_cost=unit_cost,
                         basis=basis, std=std or None, margin=margin, mpct=mpct,
                         mval=(margin * qty) if margin is not None else None, small_u=small_u, large_u=large_u,
                         saving=saving, open_wos=len(open_w), open_wo_qty=sum(w["batch"] or num(w["qty_planned"])
                                                                                for w in open_w),
                         open_ord=open_ord, usual=usual, below=below, flags="; ".join(flags), currency=", ".join(sorted({l["currency"] or "GBP"
                                                                                               for l in L}))))
    return dict(chk=chk, y0=y0, p0=p0, to=to, lines=lines, wos=wos, rows=rows, accounts=g.get("ACCOUNT", []),
                target=target)


def opportunities(a):
    """One row per finding, with a rough yearly £ figure to rank them. Estimates to start a conversation, not facts."""
    out, t = [], a["target"]
    for r in a["rows"]:
        if not r["product"]:
            continue
        if r["mpct"] is not None and r["mpct"] < t and r["qty"]:
            need = r["unit_cost"] - r["avg"] * (1 - t)               # cost cut per unit to reach the target margin
            out.append(["Margin" if r["mpct"] >= 0 else "LOSS", r["part"], r["description"],
                        f"Margin {r['mpct']:.0%} at an average price of {r['avg']:.2f} and a cost of "
                        f"{r['unit_cost']:.2f} ({r['basis']})",
                        f"Cost down {need:.2f} a unit (or price up) to reach {t:.0%}", need * r["qty"]])
        if r["saving"] and r["small_u"] and r["large_u"] and r["small_u"] >= 1.5 * r["large_u"]:
            out.append(["Batch size", r["part"], r["description"],
                        f"Labour {r['small_u']:.2f} a unit in the smaller batches vs {r['large_u']:.2f} in the larger "
                        f"(batches {r['bmin']:g}-{r['bmax']:g}, average {r['bavg']:.0f})",
                        "Make in fewer, larger batches (call-offs from stock), or cut set-up time", r["saving"]])
        if r["scrap"] and r["scrap"] >= 0.03 and r["unit_cost"]:
            out.append(["Scrap / rejects", r["part"], r["description"],
                        f"{r['lost']:g} of {r['made']:g} made were rejected or scrapped ({r['scrap']:.0%})",
                        "Find the cause (material, programme, handling) and fix it at source",
                        r["lost"] * r["unit_cost"]])
        if r["flags"] and "Price varies" in r["flags"]:
            out.append(["Price", r["part"], r["description"],
                        f"Sold at {r['pmin']:.2f} to {r['pmax']:.2f} this year (usual price {r['usual']:.2f})",
                        "Check the lower prices were intended; agree one price", r["below"]])
    big = sorted((r for r in a["rows"] if r["product"] and r["lab_u"] and r["qty"]), key=lambda r: -r["lab_u"] * r["qty"])
    for r in big[:10]:                                              # where labour time matters most
        out.append(["Volume", r["part"], r["description"],
                    f"{r['qty']:g} ordered this year; labour {r['lab_u']:.2f} a unit",
                    "Every 10% off its labour time is worth this a year", 0.1 * r["lab_u"] * r["qty"]])
    out.sort(key=lambda x: -(x[5] or 0))
    return out


# ---------------------------------------------------------------- the workbook
def _style_head(ws, row, n):
    for c in range(1, n + 1):
        cell = ws.cell(row=row, column=c)
        cell.fill = PatternFill("solid", fgColor=INK)
        cell.font = Font(bold=True, color=YELLOW)
        cell.alignment = Alignment(wrap_text=True, vertical="top")


def _table(ws, head, rows, widths, start=1, fmts=None, freeze=True):
    for i, h in enumerate(head, 1):
        ws.cell(row=start, column=i, value=h)
    _style_head(ws, start, len(head))
    for r in rows:
        ws.append(list(r))
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for col, f in (fmts or {}).items():
        for row in ws.iter_rows(min_row=start + 1, min_col=col, max_col=col):
            row[0].number_format = f
    if freeze:
        ws.freeze_panes = ws.cell(row=start + 1, column=2)
    if rows:
        ws.auto_filter.ref = f"A{start}:{get_column_letter(len(head))}{start + len(rows)}"


def _section(ws, text, width=8):
    ws.append([text])
    r = ws.max_row
    for c in range(1, width + 1):
        ws.cell(row=r, column=c).fill = PatternFill("solid", fgColor=YELLOW)
    ws.cell(row=r, column=1).font = Font(bold=True, size=12)


def write(a, path, customer):
    wb = Workbook()
    y, ly, to = a["y0"].year, a["p0"].year, a["to"]
    period = f"{a['y0']:%d %b %Y} to {to:%d %b %Y}"
    prod = [r for r in a["rows"] if r["product"]]
    other = [r for r in a["rows"] if not r["product"]]
    tot = lambda rows, k: sum((r[k] or 0) for r in rows)
    opps = opportunities(a)

    # Read me
    ws = wb.active
    ws.title = "Read me"
    ws.column_dimensions["A"].width = 4
    ws.column_dimensions["B"].width = 120
    ws["B1"] = f"{customer} - product lines {y} (year-end record before Sage X3)"
    ws["B1"].font = Font(bold=True, size=16)
    ws["B2"] = f"From Access SupplyChain (read only), {period}, with {ly} beside it. Generated {dt.datetime.now():%d %b %Y %H:%M}."
    accs = sorted({(r.get("account"), r.get("name"), r.get("found_by")) for r in a["accounts"]})
    t = a["target"]
    notes = [
        ("What's in it", [
            f"Summary: {y} so far against {ly}, the top lines by value, and where the margin sits.",
            "By part: one row per product line - quantities, value, prices, works orders, cost per unit, margin, flags.",
            "Opportunities: findings ranked by a rough yearly £ figure - margin, batch size, scrap, price, volume.",
            "Order lines and Works orders: the detail behind every figure. Accounts: which accounts are included.",
        ]),
        ("Assumptions - please check, and tell James what to change", [
            f"1. '{customer} lines' = every part on a sales order from an account whose name contains '{customer}' "
            f"({sum(1 for x in accs if x[2] == 'name')} account(s)), plus the same customer's own part codes ordered "
            f"through any other account ({sum(1 for x in accs if x[2] == 'part code')} account(s)). See Accounts.",
            f"2. The year is the calendar year {y} to {to:%d %b} (orders by order date). For the final record it "
            f"should be re-run on the last working day before the move to Sage (31 Dec), which takes a minute.",
            "3. Quantities and values are as ordered, at the order line's price (the discounted price where there is "
            "one), excluding VAT. Delivered quantities are shown beside them. Invoices are not used.",
            "4. Cost per unit = the material, labour and subcontract costs booked to the part's completed works orders "
            f"this year, divided by the good quantity made. Parts not made this year use last year's works orders, "
            "then Access's standard cost (shown in 'Cost basis'). Overheads, carriage and packing are not included "
            "unless they were booked to the works order.",
            "5. Margin = average selling price less that cost per unit - a contribution figure before overheads, not "
            "an accounts profit figure.",
            f"6. Flags: margin under {t:.0%}; loss; scrap and rejects of 3% or more; smaller batches costing 1.5x or "
            "more the labour per unit of larger ones; a part sold at prices more than 5% apart.",
            "7. Carriage, delivery, rework, installation and similar lines are kept separate ('Not a product') and "
            "left out of the product totals.",
            "8. The £ figures on Opportunities are rough yearly sizes to rank what to look at first - estimates to "
            "start a conversation, not savings.",
        ]),
        ("Accounts included", [f"{c} - {n} ({how})" for c, n, how in accs] or ["(none found)"]),
    ]
    r = 4
    for title, items in notes:
        ws.cell(row=r, column=2, value=title).font = Font(bold=True, size=12)
        ws.cell(row=r, column=2).fill = PatternFill("solid", fgColor=YELLOW)
        r += 1
        for it in items:
            c = ws.cell(row=r, column=2, value=it)
            c.alignment = Alignment(wrap_text=True, vertical="top")
            r += 1
        r += 1

    # Summary
    ws = wb.create_sheet("Summary")
    ws.column_dimensions["A"].width = 46
    for col in "BCDEFGH":
        ws.column_dimensions[col].width = 16
    ws["A1"] = f"{customer} - {y} to {to:%d %b} against {ly}"
    ws["A1"].font = Font(bold=True, size=14)
    ty_l = [l for l in a["lines"] if l["yr"] == "this" and l["product"]]
    ly_l = [l for l in a["lines"] if l["yr"] == "last" and l["product"]]
    ty_w = [w for w in a["wos"] if w["yr"] == "this"]
    ly_w = [w for w in a["wos"] if w["yr"] == "last"]
    kpi = [
        ("Product lines ordered", len({l["part"] for l in ty_l}), len({l["part"] for l in ly_l}), "0"),
        ("Order lines", len(ty_l), len(ly_l), "#,##0"),
        ("Orders", len({l["order_no"] for l in ty_l}), len({l["order_no"] for l in ly_l}), "#,##0"),
        ("Units ordered", sum(l["qty"] for l in ty_l), sum(l["qty"] for l in ly_l), "#,##0"),
        ("Order value (£, ex VAT)", sum(l["value"] for l in ty_l), sum(l["value"] for l in ly_l), "£#,##0"),
        ("Works orders completed (these parts)", len(ty_w), len(ly_w), "#,##0"),
        ("Units made (good)", sum(w["good"] for w in ty_w), sum(w["good"] for w in ly_w), "#,##0"),
        ("Rejected + scrapped", sum(w["rej"] + w["scr"] for w in ty_w), sum(w["rej"] + w["scr"] for w in ly_w), "#,##0"),
        ("Cost booked to works orders (£)", sum(w["cost"] for w in ty_w), sum(w["cost"] for w in ly_w), "£#,##0"),
        ("Estimated margin on this year's orders (£)", tot(prod, "mval"), None, "£#,##0"),
        ("Carriage / other lines (£)", sum(l["value"] for l in a["lines"] if l["yr"] == "this" and not l["product"]),
         sum(l["value"] for l in a["lines"] if l["yr"] == "last" and not l["product"]), "£#,##0"),
    ]
    ws.append([])
    ws.append(["", f"{y} to {to:%d %b}", f"{ly} (full year)", "Change"])
    _style_head(ws, 3, 4)
    for name, a1, b1, f in kpi:
        ws.append([name, a1, b1, ((a1 - b1) / b1) if (b1 and a1 is not None) else None])
        rr = ws.max_row
        ws.cell(row=rr, column=2).number_format = f
        ws.cell(row=rr, column=3).number_format = f
        ws.cell(row=rr, column=4).number_format = "0%"
    ws.append([])
    _section(ws, "Margin spread (product lines with a cost)", 4)
    bands = [("Loss", lambda m: m < 0), (f"0 - {t:.0%}", lambda m: 0 <= m < t), (f"{t:.0%} - 40%", lambda m: t <= m < .4),
             ("40% and over", lambda m: m >= .4)]
    ws.append(["Band", "Lines", f"Value {y} (£)"])
    _style_head(ws, ws.max_row, 3)
    for nm, fn in bands:
        rs = [r for r in prod if r["mpct"] is not None and fn(r["mpct"])]
        ws.append([nm, len(rs), tot(rs, "value")])
        ws.cell(row=ws.max_row, column=3).number_format = "£#,##0"
    rs = [r for r in prod if r["mpct"] is None]
    ws.append(["No cost found", len(rs), tot(rs, "value")])
    ws.cell(row=ws.max_row, column=3).number_format = "£#,##0"
    ws.append([])
    _section(ws, f"Top 15 product lines by value, {y}", 7)
    top = sorted(prod, key=lambda r: -r["value"])[:15]
    ws.append(["Part", "Description", "Units", "Value (£)", "Avg price", "Margin %", "Flags"])
    hrow = ws.max_row
    _style_head(ws, hrow, 7)
    for r0 in top:
        ws.append([r0["part"], r0["description"], r0["qty"], r0["value"], r0["avg"], r0["mpct"], r0["flags"]])
        rr = ws.max_row
        for c, f in ((3, "#,##0"), (4, "£#,##0"), (5, "£#,##0.00"), (6, "0%")):
            ws.cell(row=rr, column=c).number_format = f
    if top:
        ch = BarChart()
        ch.type, ch.title, ch.height, ch.width = "bar", f"Top product lines by value, {y} (£)", 9, 18
        ch.add_data(Reference(ws, min_col=4, min_row=hrow, max_row=hrow + len(top)), titles_from_data=True)
        ch.set_categories(Reference(ws, min_col=1, min_row=hrow + 1, max_row=hrow + len(top)))
        ch.legend = None
        ch.y_axis.majorGridlines = None
        ws.add_chart(ch, "I3")

    # By part
    ws = wb.create_sheet("By part")
    head = ["Part", "Description", "Accounts", f"Order lines {y}", f"Orders {y}", f"Units ordered {y}",
            f"Units delivered {y}", f"Value {y} (£)", "Avg price", "Lowest price", "Highest price",
            f"Units {ly}", f"Value {ly} (£)", "Change in units", "Last ordered", f"Works orders {y}",
            "Units made", "Rejected + scrap", "Scrap %", "Avg batch", "Smallest batch", "Largest batch",
            "Material / unit", "Labour / unit", "Cost / unit", "Cost basis", "Access std cost", "Margin / unit",
            "Margin %", f"Margin {y} (£)", "Labour / unit, smaller batches", "Labour / unit, larger batches",
            "Open works orders", "Open WO qty", "Open order qty", "Currency", "Flags"]
    rows = [[r["part"], r["description"], r["accounts"], r["lines"], r["orders"], r["qty"], r["delivered"], r["value"],
             r["avg"], r["pmin"], r["pmax"], r["lqty"], r["lval"], r["chg"], r["last"], r["wos"], r["made"], r["lost"],
             r["scrap"], r["bavg"], r["bmin"], r["bmax"], r["mat_u"], r["lab_u"], r["unit_cost"], r["basis"], r["std"],
             r["margin"], r["mpct"], r["mval"], r["small_u"], r["large_u"], r["open_wos"], r["open_wo_qty"],
             r["open_ord"], r["currency"], r["flags"]]
            for r in sorted(a["rows"], key=lambda r: (not r["product"], -r["value"]))]
    money = "£#,##0.00"
    _table(ws, head, rows, [18, 34, 14] + [10] * 33 + [60],
           fmts={6: "#,##0", 7: "#,##0", 8: "£#,##0", 9: money, 10: money, 11: money, 12: "#,##0", 13: "£#,##0",
                 14: "0%", 15: "dd/mm/yyyy", 19: "0.0%", 20: "#,##0", 23: money, 24: money, 25: money, 27: money,
                 28: money, 29: "0%", 30: "£#,##0", 31: money, 32: money})
    for i, r in enumerate(sorted(a["rows"], key=lambda r: (not r["product"], -r["value"])), 2):
        fill = RED if ("LOSS" in r["flags"] or "Margin under" in r["flags"]) else AMBER if r["flags"] and r["product"] \
            else SOFT if not r["product"] else None
        if fill:
            ws.cell(row=i, column=len(head)).fill = PatternFill("solid", fgColor=fill)

    # Opportunities
    ws = wb.create_sheet("Opportunities")
    ws["A1"] = (f"Where manufacturing could cost less - ranked by a rough yearly £ size (estimates to start a "
                f"conversation, not savings). Target margin {t:.0%}.")
    ws["A1"].font = Font(bold=True)
    _table(ws, ["Type", "Part", "Description", "What the data shows", "What to look at", "Rough £ a year"],
           opps, [16, 18, 34, 70, 56, 14], start=3, fmts={6: "£#,##0"})

    # Order lines
    ws = wb.create_sheet("Order lines")
    L = sorted(a["lines"], key=lambda l: (l["part"], l["d"]))
    _table(ws, ["Part", "Year", "Order date", "Our order", "Line", "Customer PO", "Account", "Found by", "Qty ordered",
                "Qty delivered", "Unit price", "Value (£)", "Currency", "Customer due", "Status", "Product?"],
           [[l["part"], l["d"].year, l["d"], l["order_no"], num(l["line"]), l["customer_po"], l["account"],
             l["found_by"], l["qty"], l["dq"], l["price"], l["value"], l["currency"] or "GBP", day(l["customer_due"]),
             l["line_status"], "yes" if l["product"] else "no (carriage etc.)"] for l in L],
           [18, 7, 11, 11, 6, 16, 10, 10, 10, 10, 10, 11, 8, 11, 7, 16],
           fmts={3: "dd/mm/yyyy", 9: "#,##0", 10: "#,##0", 11: "£#,##0.00", 12: "£#,##0.00", 14: "dd/mm/yyyy"})

    # Works orders
    ws = wb.create_sheet("Works orders")
    W = sorted(a["wos"], key=lambda w: (w["part"], w["fin"] or dt.date.max))
    _table(ws, ["Part", "Works order", "Status", "Type", "Parent order", "Made for", "Sales order", "Created",
                "Completed / due", "Planned qty", "Good", "Rejected", "Scrap", "Material £", "Labour £", "Subcon £",
                "Cost / good unit", "Labour / good unit"],
           [[w["part"], w["wo"], "open" if w["open"] else "complete", w["order_type"], w["parent_order"], w["customer"],
             w["sales_order"], day(w["created"]), w["fin"], num(w["qty_planned"]), w["good"], w["rej"], w["scr"],
             w["mat"], w["lab"], w["sc"], (w["cost"] / w["good"]) if w["good"] else None,
             (w["lab"] / w["good"]) if w["good"] else None] for w in W],
           [18, 12, 9, 6, 12, 10, 12, 11, 11, 9, 9, 9, 9, 11, 11, 11, 12, 12],
           fmts={8: "dd/mm/yyyy", 9: "dd/mm/yyyy", 14: "£#,##0.00", 15: "£#,##0.00", 16: "£#,##0.00",
                 17: "£#,##0.00", 18: "£#,##0.00"})

    # Accounts
    ws = wb.create_sheet("Accounts")
    _table(ws, ["Account", "Name", "Included because", "Order lines", "First order", "Last order"],
           [[x.get("account"), x.get("name"), x.get("found_by"), num(x.get("order_lines")), day(x.get("first_order")),
             day(x.get("last_order"))] for x in a["accounts"]], [12, 40, 28, 12, 12, 12],
           fmts={5: "dd/mm/yyyy", 6: "dd/mm/yyyy"})
    wb.save(path)
    return dict(parts=len(prod), other=len(other), value=tot(prod, "value"), opps=len(opps), flagged=sum(1 for r in prod if r["flags"]))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("txt", nargs="?", help="an SSMS Results-to-File output (not needed with --run)")
    ap.add_argument("out_pos", nargs="?", metavar="out")
    ap.add_argument("--run", action="store_true", help="read SDILive directly (read only, Windows login)")
    ap.add_argument("--name", help="with --run: the customer's name as in the sales ledger, e.g. %%NAME%%")
    ap.add_argument("--prefix", default="", help="with --run: their part-code prefix, e.g. ABC-%%")
    ap.add_argument("--server", default=os.environ.get("SDI_SQL_SERVER", "10.0.0.200"))
    ap.add_argument("--database", default="SDILive")
    ap.add_argument("--login", default="", help="a SQL Server login (as SSMS 'SQL Server Authentication'); the "
                                                  "password is asked for, hidden. Default: your Windows login")
    ap.add_argument("--out", help="the workbook (default: your Desktop)")
    ap.add_argument("--customer", required=True, help="the name shown in the workbook (never stored in git)")
    ap.add_argument("--target-margin", type=float, default=25, help="percent (default 25)")
    a = ap.parse_args(argv)
    safe = re.sub(r"[^\w-]+", "_", a.customer)
    a.out = a.out or a.out_pos or str(Path.home() / "Desktop" / f"{safe}_product_lines_{dt.date.today():%Y-%m-%d}.xlsx")
    if a.run:
        if not a.name:
            sys.exit("--run needs --name (the customer's name as in the sales ledger, e.g. %NAME%)")
        print(f"Reading {a.database} on {a.server} (read only) - about a minute ...", flush=True)
        g = run_sql(a.server, a.database, a.name, a.prefix, a.login)
    elif a.txt:
        g = read(a.txt)
    else:
        sys.exit("Give --run (read SDILive directly) or an SSMS output file")
    chk = (g.get("CHECK") or [{}])[0]
    print(f"Found: {chk.get('accounts_by_name', '?')} account(s) by name, {chk.get('other_accounts_by_part_code', '?')} "
          f"more by part code, {chk.get('order_lines', '?')} order lines, {chk.get('parts', '?')} parts, "
          f"{chk.get('works_orders', '?')} works orders")
    if not g.get("LINE"):
        sys.exit("No order lines found: check the name / prefix against the sales ledger (the CHECK line above)")
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    res = write(analyse(g, a.target_margin / 100), a.out, a.customer)
    print(f"{a.out}: {res['parts']} product lines (+{res['other']} carriage / other), "
          f"£{res['value']:,.0f} ordered this year, {res['flagged']} flagged, {res['opps']} opportunities listed")


if __name__ == "__main__":
    main()
