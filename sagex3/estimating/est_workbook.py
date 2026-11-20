"""The estimate -> Sage X3 write-up workbook, generated on every run (20 Nov 2026).

Modelled on the hand-made 16 Nov write-up of Tim's Gift Card Header estimate (James: "the excellent s/sheet"):
    Read me        the result: READY / NOT READY, counts, the files and the load order
    Estimate → X3  every estimate line, its cell and value, next to where it lands in the X3 files and how it's worked out
    BOM file       the BOM import file, line by line, readable
    Route file     the route import file, operation by operation, readable
    Product file   the product import file (always written: X3 rejects it if the part already exists)
    Checks         every check the converter made, by estimate cell

    write(res, path)      res = est_to_x3.build(...) (it carries res["detail"])
Holds the estimate's own content (customer, descriptions): it lives in the run folder, never in git.
"""
import datetime as dt
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

INK, YELLOW = "282928", "F5D947"
HEAD_FONT, HEAD_FILL = Font(bold=True, color=YELLOW), PatternFill("solid", fgColor=INK)
SECTION_FILL = PatternFill("solid", fgColor=YELLOW)
LEVEL_FILL = {"STOP": PatternFill("solid", fgColor="FDE2E1"), "WARN": PatternFill("solid", fgColor="FFF1C7")}
WRAP = Alignment(wrap_text=True, vertical="top")


def g(v, places=6):
    """A number as people write it: 1, 0.25, 0.015848 - text left alone."""
    if isinstance(v, bool) or v is None:
        return "" if v is None else v
    try:
        f = round(float(v), places)
    except (TypeError, ValueError):
        return v
    return int(f) if f == int(f) else f


def _head(ws, row, heads, widths=None):
    for i, h in enumerate(heads, 1):
        c = ws.cell(row, i, h)
        c.font, c.fill, c.alignment = HEAD_FONT, HEAD_FILL, Alignment(wrap_text=True, vertical="center")
    if widths:
        for i, w in enumerate(widths):
            ws.column_dimensions[chr(65 + i)].width = w


def _section(ws, row, text, width):
    c = ws.cell(row, 1, text)
    c.font, c.fill = Font(bold=True, size=12), SECTION_FILL
    for i in range(2, width + 1):
        ws.cell(row, i).fill = SECTION_FILL


def _rows(ws, start, rows, wrap=True):
    r = start
    for row in rows:
        for i, v in enumerate(row, 1):
            c = ws.cell(r, i, v)
            if wrap:
                c.alignment = WRAP
        r += 1
    return r


def write(res, path):
    d = res["detail"]
    head, x3 = d["head"], d.get("x3") or {}
    imp = head.get("layout") == "IMPORT"
    code, stem = res["code"], Path(path).stem
    ready = res["stop"] == 0
    x3desc = lambda c: (x3.get(c) or ("", ""))[1]
    wb = Workbook()

    # ---------- Read me
    rm = wb.active
    rm.title = "Read me"
    rm.column_dimensions["A"].width, rm.column_dimensions["B"].width = 24, 120
    rm["A1"] = f"Estimate {d['estimate']} → Sage X3 import files"
    rm["A1"].font = Font(bold=True, size=14)
    est_line = " · ".join(x for x in [
        f"{head.get('drawing_full') or head.get('drawing')} {head.get('description')}".strip()
        + (f" rev {head['rev']}" if head.get("rev") else ""),
        f"customer {head['customer']}" if head.get("customer") else "",
        f"quantity {g(head.get('quantity'))}" if head.get("quantity") not in (None, "") else "",
        f"unit cost £{float(head['unit_cost']):.2f}" if _isnum(head.get("unit_cost")) else "",
        f"file: {d['estimate']}"] if x)
    if d.get("existing"):
        part = (f"part {code} already exists in X3 ({d['existing'][1]}): its product line will be rejected on import - "
                f"expected; the BOM and route load onto it")
    else:
        part = f"part {code} is new: the product file creates it (category {d['category']})"
    result = (f"{'READY TO LOAD' if ready else 'NOT READY - fix the STOP checks first'} · {res['stop']} stops · "
              f"{res['warn']} warnings · BOM {res['bom']} lines · route {res['ops']} operations · {part}.")
    order = " → ".join(f for f in (f"{stem_of(code)}_ZSDIITM.txt (product)", f"{stem_of(code)}_YA00408BOM.txt (BOM)",
                                   f"{stem_of(code)}_ZSDIROU2.txt (route)")
                       if f.split(" ")[0] in d.get("load_files", []))
    rows = [
        ["Estimate", est_line],
        ["How it was converted", "SDI's converter (est_to_x3) read the estimate exactly as it was saved - no macro, no copy "
                                 "and paste - applied the estimators' rules, checked every line against the Sage X3 "
                                 "product list and work centres, and wrote the Sage X3 import files."],
        ["Result", result],
        ["Checked against", f"X3 product list: {Path(d['products']).name} ({_age(d['products'])}); work centres: "
                            f"work_centres.csv (Access department → X3 work centre)" + (
                                f"; sheet steel picked as {d['sheet_material']}" if not imp else "")],
        ["Files for Sage X3", (f"{order}. Load in Usage > Imports, TEST (SDI Mig) first, in this order." if ready else
                               "Not to be loaded until the STOP checks are fixed and the estimate is run again.")],
        ["Generated", dt.datetime.now().strftime("%d/%m/%Y %H:%M") + " by the SDI Intelligence portal (Estimate → X3)"],
        [],
        ["Tab", "What it shows"],
        ["Estimate → X3", "START HERE. Every line of the estimate (cell and value) next to where it lands in the X3 "
                          "files, with how each quantity and run time is worked out."],
        ["BOM file", "The BOM import file, line by line, in readable form."],
        ["Route file", "The route import file, operation by operation, in readable form."],
        ["Product file", "The product import file. Always written: X3 rejects it if the part already exists."],
        ["Checks", "Every check the converter made, by estimate cell (INFO = for information; WARN = look at it; "
                   "STOP = must be fixed before loading)."]]
    for i, (r) in enumerate(rows, 3):
        for j, v in enumerate(r, 1):
            c = rm.cell(i, j, v)
            c.alignment = WRAP
            if j == 1 or (r and r[0] == "Tab"):
                c.font = Font(bold=True)
    rm["B5"].font = Font(bold=True, color="1E7A3A" if ready else "B42318")

    # ---------- Estimate -> X3
    ex = wb.create_sheet("Estimate → X3")
    for col, w in zip("ABCDEFGH", (12, 22, 36, 44, 10, 20, 16, 52)):
        ex.column_dimensions[col].width = w
    ex["A1"] = "The estimate, line by line, into the Sage X3 import files"
    ex["A1"].font = Font(bold=True, size=14)
    r = 3
    _section(ex, r, "1. The part", 8)
    _head(ex, r + 1, ["Estimate cell", "What it holds", "Value in the estimate", "X3 file", "X3 field",
                      "Value in the X3 file", "", "How"])
    itm = d["itm_row"]
    c_code, c_desc, c_draw, c_cust, c_qty = (("E5", "E4", "E5 / H5", "E3", "E6 / H6") if imp else
                                             ("A63", "D4", "D5 / G5", "D3", "D6 / G6"))
    raw_parent = head.get("drawing") if imp else (head.get("labour_parent") or head.get("drawing"))
    part_rows = [
        [c_code, "Part code" + ("" if imp else " (first labour line)"), raw_parent, "Product, BOM and route",
         "Product (ITMREF)", code, "", "X3 code rule, as in the migration (upper case; spaces, &, ( ) removed; . / _ → -)"
         if raw_parent != code else "Used as it is"],
        [c_desc, "Description", head.get("description"), "Product file", "Description (ITMDES1)", itm[2], "",
         ("X3 keeps its own - the part exists: '" + d["existing"][1] + "'") if d.get("existing")
         else "First 30 characters"],
        [c_draw, "Drawing / revision", f"{head.get('drawing_full') or head.get('drawing')} rev {head.get('rev')}",
         "Product file", "Description 2 (ITMDES2)", itm[3] or "", "",
         "Revision in Description 2" + (" (taken by X3 only for a new part)" if d.get("existing") else "")],
        ["–", "Category", d["category"], "Product file", "Category (TCLCOD)", itm[0], "", "Chosen on the page (FGML unless changed)"],
        [c_cust, "Customer", head.get("customer"), "–", "–", "–", "", "Not part of the product: comes from the sales order"],
        [c_qty, "Quantity / unit cost", f"{g(head.get('quantity'))} / "
         + (f"£{float(head['unit_cost']):.2f}" if _isnum(head.get("unit_cost")) else ""), "–", "–", "–", "",
         "Not loaded (the standard cost load is still to add)"]]
    r = _rows(ex, r + 2, part_rows) + 1

    bom_name = f"{stem_of(code)}_YA00408BOM.txt"
    _section(ex, r, f"2. The bill of materials → {bom_name}", 8)
    _head(ex, r + 1, ["Estimate row", "Block", "What the estimate says", "In the estimate", "BOM line",
                      "Component in X3", "Link qty per unit", "How the quantity is worked out"])
    lines, by_line = [], {}
    for b in d["bom"]:
        by_line.setdefault(b.get("line"), []).append(b)
    for b in d["bom"]:
        lines.append(_bom_line(b, x3desc))
    for line, bs in by_line.items():                     # a component that several estimate rows add up to
        if line and len(bs) > 1:
            total = sum(float(x.get("qty") or 0) for x in bs)
            lines.append(["→", bs[0]["block"], " + ".join(f"row {x.get('row')}" for x in bs), "Same component, so added",
                          line, bs[0]["code"], g(total),
                          " + ".join(str(g(x.get("qty"))) for x in bs) + f" = {g(total)} per unit"])
    r = _rows(ex, r + 2, lines) + 1

    rou_name = f"{stem_of(code)}_ZSDIROU2.txt"
    _section(ex, r, f"3. The route → {rou_name}", 8)
    _head(ex, r + 1, ["Estimate row", "Operation", "Description", "Dept → X3 work centre", "Operation no.",
                      "Set-up, min", "Run per unit, min", "How run time is worked out"])
    ops = [[f"Row {o.get('row')}", o.get("labour"), o.get("text") or o.get("labour"),
            (f"{o.get('dept')} → {o.get('wc') or '(none)'}" if not imp else (o.get("wc") or "(none)")),
            o.get("opno") or "NOT LOADED", g(o.get("setup"), 4), g(o.get("run"), 4),
            o.get("how", "") + (f"; set-up from {o['setup_cell']}" if o.get("setup_cell") else "")
            + ("" if o.get("opno") else " - not loaded: see Checks")] for o in d["ops"]]
    r = _rows(ex, r + 2, ops) + 1
    stops = [c for c in res["checks"] if c[0] == "STOP"]
    note = (f"Checks: {res['stop']} STOP, {res['warn']} WARN - " + ("ready to load." if ready else
            "fix these first: " + "; ".join(f"{c[1]} {c[2]}" for c in stops[:6])))
    ex.cell(r, 1, note).font = Font(bold=True, color="1E7A3A" if ready else "B42318")

    # ---------- the three files, readable
    bf = wb.create_sheet("BOM file")
    _head(bf, 1, ["BOM line", "Parent", "BOM code", "Use status", "Base qty", "Component", "Component type",
                  "Link qty per unit", "X3 description"], [9, 14, 9, 10, 8, 20, 13, 15, 36])
    _rows(bf, 2, [[x[7], x[0], x[1], x[2], x[5], x[8], x[9], g(x[10]), x3desc(x[8])] for x in d["bom_rows"]], wrap=False)
    bf.freeze_panes = "A2"
    rf = wb.create_sheet("Route file")
    _head(rf, 1, ["Operation no.", "Product", "Routing", "Site", "Work centre", "Operation description",
                  "Set-up (min)", "Run per unit (min)", "Time unit"], [12, 14, 8, 6, 12, 34, 11, 16, 9])
    _rows(rf, 2, [[x[6], x[0], x[1], x[2], x[7], x[8], g(x[9], 4), g(x[10], 4), "minutes" if x[4] == 2 else x[4]]
                  for x in d["rou_rows"]], wrap=False)
    rf.freeze_panes = "A2"
    pf = wb.create_sheet("Product file")
    _head(pf, 1, list(d["itm_head"]), [10, 16, 32, 14, 32, 9, 10, 10, 9, 10, 9, 9, 9])
    _rows(pf, 2, [list(itm)], wrap=False)
    pf.cell(4, 1, ("Already in X3 as '" + d["existing"][1] + "': X3 rejects this line on import - expected.")
            if d.get("existing") else "New part: this line creates it in X3.").font = Font(italic=True)
    pf.freeze_panes = "A2"
    ck = wb.create_sheet("Checks")
    _head(ck, 1, ["Level", "Cell", "Check", "Detail"], [8, 12, 60, 80])
    for i, c in enumerate(res["checks"], 2):
        for j, v in enumerate(c, 1):
            cell = ck.cell(i, j, v)
            if c[0] in LEVEL_FILL:
                cell.fill = LEVEL_FILL[c[0]]
    ck.freeze_panes = "A2"
    wb.save(path)
    return path


def _bom_line(b, x3desc):
    """One estimate row of the BOM, with its working."""
    qty, line = b.get("qty"), b.get("line")
    scrap = _pct(b.get("scrap"))
    if b["block"] == "Sheet steel" and b.get("per") is not None:
        held = (f"{g(b.get('parts'))} off {b.get('size', '')}; {g((b.get('sheet') or ('', '', ''))[2])}mm gauge; "
                f"{g((b.get('sheet') or ('', ''))[0])} x {g((b.get('sheet') or ('', ''))[1])} sheet; "
                f"{g(b.get('per'))} per sheet")
        how = (f"{g(b.get('parts'))} ÷ {g(b.get('per'))} = {g(qty)} sheets per unit; sheet found in X3's product "
               f"list by size + gauge ({b.get('material', 'CR4')} assumed)")
    elif b["block"] == "Other sheet material" and b.get("per") is not None:
        held = f"{g(b.get('parts'))} off; {g(b.get('per'))} per sheet"
        how = f"{g(b.get('parts'))} ÷ {g(b.get('per'))} = {g(qty)} per unit; code taken from the description's first word"
    else:
        held = (f"{b['cell']} code {b.get('raw', b.get('code'))}"
                + (f"; {b['qty_cell']} qty {g(qty)}" if b.get("qty_cell") else ""))
        how = f"Qty per unit from {b.get('qty_cell') or b['cell']}"
    if scrap:
        how += f"; scrap {scrap} ({b.get('scrap_cell', '')}) not loaded"
    if b.get("raw") and b.get("raw") != b.get("code") and b.get("code"):
        how += f"; {b['raw']} → {b['code']} (X3 code rule)"
    if b.get("merged"):
        how += f"; added to line {line} (same component)"
    if not line:
        how += " - NOT LOADED: see Checks"
    return [f"Row {b.get('row', '')}", b["block"], b.get("text") or b.get("note", ""), held,
            line or "–", b.get("code") or "(none)", g(qty) if line else "–", how]


def _pct(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return ""
    return f"{f:.0%}" if f else ""


def _isnum(v):
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def _age(path):
    try:
        t = dt.datetime.fromtimestamp(Path(path).stat().st_mtime)
    except OSError:
        return "date unknown"
    return "as at " + t.strftime("%d/%m/%Y %H:%M")


def stem_of(code):
    import re
    return re.sub(r"[^\w\-]+", "_", code)
