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

    # ---- Estimate (monthly actuals -> full-year projection)
    e = wb.create_sheet("Estimate")
    banner(e, "Current year estimate (1 Sep 2026 – 31 Aug 2027)", 9)
    head(e, 4, ["Month"] + [a for a in ACCOUNTS if a != pass_through] + [f"{pass_through} (pass-through share)", "Qualifying total"])
    months = ["2026-09", "2026-10", "2026-11", "2026-12", "2027-01", "2027-02", "2027-03", "2027-04", "2027-05",
              "2027-06", "2027-07", "2027-08"]
    act = {}
    if actuals and Path(actuals).exists():
        lines = [l for l in Path(actuals).read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
        rdr = csv.reader(lines, delimiter="\t")
        for row in rdr:
            if len(row) >= 5 and row[0] in ACCOUNTS and row[2][:7] in months:
                try:
                    act[(row[0], row[2][:7])] = act.get((row[0], row[2][:7]), 0) + float(row[4])
                except ValueError:
                    pass
    for i, m in enumerate(months):
        r = 5 + i
        e.cell(r, 1, m)
        for j, a in enumerate(ACCOUNTS):
            v = act.get((a, m))
            cell = e.cell(r, 2 + j, v)
            cell.number_format = GBP
            if a == pass_through:
                cell.fill = PatternFill("solid", fgColor=LY)       # only the partner's pass-through share counts
        e.cell(r, 8, f"=SUM(B{r}:G{r})").number_format = GBP
    e["A18"], e["C18"] = "Actual to date", "=SUM(H5:H16)"
    e["A19"], e["C19"] = "Months with actuals", "=COUNT(H5:H16)-COUNTIF(H5:H16,0)"
    e["A20"], e["C20"] = "Projected full year (run rate)", "=IF(C19=0,0,C18/C19*12)"
    e["A21"], e["C21"] = "Projected rebate (Calculator)", "← set Calculator!B4 to =Estimate!C20"
    for r in (18, 20):
        e[f"C{r}"].number_format = GBP
        e[f"A{r}"].font = Font(bold=True)
    e["A23"] = ("Pass-through column (yellow): enter only the partner's share – the agreement counts agreed "
                "pass-through revenue, not all of that account's work. Qualifying = invoiced AND collected, net of credit notes, "
                "cancellations and returns: the run rate above is invoiced only; the year-end reconciliation adjusts.")
    e["A23"].alignment = Alignment(wrap_text=True)
    e.merge_cells("A23:H25")
    for col, w in zip("ABCDEFGH", [12, 14, 14, 14, 14, 14, 20, 16]):
        e.column_dimensions[col].width = w

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
    wb.save(out)


if __name__ == "__main__":
    build(os.environ["PARTNER_REBATE_PARAMS"], sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    print(sys.argv[1])
