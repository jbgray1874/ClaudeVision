"""Builds the FINANCE-ONLY partner rebate workbook from the private parameters file:
Calculator (live formulas, one input cell), Estimate (monthly actuals -> projected year), Referral
register (brand, dates, 12-month window, goods / design, payable with the cap), Open points.
    PARTNER_REBATE_PARAMS=<private json> python build_model.py <out.xlsx> [revenue.txt]
"""
import csv
import json
import os
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

INK, Y, LY, MUTED = "282928", "F5D947", "FDF6CF", "6B6F6C"
GBP = '£#,##0.00;[Red]-£#,##0.00;"–"'
ACCOUNTS = []   # from the parameters file ("accounts"), finance-only


def head(ws, row, values):
    for i, v in enumerate(values, 1):
        c = ws.cell(row, i, v)
        c.fill, c.font = PatternFill("solid", fgColor=INK), Font(bold=True, color="FFFFFF")
        c.alignment = Alignment(wrap_text=True, vertical="center")


def banner(ws, title, width):
    ws.sheet_view.showGridLines = False
    for c in range(1, width + 1):
        ws.cell(1, c).fill = PatternFill("solid", fgColor=INK)
        ws.cell(2, c).fill = PatternFill("solid", fgColor=Y)
    ws.cell(1, 1, f"we.are.sdi · {title} · FINANCE ONLY – CONFIDENTIAL").font = Font(bold=True, color=Y, size=13)
    ws.row_dimensions[1].height, ws.row_dimensions[2].height = 26, 4


def build(params, out, actuals=None):
    p = json.loads(Path(params).read_text())
    global ACCOUNTS
    ACCOUNTS = p["accounts"]
    pass_through = p["pass_through_account"]
    wb = Workbook()

    # ---- Calculator
    c = wb.active
    c.title = "Calculator"
    banner(c, p.get("title", "Partnership rebate"), 7)
    c["A4"], c["B4"] = "Annual qualifying revenue", 7850000
    c["B4"].fill, c["B4"].font, c["B4"].number_format = PatternFill("solid", fgColor=LY), Font(bold=True, size=13), GBP
    c["C4"] = "← type a figure (or it is linked from the Estimate tab: =Estimate!C20)"
    c["C4"].font = Font(italic=True, color=MUTED)
    c["A5"], c["B5"] = "Baseline (two-year average)", p["baseline"]
    c["A6"], c["B6"] = "Performance bonus rate", p["bonus_rate"] / 100
    for r in (5, 6):
        c[f"B{r}"].number_format = GBP if r == 5 else "0.00%"
    head(c, 8, ["From", "To", "Rate", "Revenue in band", "Rebate in band"])
    lo = 0
    for i, (hi, rate) in enumerate(p["bands"]):
        r = 9 + i
        c.cell(r, 1, lo).number_format = GBP
        c.cell(r, 2, hi).number_format = GBP
        c.cell(r, 3, rate / 100).number_format = "0.0%"
        c.cell(r, 4, f"=MAX(0,MIN($B$4,B{r})-A{r})").number_format = GBP
        c.cell(r, 5, f"=ROUND(D{r}*C{r},2)").number_format = GBP
        lo = hi
    last = 8 + len(p["bands"])
    rows = [("Tiered rebate", f"=SUM(E9:E{last})"),
            ("Year-end performance bonus", "=ROUND(MAX(0,B4-B5)*B6,2)"),
            ("Total annual rebate (excl. referrals)", f"=B{last + 2}+B{last + 3}"),
            ("Effective rate (tiered + bonus)", f"=IF(B4=0,0,B{last + 4}/B4)"),
            ("Revenue above the top band (no agreed rate yet)", f"=MAX(0,B4-B{last})")]
    for k, (lab, f) in enumerate(rows):
        r = last + 2 + k
        c.cell(r, 1, lab).font = Font(bold=True)
        c.cell(r, 2, f).number_format = "0.00%" if "Effective" in lab else GBP
        c.cell(r, 2).font = Font(bold=True, size=12 if "Total" in lab else 11)
    for col, w in zip("ABCDE", [46, 18, 10, 18, 16]):
        c.column_dimensions[col].width = w

    # ---- actuals: sales-ledger net by account and month (code, month, INV / CRN, nett - partner_revenue_2 grid 1)
    net = {}
    if actuals and Path(actuals).exists():
        for row in csv.reader([l for l in Path(actuals).read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()],
                              delimiter="\t"):
            if len(row) >= 4 and row[0] in ACCOUNTS and row[2] in ("INV", "CRN"):
                try:
                    v = float(row[3])
                except ValueError:
                    continue
                net[(row[0], row[1][:7])] = net.get((row[0], row[1][:7]), 0) + (v if row[2] == "INV" else -v)
    names = p.get("account_names", {})
    direct = [a for a in ACCOUNTS if a != pass_through]

    # ---- Estimate (monthly actuals -> full-year projection)
    e = wb.create_sheet("Estimate")
    ncol = len(direct) + 4
    banner(e, "Current year estimate (" + " – ".join(p["year"]) + ")", ncol)
    head(e, 4, ["Month"] + [f"{a} {names.get(a, '')}".strip() for a in direct]
         + [f"{pass_through} share that qualifies (enter)", "Qualifying total", f"{pass_through} all work (info, not counted)"])
    y0 = int(p["year"][0][:4])
    months = [f"{y0 + (m > 12)}-{(m - 1) % 12 + 1:02d}" for m in range(9, 21)]
    tot_col = len(direct) + 3
    T = get_column_letter(tot_col)
    for i, m in enumerate(months):
        r = 5 + i
        e.cell(r, 1, m)
        for j, a in enumerate(direct):
            e.cell(r, 2 + j, round(net[(a, m)], 2) if (a, m) in net else None).number_format = GBP
        share = e.cell(r, len(direct) + 2)
        share.fill, share.number_format = PatternFill("solid", fgColor=LY), GBP
        e.cell(r, tot_col, f"=SUM(B{r}:{get_column_letter(tot_col - 1)}{r})").number_format = GBP
        info = e.cell(r, tot_col + 1, round(net[(pass_through, m)], 2) if (pass_through, m) in net else None)
        info.number_format, info.font = GBP, Font(color=MUTED, italic=True)
    e["A18"], e["C18"] = "Qualifying to date", f"=SUM({T}5:{T}16)"
    e["A19"], e["C19"] = "Months with invoicing", f"=COUNTIF({T}5:{T}16,\"<>0\")"
    e["A20"], e["C20"] = "Projected full year (simple run rate)", "=IF(C19=0,0,C18/C19*12)"
    e["A21"], e["C21"] = "Projected rebate", "Put =Estimate!C20 in Calculator!B4 (see How to use, step 4)"
    for r in (18, 20):
        e[f"C{r}"].number_format = GBP
        e[f"A{r}"].font = Font(bold=True)
    e["A23"] = ("Figures: Access sales ledger, net of VAT, invoices less credit notes, by invoice date. Yellow column: type only "
                "the share of the pass-through account that is the partner's work (the grey column shows all its work for "
                "reference). Qualifying revenue is invoiced AND collected: the run rate is invoiced only, and the year-end "
                "reconciliation adjusts for anything unpaid. Invoicing is lumpy - treat an early-year run rate with care.")
    e["A23"].alignment = Alignment(wrap_text=True, vertical="top")
    e.merge_cells(f"A23:{get_column_letter(ncol)}26")
    e.column_dimensions["A"].width = 12
    for k in range(2, ncol + 1):
        e.column_dimensions[get_column_letter(k)].width = 17
    e.freeze_panes = "B5"

    # ---- Reconciliation to the agreed baseline years
    rc = wb.create_sheet("Reconciliation")
    banner(rc, "Access figures against the agreed baseline years", 4)
    yrs = list(p.get("baseline_years", {}).items())
    head(rc, 4, ["Account"] + [k for k, _ in yrs])
    def fy_total(a, label):
        a0, a1 = label.split("..")
        return round(sum(v for (c, m), v in net.items() if c == a and a0 <= m <= a1), 2)
    for i, a in enumerate(ACCOUNTS):
        r = 5 + i
        rc.cell(r, 1, f"{a} {names.get(a, '')}".strip() + (" (all work)" if a == pass_through else ""))
        for k, (label, _) in enumerate(yrs):
            rc.cell(r, 2 + k, fy_total(a, label)).number_format = GBP
    last = 4 + len(ACCOUNTS)
    rows = [("All accounts in Access", lambda L: f"=SUM({L}5:{L}{last})"),
            ("Agreed baseline year", None),
            ("Difference (Access – agreed)", lambda L: f"={L}{last + 1}-{L}{last + 2}")]
    for k, (label, val) in enumerate(yrs):
        L = get_column_letter(2 + k)
        rc[f"{L}{last + 1}"] = rows[0][1](L)
        rc[f"{L}{last + 2}"] = val
        rc[f"{L}{last + 3}"] = rows[2][1](L)
        for r in (last + 1, last + 2, last + 3):
            rc[f"{L}{r}"].number_format = GBP
            rc[f"{L}{r}"].font = Font(bold=True)
    for k, (lab, _) in enumerate(rows):
        rc.cell(last + 1 + k, 1, lab).font = Font(bold=True)
    rc.cell(last + 5, 1, "No combination of these accounts (with or without VAT) reproduces both agreed years: the baselines "
                         "came from another source. Finance to confirm the source before the year-end reconciliation.")
    rc.cell(last + 5, 1).alignment = Alignment(wrap_text=True)
    rc.merge_cells(start_row=last + 5, start_column=1, end_row=last + 7, end_column=4)
    for col, w in zip("ABCD", [44, 20, 20, 20]):
        rc.column_dimensions[col].width = w

    # ---- Referral register
    rr = wb.create_sheet("Referral register")
    banner(rr, "Customers introduced by the partner", 13)
    head(rr, 4, ["Introduced customer (X3 code)", "Name / brand", "Partner introducer", "Opportunity ref",
                 "Registered (before selling)", "SDI confirmed qualifying", "First qualifying invoice",
                 "Window ends", "Goods revenue in window", "Design services in window (separately invoiced)",
                 "Calculated reward", "Payable (capped)", "Notes"])
    dv = DataValidation(type="list", formula1='"Yes,No,Pending"', allow_blank=True)
    rr.add_data_validation(dv)
    for r in range(5, 55):
        rr.cell(r, 8, f'=IF(G{r}="","",EDATE(G{r},{p["referral_window_months"]})-1)').number_format = "dd/mm/yyyy"
        for col in (5, 7):
            rr.cell(r, col).number_format = "dd/mm/yyyy"
        for col in (9, 10, 11, 12):
            rr.cell(r, col).number_format = GBP
        rr.cell(r, 11, f'=IF(A{r}="","",ROUND(I{r}*{p["referral_goods_rate"] / 100}+J{r}*{p["referral_design_rate"] / 100},2))')
        rr.cell(r, 12, f'=IF(A{r}="","",MIN(K{r},{p["referral_cap"]}))')
        dv.add(f"F{r}")
    rr["A56"], rr["L56"] = "Total referral reward", "=SUM(L5:L54)"
    rr["L56"].number_format = GBP
    rr["A56"].font = rr["L56"].font = Font(bold=True)
    for col, w in zip("ABCDEFGHIJKLM", [16, 26, 18, 14, 12, 12, 13, 12, 16, 18, 14, 14, 30]):
        rr.column_dimensions[col].width = w
    rr.freeze_panes = "C5"

    # ---- Open points
    o = wb.create_sheet("Open points")
    banner(o, "Points to settle", 2)
    pts = [["Point", "Why it matters"]] + p.get("open_points", [])
    for row in pts:
        o.append(row)
    head(o, 3, pts[0])
    for col, w in zip("AB", [32, 120]):
        o.column_dimensions[col].width = w
    for row in o.iter_rows(min_row=4):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    # ---- How to use (first tab)
    h = wb.create_sheet("How to use", 0)
    banner(h, "How to use this workbook", 2)
    guide = [
        ("What it is", "The partnership rebate, worked out exactly as the agreement says. Finance only - keep it within Finance; "
                       "account managers must not see rebate values."),
        ("Tabs", "Calculator – the rebate for any annual revenue.  Estimate – this year's revenue month by month and a projection.  "
                 "Reconciliation – Access against the agreed baseline years.  Referral register – customers the partner introduces.  "
                 "Open points – what still needs deciding."),
        ("1. Rebate for a revenue figure", "Calculator tab: type the annual qualifying revenue in the yellow cell (B4). The bands, "
                 "tiered rebate, year-end bonus, total and effective rate update. Each rate applies only to revenue inside its band."),
        ("2. Update this year's actuals", "Estimate tab: each month, type (or paste) the net invoiced revenue per account – invoices "
                 "less credit notes, excluding VAT. The figures already there come from the Access sales ledger."),
        ("3. Pass-through revenue", "Estimate tab, yellow column: type only the part of the pass-through account's revenue that is the "
                 "partner's work. The grey column beside it shows all of that account's work, for reference only - it is not counted."),
        ("4. Projected rebate", "Estimate shows 'Projected full year' (C20). To see its rebate, type =Estimate!C20 into Calculator B4. "
                 "Early in the year invoicing is lumpy - use the projection as a guide, not a forecast."),
        ("5. Referrals", "Referral register: one row per customer the partner introduces. Fill the code, name, introducer, registration "
                 "date (before selling starts), SDI confirmed (Yes / No / Pending) and first qualifying invoice date. 'Window ends' "
                 "is worked out (12 months). Each quarter, enter goods revenue and separately invoiced design revenue in the window: "
                 "the reward and the capped payable amount are worked out. The total is at the bottom."),
        ("6. Year end", "After the partner's year closes: use revenue that is invoiced AND paid (net of credits and returns), to the "
                 "penny, put it in Calculator B4, add the referral total, and agree the settlement (credit note or payment)."),
        ("Checks built in", "The calculator was proved against every worked example in the agreement. The agreement's examples round "
                 "to the pound; this workbook works to the penny, so one example differs by under £1."),
        ("Do not", "Overwrite formulas (white cells with figures on the Calculator; Window ends, Calculated, Payable on the register). "
                   "Type only in yellow or blank input cells."),
        ("Source and support", "Built by James Gray (AI and Systems Controller). Rebuilt from the private parameters file with "
                 "build_model.py; figures from read-only Access queries. In Sage X3 the same calculation will run as a finance-only report."),
    ]
    for r, (a, b) in enumerate(guide, 4):
        h.cell(r, 1, a).font = Font(bold=True)
        h.cell(r, 2, b).alignment = Alignment(wrap_text=True, vertical="top")
        h.cell(r, 1).alignment = Alignment(vertical="top")
        h.row_dimensions[r].height = 48 if len(b) > 160 else 32
    h.column_dimensions["A"].width, h.column_dimensions["B"].width = 30, 120
    wb.active = 0
    wb.save(out)


if __name__ == "__main__":
    build(os.environ["PARTNER_REBATE_PARAMS"], sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    print(sys.argv[1])
