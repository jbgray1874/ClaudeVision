"""Rebate rolling report (REP-22, Jira SCRUM-275): Morrisons goalposts / branded bays.

Reads invoiced lines (a CSV or the tab-delimited output of rebate_rolling.sql), keeps the parts in
rebate_parts.csv, and writes an SDI-branded HTML report and Excel workbook:
  * one row per invoiced line: customer, part, description, price per, value in its month
  * a rolling 12 months ending with --end (default: the month of the run date)
  * monthly totals, a rebate of --rate (default 6%) on each month's total, grand totals
  * invoice, due and order dates are carried on every line; --basis picks which one puts a line in
    a month (default invoice). Source: rebate_rolling.sql - Access's own invoiced-sales joins
    (TBI_TBL invoice lines -> COR_TBL order lines -> SL_ACCOUNTS2), as in dbo.UDEF_INVOICED_SALES

Usage:
    python build_rebate_report.py <lines.csv|.txt> <out_dir> [--end 2026-11] [--rate 0.06]
        [--basis invoice|due|order] [--parts rebate_parts.csv] [--sample]
Input columns (header row, any order): customer_code, customer_name, part_code, description,
price_per, quantity, invoice_no, invoice_date, due_date, order_no, order_date
(optional: project_no, customer_rebate_pct)
(value = quantity x price_per; dates as YYYY-MM-DD or YYYYMMDD).
"""
import argparse
import csv
import datetime as dt
import html
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.workbook.defined_name import DefinedName

HERE = Path(__file__).parent
Y, INK, SOFT, LINE, MUTED = "F5D947", "282928", "FBFBF8", "E6E7E4", "6B6F6C"
e = html.escape


def money(x):
    return Decimal(str(x)).quantize(Decimal("0.01"), ROUND_HALF_UP)


def day(v):
    v = (v or "").strip()[:10].replace("-", "")
    return dt.date(int(v[:4]), int(v[4:6]), int(v[6:8])) if len(v) == 8 and v.isdigit() else None


def months_ending(end):
    y, m = end
    out = []
    for _ in range(12):
        out.append((y, m))
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return out[::-1]


def read_lines(path):
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    delim = "\t" if text.split("\n", 1)[0].count("\t") > text.split("\n", 1)[0].count(",") else ","
    rows = list(csv.DictReader(text.splitlines(), delimiter=delim))
    return [{k.strip().lower(): (v or "").strip() for k, v in r.items() if k} for r in rows]


def build(lines_path, out_dir, end=None, rate="0.06", basis="invoice", parts_path=None, sample=False):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    today = dt.date.today()
    end = end or (today.year, today.month)
    rate = Decimal(str(rate))
    window = months_ending(end)
    labels = [dt.date(y, m, 1).strftime("%B") for y, m in window]
    parts = [r["part_code"].strip() for r in csv.DictReader(open(parts_path or HERE / "rebate_parts.csv"))
             if r["part_code"].strip()]
    pset = {p.upper() for p in parts}

    rows, skipped = [], 0
    for r in read_lines(lines_path):
        if r["part_code"].strip().upper() not in pset:
            skipped += 1
            continue
        price, qty = Decimal(r["price_per"] or "0"), Decimal(r["quantity"] or "0")
        d = {"invoice": day(r.get("invoice_date")), "due": day(r.get("due_date") or r.get("delivery_date")),
             "order": day(r.get("order_date"))}
        when = d[basis]
        r.update(price=price, qty=qty, value=money(price * qty), dates=d,
                 col=window.index((when.year, when.month)) if when and (when.year, when.month) in window else None)
        rows.append(r)
    rows.sort(key=lambda r: (r["customer_code"], r["part_code"], r["dates"][basis] or dt.date.min))

    month_tot = [sum((r["value"] for r in rows if r["col"] == i), Decimal("0")) for i in range(12)]
    month_reb = [money(t * rate) for t in month_tot]
    grand, rebate = sum(month_tot, Decimal("0")), sum(month_reb, Decimal("0"))
    in_window = [r for r in rows if r["col"] is not None]
    by_cust = defaultdict(lambda: [None, Decimal("0"), 0])
    for r in in_window:
        c = by_cust[r["customer_code"]]
        c[0], c[1], c[2] = r["customer_name"], c[1] + r["value"], c[2] + 1
    by_part = defaultdict(lambda: [Decimal("0"), Decimal("0")])
    for r in in_window:
        by_part[r["part_code"]][0] += r["qty"]
        by_part[r["part_code"]][1] += r["value"]
    period = f"{labels[0]} {window[0][0]} – {labels[-1]} {window[-1][0]}"
    stamp = f"{today:%d %B %Y}"
    meta = dict(period=period, stamp=stamp, rate=rate, basis=basis, sample=sample, lines=len(rows),
                in_window=len(in_window), customers=len(by_cust), skipped=skipped, parts=parts)
    name = f"SDI_Rebate_Rolling_{window[-1][0]}-{window[-1][1]:02d}" + ("_SAMPLE" if sample else "")
    write_xlsx(out / f"{name}.xlsx", rows, window, labels, month_tot, month_reb, grand, rebate, by_cust, by_part, meta)
    write_html(out / f"{name}.html", rows, window, labels, month_tot, month_reb, grand, rebate, by_cust, by_part, meta)
    return dict(grand=grand, rebate=rebate, month_tot=month_tot, month_reb=month_reb, name=name, meta=meta)


# --------------------------------------------------------------------------------------------- Excel
def write_xlsx(path, rows, window, labels, mt, mr, grand, rebate, by_cust, by_part, meta):
    wb = Workbook()
    ink, yel, soft = (PatternFill("solid", fgColor=c) for c in (INK, Y, SOFT))
    thin = Side(style="thin", color=LINE)
    gbp = '£#,##0.00;[Red]-£#,##0.00;"–"'
    W = Font(name="Calibri", bold=True, color="FFFFFF")

    def banner(ws, title, width):
        ws.sheet_view.showGridLines = False
        for c in range(1, width + 1):
            ws.cell(1, c).fill = ink
            ws.cell(2, c).fill = ink
            ws.cell(3, c).fill = yel
        ws.row_dimensions[1].height, ws.row_dimensions[2].height, ws.row_dimensions[3].height = 22, 30, 4
        ws.cell(1, 1, "we.are.sdi").font = Font(name="Calibri", bold=True, color=Y, size=11)
        ws.cell(2, 1, title).font = Font(name="Calibri", bold=True, color="FFFFFF", size=18)
        sub = f"{meta['period']} · rebate {meta['rate'] * 100:.0f}% · months by {meta['basis']} date · run {meta['stamp']}"
        ws.cell(4, 1, ("SAMPLE – figures rebuilt from the November 2026 PDF · " if meta["sample"] else "") + sub
                ).font = Font(name="Calibri", italic=True, color=MUTED, size=10)

    def head(ws, row, values, start=1):
        for i, v in enumerate(values):
            c = ws.cell(row, start + i, v)
            c.fill, c.font = ink, W
            c.alignment = Alignment(horizontal="center" if i >= 5 else "left", vertical="center", wrap_text=True)
        ws.row_dimensions[row].height = 30

    # ---- Summary
    s = wb.active
    s.title = "Summary"
    banner(s, "Rebate rolling report – Morrisons goalposts & branded bays", 10)
    s["A5"] = "Rebate rate"
    s["B5"] = float(meta["rate"])
    s["B5"].number_format, s["B5"].fill, s["B5"].font = "0.0%", PatternFill("solid", fgColor="FDF6CF"), Font(bold=True)
    s["C5"] = "← change this and every rebate in the workbook follows"
    s["C5"].font = Font(italic=True, color=MUTED)
    wb.defined_names["RebateRate"] = DefinedName("RebateRate", attr_text="Summary!$B$5")
    tiles = ["Sales in period", "Rebate due", "Invoiced lines", "Customers"]
    for i, lab in enumerate(tiles):
        c = s.cell(7, 1 + i * 2, lab)
        c.font = Font(color=MUTED, size=10)
    first_tot = 6 + len(rows)                          # the Totals row on "Rebate report"
    s.cell(8, 1, f"='Rebate report'!R{first_tot}")
    s.cell(8, 3, f"='Rebate report'!R{first_tot + 1}")
    s.cell(8, 5, meta["in_window"])
    s.cell(8, 7, meta["customers"])
    for col, fmt in ((1, gbp), (3, gbp), (5, "#,##0"), (7, "#,##0")):
        c = s.cell(8, col)
        c.font, c.number_format = Font(bold=True, size=20, color=INK), fmt
        s.cell(9, col).fill = yel
    for col in (1, 3, 5, 7):                           # each tile spans two columns
        for rr in (7, 8, 9):
            s.merge_cells(start_row=rr, start_column=col, end_row=rr, end_column=col + 1)
        s.cell(8, col).alignment = Alignment(horizontal="left", vertical="center")
    s.page_setup.orientation = "landscape"
    s.page_setup.fitToWidth, s.page_setup.fitToHeight = 1, 0
    s.sheet_properties.pageSetUpPr.fitToPage = True
    s.row_dimensions[8].height = 30
    s.row_dimensions[9].height = 3
    r0 = 11
    s.cell(r0, 1, "By month").font = Font(bold=True, size=13)
    head(s, r0 + 1, ["Month", "Year", "Sales £", "Rebate £"])
    for i, ((y, m), lab) in enumerate(zip(window, labels)):
        rr = r0 + 2 + i
        col = get_column_letter(6 + i)
        s.cell(rr, 1, lab)
        s.cell(rr, 2, y)
        s.cell(rr, 3, f"='Rebate report'!{col}{first_tot}").number_format = gbp
        s.cell(rr, 4, f"='Rebate report'!{col}{first_tot + 1}").number_format = gbp
    rt = r0 + 14
    s.cell(rt, 1, "Total").font = Font(bold=True)
    s.cell(rt, 3, f"=SUM(C{r0 + 2}:C{rt - 1})").number_format = gbp
    s.cell(rt, 4, f"=SUM(D{r0 + 2}:D{rt - 1})").number_format = gbp
    for c in (1, 2, 3, 4):
        s.cell(rt, c).font = Font(bold=True)
        s.cell(rt, c).border = Border(top=Side(style="medium", color=INK))
    ch = BarChart()
    ch.type, ch.style, ch.title = "col", 10, "Sales by month (£)"
    ch.y_axis.title, ch.legend = None, None
    ch.add_data(Reference(s, min_col=3, min_row=r0 + 1, max_row=rt - 1), titles_from_data=True)
    ch.set_categories(Reference(s, min_col=1, min_row=r0 + 2, max_row=rt - 1))
    ch.series[0].graphicalProperties.solidFill = INK
    ch.series[0].graphicalProperties.line.solidFill = INK
    ch.gapWidth, ch.height, ch.width = 60, 8.5, 17
    s.add_chart(ch, f"F{r0}")
    rc = rt + 3
    s.cell(rc, 1, "By customer (in period)").font = Font(bold=True, size=13)
    head(s, rc + 1, ["Customer", "Name", "Lines", "Sales £", "Rebate £"])
    for i, (code, (nm, val, n)) in enumerate(sorted(by_cust.items(), key=lambda kv: -kv[1][1])):
        rr = rc + 2 + i
        s.cell(rr, 1, code)
        s.cell(rr, 2, nm)
        s.cell(rr, 3, n)
        s.cell(rr, 4, float(val)).number_format = gbp
        s.cell(rr, 5, f"=ROUND(D{rr}*RebateRate,2)").number_format = gbp
    for col, w in zip("ABCDEFGHIJ", [16, 30, 16, 14, 14, 12, 12, 12, 12, 12]):
        s.column_dimensions[col].width = w

    # ---- Rebate report (the PDF layout, live formulas)
    rp = wb.create_sheet("Rebate report")
    hdr = ["Cus Code", "Customer Name", "Part code", "Description", "Price per"] + labels + ["Total"]
    banner(rp, "Rebate report", len(hdr))
    head(rp, 5, hdr)
    for i, (y, _) in enumerate(window):
        rp.cell(4, 6 + i, y).font = Font(color=MUTED, size=9)
        rp.cell(4, 6 + i).alignment = Alignment(horizontal="center")
    for i, r in enumerate(rows):
        rr = 6 + i
        vals = [r["customer_code"], r["customer_name"], r["part_code"], r["description"], float(r["price"])]
        for c, v in enumerate(vals, 1):
            rp.cell(rr, c, v)
        rp.cell(rr, 5).number_format = gbp
        if r["col"] is not None:
            rp.cell(rr, 6 + r["col"], f"=ROUND({float(r['qty'])}*E{rr},2)").number_format = gbp
        rp.cell(rr, 18, f"=SUM(F{rr}:Q{rr})").number_format = gbp
        if i % 2:
            for c in range(1, 19):
                rp.cell(rr, c).fill = soft
    tr = 6 + len(rows)
    rp.cell(tr, 4, "Totals").font = Font(bold=True)
    rp.cell(tr + 1, 4, "Rebate").font = Font(bold=True)
    rp.cell(tr + 1, 5, "=RebateRate").number_format = "0.0%"
    for c in range(6, 19):
        L = get_column_letter(c)
        rp.cell(tr, c, f"=SUM({L}6:{L}{tr - 1})").number_format = gbp
        rp.cell(tr + 1, c, f"=ROUND({L}{tr}*RebateRate,2)" if c < 18 else f"=SUM(F{tr + 1}:Q{tr + 1})").number_format = gbp
        for rr in (tr, tr + 1):
            rp.cell(rr, c).font = Font(bold=True)
            rp.cell(rr, c).border = Border(top=Side(style="medium", color=INK)) if rr == tr else Border()
    for rr in (tr, tr + 1):
        for c in range(1, 19):
            rp.cell(rr, c).fill = PatternFill("solid", fgColor="FDF6CF") if rr == tr + 1 else PatternFill()
    rp.cell(tr + 3, 1, "Grand total").font = Font(bold=True)
    rp.cell(tr + 3, 3, f"=R{tr}").number_format = gbp
    rp.cell(tr + 4, 1, "Rebate total").font = Font(bold=True)
    rp.cell(tr + 4, 3, f"=R{tr + 1}").number_format = gbp
    for c in (3,):
        rp.cell(tr + 3, c).font = rp.cell(tr + 4, c).font = Font(bold=True, size=12)
    for col, w in zip(range(1, 19), [10, 30, 18, 46, 11] + [12] * 13):
        rp.column_dimensions[get_column_letter(col)].width = w
    rp.freeze_panes = "F6"
    rp.auto_filter.ref = f"A5:R{tr - 1}"
    rp.print_options.gridLines = False
    rp.page_setup.orientation, rp.page_setup.fitToWidth, rp.page_setup.fitToHeight = "landscape", 1, 0
    rp.sheet_properties.pageSetUpPr.fitToPage = True
    rp.print_title_rows = "5:5"

    # ---- Lines (every date, for checking)
    ln = wb.create_sheet("Lines")
    lh = ["Customer", "Name", "Part code", "Description", "Price per", "Quantity", "Value £", "Invoice no",
          "Invoice date", "Due date", "Order no", "Order date", f"Month ({meta['basis']})", "In period",
          "Project no", "Customer rebate % in Access"]
    banner(ln, "Invoiced lines – every date", len(lh))
    head(ln, 5, lh)
    for i, r in enumerate(rows):
        rr = 6 + i
        d = r["dates"]
        when = d[meta["basis"]]
        vals = [r["customer_code"], r["customer_name"], r["part_code"], r["description"], float(r["price"]),
                float(r["qty"]), float(r["value"]), r.get("invoice_no", ""), d["invoice"], d["due"],
                r.get("order_no", ""), d["order"], when.strftime("%b %Y") if when else "", "Yes" if r["col"] is not None else "No",
                r.get("project_no", ""), float(r["customer_rebate_pct"]) if r.get("customer_rebate_pct") else None]
        for c, v in enumerate(vals, 1):
            ln.cell(rr, c, v)
        for c in (5, 7):
            ln.cell(rr, c).number_format = gbp
        for c in (9, 10, 12):
            ln.cell(rr, c).number_format = "dd/mm/yyyy"
    for col, w in zip(range(1, 17), [10, 30, 18, 46, 11, 9, 12, 13, 12, 12, 13, 12, 12, 9, 12, 14]):
        ln.column_dimensions[get_column_letter(col)].width = w
    ln.freeze_panes = "E6"
    ln.auto_filter.ref = f"A5:P{5 + len(rows)}"

    # ---- By part
    bp = wb.create_sheet("By part")
    banner(bp, "By part (in period)", 4)
    head(bp, 5, ["Part code", "Quantity", "Sales £", "Rebate £"])
    for i, p in enumerate(meta["parts"]):
        q, v = by_part.get(p, (0, 0))
        rr = 6 + i
        bp.cell(rr, 1, p)
        bp.cell(rr, 2, float(q))
        bp.cell(rr, 3, float(v)).number_format = gbp
        bp.cell(rr, 4, f"=ROUND(C{rr}*RebateRate,2)").number_format = gbp
    for col, w in zip("ABCD", [22, 11, 14, 14]):
        bp.column_dimensions[col].width = w

    # ---- Notes
    nt = wb.create_sheet("Notes & assumptions")
    nt.sheet_view.showGridLines = False
    nt.column_dimensions["A"].width = 130
    for t in notes(meta):
        nt.append([t])
    nt["A1"].font = Font(bold=True, size=14)
    for row in nt.iter_rows(min_row=2):
        row[0].alignment = Alignment(wrap_text=True, vertical="top")
    wb.save(path)


def notes(meta):
    return [
        "Rebate rolling report – how it is built (REP-22, Jira SCRUM-275)",
        "",
        "Source: Access SupplyChain (SDILive), read-only (rebate_rolling.sql): invoice lines (TBI_TBL) joined to their order "
        "lines (COR_TBL) for the price, as Access's own invoiced-sales view does. Run on any day and the 12 months roll with it.",
        f"Period: {meta['period']} – the 12 months ending with the month of the run.",
        f"Selection: by part code only, any customer – the {len(meta['parts'])} codes in rebate_parts.csv (the codes on the "
        "November 2026 report). Add or remove a code there; no code change is needed.",
        "Value = quantity x price per, to the penny; a credit note is a negative line.",
        f"Month: by {meta['basis']} date. Invoice, due and order dates are all on the Lines tab, and the report can be "
        "re-run by due or order date.",
        f"Rebate: {meta['rate'] * 100:.0f}% of each month's total, rounded to the penny per month; the rebate total is the sum "
        "of the twelve. The rate is one cell (Summary!B5) – change it and every rebate follows.",
        "Lines with no value in any month were invoiced outside the 12 months (on the November report: November 2025). "
        "They are listed so the report shows the same lines as the Access report; they add nothing to the totals.",
        "Prices are as on the invoice line, in GBP.",
        "",
        "Assumptions to confirm (Finance):",
        "1. The rebate is due on invoiced value (not ordered or delivered).",
        "2. The rate is a flat 6% on every part and customer, paid to Morrisons - not the per-customer rebate % that Access "
        "holds on the customer account (used by Access's invoiced-sales view; shown on the Lines tab).",
        "3. Lines invoiced before the window are listed but not counted, as on the Access report.",
        "4. The part list is complete – other 10932-00-GA variants (e.g. PEP, DOV, CCE, REG) are sold but are not on the report.",
    ] + (["", "THIS IS A SAMPLE: lines, quantities and prices rebuilt from the November 2026 PDF; dates are the month only "
          "(15th of the month). It reproduces the PDF to the penny: £549,211.31 and rebate £32,952.68."] if meta["sample"] else [])


# --------------------------------------------------------------------------------------------- HTML
def gbp(x, dash=True):
    if x == 0 and dash:
        return "–"
    s = f"£{abs(x):,.2f}"
    return f"-{s}" if x < 0 else s


def write_html(path, rows, window, labels, mt, mr, grand, rebate, by_cust, by_part, meta):
    peak = max(mt) if any(mt) else Decimal(1)
    W_, H_, pad_l, pad_b, top = 760, 260, 64, 34, 16
    bw = (W_ - pad_l) / 12
    ticks = 4
    step = Decimal(10) ** (len(str(int(peak))) - 1)
    nice = ((peak / step).to_integral_value(rounding="ROUND_CEILING")) * step or Decimal(1)
    bars, grid = [], []
    for k in range(ticks + 1):
        v = nice * k / ticks
        yy = top + (H_ - pad_b - top) * (1 - float(v / nice))
        grid.append(f'<line x1="{pad_l}" x2="{W_}" y1="{yy:.1f}" y2="{yy:.1f}" class="g"/>'
                    f'<text x="{pad_l - 8}" y="{yy + 4:.1f}" class="ax" text-anchor="end">£{v / 1000:,.0f}k</text>')
    for i, (t, rb, lab) in enumerate(zip(mt, mr, labels)):
        x = pad_l + i * bw + bw * 0.18
        w = bw * 0.64
        h = (H_ - pad_b - top) * float(t / nice) if t > 0 else 0
        yy = H_ - pad_b - h
        if h:
            r = min(4, h)
            bars.append(f'<g class="bar"><rect class="hit" x="{pad_l + i * bw:.1f}" y="{top}" width="{bw:.1f}" height="{H_ - pad_b - top}"/>'
                        f'<path d="M{x:.1f},{H_ - pad_b} V{yy + r:.1f} Q{x:.1f},{yy:.1f} {x + r:.1f},{yy:.1f} H{x + w - r:.1f} '
                        f'Q{x + w:.1f},{yy:.1f} {x + w:.1f},{yy + r:.1f} V{H_ - pad_b} Z" class="m"/>'
                        f'<title>{lab} {window[i][0]}: sales {gbp(t)} · rebate {gbp(rb)}</title>'
                        f'<text x="{x + w / 2:.1f}" y="{yy - 6:.1f}" class="vl" text-anchor="middle">£{t / 1000:,.0f}k</text></g>')
        bars.append(f'<text x="{x + w / 2:.1f}" y="{H_ - 12}" class="ax" text-anchor="middle">{lab[:3]}</text>')
    svg = (f'<svg viewBox="0 0 {W_} {H_}" role="img" aria-label="Sales by month">{"".join(grid)}'
           f'<line x1="{pad_l}" x2="{W_}" y1="{H_ - pad_b}" y2="{H_ - pad_b}" class="base"/>{"".join(bars)}</svg>')

    mrows = "".join(f"<tr><td>{lab} {y}</td><td class=n>{gbp(t)}</td><td class=n>{gbp(rb)}</td></tr>"
                    for (y, _), lab, t, rb in zip(window, labels, mt, mr))
    crows = "".join(f"<tr><td class=mono>{e(c)}</td><td>{e(n or '')}</td><td class=n>{k}</td><td class=n>{gbp(v)}</td>"
                    f"<td class=n>{gbp(money(v * meta['rate']))}</td></tr>"
                    for c, (n, v, k) in sorted(by_cust.items(), key=lambda kv: -kv[1][1]))
    th = "".join(f"<th class=n>{lab[:3]}<span>{y}</span></th>" for (y, _), lab in zip(window, labels))
    body = []
    for r in rows:
        neg = " neg" if r["value"] < 0 else ""
        cells = "".join(f"<td class='n{neg if r['col'] == i else ''}'>{gbp(r['value']) if r['col'] == i else ''}</td>" for i in range(12))
        body.append(f"<tr class='{'' if r['col'] is not None else 'out'}'><td class=mono>{e(r['customer_code'])}</td>"
                    f"<td>{e(r['customer_name'])}</td><td class=mono>{e(r['part_code'])}</td><td class=desc>{e(r['description'])}</td>"
                    f"<td class=n>{gbp(r['price'])}</td>{cells}</tr>")
    tot = "".join(f"<td class=n>{gbp(t)}</td>" for t in mt)
    reb = "".join(f"<td class=n>{gbp(t)}</td>" for t in mr)
    notes_html = "".join(f"<li>{e(t)}</li>" for t in notes(meta)[2:] if t and not t.startswith("Assumptions") and not t[:2] in ("1.", "2.", "3.", "4."))
    assume = "".join(f"<li>{e(t[3:])}</li>" for t in notes(meta) if t[:2] in ("1.", "2.", "3.", "4."))
    sample = ('<div class="sample">SAMPLE – lines, quantities and prices rebuilt from the November 2026 Access report (PDF); '
              'dates are month only. It reproduces the PDF to the penny.</div>') if meta["sample"] else ""
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Rebate Rolling Report</title><style>
:root{{--y:#F5D947;--ink:#282928;--t:#1f2321;--muted:#6b6f6c;--line:#e6e7e4;--soft:#fbfbf8;--bg:#f4f4f1;--card:#fff;--neg:#b42318}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--t:#ececea;--muted:#a3a7a4;--line:#3a3c3b;--soft:#232524;--bg:#151615;--card:#1c1d1c;--neg:#f97066}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--t);font:14.5px/1.5 'Segoe UI','Helvetica Neue',Arial,sans-serif}}
header{{background:var(--ink);color:#fff;border-bottom:6px solid var(--y)}}.w{{max-width:1280px;margin:0 auto;padding:0 16px}}
.hd{{padding:24px 0 20px;display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap;align-items:flex-end}}
.brand{{color:var(--y);font-weight:700;letter-spacing:.3px}}h1{{margin:4px 0 2px;font-size:28px}}.sub{{color:#d8d8d2;font-size:13.5px}}
.pill{{background:rgba(245,217,71,.14);border:1px solid rgba(245,217,71,.5);color:var(--y);border-radius:999px;padding:3px 12px;font-size:12.5px;white-space:nowrap}}
main{{padding:22px 0 48px}}.sample{{background:#fdf6cf;color:#5b4b00;border:1px solid #ecd76a;border-radius:8px;padding:10px 14px;margin-bottom:16px;font-size:13.5px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:14px}}
.kpi{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;border-bottom:4px solid var(--y)}}
.kpi .l{{color:var(--muted);font-size:12.5px;text-transform:uppercase;letter-spacing:.5px}}.kpi .v{{font-size:27px;font-weight:700;margin-top:2px;font-variant-numeric:tabular-nums}}
.kpi .s{{color:var(--muted);font-size:12.5px}}
.grid2{{display:grid;grid-template-columns:2fr 1fr;gap:16px;margin-top:16px}}@media(max-width:900px){{.grid2{{grid-template-columns:1fr}}}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px 18px}}h2{{font-size:16px;margin:0 0 10px}}
svg{{width:100%;height:auto;display:block}}.g{{stroke:var(--line);stroke-width:1}}.base{{stroke:var(--muted);stroke-width:1}}
.ax{{fill:var(--muted);font-size:11px}}.vl{{fill:var(--t);font-size:11px;font-weight:600}}.m{{fill:var(--ink)}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]) .m{{fill:var(--y)}}}}
.hit{{fill:transparent}}.bar:hover .m{{fill:#55574f}}
table{{border-collapse:collapse;width:100%;font-size:13px}}th{{background:var(--ink);color:#fff;text-align:left;padding:7px 8px;font-weight:600;white-space:nowrap}}
th span{{display:block;font-weight:400;color:#c9c9c2;font-size:10.5px}}td{{border-top:1px solid var(--line);padding:6px 8px;vertical-align:top}}
.n{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}.mono{{font-family:Consolas,monospace;font-size:12.5px;white-space:nowrap}}
tbody tr:nth-child(even) td{{background:var(--soft)}}tr.out td{{color:var(--muted)}}td.neg{{color:var(--neg);font-weight:600}}
table.wide{{font-size:12.5px}}table.wide td{{white-space:nowrap}}table.wide td.desc{{white-space:normal;min-width:240px;max-width:330px}}
tfoot td{{font-weight:700;border-top:2px solid var(--ink)}}tfoot tr.rb td{{background:#fdf6cf;color:#3b3200}}
.scroll{{overflow-x:auto}}.hint{{color:var(--muted);font-size:12.5px;margin:-4px 0 10px}}.mt{{margin-top:16px}}ul{{margin:6px 0 0 18px;padding:0}}li{{margin:3px 0}}
footer{{color:var(--muted);font-size:12.5px;border-top:1px solid var(--line);padding:14px 0 30px}}
@media print{{body{{background:#fff}}header{{print-color-adjust:exact;-webkit-print-color-adjust:exact}}.card{{break-inside:avoid}}}}
</style></head><body>
<header><div class="w hd"><div><div class="brand">we.are.sdi</div><h1>Rebate rolling report</h1>
<div class="sub">Morrisons goalposts &amp; branded bays · {e(meta['period'])} · months by {e(meta['basis'])} date</div></div>
<div class="pill">Run {e(meta['stamp'])} · Access SupplyChain</div></div></header>
<main class="w">{sample}
<section class="kpis">
<div class="kpi"><div class="l">Sales in period</div><div class="v">{gbp(grand)}</div><div class="s">{meta['in_window']} invoiced lines</div></div>
<div class="kpi"><div class="l">Rebate due ({meta['rate'] * 100:.0f}%)</div><div class="v">{gbp(rebate)}</div><div class="s">sum of the 12 monthly rebates</div></div>
<div class="kpi"><div class="l">Customers</div><div class="v">{meta['customers']}</div><div class="s">with sales in the period</div></div>
<div class="kpi"><div class="l">Best month</div><div class="v">{labels[mt.index(max(mt))] if any(mt) else '–'}</div><div class="s">{gbp(max(mt))}</div></div>
</section>
<div class="grid2"><section class="card"><h2>Sales by month</h2>{svg}</section>
<section class="card"><h2>Month by month</h2><div class="scroll"><table><thead><tr><th>Month</th><th class=n>Sales</th><th class=n>Rebate</th></tr></thead>
<tbody>{mrows}</tbody><tfoot><tr><td>Total</td><td class=n>{gbp(grand)}</td><td class=n>{gbp(rebate)}</td></tr></tfoot></table></div></section></div>
<section class="card mt"><h2>By customer</h2><div class="scroll"><table><thead><tr><th>Customer</th><th>Name</th><th class=n>Lines</th><th class=n>Sales</th><th class=n>Rebate</th></tr></thead>
<tbody>{crows}</tbody></table></div></section>
<section class="card mt"><h2>Rebate report</h2><p class="hint">One row per invoiced line. Scroll sideways for every month; grey rows were invoiced before the period.</p><div class="scroll"><table class="wide"><thead><tr><th>Cus code</th><th>Customer name</th><th>Part code</th><th>Description</th><th class=n>Price per</th>{th}</tr></thead>
<tbody>{''.join(body)}</tbody><tfoot><tr><td colspan=5>Totals</td>{tot}</tr><tr class="rb"><td colspan=5>Rebate {meta['rate'] * 100:.0f}%</td>{reb}</tr></tfoot></table></div>
<p><b>Grand total: {gbp(grand)}</b> &nbsp;·&nbsp; <b>Rebate total: {gbp(rebate)}</b></p></section>
<div class="grid2"><section class="card mt"><h2>How it is built</h2><ul>{notes_html}</ul></section>
<section class="card mt"><h2>Assumptions to confirm</h2><ol style="margin:6px 0 0 18px;padding:0">{assume}</ol></section></div>
</main><footer class="w">we.are.sdi · SDI Displays Ltd · Rebate rolling report (REP-22) · built from Access SupplyChain · {e(meta['stamp'])}</footer></body></html>"""
    Path(path).write_text(page, encoding="utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("lines")
    ap.add_argument("out_dir")
    ap.add_argument("--end", help="last month of the 12, YYYY-MM (default: this month)")
    ap.add_argument("--rate", default="0.06")
    ap.add_argument("--basis", default="invoice", choices=["invoice", "due", "order"])
    ap.add_argument("--parts")
    ap.add_argument("--sample", action="store_true", help="label the output as a sample")
    a = ap.parse_args()
    end = tuple(int(x) for x in a.end.split("-")) if a.end else None
    res = build(a.lines, a.out_dir, end, a.rate, a.basis, a.parts, a.sample)
    print(res["name"], "| total", res["grand"], "| rebate", res["rebate"], "|",
          ", ".join(f"{t}" for t in res["month_tot"]))
