"""Estimating spreadsheet -> Sage X3 import files (EST-10 stage 1, Jira SCRUM-210 / 242-244).

Reads one estimate workbook and writes the same X3
import files the migration kit produces, ready to load in Usage > Imports. Two layouts are read, told
apart by row 10:
  * the estimating template as the estimators use it today (e.g. 12539-04-GA GIFT CARD HEADER, 1 Sep 2026):
    codes in H, no sheet-steel / other-sheet codes, labour by Access department; the parent is the
    Access part code in the labour block (A63), the X3 work centre comes from work_centres.csv and the
    sheet steel from gauge + sheet size against the X3 products' Description 2 / 3 (CR4 unless told);
  * Dave Wright's IMPORT layout (IMPORT.xls), the same sheet with X3 columns added (component code B / I,
    link quantity C, X3 work centre R, run minutes Q).
  * ZSDIITM   the parent product (only if it is not already in X3)
  * YA00408BOM its bill of materials: standard materials, wire, sheet steel, other sheet material
  * ZSDIROU2  its route: one operation per labour line, X3 work centre, set-up and run time (minutes)
Nothing is written to X3. Every line is checked first and the checks are in the workbook:
  component in X3? marked "DONT USE"? work centre valid? quantity > 0? parent new or existing?

Usage:
    python est_to_x3.py <estimate.xls|.xlsx> <out_dir> --products <ZSDIITM_products_MAPPED.xlsx>
        [--parent CODE] [--category FGML] [--rev-in-code]
  --products   the current X3 product list (the latest ZSDIITM file, or an X3 product export with
               the same layout) - every component is checked against it
  --parent     override the parent code (e.g. IMPORT, Dave's test part in X3)
IMPORT layout: the X3 code is the SDI drawing number (E5) (runbook 21.5); the revision (H5) goes in
Description 2. --rev-in-code appends it. Estimating template: the code is the part in A63 (runbook 22.7).
  --sheet-material  the material of sheet steel picked by gauge (default CR4; e.g. ZINTEC, Galvanised)
"""
import argparse
import csv
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from openpyxl import Workbook, load_workbook

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "migration" / "rebuild"))
from common import add_sheet, notes, product_code, write_load, x3_text  # noqa: E402

BOM_HEAD = ["ITMREF", "BOMALT", "USESTA", "BOHSTRDAT", "BOHENDDAT", "BASQTY", "QTYCOD", "BOMSEQ", "CPNITMREF",
            "CPNTYP", "LIKQTY"]
BOM_TITLES = ["Parent Product", "BOM Code", "Use Status", "Valid from", "Valid to", "Base Quantity",
              "Management Unit", "Sequence", "Component", "Component Type", "Link Quantity"]
ROU_H1 = ["ROUTING"] * 6 + ["ROUOPE"] * 5
ROU_H2 = ["ITMREF", "ROUALT", "FCY", "USESTA", "TIMUOMCOD", "WORTYP", "OPENUM", "WST", "ROODES", "SETTIM", "OPETIM"]
ROU_H3 = ["Routing", "Routing Code", "Site", "Use Status", "Time Unit", "Work Order Management Mode", "Operation",
          "Main Work Centre", "Operation Description", "Setup Time", "Run Time"]
ITM_H1 = ["ITMMASTER"] * 12 + ["ITMSALES"]
ITM_H2 = ["TCLCOD", "ITMREF", "ITMDES1", "ITMDES2", "ITMDES3", "STU", "PUU", "PUUSTUCOE", "SAU", "SAUSTUCOE",
          "WEU", "ITMWEI", "BASPRI"]
ITM_H3 = ["Category", "Product", "Description", "Description 2", "Description 3", "Stock unit", "Purchase Unit",
          "PUR-STK Conversion", "Sales Unit", "SAL-STK Conversion", "Weight Unit", "Item Weight", "Base Price"]
PLACEHOLDER = re.compile(r"(?i)^description of labour \d+$")


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def clean(v, places=6):
    f = round(num(v), places)
    return int(f) if f.is_integer() else f


def open_estimate(path):
    path = Path(path)
    if path.suffix.lower() == ".xls":                       # old Excel: convert with LibreOffice, values kept
        tmp = Path(tempfile.mkdtemp())
        subprocess.run(["soffice", "--headless", "--convert-to", "xlsx", "--outdir", str(tmp), str(path)],
                       check=True, capture_output=True, timeout=180)
        path = tmp / (path.stem + ".xlsx")
    wb = load_workbook(path, data_only=True)
    return wb["Estimate"]


def x3_products(path):
    ws = load_workbook(path, read_only=True)["Data with Headings"]
    return {str(r[1]).strip(): (r[0], r[2] or "") for r in ws.iter_rows(min_row=4, values_only=True) if r and r[1]}


def x3_work_centres():
    with open(HERE.parent / "migration" / "rebuild" / "work_centres.csv") as f:
        rows = [r for r in csv.DictReader(f) if r["x3_work_centre"] != "x3_work_centre"]
    return {r["x3_work_centre"].strip() for r in rows if r["x3_work_centre"].strip()}


def access_work_centres():
    """Access department (as the estimate's Dept. column) -> X3 work centre, the migration's own map."""
    with open(HERE.parent / "migration" / "rebuild" / "work_centres.csv") as f:
        return {r["access_work_centre"].strip(): r["x3_work_centre"].strip() for r in csv.DictReader(f)
                if r["x3_work_centre"].strip() and r["x3_work_centre"] != "x3_work_centre"}


def sheet_index(path):
    """(sheet length, width, gauge) -> [(X3 code, material)] from Description 2 / 3, e.g. '2500 x 1250 x 1.2mm CR4'."""
    ws = load_workbook(path, read_only=True)["Data with Headings"]
    idx, rows = {}, ws.iter_rows(values_only=True)
    h2 = next(r for r in rows if r and "ITMREF" in r)                    # the X3 field-name row
    ref, des = h2.index("ITMREF"), (h2.index("ITMDES2"), h2.index("ITMDES3"))
    for r in rows:
        if r and str(r[ref] or "").startswith("SHEETMETAL"):
            m = re.search(r"(\d+)\s*[xX]\s*(\d+)\s*(?:mm)?\s*[xX]\s*([\d.]+)\s*(?:mm)?\s*(.*)", " ".join(str(r[i] or "") for i in des))
            if m:
                idx.setdefault((int(m[1]), int(m[2]), float(m[3])), []).append((str(r[ref]), m[4].strip(" -") or "?"))
    return idx


def read_template(ws, sheets, wcmap, material="CR4"):
    """The estimating template as used today. Same blocks one column to the left, no X3 columns."""
    v = lambda a: ws[a].value
    drawing = str(v("D5") or "").strip()
    head = dict(drawing=re.sub(r"\s*\(.*\)\s*$", "", drawing), drawing_full=drawing, rev=str(v("G5") or "").strip(),
                description=str(v("D4") or "").strip(), customer=str(v("D3") or "").strip(),
                quantity=v("D6"), unit_cost=v("G6"), material=v("M59"), labour=v("M103"), layout="Estimating template")
    pre, bom = [], []
    for r in range(11, 26):                                  # standard materials: code H, qty per unit K, scrap L
        if v(f"H{r}"):
            bom.append(dict(block="Standard materials", cell=f"H{r}", code=str(v(f"H{r}")).strip(), qty=v(f"K{r}"),
                            scrap=v(f"L{r}"), cost=v(f"M{r}"), note=str(v(f"C{r}") or "")))
        elif v(f"C{r}") and num(v(f"K{r}")) > 0:
            pre.append(["STOP", f"H{r}", f"'{v(f'C{r}')}': no part code", "Standard materials - type the code in H"])
    for r in range(28, 36):                                  # wire: code H (gauge table), kg per unit K
        if num(v(f"E{r}")) > 0:
            bom.append(dict(block="Wire", cell=f"H{r}", code=str(v(f"H{r}") or "").strip(), qty=v(f"K{r}"),
                            scrap=v(f"L{r}"), cost=v(f"M{r}"), note=f"gauge {v(f'F{r}')} x {v(f'G{r}')}mm x {v(f'E{r}')}"))
    for r in range(38, 49):                                  # sheet steel: no code - gauge H, sheet I x J, per sheet K
        if num(v(f"E{r}")) > 0:
            per = num(v(f"K{r}"))
            key = (int(num(v(f"I{r}"))), int(num(v(f"J{r}"))), round(num(v(f"H{r}")), 2))
            cands = sheets.get(key, [])
            pick = [c for c, m in cands if m.upper() == material.upper()]
            note = (f"{v(f'C{r}')}: {v(f'F{r}')} x {v(f'G{r}')}mm from {key[0]} x {key[1]} x {key[2]}mm, "
                    f"{per:g} per sheet")
            if len(pick) == 1:
                pre.append(["INFO", f"H{r}", f"Sheet {key[0]} x {key[1]} x {key[2]}mm {material} -> {pick[0]}",
                            "other materials in X3: " + (", ".join(f"{c} {m}" for c, m in cands if c != pick[0]) or "none")])
            else:
                pre.append(["STOP", f"H{r}", f"Sheet {key[0]} x {key[1]} x {key[2]}mm {material}: "
                            + ("no X3 sheet" if not pick else f"{len(pick)} X3 sheets ({', '.join(pick)})"),
                            "X3 has: " + (", ".join(f"{c} {m}" for c, m in cands) or "nothing that size")])
            bom.append(dict(block="Sheet steel", cell=f"H{r}", code=pick[0] if len(pick) == 1 else "",
                            qty=num(v(f"E{r}")) / per if per else 0, scrap=v(f"L{r}"), cost=v(f"M{r}"), note=note))
    for r in range(51, 59):                                  # other sheet material: no code column
        if num(v(f"D{r}")) > 0:
            txt = str(v(f"C{r}") or "").strip()
            per = num(v(f"J{r}"))
            first = re.split(r"[\s\-]+", txt)[0] if txt else ""
            bom.append(dict(block="Other sheet material", cell=f"C{r}", code=first, qty=num(v(f"D{r}")) / per if per else 0,
                            scrap=v(f"K{r}"), cost=v(f"M{r}"), note=f"{txt}: {v(f'E{r}')} x {v(f'F{r}')}mm, {per:g} per sheet"))
            pre.append(["WARN", f"C{r}", f"Other sheet material: code taken from the description ('{first}')",
                        "the template has no code column for this block - check it"])
    ops, parent = [], ""
    for r in range(63, 103):                                 # labour: type C, text D, Access dept G, qty H, rate/h I, set-up L
        parent = parent or str(v(f"A{r}") or "").strip()
        if v(f"C{r}") and num(v(f"H{r}")) > 0 and num(v(f"I{r}")) > 0:
            dept = str(v(f"G{r}") or "").strip()
            ops.append(dict(cell=f"G{r}", parent="", labour=str(v(f"C{r}")).strip(), text=str(v(f"D{r}") or "").strip(),
                            wc=wcmap.get(dept, ""), dept=dept, run=60 / num(v(f"I{r}")) * num(v(f"H{r}")),
                            setup=num(v(f"L{r}")), seq=None))
    head["labour_parent"] = parent
    return head, bom, ops, pre


def read(ws):
    """The yellow cells, block by block. Returns header, BOM lines and operations, each with its cell."""
    v = lambda a: ws[a].value
    head = dict(drawing=str(v("E5") or "").strip(), rev=str(v("H5") or "").strip(),
                description=str(v("E4") or "").strip(), customer=str(v("E3") or "").strip(),
                quantity=v("E6"), unit_cost=v("H6"), material=v("N59"), labour=v("N103"), layout="IMPORT")
    bom = []
    for r in range(11, 26):                                  # standard materials: code I, link qty L
        if v(f"I{r}"):
            bom.append(dict(block="Standard materials", cell=f"I{r}", code=str(v(f"I{r}")).strip(),
                            qty=v(f"L{r}"), scrap=v(f"M{r}"), cost=v(f"N{r}")))
    for r in range(28, 36):                                  # wire: code B (from the gauge table), link qty C
        if num(v(f"F{r}")) > 0:
            bom.append(dict(block="Wire", cell=f"B{r}", code=str(v(f"B{r}") or "").strip(), qty=v(f"C{r}"),
                            scrap=v(f"M{r}"), cost=v(f"N{r}"), note=f"gauge {v(f'G{r}')} x {v(f'H{r}')}mm x {v(f'F{r}')}"))
    for r in range(38, 49):                                  # sheet steel: code B, link qty C (sheets per unit)
        if v(f"B{r}") and num(v(f"F{r}")) > 0:
            bom.append(dict(block="Sheet steel", cell=f"B{r}", code=str(v(f"B{r}")).strip(), qty=v(f"C{r}"),
                            scrap=v(f"M{r}"), cost=v(f"N{r}"),
                            note=f"{v(f'G{r}')} x {v(f'H{r}')}mm, gauge {v(f'I{r}')}, {v(f'L{r}')} per sheet"))
    for r in range(51, 59):                                  # other sheet material: code B, link qty C
        if v(f"B{r}") and num(v(f"E{r}")) > 0:
            bom.append(dict(block="Other sheet material", cell=f"B{r}", code=str(v(f"B{r}")).strip(), qty=v(f"C{r}"),
                            scrap=v(f"L{r}"), cost=v(f"N{r}"),
                            note=f"{v(f'F{r}')} x {v(f'G{r}')}mm, {v(f'K{r}')} per sheet"))
    ops = []
    for r in range(63, 101):                                 # labour: parent C, type D, text E, X3 WC R, run Q, set-up M
        if v(f"D{r}") and num(v(f"I{r}")) > 0 and num(v(f"J{r}")) > 0:
            text = str(v(f"E{r}") or "").strip()
            ops.append(dict(cell=f"R{r}", parent=str(v(f"C{r}") or "").strip(), labour=str(v(f"D{r}")).strip(),
                            text=text if text and not PLACEHOLDER.match(text) else "", wc=str(v(f"R{r}") or "").strip(),
                            dept=str(v(f"H{r}") or "").strip(), run=v(f"Q{r}"), setup=v(f"M{r}"), seq=v(f"S{r}")))
    return head, bom, ops, []


def build(est_path, out_dir, products_path, parent=None, category="FGML", rev_in_code=False, sheet_material="CR4"):
    ws = open_estimate(est_path)
    prods, wcs = x3_products(products_path), x3_work_centres()
    if str(ws["H10"].value or "").strip().lower() == "part code":         # the estimating template as used today
        head, bom, ops, pre = read_template(ws, sheet_index(products_path), access_work_centres(), sheet_material)
        base = head["labour_parent"] or head["drawing"]
    else:                                                                # Dave's IMPORT layout
        head, bom, ops, pre = read(ws)
        base = head["drawing"] + (head["rev"] if rev_in_code else "")
    code = product_code(parent or base)                                  # the migration's code rule
    if not code:
        raise SystemExit("No parent code: no part code in the estimate and --parent was not given")
    checks, stop = [], 0

    def check(level, where, what, detail=""):
        nonlocal stop
        stop += level == "STOP"
        checks.append([level, where, what, detail])

    for c in pre:
        check(*c)
    if head["layout"] != "IMPORT":
        check("INFO", "A63 / D5", f"Parent = the part code in the labour block ({head['labour_parent'] or '(blank)'})",
              f"drawing {head['drawing_full']} rev {head['rev']} goes in Description 2 if the product is new")
    exists = code in prods
    check("INFO", "E5 / H5" if head["layout"] == "IMPORT" else "A63", f"Parent {code}" + (f" ({head['rev']})" if head["rev"] else ""),
          f"already in X3 as {prods[code][0]} - '{prods[code][1]}': BOM / route will be added to it" if exists
          else f"new product, category {category}")
    labour_parents = {o["parent"] for o in ops if o["parent"]}
    if labour_parents - {code}:
        check("WARN", "Labour C63:C100", f"Labour lines name parent {', '.join(sorted(labour_parents))}",
              f"the files use {code} (E5" + (" / --parent" if parent else "") + ")")

    bom_rows, seq = [], 0
    for b in bom:
        raw, b["code"] = b["code"], product_code(b["code"])     # Access-style code -> X3 code (spaces, & ...)
        if raw != b["code"]:
            check("INFO", b["cell"], f"{raw} -> {b['code']}", "X3 code rule, as in the migration")
        if not b["code"]:
            if b["block"] != "Sheet steel":                       # sheet steel already has its own STOP
                check("STOP", b["cell"], f"{b['block']}: no part code", b.get("note", ""))
            continue
        qty = num(b["qty"])
        p = prods.get(b["code"])
        if qty <= 0:
            check("STOP", b["cell"], f"{b['code']}: no link quantity", b["block"])
            continue
        if not p:
            check("STOP", b["cell"], f"{b['code']}: not a product in X3", f"{b['block']} - the code must exist "
                  "before the BOM loads (or be added to this estimate's product file)")
        elif re.search(r"(?i)don'?t use|do not use", str(p[1])):
            check("WARN", b["cell"], f"{b['code']}: X3 description says '{p[1]}'", b["block"])
        if num(b.get("scrap")):
            check("INFO", b["cell"], f"{b['code']}: scrap {num(b['scrap']):.0%} not carried",
                  "the X3 BOM template has no scrap column - link quantity loads without it")
        same = next((r for r in bom_rows if r[8] == b["code"]), None)
        if same:                                               # one line per component, as Access holds it
            same[10] = clean(num(same[10]) + qty)
            check("INFO", b["cell"], f"{b['code']} appears again: quantities added", f"now {same[10]} per unit")
            continue
        seq += 10
        bom_rows.append([code, 10, 2, None, None, 1, 1, seq, b["code"], 1, clean(qty)])

    rou_rows, n = [], 0
    for o in ops:
        if o["wc"] not in wcs:
            check("STOP", o["cell"], f"{o['labour']}: work centre '{o['wc'] or '(blank)'}'"
                  + (f" (Access dept {o['dept']})" if head["layout"] != "IMPORT" else "") + " is not an X3 work centre",
                  "map it in work_centres.csv (OVEN has no X3 work centre yet)")
            continue
        if not o["text"]:
            check("INFO", o["cell"].replace("R", "E"), f"{o['labour']}: no operation description",
                  "the labour type is used instead")
        n += 5
        rou_rows.append([code, 10, "S01A", 1, 2, 4, n, o["wc"], x3_text(o["text"] or o["labour"])[:30].rstrip(),
                         clean(o["setup"], 4), clean(o["run"], 4)])
    if len(rou_rows) > 150:
        check("STOP", "Labour", f"{len(rou_rows)} operations", "X3 holds 150 per route")

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^\w\-]+", "_", code)
    files = []
    if not exists:
        wb = Workbook()
        s = wb.active
        s.title = "Data with Headings"
        for h in (ITM_H1, ITM_H2, ITM_H3):
            s.append(h)
        desc = x3_text(head["description"] or code)[:30].rstrip()
        s.append([category, code, desc, f"Rev {head['rev']}" if head["rev"] and not rev_in_code else None, desc,
                  "EA", "EA", 1, "EA", 1, "KG", 0, 0])
        notes(wb, [[f"ZSDIITM - parent product from estimate {Path(est_path).name}"], [],
                   ["Rule", ("Code = SDI drawing number (E5)" if head["layout"] == "IMPORT" else "Code = the part code in A63")
                    + "; revision in Description 2; category " + category]], index=0)
        p = out / f"{stem}_ZSDIITM.xlsx"
        wb.save(p)
        files.append((p, write_load(p, "Data with Headings", 4)))
    for name, h, rows, first, sheet in (("YA00408BOM", (BOM_HEAD, BOM_TITLES), bom_rows, 3, "Data with Headings"),
                                        ("ZSDIROU2", (ROU_H1, ROU_H2, ROU_H3), rou_rows, 4, "ZSDROU2")):
        if not rows:
            continue
        wb = Workbook()
        s = wb.active
        s.title = sheet
        for x in h:
            s.append(x)
        for r in rows:
            s.append(r)
        p = out / f"{stem}_{name}.xlsx"
        wb.save(p)
        files.append((p, write_load(p, sheet, first)))

    # the check workbook: what was read, what will load, and every problem
    wb = Workbook()
    wb.remove(wb.active)
    add_sheet(wb, "Checks", ["Level", "Cell", "Check", "Detail"], checks, [8, 14, 60, 80])
    add_sheet(wb, "BOM read", ["Block", "Cell", "Component", "Link qty", "Scrap", "Est. cost", "X3 category",
                               "X3 description", "Note"],
              [[b["block"], b["cell"], b["code"], clean(b["qty"]), b.get("scrap"), round(num(b.get("cost")), 4),
                (prods.get(b["code"]) or ("NOT IN X3", ""))[0], (prods.get(b["code"]) or ("", ""))[1], b.get("note", "")]
               for b in bom], [20, 8, 18, 10, 7, 10, 11, 32, 40])
    add_sheet(wb, "Route read", ["Cell", "Labour", "Dept", "X3 work centre", "Run (min / unit)", "Set-up (min)",
                                 "Description"],
              [[o["cell"], o["labour"], o["dept"], o["wc"], clean(o["run"], 4), clean(o["setup"], 4), o["text"]]
               for o in ops], [8, 26, 8, 14, 14, 12, 30])
    summary = [[f"Estimate {Path(est_path).name} -> X3 import files"], [],
               ["Layout", head["layout"]],
               ["Parent", f"{code} ({'existing' if exists else 'new'}) - drawing {head['drawing']} rev {head['rev']}"],
               ["Estimate", f"quantity {head['quantity']}, unit cost {round(num(head['unit_cost']), 2)} "
                            f"(material {round(num(head['material']), 2)}, labour {round(num(head['labour']), 2)})"],
               ["BOM", f"{len(bom_rows)} lines from {len(bom)} read"], ["Route", f"{len(rou_rows)} operations from {len(ops)} read"],
               ["Result", "READY TO LOAD" if not stop else f"NOT READY - {stop} STOP check(s) on the Checks tab"],
               ["Load order", "ZSDIITM (if new) -> YA00408BOM -> ZSDIROU2, in the TEST folder first"]]
    notes(wb, summary, index=0)
    wb.save(out / f"{stem}_CHECKS.xlsx")
    return dict(code=code, new=not exists, bom=len(bom_rows), ops=len(rou_rows), stop=stop,
                warn=sum(c[0] == "WARN" for c in checks), files=[f[0].name for f in files], checks=checks)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("estimate")
    ap.add_argument("out_dir")
    ap.add_argument("--products", required=True)
    ap.add_argument("--parent")
    ap.add_argument("--category", default="FGML")
    ap.add_argument("--rev-in-code", action="store_true")
    ap.add_argument("--sheet-material", default="CR4")
    a = ap.parse_args()
    res = build(a.estimate, a.out_dir, a.products, a.parent, a.category, a.rev_in_code, a.sheet_material)
    print(f"{res['code']} ({'new' if res['new'] else 'existing'}): BOM {res['bom']} lines, route {res['ops']} ops, "
          f"{res['stop']} stop, {res['warn']} warn -> {', '.join(res['files'])}")
    for c in res["checks"]:
        if c[0] != "INFO":
            print("  ", c[0], c[1], c[2], "-", c[3])
