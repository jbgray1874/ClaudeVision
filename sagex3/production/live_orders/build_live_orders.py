"""Live Orders board (LO-00..05, Jira SCRUM-241 / 245-249): Production's Live Orders workbook, built from data.

Reads the day's transactions (live_orders.sql, or the migration's extract_transactions.txt - same grids):
open works orders, open sales-order lines, open purchase-order lines and stock; and the master data in
Sage X3 form (the migration's product, BOM and route files, so codes and work centres are already X3's).
Writes an HTML board and an Excel workbook with Dave Wright's three tabs, worked out instead of typed:

  Live Orders     one row per open works order: due date, customer date (from its sales order), WO / SO,
                  part, description, drawing, rev, MATERIAL STATUS (red / amber / green, worked out),
                  qty / booked in / balance, Metal / Joinery / Acrylics (from the route), and the hours
                  still to do in every work centre (route x balance)
  Work-centre load  those hours by week of the due date, per work centre
  WO Suggestions  sales-order lines for made parts not covered by a works order, stock or other orders;
                  red where the part has no BOM or no route
  Exploded BOMs   every works order's BOM, all levels, against stock, POs and works orders

Material status, the rule (to agree with Dave / Rachael, LO-01): each works order needs BOM x balance of
every component. Stock is shared out to works orders in due-date order (earliest first); what is left
short is covered by open PO lines (earliest first) and, for made components, by their own works orders.
  GREEN  everything is in stock
  AMBER  short, but covered by a PO / works order due on or before the works order's due date
  RED    short with nothing due in time (or no BOM at all)
Stock is physical stock in Access (lots); Access holds no allocations we can read, so the sharing-out is
the board's own - in X3 the works order's allocations replace it.

    python build_live_orders.py <extract.txt> <out_dir> --products ZSDIITM.xlsx --boms YA00408BOM.txt
        --routes ZSDIROU2.txt [--dave Live_Orders.xlsx] [--suggest-lead-days 14]
"""
import argparse
import csv
import datetime as dt
import html
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HERE = Path(__file__).parent
REBUILD = HERE.parent.parent / "migration" / "rebuild"
sys.path.insert(0, str(REBUILD))
from common import product_code  # noqa: E402

WOR = ["grid", "unique", "works_order", "parent_order", "product", "rev", "sales_order", "customer", "order_type",
       "orig_qty", "amd_qty", "good_qty", "rejected_qty", "scrap_qty", "created", "first_date", "mrp_date",
       "scheduled", "last_mat_due", "done_date", "mat_stat", "booked_mat", "booked_lab", "booked_subcon",
       "dest_wh", "dest_bin"]
SOH = ["grid", "SALFCY", "SOHTYP", "SOHNUM", "BPCORD", "ORDDAT", "DEMDLVDAT", "CUSORDREF", "STOFCY", "SHIDAT",
       "BPTNUM", "INVDTAAMT", "CUR", "T71", "SOPLIN", "ITMREF", "ITMDES", "SAU", "QTY", "GROPRI", "T91",
       "order_no", "access_customer", "order_status", "no_price"]
POH = ["grid", "POHFCY", "POHNUM", "ORDDAT", "BPSNUM", "CUR", "T71", "POPLIN", "ITMREF", "ITMDES", "PRHFCY", "UOM",
       "QTYUOM", "EXTRCPDAT", "GROPRI", "T91", "order_no", "access_supplier", "supplier_ref", "no_price"]
SMR = ["grid", "VCRTYP", "VCRNUM", "STOFCY", "IPTDAT", "VCRDES", "TRSCOD", "VCRLIN", "ITMREF", "PCU", "QTYPCU", "STU",
       "QTYSTU", "PRI", "PCU2", "QTYPCU2", "BPSLOT", "LOT", "LOC", "STA", "warehouse", "lot_value", "no_bin"]
GREEN, AMBER, RED = "GREEN", "AMBER", "RED"
# Bought on call-off, not held against each works order (sheet, powder, packing, pallets, wire, carriage):
# short with no PO = AMBER "to call off", not RED. PROVISIONAL - Dave / Rachael to confirm the list (LO-01).
CALL_OFF = ("SHEETMETAL", "POWDER", "PACK", "PALLET", "WIRE", "CARRIAGE")
STALE_DAYS = 60          # sales-order lines due more than this long ago are reported, not suggested


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def day(v):
    v = str(v or "").strip()
    if re.fullmatch(r"\d{8}", v) and v > "19000102":
        return dt.date(int(v[:4]), int(v[4:6]), int(v[6:]))
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", v)
    return dt.date(int(m[1]), int(m[2]), int(m[3])) if m else None


def fmt(d):
    return d.strftime("%d/%m/%y") if d else ""


# ---------------------------------------------------------------- reading
def read_extract(path):
    grids, as_at = defaultdict(list), ""
    names = {"WOR": WOR, "SOH": SOH, "POH": POH, "SMR": SMR}
    for line in open(path, encoding="utf-8-sig", errors="replace"):
        cells = line.rstrip("\r\n").split("\t")
        g = cells[0].strip()
        if g == "CHECK" and len(cells) > 2 and cells[1].strip() == "as at":
            as_at = cells[2].strip()
        if g in names:
            cells = ["" if c == "NULL" else c.strip() for c in cells]
            grids[g].append(dict(zip(names[g], cells + [""] * (len(names[g]) - len(cells)))))
    return grids, as_at


def read_products(path):
    ws = load_workbook(path, read_only=True)["Data with Headings"]
    rows = ws.iter_rows(values_only=True)
    h = next(r for r in rows if r and "ITMREF" in r)
    ix = {k: h.index(k) for k in ("TCLCOD", "ITMREF", "ITMDES1", "ITMDES2", "ITMDES3")}
    return {str(r[ix["ITMREF"]]).strip(): dict(cat=r[ix["TCLCOD"]] or "", des=r[ix["ITMDES1"]] or "",
                                               des2=r[ix["ITMDES2"]] or "", des3=r[ix["ITMDES3"]] or "")
            for r in rows if r and r[ix["ITMREF"]]}


def read_load(path):
    """An X3 load file: ; separated, cp850, no headings."""
    with open(path, encoding="cp850", errors="replace") as f:
        return [l.rstrip("\r\n").split(";") for l in f if l.strip()]


def read_boms(path):
    boms = defaultdict(list)                   # parent -> [(component, link qty)]
    for r in read_load(path):
        if len(r) >= 11 and r[1] == "10":
            boms[r[0]].append((r[8], num(r[10])))
    return boms


def read_routes(path):
    routes = defaultdict(list)                 # product -> [(op, wc, description, setup min, run min / unit)]
    for r in read_load(path):
        if len(r) >= 11 and r[1] == "10":
            routes[r[0]].append((int(num(r[6])), r[7], r[8], num(r[9]), num(r[10])))
    return routes


def read_work_centres():
    """X3 work centre -> the Access department codes Production knows it by (LASM, FOLD ...)."""
    names = defaultdict(list)
    with open(REBUILD / "work_centres.csv") as f:
        for r in csv.DictReader(f):
            if r["x3_work_centre"].strip() and r["access_work_centre"] != "SALV":
                names[r["x3_work_centre"].strip()].append(r["access_work_centre"].strip())
    return names


def family(wc):
    return {"M": "Metal", "J": "Joinery", "A": "Acrylics"}.get(wc[:1], "")


def drawing_of(code):
    m = re.match(r"^[A-Z&]{2,5}-(\d.*)$", code)       # ABC-9149-00-GA1 -> 9149-00-GA1
    return m.group(1) if m else code


# ---------------------------------------------------------------- the board
def build(extract, out_dir, products_path, boms_path, routes_path, dave=None, lead_days=14):
    grids, as_at = read_extract(extract)
    prods, boms, routes, wcnames = read_products(products_path), read_boms(boms_path), read_routes(routes_path), read_work_centres()
    today = day(as_at[:10]) or dt.date.today()
    checks = []

    # works orders still to make
    wos = []
    for w in grids["WOR"]:
        qty = num(w["amd_qty"]) or num(w["orig_qty"])
        done = num(w["good_qty"])
        bal = qty - done
        if bal <= 0:
            continue
        code = product_code(w["product"])
        so_no, _, so_sub = w["sales_order"].partition("/")
        wos.append(dict(wo=w["works_order"], parent=w["parent_order"] or w["works_order"].split("/")[0],
                        level="Sub-assembly" if "/" in w["works_order"] else "Top", access_part=w["product"],
                        code=code, rev=w["rev"], so=w["sales_order"], so_no=so_no, so_sub=so_sub,
                        customer=w["customer"], qty=qty, done=done, bal=bal,
                        due=day(w["scheduled"]), start=day(w["first_date"]) or day(w["created"]),
                        type=w["order_type"], booked=num(w["booked_mat"]) + num(w["booked_lab"]) + num(w["booked_subcon"])))
    wos.sort(key=lambda w: (w["due"] or dt.date.max, w["wo"]))

    # sales-order lines, by order number + product
    so_lines, so_orders = defaultdict(list), defaultdict(list)
    for s in grids["SOH"]:
        so_lines[(s["order_no"], s["ITMREF"])].append(s)
        so_orders[s["order_no"]].append(s)
    for w in wos:
        lines = so_lines.get((w["so_no"], w["code"]), []) if w["so_no"] else []
        if not lines and w["so_no"]:          # the order line is for the finished part, the WO for a version of it
            lines = so_orders.get(w["so_no"], [])
        dates = sorted({day(s["DEMDLVDAT"]) for s in lines if day(s["DEMDLVDAT"])})
        w["cust_date"] = (dates[0] if len(dates) == 1 else None)
        w["cust_note"] = ("" if not w["so_no"] or w["so_no"].upper() == "STOCK" else
                          "SO not open" if not lines else "Check SO dates" if len(dates) > 1 else "")
        w["account"] = lines[0]["BPCORD"] if lines else ""

    # supply: stock, open PO lines, works orders
    stock = defaultdict(float)
    for s in grids["SMR"]:
        stock[s["ITMREF"]] += num(s["QTYSTU"])
    pos = defaultdict(list)
    for p in grids["POH"]:
        pos[p["ITMREF"]].append([day(p["EXTRCPDAT"]), num(p["QTYUOM"]), p["order_no"]])
    for v in pos.values():
        v.sort(key=lambda x: x[0] or dt.date.max)
    wo_supply = defaultdict(list)
    for w in wos:
        wo_supply[w["code"]].append([w["due"], w["bal"], w["wo"]])
    on_po = {k: sum(x[1] for x in v) for k, v in pos.items()}
    on_wo = {k: sum(x[1] for x in v) for k, v in wo_supply.items()}

    # material status: share stock out in due-date order, then POs / works orders
    free = dict(stock)
    po_left = {k: [x[:] for x in v] for k, v in pos.items()}
    wo_left = {k: [x[:] for x in v] for k, v in wo_supply.items()}
    for w in wos:
        comps = boms.get(w["code"], [])
        w["lines"] = []
        if not comps:
            w["status"], w["mat_text"] = RED, "No BOM in X3"
            continue
        worst = GREEN
        for comp, link in comps:
            need = link * w["bal"]
            take = min(need, max(free.get(comp, 0), 0))
            free[comp] = free.get(comp, 0) - take
            short, cover, late = need - take, [], False
            for src, kind in ((po_left.get(comp, []), "PO"), (wo_left.get(comp, []), "WO")):
                for x in src:
                    if short <= 1e-9:
                        break
                    if x[1] <= 1e-9 or x[2] == w["wo"]:
                        continue
                    use = min(short, x[1])
                    x[1] -= use
                    short -= use
                    cover.append((kind, x[2], x[0], use))
                    if not x[0] or not w["due"] or x[0] > w["due"]:
                        late = True
            call_off = comp.startswith(CALL_OFF)
            st = (GREEN if need - take <= 1e-9 else AMBER if call_off and not cover
                  else RED if short > 1e-9 or late else AMBER)
            worst = RED if RED in (worst, st) else AMBER if AMBER in (worst, st) else GREEN
            w["lines"].append(dict(comp=comp, need=need, from_stock=take, short=need - take, cover=cover,
                                   status=st, uncovered=max(short, 0), call_off=call_off))
        w["status"] = worst
        bits = []
        for l in w["lines"]:
            if l["status"] == GREEN:
                continue
            if l["call_off"] and not l["cover"]:
                bits.append(f"{l['comp']} to call off {l['uncovered']:g}")
            elif l["uncovered"] > 1e-9:
                bits.append(f"{l['comp']} short {l['uncovered']:g}" + (" (no PO)" if not l["cover"] else " (late)"))
            else:
                bits.append(f"{l['comp']} " + " ".join(f"{k} {fmt(d) or 'no date'}" for k, _, d, _ in l["cover"][:2]))
        w["mat_text"] = "Material in stock" if worst == GREEN else "; ".join(bits)

    # hours still to do, by work centre
    wcs_used = set()
    for w in wos:
        w["hours"] = defaultdict(float)
        rt = routes.get(w["code"], [])
        w["has_route"] = bool(rt)
        for op, wc, desc, setup, run in rt:
            w["hours"][wc] += run * w["bal"] / 60 + (setup / 60 if w["done"] == 0 else 0)
            wcs_used.add(wc)
        w["families"] = sorted({family(wc) for wc in w["hours"] if family(wc)})
        if not rt:
            checks.append(["WARN", w["wo"], f"{w['code']}: no route in X3", "no work-centre hours for this works order"])
    for w in wos:
        p = prods.get(w["code"])
        w["des"] = p["des"] if p else ""
        w["cat"] = p["cat"] if p else ""
        if not p:
            checks.append(["WARN", w["wo"], f"{w['access_part']} -> {w['code']}: not in the X3 product file", ""])
    wc_cols = sorted(wcs_used, key=lambda c: (family(c) or "Z", c))

    # work-centre load by week of the due date
    load = defaultdict(lambda: defaultdict(float))
    for w in wos:
        wk = (w["due"] - dt.timedelta(days=w["due"].weekday())) if w["due"] else None
        wk = max(wk, today - dt.timedelta(days=today.weekday())) if wk else None   # overdue -> this week
        for wc, h in w["hours"].items():
            load[wk][wc] += h

    # WO suggestions: SO lines for made parts not covered by works orders / stock
    stale = [s for s in grids["SOH"] if day(s["DEMDLVDAT"]) and day(s["DEMDLVDAT"]) < today - dt.timedelta(days=STALE_DAYS)]
    for s in stale:
        checks.append(["INFO", s["order_no"], f"Sales-order line {s['ITMREF']} x {num(s['QTY']):g} due {fmt(day(s['DEMDLVDAT']))} "
                       "is still open", f"due more than {STALE_DAYS} days ago - not suggested; close it or re-date it before go-live"])
    stale_ids = {id(s) for s in stale}
    sug, cover_left = [], {k: stock.get(k, 0) + on_wo.get(k, 0) for k in set(stock) | set(on_wo)}
    for s in sorted(grids["SOH"], key=lambda s: day(s["DEMDLVDAT"]) or dt.date.max):
        code, qty = s["ITMREF"], num(s["QTY"])
        made = code in boms or code in routes or (prods.get(code, {}).get("cat") in ("FGML",))
        if not made or qty <= 0 or id(s) in stale_ids:
            continue
        have = cover_left.get(code, 0)
        use = min(have, qty)
        cover_left[code] = have - use
        if qty - use <= 1e-9:
            continue
        due = day(s["DEMDLVDAT"])
        rt = routes.get(code, [])
        sug.append(dict(code=code, des=s["ITMDES"] or prods.get(code, {}).get("des", ""), so=s["order_no"],
                        mrp_qty=qty - use, so_qty=qty, due=due, start=(due - dt.timedelta(days=lead_days)) if due else None,
                        bom=code in boms, route=bool(rt), account=s["BPCORD"], ordered=day(s["ORDDAT"]),
                        families=sorted({family(o[1]) for o in rt if family(o[1])}), drawing=drawing_of(code)))

    # exploded BOMs, all levels
    def explode(code, qty, level, seen):
        out = []
        for comp, link in boms.get(code, []):
            need = link * qty
            out.append(dict(level=level, comp=comp, des=prods.get(comp, {}).get("des", ""), link=link, need=need,
                            stock=stock.get(comp, 0), on_po=on_po.get(comp, 0),
                            po_due=fmt(next((x[0] for x in pos.get(comp, []) if x[0]), None)), on_wo=on_wo.get(comp, 0),
                            bom=comp in boms, route=comp in routes,
                            make="Manufactured" if comp in boms or comp in routes else "Purchased"))
            if comp in boms and comp not in seen and level < 8:
                out += explode(comp, need, level + 1, seen | {comp})
        return out
    for w in wos:
        w["explode"] = explode(w["code"], w["bal"], 1, {w["code"]})

    compare = compare_dave(dave, wos) if dave else None
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = (as_at or dt.datetime.now().strftime("%Y-%m-%d %H:%M"))[:16]
    meta = dict(as_at=stamp, wos=len(wos), top=sum(w["level"] == "Top" for w in wos),
                green=sum(w["status"] == GREEN for w in wos), amber=sum(w["status"] == AMBER for w in wos),
                red=sum(w["status"] == RED for w in wos), no_bom=sum(not boms.get(w["code"]) for w in wos),
                no_route=sum(not w["has_route"] for w in wos), suggestions=len(sug),
                sug_red=sum(not (s["bom"] and s["route"]) for s in sug), stale_so=len(stale),
                overdue=sum(1 for w in wos if w["due"] and w["due"] < today),
                hours=round(sum(sum(w["hours"].values()) for w in wos), 1))
    name = f"SDI_Live_Orders_{stamp[:10]}"
    write_xlsx(out / f"{name}.xlsx", meta, wos, wc_cols, wcnames, load, sug, checks, compare)
    write_html(out / f"{name}.html", meta, wos, wc_cols, wcnames, load, sug, compare)
    return dict(meta=meta, files=[f"{name}.xlsx", f"{name}.html"], compare=compare and compare["summary"])


def compare_dave(path, wos):
    """Dave's workbook against the board, works order by works order (the ones still open in both)."""
    ws = load_workbook(path, data_only=True).worksheets[0]
    head = [str(c.value or "").strip() for c in ws[1]]
    by = {w["wo"]: w for w in wos}
    rows, only_dave = [], 0
    for r in ws.iter_rows(min_row=2, values_only=True):
        if not r[2]:
            continue
        wo = str(r[2]).strip()
        w = by.get(wo)
        if not w:
            only_dave += 1
            continue
        d_part = str(r[4] or "").strip()
        rows.append([wo, d_part, w["code"], "same" if product_code(d_part) == w["code"] else "DIFFERENT",
                     num(r[9]), w["qty"], num(r[11]), w["bal"], "same" if abs(num(r[11]) - w["bal"]) < 1e-6 else "changed",
                     r[0].strftime("%d/%m/%y") if isinstance(r[0], dt.datetime) else str(r[0] or ""), fmt(w["due"]),
                     str(r[8] or "")[:80], w["status"], w["mat_text"][:80]])
    same_part = sum(x[3] == "same" for x in rows)
    summary = dict(dave_rows=sum(1 for r in ws.iter_rows(min_row=2, values_only=True) if r[2]), matched=len(rows),
                   closed_since=only_dave, same_part=same_part, same_balance=sum(x[8] == "same" for x in rows),
                   board_only=sum(1 for w in wos if w["level"] == "Top") - len(rows))
    return dict(summary=summary, rows=rows, head=head)


# ---------------------------------------------------------------- Excel
FILL = {GREEN: "E3F4E8", AMBER: "FFF1C7", RED: "FDE2E1"}
INK = PatternFill("solid", fgColor="282928")


def sheet(wb, title, head, rows, widths=None, status_col=None):
    ws = wb.create_sheet(title)
    ws.append(head)
    for c in ws[1]:
        c.font, c.fill = Font(bold=True, color="FFFFFF"), INK
        c.alignment = Alignment(wrap_text=True, vertical="top")
    for r in rows:
        ws.append(r)
        if status_col is not None and r[status_col] in FILL:
            ws.cell(ws.max_row, status_col + 1).fill = PatternFill("solid", fgColor=FILL[r[status_col]])
    for i, w in enumerate(widths or [], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"
    if rows:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(head))}{ws.max_row}"
    return ws


def wc_label(wc, wcnames):
    return "/".join(wcnames.get(wc, [])) or wc


def write_xlsx(path, meta, wos, wc_cols, wcnames, load, sug, checks, compare):
    wb = Workbook()
    ws = wb.active
    ws.title = "Read me"
    for r in [["SDI Live Orders board", f"as at {meta['as_at']}"], [],
              ["Works orders still to make", meta["wos"], f"{meta['top']} top level, the rest sub-assemblies"],
              ["Material status", f"{meta['green']} green · {meta['amber']} amber · {meta['red']} red",
               "red includes works orders whose part has no BOM in X3"],
              ["No BOM / no route in X3", f"{meta['no_bom']} / {meta['no_route']}"],
              ["Hours still to do", meta["hours"]], ["Overdue works orders", meta["overdue"]],
              ["Old sales-order lines still open", f"{meta['stale_so']} due more than {STALE_DAYS} days ago - listed on Checks, not suggested"], ["WO suggestions", f"{meta['suggestions']} ({meta['sug_red']} with no BOM or route)"], [],
              ["How it's worked out", ""],
              ["Live Orders", "Open works orders (Access now, X3 after go-live). Balance = (amended or ordered) - made."],
              ["Customer date", "From the works order's sales order: one date = shown; none open = 'SO not open'; several = 'Check SO dates'."],
              ["Material status", "BOM x balance. Stock is shared out by due date; shortages covered by POs, then works orders. "
                                  "GREEN in stock; AMBER covered on time, or a call-off material (sheet, powder, packing, pallets, wire, carriage) "
                                  "still to call off; RED short with nothing due in time, or no BOM. The call-off list is provisional (LO-01)."],
              ["Work-centre hours", "Route run time x balance, plus set-up if nothing is made yet. Column = X3 work centre (Access dept)."],
              ["Work-centre load", "Those hours by week of the works order's due date; overdue counts in this week."],
              ["WO Suggestions", "Sales-order lines for made parts not covered by stock or works orders. Start = due - lead days."],
              ["Exploded BOMs", "Every level, with stock, on PO (next due), on WO and make / buy."],
              ["Typed by Production", "Comments, Prog and Tube req are not in Access or X3 data: kept on the board's side (LO-01)."]]:
        ws.append(r)
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width, ws.column_dimensions["C"].width = 26, 70, 50
    ws["A1"].font = Font(bold=True, size=14)

    head = (["Due date", "Customer date", "WO Num", "Level", "Parent WO", "SO Num", "Account", "Part code", "Description",
             "DRAWING NUMBER", "REV", "MATERIAL STATUS", "Material detail", "QTY", "Booked in", "Balance",
             "Metal", "Joinery", "Acrylics", "Comments", "Prog", "Tube req"]
            + [f"{wc_label(c, wcnames)} ({c})" for c in wc_cols])
    rows = [[w["due"], w["cust_date"] or w["cust_note"], w["wo"], w["level"], w["parent"], w["so"], w["account"], w["code"],
             w["des"], drawing_of(w["code"]), w["rev"], w["status"], w["mat_text"], w["qty"], w["done"], w["bal"],
             *["Y" if f in w["families"] else "" for f in ("Metal", "Joinery", "Acrylics")], "", "", ""]
            + [round(w["hours"][c], 2) if w["hours"].get(c) else None for c in wc_cols] for w in wos]
    s = sheet(wb, "Live Orders", head, rows, [10, 12, 13, 12, 11, 17, 9, 20, 34, 16, 5, 10, 48, 7, 8, 8, 6, 7, 8, 24, 6, 8]
              + [9] * len(wc_cols), status_col=11)
    for r in range(2, s.max_row + 1):
        s.cell(r, 1).number_format = "dd/mm/yy"
        if isinstance(s.cell(r, 2).value, dt.date):
            s.cell(r, 2).number_format = "dd/mm/yy"

    weeks = sorted(k for k in load if k)
    rows = [[wc_label(c, wcnames), c] + [round(load[k].get(c, 0), 1) for k in weeks] + [round(sum(load[k].get(c, 0) for k in weeks), 1)]
            for c in wc_cols]
    sheet(wb, "Work-centre load", ["Work centre", "X3"] + [f"w/c {k:%d/%m/%y}" for k in weeks] + ["Total"], rows,
          [16, 10] + [10] * (len(weeks) + 1))

    rows = [[s_["code"], s_["des"], s_["so"], s_["mrp_qty"], *["Y" if f in s_["families"] else "" for f in ("Metal", "Joinery", "Acrylics")],
             s_["start"], s_["due"], "Yes" if s_["bom"] else "No", "Yes" if s_["route"] else "No", s_["so_qty"], s_["drawing"],
             s_["ordered"], s_["account"], RED if not (s_["bom"] and s_["route"]) else ""] for s_ in sug]
    s = sheet(wb, "WO Suggestions", ["Part code", "Description", "Order No", "MRP Qty", "Metal", "Joinery", "Acrylics",
                                     "WO Suggested date", "SO Due Date", "BOM", "Route", "SO Qty", "Drawing No", "SO Created",
                                     "Cus Code", "Flag"], rows, [20, 34, 15, 8, 6, 7, 8, 12, 12, 6, 6, 7, 16, 11, 9, 7], status_col=15)
    for r in range(2, s.max_row + 1):
        for c in (8, 9, 14):
            s.cell(r, c).number_format = "dd/mm/yy"

    rows = []
    for w in wos:
        rows.append([w["wo"], w["code"], 0, w["code"], w["des"], 1, w["bal"], stock_of(w), None, None, None, None, None, w["status"]])
        for e_ in w["explode"]:
            rows.append([w["wo"], w["code"], e_["level"], e_["comp"], e_["des"], e_["link"], round(e_["need"], 4), e_["stock"],
                         e_["on_po"], e_["po_due"], e_["on_wo"], e_["make"], "Yes" if e_["bom"] else "", ""])
    sheet(wb, "Exploded BOMs", ["WO", "Part", "Level", "Component", "Description", "Qty used", "Required", "In stock",
                                "On PO", "Next PO due", "On WO", "Procurement", "Has BOM", "Status"], rows,
          [13, 20, 6, 22, 34, 9, 10, 9, 9, 11, 8, 13, 8, 9], status_col=13)
    if compare:
        sheet(wb, "Check against Dave", ["WO", "Dave part", "Board part", "Part", "Dave qty", "Board qty", "Dave balance",
                                         "Board balance", "Balance", "Dave due", "Board due", "Dave material status",
                                         "Board status", "Board material"], compare["rows"],
              [13, 20, 20, 10, 8, 8, 9, 9, 9, 10, 10, 40, 9, 40], status_col=12)
    sheet(wb, "Checks", ["Level", "WO", "Check", "Detail"], checks, [8, 14, 60, 50])
    wb.save(path)


def stock_of(w):
    return None


# ---------------------------------------------------------------- HTML
def write_html(path, meta, wos, wc_cols, wcnames, load, sug, compare):
    data = dict(meta=meta, wcs=[[c, wc_label(c, wcnames), family(c)] for c in wc_cols],
                wos=[dict(due=w["due"].isoformat() if w["due"] else "", cd=w["cust_date"].isoformat() if w["cust_date"] else w["cust_note"],
                          wo=w["wo"], lv=w["level"], so=w["so"], ac=w["account"], p=w["code"], d=w["des"], rev=w["rev"],
                          st=w["status"], mt=w["mat_text"], q=w["qty"], b=w["done"], bal=w["bal"], f=w["families"],
                          h={c: round(v, 2) for c, v in w["hours"].items() if v},
                          x=[[e_["level"], e_["comp"], e_["des"], round(e_["need"], 3), e_["stock"], e_["on_po"], e_["po_due"],
                              e_["on_wo"], e_["make"]] for e_ in w["explode"]]) for w in wos],
                load=[[k.isoformat(), {c: round(v, 1) for c, v in load[k].items()}] for k in sorted(k for k in load if k)],
                sug=[[s["code"], s["des"], s["so"], s["mrp_qty"], s["due"].isoformat() if s["due"] else "", s["bom"], s["route"],
                      s["account"]] for s in sug],
                cmp=compare["summary"] if compare else None)
    page = TEMPLATE.replace("__DATA__", json.dumps(data, default=str).replace("</", "<\\/")).replace("__ASAT__", html.escape(meta["as_at"]))
    Path(path).write_text(page, encoding="utf-8")


TEMPLATE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SDI Live Orders</title><style>
:root{--y:#F5D947;--ink:#282928;--t:#1f2321;--muted:#6b6f6c;--line:#e6e7e4;--bg:#f4f4f1;--card:#fff;
--g:#146c2e;--gb:#e3f4e8;--a:#8a5a00;--ab:#fff1c7;--r:#b42318;--rb:#fde2e1}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--t:#ececea;--muted:#a3a7a4;--line:#3a3c3b;--bg:#151615;--card:#1c1d1c;
--g:#8fd9a5;--gb:#16301f;--a:#f5d27a;--ab:#3a2f12;--r:#ff9b8f;--rb:#3a1d1b}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--t);font:14px/1.45 'Segoe UI','Helvetica Neue',Arial,sans-serif}
header{background:var(--ink);color:#fff;border-bottom:6px solid var(--y)}.w{max-width:1600px;margin:0 auto;padding:0 16px}
.hd{padding:18px 0 14px}.brand{color:var(--y);font-weight:700}h1{margin:2px 0 0;font-size:24px}.sub{color:#cfd1ce;font-size:13px}
main{padding:16px 0 40px}.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:14px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 14px}.tile b{display:block;font-size:22px}
.tile span{color:var(--muted);font-size:12px}.tabs{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px}
.tabs button{font:inherit;border:1px solid var(--line);background:var(--card);color:var(--t);border-radius:6px;padding:7px 12px;cursor:pointer}
.tabs button.on{background:var(--ink);color:#fff;border-color:var(--ink)}.bar{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px}
input,select{font:inherit;padding:7px 9px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--t);max-width:100%}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:auto;max-height:72vh}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:5px 7px;border-top:1px solid var(--line);text-align:left;white-space:nowrap}
th{position:sticky;top:0;background:var(--ink);color:#fff;font-weight:600;z-index:1;cursor:pointer}td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
td.wrap{white-space:normal;min-width:240px;max-width:380px}.st{font-weight:700;border-radius:4px;padding:1px 6px;font-size:12px}
.GREEN{background:var(--gb);color:var(--g)}.AMBER{background:var(--ab);color:var(--a)}.RED{background:var(--rb);color:var(--r)}
tr.x td{background:var(--bg);white-space:normal}tr.main{cursor:pointer}.muted{color:var(--muted)}.hide{display:none}
.heat{border-radius:3px;padding:1px 4px}.xin{position:sticky;left:8px;max-width:min(1150px,calc(100vw - 48px))}.xin table{width:auto}
</style></head><body><header><div class="w hd"><div class="brand">we.are.sdi</div><h1>Live Orders</h1>
<div class="sub">as at __ASAT__ · worked out from works orders, sales orders, stock, POs, BOMs and routes</div></div></header>
<main class="w"><div class="tiles" id="tiles"></div>
<div class="tabs" id="tabs"></div><div id="view"></div>
<p class="muted">Material status: stock shared out by due date; shortages covered by POs, then works orders. GREEN in stock · AMBER covered on time · RED short / late / no BOM. Hours = route × balance (+ set-up if nothing made). Click a works order for its exploded BOM.</p>
</main><script>
const D=__DATA__;const $=s=>document.querySelector(s);const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const dd=s=>s&&/^\d{4}-/.test(s)?s.slice(8,10)+'/'+s.slice(5,7)+'/'+s.slice(2,4):esc(s);const m=D.meta;
$('#tiles').innerHTML=[[m.wos,'works orders to make ('+m.top+' top level)'],[m.green,'green: in stock'],[m.amber,'amber: covered on time'],
[m.red,'red: short / late / no BOM'],[m.hours.toLocaleString(),'hours still to do'],[m.suggestions,'WO suggestions ('+m.sug_red+' no BOM / route)']]
.concat(D.cmp?[[D.cmp.matched+' / '+D.cmp.dave_rows,"of Dave's sheet still open"]]:[]).map(t=>`<div class="tile"><b>${t[0]}</b><span>${t[1]}</span></div>`).join('');
const tabs=[['orders','Live Orders'],['load','Work-centre load'],['sug','WO Suggestions']];let cur='orders';
function tabbar(){$('#tabs').innerHTML=tabs.map(t=>`<button class="${t[0]==cur?'on':''}" data-t="${t[0]}">${t[1]}</button>`).join('');
document.querySelectorAll('#tabs button').forEach(b=>b.onclick=()=>{cur=b.dataset.t;tabbar();show()})}
let f={q:'',st:'',fam:'',lv:'Top',wc:''},sortk='due',sortd=1;
function orders(){const wc=f.wc;let r=D.wos.filter(w=>(!f.st||w.st==f.st)&&(!f.lv||w.lv==f.lv)&&(!f.fam||w.f.includes(f.fam))&&(!wc||w.h[wc])
&&(!f.q||(w.wo+' '+w.p+' '+w.d+' '+w.so+' '+w.ac+' '+w.mt).toLowerCase().includes(f.q)));
r.sort((a,b)=>{const x=sortk.startsWith('h:')?(a.h[sortk.slice(2)]||0):a[sortk],y=sortk.startsWith('h:')?(b.h[sortk.slice(2)]||0):b[sortk];return (x>y?1:x<y?-1:0)*sortd});
const wcs=D.wcs.filter(c=>!f.fam||c[2]==f.fam);
const head=[['due','Due'],['cd','Customer date'],['wo','WO'],['so','SO'],['ac','Account'],['p','Part'],['d','Description'],['st','Material'],['mt','Detail'],['q','Qty','n'],['b','Booked in','n'],['bal','Balance','n']]
.concat(wcs.map(c=>['h:'+c[0],c[1],'n']));
let h=`<div class="bar"><input id="q" placeholder="Search WO, part, SO, account…" value="${esc(f.q)}">
<select id="st"><option value="">All status</option>${['RED','AMBER','GREEN'].map(s=>`<option ${f.st==s?'selected':''}>${s}</option>`).join('')}</select>
<select id="fam"><option value="">All areas</option>${['Metal','Joinery','Acrylics'].map(s=>`<option ${f.fam==s?'selected':''}>${s}</option>`).join('')}</select>
<select id="wc"><option value="">Any work centre</option>${D.wcs.map(c=>`<option value="${c[0]}" ${f.wc==c[0]?'selected':''}>${esc(c[1])} (${c[0]})</option>`).join('')}</select>
<select id="lv"><option value="">Top + sub-assemblies</option><option value="Top" ${f.lv=='Top'?'selected':''}>Top-level WOs</option><option value="Sub-assembly" ${f.lv=='Sub-assembly'?'selected':''}>Sub-assemblies</option></select>
<span class="muted" style="align-self:center">${r.length} works orders</span></div><div class="card"><table><tr>${head.map(c=>`<th class="${c[2]||''}" data-k="${c[0]}">${esc(c[1])}</th>`).join('')}</tr>`;
for(const w of r){h+=`<tr class="main" data-wo="${esc(w.wo)}"><td>${dd(w.due)}</td><td>${dd(w.cd)}</td><td>${esc(w.wo)}</td><td>${esc(w.so)}</td><td>${esc(w.ac)}</td><td>${esc(w.p)}</td>
<td>${esc(w.d)}</td><td><span class="st ${w.st}">${w.st}</span></td><td class="wrap">${esc(w.mt)}</td><td class="n">${w.q}</td><td class="n">${w.b}</td><td class="n">${w.bal}</td>
${wcs.map(c=>`<td class="n">${w.h[c[0]]?w.h[c[0]].toFixed(2):''}</td>`).join('')}</tr>`}
$('#view').innerHTML=h+'</table></div>';
$('#q').oninput=e=>{f.q=e.target.value.toLowerCase();orders();const q=$('#q');q.focus();q.setSelectionRange(q.value.length,q.value.length)};
['st','fam','wc','lv'].forEach(k=>$('#'+k).onchange=e=>{f[k]=e.target.value;orders()});
document.querySelectorAll('th[data-k]').forEach(t=>t.onclick=()=>{sortd=sortk==t.dataset.k?-sortd:1;sortk=t.dataset.k;orders()});
document.querySelectorAll('tr.main').forEach(t=>t.onclick=()=>{const n=t.nextElementSibling;if(n&&n.classList.contains('x')){n.remove();return}
const w=D.wos.find(x=>x.wo==t.dataset.wo);const x=document.createElement('tr');x.className='x';
x.innerHTML=`<td colspan="${head.length}"><div class="xin">${w.x.length?`<table><tr><th>Level</th><th>Component</th><th>Description</th><th class="n">Required</th><th class="n">In stock</th><th class="n">On PO</th><th>Next PO due</th><th class="n">On WO</th><th>Make / buy</th></tr>`+
w.x.map(e=>`<tr><td>${'·'.repeat(e[0])} ${e[0]}</td><td>${esc(e[1])}</td><td>${esc(e[2])}</td><td class="n">${e[3]}</td><td class="n">${e[4]}</td><td class="n">${e[5]}</td><td>${esc(e[6])}</td><td class="n">${e[7]}</td><td>${e[8]}</td></tr>`).join('')+'</table>':'No BOM in X3 for this part.'}</div></td>`;t.after(x)})}
function loadv(){const wcs=D.wcs;const max=Math.max(1,...D.load.flatMap(l=>Object.values(l[1])));
let h=`<div class="card"><table><tr><th>Week commencing</th>${wcs.map(c=>`<th class="n">${esc(c[1])}<br><span style="font-weight:400">${c[0]}</span></th>`).join('')}<th class="n">Total</th></tr>`;
for(const [k,v] of D.load){const tot=Object.values(v).reduce((a,b)=>a+b,0);h+=`<tr><td>${dd(k)}</td>${wcs.map(c=>{const x=v[c[0]]||0;return `<td class="n"><span class="heat" style="background:rgba(245,217,71,${(x/max*0.9).toFixed(2)})">${x?x.toFixed(1):''}</span></td>`}).join('')}<td class="n"><b>${tot.toFixed(1)}</b></td></tr>`}
$('#view').innerHTML=h+'</table></div><p class="muted">Hours by the week each works order is due (overdue counts in this week). Capacity per work centre is to come from X3 (REP-08).</p>'}
function sugv(){let h=`<div class="card"><table><tr><th>Part</th><th>Description</th><th>Sales order</th><th class="n">To make</th><th>SO due</th><th>BOM</th><th>Route</th><th>Account</th></tr>`;
for(const s of D.sug){const bad=!(s[5]&&s[6]);h+=`<tr><td>${esc(s[0])}</td><td>${esc(s[1])}</td><td>${esc(s[2])}</td><td class="n">${s[3]}</td><td>${dd(s[4])}</td>
<td>${s[5]?'Yes':'<span class="st RED">No</span>'}</td><td>${s[6]?'Yes':'<span class="st RED">No</span>'}</td><td>${esc(s[7])}</td></tr>`}
$('#view').innerHTML=h+'</table></div><p class="muted">Sales-order lines for made parts not covered by stock or open works orders. In red: no BOM or no route in X3, so they can\'t be made yet. X3 MRP replaces this list after go-live.</p>'}
function show(){({orders,load:loadv,sug:sugv})[cur]()}tabbar();show();
</script></body></html>"""


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("extract")
    ap.add_argument("out_dir")
    ap.add_argument("--products", required=True)
    ap.add_argument("--boms", required=True)
    ap.add_argument("--routes", required=True)
    ap.add_argument("--dave")
    ap.add_argument("--suggest-lead-days", type=int, default=14)
    a = ap.parse_args()
    res = build(a.extract, a.out_dir, a.products, a.boms, a.routes, a.dave, a.suggest_lead_days)
    print(json.dumps(res["meta"]), "\n", res["files"])
    if res["compare"]:
        print("against Dave's sheet:", res["compare"])
