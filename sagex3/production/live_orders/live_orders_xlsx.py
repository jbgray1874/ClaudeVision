"""The Live Orders workbook - Production's sheet, built from Sage X3 data, made to be edited. Written 20 Nov 2026.

Same tabs and column names as Dave's sheet (Live Orders, Work-centre load, WO Suggestions, BOM explosion), plus a
Dashboard. Production type in the yellow columns (Comments, Prog, Tube req, Material, Notes - here or in the portal);
next run carries them forward by works order (build_live_orders.read_carry), so nothing is re-typed on Monday.

Called by build_live_orders.write_xlsx. openpyxl only - no macros, opens in any Excel.
"""
import datetime as dt
from collections import defaultdict

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.formatting.rule import CellIsRule, ColorScaleRule, DataBarRule, FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.hyperlink import Hyperlink

# ---------------------------------------------------------------- look
INK, YELLOW, PAPER, LINE, MUTED = "1C1C1C", "FFD400", "FAFAF7", "D9D9D4", "6B6B66"
RAG = {"GREEN": ("1E8E3E", "E3F4E8"), "AMBER": ("B06D00", "FFF1C7"), "RED": ("C5221F", "FDE2E1")}
FAMILY = {"Metal": "2F6FB2", "Joinery": "9A6B2F", "Acrylics": "7E57C2"}
EDIT_FILL = PatternFill("solid", fgColor="FFF7CC")
# Production's typed columns (25 Nov: "Material" is now typed, blank for their notes; "Notes" added for Dave) and the
# keys they're carried forward under (build_live_orders.read_carry) and kept by the portal (live_orders_routes notes).
EDITABLE = ("Comments", "Prog", "Tube req", "Material", "Notes")
CARRY_KEYS = ("comments", "prog", "tube", "mat", "notes")
F = lambda c: PatternFill("solid", fgColor=c)
thin, thick = Side(style="thin", color=LINE), Side(style="medium", color=INK)


def _banner(ws, title, sub, width):
    ws.sheet_view.showGridLines = False
    ws.row_dimensions[1].height = 30
    ws.row_dimensions[2].height = 18
    for r in (1, 2):
        for c in range(1, width + 1):
            ws.cell(r, c).fill = F(INK)
    ws.cell(1, 1, "we.are.sdi").font = Font(bold=True, color=YELLOW, size=10)
    ws.cell(1, 2, title).font = Font(bold=True, color="FFFFFF", size=16)
    ws.cell(2, 2, sub).font = Font(color="BFBFBA", size=9)
    for c in range(1, width + 1):
        ws.cell(3, c).fill = F(YELLOW)
    ws.row_dimensions[3].height = 4


def _header(ws, row, heads, widths, editable=()):
    for i, h in enumerate(heads, 1):
        c = ws.cell(row, i, ("✎ " + h) if h in editable else h)
        c.font = Font(bold=True, color=INK if h in editable else "FFFFFF", size=9)
        c.fill = F(YELLOW) if h in editable else F(INK)
        c.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
        c.border = Border(bottom=thick)
    ws.row_dimensions[row].height = 42
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w


def _print(ws, header_row, landscape=True, a3=True):
    ws.page_setup.orientation = "landscape" if landscape else "portrait"
    ws.page_setup.paperSize = ws.PAPERSIZE_A3 if a3 else ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth, ws.page_setup.fitToHeight = 1, 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_title_rows = f"{header_row}:{header_row}"
    ws.page_margins.left = ws.page_margins.right = 0.3
    ws.oddFooter.center.text = "Page &P of &N"
    ws.oddFooter.right.text = "SDI Live Orders · &D"


def _rag_rules(ws, rng):
    for k, (ink, bg) in RAG.items():
        ws.conditional_formatting.add(rng, FormulaRule(formula=[f'ISNUMBER(SEARCH("{k}",{rng.split(":")[0]}))'],
                                                       fill=F(bg), font=Font(bold=True, color=ink)))


def week_of(d):
    return d - dt.timedelta(days=d.weekday()) if d else None


# ---------------------------------------------------------------- the workbook
def write(path, meta, wos, wc_cols, wcnames, load, sug, checks, compare, wc_label, drawing_of, stale_days, po_sug=()):
    wb = Workbook()
    as_at = meta["as_at"]
    sub = f"as at {as_at} · {meta['wos']} works orders still to make · from Sage X3 · nothing typed except the ✎ columns"

    # ---------- Live Orders (built first: the Dashboard's charts point at the other tabs)
    lo = wb.active
    lo.title = "Live Orders"
    lo.sheet_properties.tabColor = YELLOW
    # 25 Nov (Simon, Dave): no Customer date (not for the shop floor), no auto material text (the BOM drill-down keeps
    # it) - "Material" is now a blank typed column, plus "Notes"; shops as M / J / A letters, not coloured dots.
    fixed = ["Week", "Due date", "WO Num", "Level", "Parent WO", "SO Num", "Account", "Part code", "Description",
             "DRAWING NUMBER", "REV", "MATERIAL STATUS", "QTY", "Booked in", "Balance", "Metal", "Joinery", "Acrylics",
             *EDITABLE]
    ix = {h: i for i, h in enumerate(fixed, 1)}
    CL = {h: get_column_letter(i) for h, i in ix.items()}
    wc_heads = [f"{wc_label(c, wcnames)} ({c})" for c in wc_cols]
    heads = fixed + wc_heads
    widths = [9, 10, 12, 9, 11, 14, 9, 20, 32, 15, 5, 11, 7, 8, 8, 4, 4, 4, 28, 8, 9, 26, 28] + [7.5] * len(wc_cols)
    _banner(lo, "Live Orders", sub, len(heads))
    # row 4: group captions; row 5: totals that follow the filter; row 6: headers
    first_wc = len(fixed) + 1
    e0, e1 = ix[EDITABLE[0]], ix[EDITABLE[-1]]
    if wc_cols:
        lo.cell(4, first_wc, "Hours still to do, by work centre").font = Font(bold=True, color=MUTED, size=9)
        lo.merge_cells(start_row=4, start_column=first_wc, end_row=4, end_column=len(heads))
    lo.cell(4, e0, "Production's columns - type here or in the portal, carried forward every run").font = \
        Font(bold=True, color="8A6D00", size=9)
    lo.merge_cells(start_row=4, start_column=e0, end_row=4, end_column=e1)
    H = 6
    _header(lo, H, heads, widths, EDITABLE)
    for i, c in enumerate(wc_cols, first_wc):                       # colour the work-centre headers by shop
        fam = {"M": "Metal", "J": "Joinery", "A": "Acrylics"}.get(c[:1])
        if fam:
            lo.cell(H, i).fill = F(FAMILY[fam])
    first, last = H + 1, H + len(wos)
    lo.cell(5, ix["Part code"], "Totals (follow the filter):").font = Font(bold=True, color=MUTED, size=9)
    for col in [ix["QTY"], ix["Booked in"], ix["Balance"]] + list(range(first_wc, len(heads) + 1)):
        L = get_column_letter(col)
        c = lo.cell(5, col, f"=SUBTOTAL(109,{L}{first}:{L}{max(last, first)})")
        c.font, c.number_format = Font(bold=True, size=9), "#,##0.0" if col >= first_wc else "#,##0"
    W = CL["WO Num"]
    lo.cell(5, ix["WO Num"], f"=SUBTOTAL(103,{W}{first}:{W}{max(last, first)})&\" works orders\"").font = Font(bold=True, size=9)

    bom_first, prev_week = {}, "start"
    rows_by_wo = {}
    wrap = {ix["Description"], *range(e0, e1 + 1)} - {ix["Prog"], ix["Tube req"]}
    for i, w in enumerate(wos):
        r = first + i
        cr = w.get("carry", {})
        wk = week_of(w["due"])
        vals = [wk, w["due"], w["wo"], w["level"], w["parent"], w["so"], w["account"], w["code"], w["des"],
                drawing_of(w["code"]), w["rev"], w["status"], w["qty"], w["done"], w["bal"],
                *[f[:1] if f in w["families"] else "" for f in ("Metal", "Joinery", "Acrylics")],
                *[cr.get(k, "") for k in CARRY_KEYS]]
        vals += [round(w["hours"][c], 2) if w["hours"].get(c) else None for c in wc_cols]
        for j, v in enumerate(vals, 1):
            cell = lo.cell(r, j, v)
            cell.font = Font(size=9)
            cell.alignment = Alignment(vertical="top", wrap_text=j in wrap)
        rows_by_wo[w["wo"]] = r
        for fam in ("Metal", "Joinery", "Acrylics"):
            lo.cell(r, ix[fam]).font = Font(bold=True, color=FAMILY[fam], size=10)
            lo.cell(r, ix[fam]).alignment = Alignment(horizontal="center", vertical="top")
        for j in range(e0, e1 + 1):
            lo.cell(r, j).fill = EDIT_FILL
        if w["level"] != "Top":
            lo.cell(r, ix["Part code"]).alignment = Alignment(indent=1, vertical="top")
        if wk != prev_week:                                          # Dave's weekly break line
            for j in range(1, len(heads) + 1):
                lo.cell(r, j).border = Border(top=thick)
            prev_week = wk
    for r in range(first, last + 1):
        lo.cell(r, 1).number_format = lo.cell(r, 2).number_format = "dd/mm/yy"
        for j in range(first_wc, len(heads) + 1):
            lo.cell(r, j).number_format = "0.0;;"
    if wos:
        S = CL["MATERIAL STATUS"]
        _rag_rules(lo, f"{S}{first}:{S}{last}")
        lo.conditional_formatting.add(f"B{first}:B{last}", FormulaRule(formula=[f"AND(ISNUMBER(B{first}),B{first}<TODAY())"],
                                                                         font=Font(bold=True, color=RAG["RED"][0])))
        if wc_cols:
            rng = f"{get_column_letter(first_wc)}{first}:{get_column_letter(len(heads))}{last}"
            lo.conditional_formatting.add(rng, ColorScaleRule(start_type="num", start_value=0, start_color="FFFFFF",
                                                              mid_type="percentile", mid_value=60, mid_color="FFE7A3",
                                                              end_type="percentile", end_value=98, end_color="F28C28"))
        B = CL["Balance"]
        lo.conditional_formatting.add(f"{B}{first}:{B}{last}", DataBarRule(start_type="num", start_value=0, end_type="max",
                                                                         color="9DB9D9", showValue=True))
        lo.auto_filter.ref = f"A{H}:{get_column_letter(len(heads))}{last}"
    lo.freeze_panes = lo.cell(H + 1, ix["Description"])              # header + week..part stay put
    for h in ("Level", "Parent WO", "Account"):                       # detail columns fold away
        lo.column_dimensions[CL[h]].outlineLevel = 1
    _print(lo, H)

    # ---------- Exploded BOMs
    eb = wb.create_sheet("Exploded BOMs")
    eb.sheet_properties.tabColor = "2F6FB2"
    bh = ["WO", "Part", "Level", "Component", "Description", "Qty used", "Required", "In stock", "On PO", "Next PO due",
          "On WO", "Procurement", "Has BOM", "Has route", "Department", "Mat cost each", "Mat cost", "Status"]
    _banner(eb, "Exploded BOMs", "every level of every works order: stock, on order, first PO due, on WO, cost · "
                                 "click the WO number to go back to Live Orders · use the 1 / 2 buttons to fold", len(bh))
    _header(eb, 5, bh, [12, 18, 6, 22, 34, 8, 9, 9, 8, 10, 8, 12, 7, 7, 11, 10, 10, 8])
    r = 6
    for w in wos:
        bom_first[w["wo"]] = r
        top = [w["wo"], w["code"], 0, w["code"], w["des"], 1, w["bal"], None, None, None, None, None, None,
               "Yes" if w["has_route"] else "No", "", None, None, w["status"]]
        for j, v in enumerate(top, 1):
            c = eb.cell(r, j, v)
            c.font, c.fill = Font(bold=True, size=9), F("EFEFEA")
            c.border = Border(top=thin)
        if w["wo"] in rows_by_wo:
            eb.cell(r, 1).hyperlink = Hyperlink(ref=f"A{r}", location=f"'Live Orders'!{W}{rows_by_wo[w['wo']]}",
                                                tooltip="Back to the works order on Live Orders")
            eb.cell(r, 1).font = Font(bold=True, color="2B6CB0", underline="single", size=9)
        start_cost = r
        r += 1
        for e in w["explode"]:
            vals = [w["wo"], w["code"], e["level"], e["comp"], e["des"], e["link"], round(e["need"], 4), e["stock"],
                    e["on_po"], e["po_due"], e["on_wo"], e["make"], "Yes" if e["bom"] else "", "Yes" if e["route"] else "",
                    e["dept"], e["cost_each"], e["cost"], ""]
            for j, v in enumerate(vals, 1):
                c = eb.cell(r, j, v)
                c.font = Font(size=9, color=MUTED if j in (1, 2) else INK)
            eb.cell(r, 4).alignment = Alignment(indent=min(e["level"], 6))
            eb.row_dimensions[r].outlineLevel = 1
            r += 1
        eb.cell(start_cost, 17, f"=SUM(Q{start_cost + 1}:Q{r - 1})" if r - 1 > start_cost else None)
    if r > 6:
        _rag_rules(eb, f"R6:R{r - 1}")
        eb.conditional_formatting.add(f"D6:D{r - 1}", FormulaRule(       # bought-in, short against stock + PO
            formula=["AND($C6>0,$L6=\"Purchased\",$G6>$H6+$I6)"], font=Font(bold=True, color=RAG["RED"][0])))
        for c in ("P", "Q"):
            for rr in range(6, r):
                eb[f"{c}{rr}"].number_format = "#,##0.00"
        eb.auto_filter.ref = f"A5:R{r - 1}"
    eb.sheet_properties.outlinePr.summaryBelow = False
    eb.freeze_panes = "E6"
    _print(eb, 5)

    # part code on Live Orders -> its exploded BOM (Dave's "game changer")
    for w in wos:
        rr, tgt = rows_by_wo[w["wo"]], bom_first.get(w["wo"])
        if tgt:
            c = lo.cell(rr, ix["Part code"])
            c.hyperlink = Hyperlink(ref=c.coordinate, location=f"'Exploded BOMs'!A{tgt}",
                                    tooltip="Exploded BOM: stock, on order, PO due date")
            c.font = Font(color="2B6CB0", underline="single", size=9, bold=w["level"] == "Top")

    # ---------- Work-centre load
    wl = wb.create_sheet("Work-centre load", 1)
    wl.sheet_properties.tabColor = "F28C28"
    weeks = sorted(k for k in load if k)
    lh = ["Work centre", "X3", "Shop"] + [f"w/c {k:%d/%m}" for k in weeks] + ["Total"]
    _banner(wl, "Work-centre load", "hours still to do by the week each works order is due · overdue work counts in "
                                    "this week · capacity per work centre comes from Sage X3 later", len(lh))
    _header(wl, 5, lh, [18, 10, 9] + [8] * len(weeks) + [9])
    for i, c in enumerate(wc_cols, 6):
        fam = {"M": "Metal", "J": "Joinery", "A": "Acrylics"}.get(c[:1], "")
        wl.cell(i, 1, wc_label(c, wcnames)).font = Font(bold=True, size=9)
        wl.cell(i, 2, c).font = Font(size=9, color=MUTED)
        wl.cell(i, 3, fam).font = Font(size=9, bold=True, color=FAMILY.get(fam, MUTED))
        for j, k in enumerate(weeks, 4):
            v = round(load[k].get(c, 0), 1)
            wl.cell(i, j, v or None).number_format = "0.0;;"
        L = get_column_letter(3 + len(weeks))
        wl.cell(i, 4 + len(weeks), f"=SUM(D{i}:{L}{i})").font = Font(bold=True, size=9)
    tr = 6 + len(wc_cols)
    wl.cell(tr, 1, "Total").font = Font(bold=True)
    for j in range(4, 5 + len(weeks)):
        L = get_column_letter(j)
        c = wl.cell(tr, j, f"=SUM({L}6:{L}{tr - 1})")
        c.font, c.number_format, c.border = Font(bold=True), "0", Border(top=thick)
    if wc_cols and weeks:
        wl.conditional_formatting.add(f"D6:{get_column_letter(3 + len(weeks))}{tr - 1}",
                                      ColorScaleRule(start_type="num", start_value=0, start_color="FFFFFF",
                                                     mid_type="percentile", mid_value=60, mid_color="FFE7A3",
                                                     end_type="max", end_color="F28C28"))
        T = get_column_letter(4 + len(weeks))
        wl.conditional_formatting.add(f"{T}6:{T}{tr - 1}", DataBarRule(start_type="num", start_value=0, end_type="max",
                                                                         color="F28C28", showValue=True))
        ch = BarChart()
        ch.type, ch.grouping, ch.overlap = "col", "stacked", 100
        ch.title, ch.y_axis.title = "Hours by week, by work centre", "hours"
        ch.add_data(Reference(wl, min_col=4, max_col=3 + len(weeks), min_row=6, max_row=tr - 1), from_rows=True,
                    titles_from_data=False)
        ch.set_categories(Reference(wl, min_col=4, max_col=3 + len(weeks), min_row=5))
        for s, c in zip(ch.series, wc_cols):
            from openpyxl.chart.series import SeriesLabel
            s.tx = SeriesLabel(v=wc_label(c, wcnames))
        ch.height, ch.width = 9, 26
        wl.add_chart(ch, f"A{tr + 3}")
    wl.freeze_panes = "D6"
    _print(wl, 5)

    # ---------- WO Suggestions
    ws = wb.create_sheet("WO Suggestions", 2)
    ws.sheet_properties.tabColor = "1E8E3E"
    sh = ["Part code", "Description", "Order No", "MRP Qty", "Metal", "Joinery", "Acrylics", "WO Suggested date",
          "SO Due Date", "BOM", "Route", "SO Qty", "Drawing No", "SO Created", "Cus Code", "Flag"]
    _banner(ws, "WO Suggestions", f"sales-order lines for made parts with no works order or stock to cover them · "
                                  f"red = no BOM or no route · lines due over {stale_days} days ago are on Checks", len(sh))
    _header(ws, 5, sh, [20, 32, 14, 8, 6, 7, 8, 11, 11, 6, 6, 7, 16, 10, 9, 8])
    for i, s in enumerate(sug, 6):
        vals = [s["code"], s["des"], s["so"], s["mrp_qty"], *["●" if f in s["families"] else "" for f in FAMILY],
                s["start"], s["due"], "Yes" if s["bom"] else "No", "Yes" if s["route"] else "No", s["so_qty"],
                s["drawing"], s["ordered"], s["account"], "RED" if not (s["bom"] and s["route"]) else ""]
        for j, v in enumerate(vals, 1):
            ws.cell(i, j, v).font = Font(size=9)
        for j, fam in zip((5, 6, 7), FAMILY):
            ws.cell(i, j).font = Font(bold=True, color=FAMILY[fam], size=11)
            ws.cell(i, j).alignment = Alignment(horizontal="center")
        for j in (8, 9, 14):
            ws.cell(i, j).number_format = "dd/mm/yy"
    if sug:
        e = 5 + len(sug)
        ws.conditional_formatting.add(f"A6:P{e}", FormulaRule(formula=['$P6="RED"'], fill=F(RAG["RED"][1])))
        ws.conditional_formatting.add(f"H6:H{e}", FormulaRule(formula=["AND(ISNUMBER(H6),H6<TODAY())"],
                                                              font=Font(bold=True, color=RAG["RED"][0])))
        ws.conditional_formatting.add(f"J6:K{e}", CellIsRule(operator="equal", formula=['"No"'],
                                                             font=Font(bold=True, color=RAG["RED"][0])))
        ws.auto_filter.ref = f"A5:P{e}"
    ws.freeze_panes = "B6"
    _print(ws, 5)

    # ---------- PO Suggestions (26 Nov): Purchasing's list - read-only, they raise the orders in Sage X3
    ps = wb.create_sheet("PO Suggestions", 3)
    ps.sheet_properties.tabColor = "C5221F"
    ph = ["Status", "Order by", "Needed by", "Part", "Description", "To order", "Unit", "Call-off", "Last supplier",
          "Last price", "Currency", "Per", "Est. value", "Lead time (days)", "Lead time from", "Last ordered",
          "In stock", "On PO", "Next PO due", "Needed (all WOs)", "Works orders"]
    _banner(ps, "PO Suggestions", "bought-in parts the open works orders are short of: how many to order, by when, who "
                                  "from last time · read-only - raise the orders in Sage X3 as now", len(ph))
    _header(ps, 5, ph, [20, 10, 10, 20, 32, 9, 6, 7, 12, 9, 7, 6, 10, 8, 22, 10, 8, 8, 10, 9, 40])
    fill = {"LATE": RAG["RED"][1], "NOW": RAG["RED"][1], "WEEK": RAG["AMBER"][1]}
    for i, x in enumerate(po_sug, 6):
        vals = [x["label"], x["order_by"], x["needed_by"], x["part"], x["des"], x["short"], x["unit"],
                "Yes" if x["call_off"] else "", x["supplier"], x["price"], x["cur"], x["pu"], x["value"], x["lead"],
                x["lead_from"], x["last_order"], x["stock"], x["on_po"], x["next_po"], x["need"],
                ", ".join(x["wos"][:12]) + (f" +{len(x['wos']) - 12}" if len(x["wos"]) > 12 else "")]
        for j, v in enumerate(vals, 1):
            c = ps.cell(i, j, v)
            c.font = Font(size=9, bold=j in (1, 4, 6))
            c.alignment = Alignment(vertical="top", wrap_text=j in (5, 21))
        if x["status"] in fill:
            ps.cell(i, 1).fill = F(fill[x["status"]])
        for j in (2, 3, 16, 19):
            ps.cell(i, j).number_format = "dd/mm/yy"
        ps.cell(i, 10).number_format = ps.cell(i, 13).number_format = "#,##0.00"
    if po_sug:
        e = 5 + len(po_sug)
        ps.conditional_formatting.add(f"B6:B{e}", FormulaRule(formula=["AND(ISNUMBER(B6),B6<=TODAY())"],
                                                              font=Font(bold=True, color=RAG["RED"][0])))
        ps.auto_filter.ref = f"A5:U{e}"
    else:
        ps.cell(6, 1, "Nothing to order: stock, open POs and works orders cover every bought-in part.").font = \
            Font(italic=True, color=MUTED)
    ps.freeze_panes = "E6"
    _print(ps, 5)

    # ---------- Dashboard (first tab)
    db = wb.create_sheet("Dashboard", 0)
    db.sheet_properties.tabColor = INK
    _banner(db, "Live Orders · Production's plan", sub, 16)
    for c in range(1, 17):
        db.column_dimensions[get_column_letter(c)].width = 11
    tiles = [("Works orders to make", meta["wos"], INK, "F3F3EF"), ("Red: short", meta["red"], *RAG["RED"]),
             ("Amber: covered", meta["amber"], *RAG["AMBER"]), ("Green: in stock", meta["green"], *RAG["GREEN"]),
             ("Overdue", meta["overdue"], RAG["RED"][0], "FFFFFF"), ("Hours to do", round(meta["hours"]), INK, "F3F3EF"),
             ("WO suggestions", meta["suggestions"], INK, "F3F3EF")] + (
                [("POs to raise now", meta["po_now"], RAG["RED"][0], "FFFFFF")] if "po_now" in meta else [])
    for i, (label, val, ink, bg) in enumerate(tiles):
        col = 1 + 2 * i
        db.merge_cells(start_row=5, start_column=col, end_row=6, end_column=col + 1)
        db.merge_cells(start_row=7, start_column=col, end_row=7, end_column=col + 1)
        top = db.cell(5, col, val)
        top.font, top.alignment = Font(bold=True, size=24, color=ink), Alignment(horizontal="center", vertical="center")
        lab = db.cell(7, col, label)
        lab.font, lab.alignment = Font(size=9, color=MUTED), Alignment(horizontal="center")
        for rr in (5, 6, 7):
            for cc in (col, col + 1):
                db.cell(rr, cc).fill = F(bg)
    db.row_dimensions[5].height = db.row_dimensions[6].height = 22
    # chart data (small table, to the right): works orders by due week x status
    by_week = defaultdict(lambda: {"RED": 0, "AMBER": 0, "GREEN": 0})
    today_w = week_of(dt.date.today())
    for w in wos:
        k = week_of(w["due"]) if w["due"] else None
        k = "No date" if k is None else ("Overdue" if k < today_w else k.strftime("%d/%m"))
        by_week[k][w["status"]] = by_week[k].get(w["status"], 0) + 1
    order = (["Overdue"] if "Overdue" in by_week else []) + sorted(
        (k for k in by_week if k not in ("Overdue", "No date")), key=lambda s: dt.datetime.strptime(s, "%d/%m").replace(
            year=today_w.year + (1 if int(s[3:]) < today_w.month - 6 else 0))) + (["No date"] if "No date" in by_week else [])
    cd_ = wb.create_sheet("_chart data")          # the charts' figures, kept off the printed dashboard
    cd_.sheet_state = "hidden"
    t0 = 1
    dbx, db = db, cd_
    db.cell(t0, 1, "Week due").font = Font(bold=True, size=8, color=MUTED)
    for j, k in enumerate(("RED", "AMBER", "GREEN"), 2):
        db.cell(t0, j, k.title()).font = Font(bold=True, size=8, color=MUTED)
    for i, k in enumerate(order, t0 + 1):
        db.cell(i, 1, k).font = Font(size=8, color=MUTED)
        for j, s in enumerate(("RED", "AMBER", "GREEN"), 2):
            db.cell(i, j, by_week[k][s]).font = Font(size=8, color=MUTED)
    if order:
        ch = BarChart()
        ch.type, ch.grouping, ch.overlap = "col", "stacked", 100
        ch.title = "Works orders by the week they're due"
        ch.add_data(Reference(db, min_col=2, max_col=4, min_row=t0, max_row=t0 + len(order)), titles_from_data=True)
        ch.set_categories(Reference(db, min_col=1, min_row=t0 + 1, max_row=t0 + len(order)))
        for s, k in zip(ch.series, ("RED", "AMBER", "GREEN")):
            s.graphicalProperties.solidFill = RAG[k][0]
            s.graphicalProperties.line.solidFill = RAG[k][0]
        ch.height, ch.width = 8.5, 17
        dbx.add_chart(ch, "A9")
    hrs = sorted(((wc_label(c, wcnames), sum(w["hours"].get(c, 0) for w in wos)) for c in wc_cols), key=lambda x: -x[1])
    h0 = t0 + len(order) + 3
    db.cell(h0, 1, "Work centre").font = Font(bold=True, size=8, color=MUTED)
    db.cell(h0, 2, "Hours").font = Font(bold=True, size=8, color=MUTED)
    for i, (n, h) in enumerate(hrs, h0 + 1):
        db.cell(i, 1, n).font = Font(size=8, color=MUTED)
        db.cell(i, 2, round(h, 1)).font = Font(size=8, color=MUTED)
    if hrs:
        ch = BarChart()
        ch.type, ch.title = "bar", "Hours still to do, by work centre"
        ch.add_data(Reference(db, min_col=2, min_row=h0, max_row=h0 + len(hrs)), titles_from_data=True)
        ch.set_categories(Reference(db, min_col=1, min_row=h0 + 1, max_row=h0 + len(hrs)))
        ch.legend = None
        ch.y_axis.title = "hours"
        ch.x_axis.scaling.orientation = "maxMin"
        ch.series[0].graphicalProperties.solidFill = "2F6FB2"
        ch.height, ch.width = max(8.5, 0.55 * len(hrs) + 2), 12.5
        dbx.add_chart(ch, "I9")
    db = dbx
    notes = [("How to use it", ""),
             ("Live Orders", "One line per works order. Click a part code for its exploded BOM. Filter any column; totals "
                             "follow the filter. A thick line starts each week."),
             ("✎ yellow columns", "Comments, Prog, Tube req, Material and Notes are yours. Type them in the portal (shared, "
                                 "live) or here - the next run carries them forward by works order, so there's no "
                                 "Monday copy-over."),
             ("Material status", "GREEN all in stock · AMBER covered by a PO / works order in time, or a call-off "
                                 "material · RED short with nothing due in time, or no BOM. Why: the Exploded BOMs tab."),
             ("Shops", "M Metal · J Joinery · A Acrylics, from the part's route. Due date red = overdue."),
             ("PO Suggestions", "Bought-in parts to order: how many, needed by, order by (lead time from X3's PO lines), "
                                "last supplier and price. Read-only - raise the orders in Sage X3 as now."),
             ("Print", "Each tab prints A3 landscape, one page wide, headings on every page.")]
    note_row = 27 + max(0, int(0.55 * len(hrs) + 2 - 8.5) * 2)
    for i, (a, b) in enumerate(notes, note_row):
        db.cell(i, 1, a).font = Font(bold=True, size=9)
        db.cell(i, 3, b).font = Font(size=9, color=MUTED)
    _print(db, 1)
    db.print_title_rows = None
    db.print_area = f"A1:P{note_row + len(notes)}"

    # ---------- Read me / checks
    if compare:
        cd = wb.create_sheet("Check against Dave")
        cd.sheet_properties.tabColor = "BFBFBA"
        ch_ = ["WO", "Dave part", "Board part", "Part", "Dave qty", "Board qty", "Dave balance", "Board balance", "Balance",
               "Dave due", "Board due", "Dave material status", "Board status", "Board material"]
        _header(cd, 1, ch_, [13, 20, 20, 10, 8, 8, 9, 9, 9, 10, 10, 40, 9, 40])
        for row in compare["rows"]:
            cd.append(row)
    # ---------- How it works: the logic from Access SupplyChain, applied to live X3 data (live_orders_logic.py, 20 Nov)
    from live_orders_logic import LIVE, LOGIC
    hw = wb.create_sheet("How it works")
    hw.sheet_properties.tabColor = YELLOW
    _banner(hw, "How Live Orders works it out", "the logic reverse-engineered from Access SupplyChain and Production's "
                                                "sheet (reconciled 16 Nov 2026), applied to live Sage X3 data", 5)
    hw.cell(5, 1, "Live data").font = Font(bold=True, size=10)
    hw.cell(5, 1).alignment = Alignment(vertical="top")
    hw.cell(5, 2, LIVE).alignment = Alignment(wrap_text=True, vertical="top")
    hw.merge_cells(start_row=5, start_column=2, end_row=5, end_column=5)
    hw.row_dimensions[5].height = 48
    _header(hw, 7, ["What", "The rule", "Access SupplyChain / Production's sheet", "Where it comes from in Sage X3",
                    "Reconciled to Access (16 Nov)"], [22, 70, 38, 42, 38])
    for i, row in enumerate(LOGIC, 8):
        for j, v in enumerate(row, 1):
            c = hw.cell(i, j, v)
            c.alignment = Alignment(wrap_text=True, vertical="top")
            c.border = Border(bottom=Side(style="thin", color="E3E4E0"))
            if j == 1:
                c.font = Font(bold=True)
        hw.row_dimensions[i].height = max(30, 15 * (len(row[1]) // 80 + 1))
    hw.freeze_panes = "B8"
    _print(hw, 7)

    ck = wb.create_sheet("Checks")
    ck.sheet_properties.tabColor = "BFBFBA"
    _header(ck, 1, ["Level", "WO", "Check", "Detail"], [8, 14, 60, 50])
    for row in checks:
        ck.append(row)
    ck.auto_filter.ref = f"A1:D{max(ck.max_row, 1)}"
    wb.active = 0
    wb.save(path)
