"""ZSDIITM - the complete product file, built from scratch from extract_products.sql.

Which products go in (runbook 1a and 6.1): every product that is live in Access, whatever its
grade, plus everything the current load rule takes:
  * it holds stock, or is on an open sales, purchase or works order
  * it was sold, bought or made in the last two years (--recent-years)
  * vw_DQ_ITM grades it GOOD or INCOMPLETE (the rule the loaded file was built on)
  * it is a component, at any depth, of a BOM whose parent goes in - so no BOM line is held
    back for a missing component
Every other product Access holds is on the "Not migrated" tab with what it was last doing.
Nothing is left out without a line saying why.

The rest is the runbook's, one copy each in common.py: the product code rule (4.1), Ethan's
character rule (5), a blank first description filled from description 3, then 2, then the code
(6.1), units EA as SDI decided (template guide).

Category: vw_ITM's, except PHANT, which is set by the usage test (runbook 13, item 9) unless
--phant access is given:
  A  on an open sales order, or not used in any migrated BOM      -> FGML (a product in its own right)
  B  used in a migrated BOM, but holds stock or has a works order -> FGML (a made, stocked sub-assembly)
  C  used only in BOMs, nothing on hand or being made, but bought -> PHANT, listed on Check
  D  used only inside migrated BOMs                               -> PHANT
A product vw_ITM does not hold takes vw_ITM's rule on the BOM: parent and component PHANT,
parent only FGML, component only RAWML, neither FGSL.

Usage:
    python products.py <run folder> [--today 20261231] [--phant usage|access] [--recent-years 2]
Reads <run folder>/extract/extract_products.txt, writes <run folder>/out/ZSDIITM_products_MAPPED.xlsx.
"""
import argparse
import datetime as dt
import re
from collections import defaultdict
from pathlib import Path

from openpyxl import load_workbook

from common import add_sheet, clip, ensure_dir, notes, product_codes, read_grids, x3_text

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE / "templates" / "ZSDIITM.xlsx"
MAKE = {"FGML", "PHANT"}
LOADED = {"GOOD", "INCOMPLETE"}           # the grades the loaded file was built on
NUMERIC = {7, 9, 11, 12}                  # PUUSTUCOE, SAUSTUCOE, ITMWEI, BASPRI
MAX_CODE = 20                             # X3's product code length


def val(v):
    """A cell from the extract: SSMS writes a SQL NULL as the word NULL."""
    v = (v or "").strip()
    return "" if v == "NULL" else v


def num(v):
    try:
        return float(val(v) or 0)
    except ValueError:
        return 0.0


def as_cell(v, numeric):
    if numeric:
        f = num(v)
        return int(f) if f.is_integer() else f
    return v if v != "" else None


def load(extract):
    grids, plain = read_grids(extract)
    for need in ("ITEM", "MASTER", "USE", "BOM"):
        if need not in grids:
            raise SystemExit(f"{extract}: no {need} grid - was the whole of extract_products.sql run "
                             f"and saved with Results To File? ({len(plain)} unlabelled grids found)")
    item = defaultdict(list)
    for r in grids["ITEM"]:
        r = [val(x) for x in r] + [""] * 14
        item[r[0]].append(r[:14])
    master = {val(r[0]): [val(x) for x in r] + [""] * 8 for r in grids["MASTER"]}
    use = {val(r[0]): [val(x) for x in r] + [""] * 16 for r in grids["USE"]}
    bom = {(val(r[0]), val(r[1])) for r in grids["BOM"]}
    rate = {val(r[0]): (num(r[2]), num(r[3]), num(r[4]), val(r[1])) for r in grids.get("RATE", [])}
    return item, master, use, bom, rate


def build(run_dir, today=None, phant="usage", recent_years=2):
    run_dir = Path(run_dir)
    today = today or dt.date.today().strftime("%Y%m%d")
    recent = f"{int(today[:4]) - recent_years}{today[4:]}"
    item, master, use, bom_raw, rate = load(run_dir / "extract" / "extract_products.txt")

    # ---- one X3 code per Access code, decided over every code Access holds ----------------
    raw_all = sorted(set(item) | set(master))
    code, shared = product_codes(raw_all)
    raws = defaultdict(list)
    for c in raw_all:
        raws[code[c]].append(c)

    # ---- what each product is doing, summed over the Access codes that become it ----------
    act = {}
    for x, cs in raws.items():
        a = dict(stock_qty=0.0, stock_value=0.0, so=0, po=0, wo=0, last_sale="", last_purchase="",
                 last_made="", part_dnu=0, stock_dnu="", archive="")
        for c in cs:
            u = use.get(c)
            if not u:
                continue
            a["stock_qty"] += num(u[1])
            a["stock_value"] += num(u[2])
            a["so"] += int(num(u[3]))
            a["po"] += int(num(u[4]))
            a["wo"] += int(num(u[5]))
            a["last_sale"] = max(a["last_sale"], u[6])
            a["last_purchase"] = max(a["last_purchase"], u[7])
            a["last_made"] = max(a["last_made"], u[8])
            a["part_dnu"] = max(a["part_dnu"], int(num(u[9])))
            a["stock_dnu"] = max(a["stock_dnu"], u[10])
            a["archive"] = max(a["archive"], u[11])
        grades = [r[13] for c in cs for r in item.get(c, [])] + [master[c][7] for c in cs if c in master]
        a["grade"] = next((g for g in ("GOOD", "INCOMPLETE", "REVIEW", "OLD", "EXCLUDE") if g in grades),
                          grades[0] if grades else "(not graded)")
        act[x] = a

    bom = {(code.get(p, p), code.get(c, c)) for p, c in bom_raw}
    comps, parents = defaultdict(set), defaultdict(set)
    for p, c in bom:
        if p != c:
            comps[p].add(c)
            parents[c].add(p)

    # ---- which products go in, and why ----------------------------------------------------
    why = defaultdict(list)
    for x, a in act.items():
        if a["stock_qty"] > 0:
            why[x].append("holds stock")
        for k, label in (("so", "open sales order"), ("po", "open purchase order"), ("wo", "open works order")):
            if a[k]:
                why[x].append(label)
        for k, label in (("last_sale", "sold"), ("last_purchase", "bought"), ("last_made", "made")):
            if a[k] >= recent:
                why[x].append(f"{label} since {recent}")
        if a["grade"] in LOADED:
            why[x].append(f"graded {a['grade']}")
    todo = list(why)
    while todo:                              # every component of a BOM that goes in, at any depth
        p = todo.pop()
        for c in comps.get(p, ()):
            if c not in act:
                continue                     # not a product Access holds: shows on the BOM file
            if c not in why:
                todo.append(c)
            if not any(w.startswith("component of") for w in why[c]):
                why[c].append(f"component of {p}")

    # ---- one row per product ----------------------------------------------------------------
    def bom_category(x):
        return ("PHANT" if comps.get(x) and parents.get(x) else "FGML" if comps.get(x)
                else "RAWML" if parents.get(x) else "FGSL")

    rows, held, codes_only = {}, [], []
    for x in sorted(why):
        cands = [(c, r) for c in raws[x] for r in item.get(c, [])]
        if cands:
            # a code on two Access products: the made one where the code has a BOM, then the
            # busier one, then the first (runbook 4.1, the 33 shared codes)
            def rank(cr):
                c, r = cr
                u = use.get(c, [""] * 16)
                return (-(r[1] in MAKE and x in comps), -num(u[2]), -(num(u[3]) + num(u[4]) + num(u[5])), c)
            cands.sort(key=rank)
            c, r = cands[0]
            cat = r[1] or bom_category(x)
            d1, d2, d3 = (clip(x3_text(v), 30) for v in r[2:5])
            units = [r[5] or "EA", r[6] or "EA", r[7] or "1", r[8] or "EA", r[9] or "1", r[10] or "KG",
                     r[11] or "0", r[12] or "0"]
            for c2, r2 in cands[1:]:
                held.append([r2[1], x, c2, clip(x3_text(r2[2]), 30),
                             f"Access code {c2} becomes {x}, the same code as {c} - X3 keeps one product per code"])
        else:
            c = raws[x][0]
            m = master[c]
            cat = bom_category(x)
            d1, d2, d3 = clip(x3_text(m[3] or m[4]), 30), "", clip(x3_text(m[5]), 30)
            units = ["EA", "EA", "1", "EA", "1", "KG", "0", "0"]
            for c2 in raws[x][1:]:
                held.append(["", x, c2, "", f"Access code {c2} becomes {x}, the same code as {c} - X3 keeps one product per code"])
        if not d1:
            d1 = d3 or d2 or x[:30]
        if re.sub(r"[^A-Z0-9]", "", d1.upper()) == re.sub(r"[^A-Z0-9]", "", x) and d3 and d3 != d1:
            codes_only.append([x, d1, d3])
        rows[x] = [cat, x, d1, d2, d3] + units

    # ---- PHANT: the usage test --------------------------------------------------------------
    phant_rows = []
    for x, r in rows.items():
        if r[0] != "PHANT":
            continue
        a = act[x]
        used_in = sorted(p for p in parents.get(x, ()) if p in rows)
        if a["so"] or not used_in:
            g, new = "A", "FGML"
        elif a["stock_qty"] > 0 or a["wo"]:
            g, new = "B", "FGML"
        elif a["po"] or a["last_purchase"]:
            g, new = "C", "PHANT"
        else:
            g, new = "D", "PHANT"
        if phant == "usage":
            r[0] = new
        phant_rows.append([x, r[2], g, "PHANT", r[0], len(used_in), ", ".join(used_in[:4]), len(comps.get(x, ())),
                           a["so"], a["wo"], round(a["stock_value"], 2), a["last_purchase"]])

    # ---- the checks: stop on anything that would be a silent drop ---------------------------
    live = [x for x, a in act.items() if a["stock_qty"] > 0 or a["so"] or a["po"] or a["wo"]]
    missing = [x for x in live if x not in rows]
    assert not missing, f"live products left out: {missing[:10]}"
    gaps = [(p, c) for p in rows for c in comps.get(p, ()) if c in act and c not in rows]
    assert not gaps, f"BOM components left out: {gaps[:10]}"
    assert len(rows) == len({r[1] for r in rows.values()})

    check = []
    for x, r in rows.items():
        a = act[x]
        busy = a["stock_qty"] > 0 or a["so"] or a["po"] or a["wo"]
        if a["grade"] not in LOADED:
            check.append([x, r[2], r[0], a["grade"], "; ".join(why[x]),
                          f"graded {a['grade']} by vw_DQ_ITM but live - goes in (rule 1a); the grade ignores stock and purchases"])
        if a["part_dnu"] or a["stock_dnu"] not in ("", "0", "N", "False"):
            check.append([x, r[2], r[0], a["grade"], "; ".join(why[x]),
                          "marked do-not-use in Access" + (" but holds stock or is on an open order" if busy else "")])
        if len(x) > MAX_CODE:
            check.append([x, r[2], r[0], a["grade"], "; ".join(why[x]), f"code longer than {MAX_CODE} characters"])
    for p in phant_rows:
        if p[2] == "C":
            check.append([p[0], p[1], p[4], act[p[0]]["grade"], "; ".join(why[p[0]]),
                          "PHANT test C: used only inside BOMs but bought in - RAWML or FGSL rather than PHANT? (Marc / Ethan)"])

    not_migrated = []
    for x in sorted(set(act) - set(rows)):
        a = act[x]
        c = raws[x][0]
        d = item[c][0][2] if item.get(c) else (master.get(c, [""] * 8)[3] or master.get(c, [""] * 8)[5])
        not_migrated.append([x, ", ".join(raws[x]), clip(x3_text(d), 30), a["grade"], a["last_sale"] or "never",
                             a["last_purchase"] or "never", a["last_made"] or "never",
                             "no stock, no open order, nothing sold, bought or made since " + recent
                             + ", not in a migrated BOM, and not graded GOOD or INCOMPLETE"])

    # ---- the workbook -----------------------------------------------------------------------
    out = ensure_dir(run_dir / "out") / "ZSDIITM_products_MAPPED.xlsx"
    data = [rows[x] for x in sorted(rows)]
    wb = load_workbook(TEMPLATE)
    ws = wb["Data with Headings"]
    if ws.max_row >= 4:
        ws.delete_rows(4, ws.max_row)
    for r in data:
        ws.append([as_cell(v, i in NUMERIC) for i, v in enumerate(r)])
    ws.freeze_panes = "A4"

    reason_head = ["Product", "Access code(s)", "Description", "Category", "Why it goes in", "Grade (vw_DQ_ITM)",
                   "Stock qty", "Stock value GBP", "Open SO lines", "Open PO lines", "Open works orders",
                   "Last sale", "Last purchase", "Last works order"]
    reasons = [[x, ", ".join(raws[x]), rows[x][2], rows[x][0], "; ".join(why[x]), act[x]["grade"],
                round(act[x]["stock_qty"], 4), round(act[x]["stock_value"], 2), act[x]["so"], act[x]["po"],
                act[x]["wo"], act[x]["last_sale"], act[x]["last_purchase"], act[x]["last_made"]] for x in sorted(rows)]
    add_sheet(wb, "Why it goes in", reason_head, reasons, [20, 20, 32, 9, 50, 12, 10, 12, 8, 8, 8, 10, 10, 10])
    add_sheet(wb, "Check", ["Product", "Description", "Category", "Grade", "Why it goes in", "To check"], check,
              [20, 32, 9, 12, 40, 90])
    add_sheet(wb, "PHANT test", ["Product", "Description", "Group", "vw_ITM category", "Category in this file",
                                 "Used in migrated BOMs", "Parents (first few)", "Own BOM components",
                                 "Open SO lines", "Open works orders", "Stock value GBP", "Last purchase"],
              phant_rows, [20, 32, 7, 10, 10, 9, 40, 9, 8, 8, 12, 10])
    add_sheet(wb, "Held back", ["Category", "Product", "Access code", "Description", "Why"], held, [9, 20, 20, 32, 90])
    add_sheet(wb, "Description is the code", ["Product", "Description 1", "Description 3"], codes_only, [20, 32, 32])
    add_sheet(wb, "Not migrated", ["Product", "Access code(s)", "Description", "Grade", "Last sale", "Last purchase",
                                   "Last works order", "Why not"], not_migrated, [20, 20, 32, 12, 10, 10, 10, 90])

    count = lambda k: sum(1 for x in rows if k in " ".join(why[x]))
    cats = defaultdict(int)
    for r in data:
        cats[r[0]] += 1
    groups = defaultdict(int)
    for p in phant_rows:
        groups[p[2]] += 1
    notes(wb, [
        ["ZSDIITM - products, complete file"], [],
        ["Built", f"{dt.date.today():%d %b %Y} by rebuild/products.py from extract_products.sql. A complete file, "
                  "built from scratch - load it as the product file, not as a top-up (runbook 1b)"],
        ["Products", f"{len(data):,}: " + ", ".join(f"{k} {v:,}" for k, v in sorted(cats.items()))],
        ["Why they go in", f"holding stock {count('holds stock'):,}; on an open order {count('open '):,}; "
                           f"sold, bought or made since {recent} {count(' since '):,}; graded GOOD or INCOMPLETE "
                           f"{count('graded '):,}; BOM components {count('component of'):,}. A product can have several "
                           "reasons - the 'Why it goes in' tab has each one"],
        ["Rule", "Every live product goes in, whatever its grade (runbook 1a). vw_DQ_ITM ignores stock and purchases, "
                 "so live products it grades OLD are in, and listed on Check"],
        ["PHANT", ("usage test applied: " if phant == "usage" else "vw_ITM's category kept (--phant access): ")
                  + ", ".join(f"{k} {v:,}" for k, v in sorted(groups.items()))
                  + ". A and B become FGML; C (bought in) is on Check; D stays PHANT"],
        ["Codes", "Upper case, letters, numbers and hyphens only - the same codes in every other file"],
        ["Descriptions", "Ethan's character rule, within 30 characters. A blank first description takes description 3, "
                         f"then 2, then the code. {len(codes_only):,} products have the code as description 1 and the "
                         "text in description 3 - listed, not changed"],
        ["Units", "EA, conversion 1, as the template's guide records SDI's decision"],
        ["Held back", f"{len(held):,} Access products whose code becomes the same X3 code as another - X3 keeps one"],
        ["Not migrated", f"{len(not_migrated):,} Access products that are not live - each with its last activity"],
        ["Check", f"{len(check):,} lines for SDI to look at - none stops the load"],
    ], index=0)
    wb.save(out)

    # read back: what was saved is what was built
    got = [r for r in load_workbook(out, read_only=True)["Data with Headings"].iter_rows(min_row=4, values_only=True)
           if any(v is not None for v in r)]
    assert len(got) == len(data), (len(got), len(data))
    for g, r in zip(got, data):
        for i, v in enumerate(r):
            gv = g[i] if i < len(g) else None
            assert (num(v) == float(gv or 0)) if i in NUMERIC else ((gv or "") == v), (r, g)

    summary = dict(products=len(data), categories=dict(cats), held=len(held), check=len(check),
                   not_migrated=len(not_migrated), phant=dict(groups), rates=rate, shared=len(shared))
    return out, summary, rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("run_dir")
    ap.add_argument("--today", help="the run's date, yyyymmdd (default today)")
    ap.add_argument("--phant", choices=("usage", "access"), default="usage")
    ap.add_argument("--recent-years", type=int, default=2)
    a = ap.parse_args()
    out, summary, _ = build(a.run_dir, a.today, a.phant, a.recent_years)
    print(out)
    for k, v in summary.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
