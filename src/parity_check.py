#!/usr/bin/env python3
"""
parity_check.py  —  SDI estimating-engine parity harness
=========================================================
Compare one engine JSON against its manual estimate workbook (.xls), print a parity
report, and append one row to a running ledger so patterns across the week's jobs surface.

Usage (from C:\\ClaudeVision\\src, in your venv):
    python parity_check.py  <engine.json>  <manual.xls>  [--ledger parity_ledger.csv]

The point: turn each parity from a 30-min hand analysis into a 2-min structured report,
and build a ledger that is both your go-live evidence and the corpus for the RAG layer.
Needs xlrd  (pip install xlrd  — v2 still reads .xls, which is what these manuals are).
"""
import sys, os, re, json, csv, argparse, datetime
import xlrd  # .xls reader

PN_RE = re.compile(r"\b\d{4,5}-\d{2}-[A-Z0-9.]+", re.IGNORECASE)

# Category cues for bucketing manual material lines the engine fails to capture.
CATEGORY_CUES = [
    ("packing",  ("PALLET", "BOX TOP", "BOX METAL", "PACK", "CARRIAGE", "COMPLEAT", "CRATE")),
    ("tube",     ("TUBE", " RHS", " SHS", "BOX SECTION", "SECTION ", "ANGLE ", "CHANNEL TUBE")),
    ("edging",   ("EDGING", "EDGE BAND", "ABS EDG", "HRANIPEX")),
    ("powder",   ("POWDER", "P.COAT", "POWDERCOAT", "TIGER COAT")),
    ("board",    ("MFC", "MFMDF", "MELAMINE", "PRE LAM", "VENEER", "EGGER", "MDF")),
    ("fixings",  ("SCREW", "BOLT", "INSERT", "DOWEL", " NUT", "ALLEN", "FIXING", "FOOT",
                  "GLIDE", "MINI FIX", "MINIFIX", "HANK", "BUSH", "RIVET", "STICKER", "WELD NUT")),
]

def _cat(desc, supplier):
    blob = f"{desc} {supplier}".upper()
    for name, cues in CATEGORY_CUES:
        if any(c in blob for c in cues):
            return name
    return "other"

def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

# ----------------------------------------------------------------------------- manual
def parse_manual_xls(path):
    """SDI house template: the Estimate sheet carries explicit 'Total Material Cost' and
    'Total Labour Cost' cells (col 12) — read those directly rather than re-summing across
    the five differently-shaped sections. Line items for the lane analysis come from the
    'Standard Materials' block (rows between its header and the 'Wire'/'Sheet Steel'
    section), which is where every bought-in / consumable / packing item lives."""
    wb = xlrd.open_workbook(path)
    out = {"headline": {}, "material_lines": [], "material_total": 0.0,
           "labour_total": 0.0, "sheet_names": wb.sheet_names()}
    est = None
    for nm in wb.sheet_names():
        if nm.strip().upper() == "ESTIMATE":
            est = wb.sheet_by_name(nm); break
    if est is None:
        est = wb.sheet_by_index(0)

    def c(r, col):
        return est.cell_value(r, col) if est.ncols > col else ""
    def c2u(r):
        return str(c(r, 2)).strip().upper()

    bom_header = next_section = total_mat_row = None
    for r in range(est.nrows):
        lab = c2u(r)
        if lab == "QUANTITY":
            out["headline"]["quantity"] = _f(c(r, 3))
            if str(c(r, 5)).strip().upper() == "UNIT COST":
                out["headline"]["unit_cost"] = _f(c(r, 6))
        elif lab == "DRAWING NO.":
            out["headline"]["drawing"] = c(r, 3); out["headline"]["rev"] = c(r, 6)
        elif lab == "DESCRIPTION" and "description" not in out["headline"]:
            out["headline"]["description"] = c(r, 3)
        elif lab == "BILL OF MATERIALS (PER UNIT)" and bom_header is None:
            bom_header = r
        elif lab in ("WIRE", "SHEET STEEL") and bom_header is not None and next_section is None:
            next_section = r
        elif lab == "TOTAL MATERIAL COST":
            out["material_total"] = round(_f(c(r, 12)) or 0.0, 2); total_mat_row = r
        elif lab.startswith("TOTAL LABOUR COST"):   # real label: 'Total Labour Cost (Including  Downtime)'
            out["labour_total"] = round(_f(c(r, 12)) or 0.0, 2)

    # Standard Materials line items (bought-in / consumables / packing / board / tube)
    if bom_header is not None:
        end = next_section or total_mat_row or est.nrows
        for r in range(bom_header + 1, end):
            desc = str(c(r, 2)).strip()
            total = _f(c(r, 12))
            if total is None:                      # header / sub-header / text row
                continue
            if not desc:
                desc = str(c(r, 1)).strip()
            if not desc and not total:             # padding row
                continue
            if c2u(r) in ("STANDARD MATERIALS", "WIRE", "SHEET STEEL",
                          "OTHER SHEET MATERIAL", "BILL OF MATERIALS (PER UNIT)"):
                continue
            code = str(c(r, 7)).strip()
            if not code:
                c1 = str(c(r, 1)).strip()
                if c1 and c1 != desc and not _f(c1):
                    code = c1
            supp = str(c(r, 8)).strip()
            pn = PN_RE.search(f"{code} {desc}")
            out["material_lines"].append({
                "desc": desc, "code": code, "supplier": supp,
                "price": _f(c(r, 9)), "qty": _f(c(r, 10)), "total": total,
                "part_number": pn.group(0).upper() if pn else None,
                "category": _cat(desc, supp),
            })
    return out

# ----------------------------------------------------------------------------- engine
def parse_engine_json(path):
    d = json.load(open(path, encoding="utf-8"))
    es = d.get("estimate_summary", {})
    parts = []
    mat_tot = lab_tot = 0.0
    for e in es.get("part_estimates", []):
        q = e.get("quantity") or 1
        me = e.get("material_estimate") or {}
        le = e.get("labour_estimate") or {}
        mat = me.get("extended_material_cost_gbp")
        if mat is None:
            mat = (me.get("cost_per_part_gbp") or 0) * q
        lab = (le.get("total_labour_cost_gbp") or 0) * q
        pn = str(e.get("part_number") or "").upper()
        parts.append({"pn": pn, "material": e.get("normalized_material"),
                      "cost_method": me.get("cost_method"), "mat": mat or 0.0, "lab": lab or 0.0, "qty": q})
        mat_tot += mat or 0.0
        lab_tot += lab or 0.0
    return {
        "doc_total": es.get("document_total_estimated_cost_gbp") or es.get("document_total_provisional_gbp"),
        "estimate_status": es.get("estimate_status"),
        "parts": parts,
        "material_total": round(mat_tot, 2),
        "labour_total": round(lab_tot, 2),
        "part_index": {p["pn"]: p for p in parts},
    }

# ----------------------------------------------------------------------------- report
def build_report(manual, engine, job):
    L = []
    h = manual["headline"]
    L.append(f"PARITY  —  {job}")
    L.append(f"  {h.get('description','')}  |  {h.get('drawing','')} Rev {h.get('rev','')}  |  qty {h.get('quantity')}")
    L.append("")
    mm, ml = manual["material_total"], manual["labour_total"]
    em, el = engine["material_total"], engine["labour_total"]
    def delta(a, b):
        d = (a - b)
        p = (d / b * 100) if b else float('nan')
        return f"{d:+.2f}  ({p:+.0f}%)"
    L.append(f"  MATERIAL   manual £{mm:>8.2f}   engine £{em:>8.2f}   Δ {delta(em, mm)}")
    L.append(f"  LABOUR     manual £{ml:>8.2f}   engine £{el:>8.2f}   Δ {delta(el, ml)}")
    L.append(f"  UNIT(man)  £{h.get('unit_cost') or 0:>8.2f}   engine doc-total £{engine['doc_total']}   status: {engine['estimate_status']}")
    L.append("")

    # engine-missing material, bucketed by category (the actionable lane view)
    eng_pns = set(engine["part_index"].keys())
    missing = {}
    matched_pairs = []
    for ln in manual["material_lines"]:
        pn = ln["part_number"]
        ep = engine["part_index"].get(pn) if pn else None
        if ep and ep["mat"] >= (ln["total"] or 0) * 0.5:
            matched_pairs.append((ln, ep))           # engine captured it at a comparable figure
        elif ep:
            # engine has the part but priced it well under the manual (e.g. tube as sheet)
            missing.setdefault(ln["category"], []).append((ln, ep["mat"]))
            matched_pairs.append((ln, ep))
        else:
            missing.setdefault(ln["category"], []).append((ln, 0.0))
    L.append("  ENGINE-MISSING / UNDER-CAPTURED MATERIAL  (manual £ the engine isn't booking):")
    cat_tot = {}
    for cat, items in sorted(missing.items(), key=lambda kv: -sum((l['total'] or 0) - e for l, e in kv[1])):
        gap = sum((l["total"] or 0) - e for l, e in items)
        cat_tot[cat] = round(gap, 2)
        L.append(f"      {cat:9} £{gap:>7.2f}   ({len(items)} line(s))")
    L.append(f"      {'TOTAL':9} £{sum(cat_tot.values()):>7.2f}")
    L.append("")

    # biggest per-part material deltas where aligned
    deltas = sorted(((ln, em_) for ln, em_ in [(l, e["mat"]) for l, e in matched_pairs]),
                    key=lambda t: -abs((t[0]["total"] or 0) - t[1]))[:6]
    if deltas:
        L.append("  TOP PER-PART MATERIAL DELTAS (matched lines):")
        for ln, emv in deltas:
            L.append(f"      {ln['part_number'] or ln['desc'][:28]:<28} manual £{ln['total'] or 0:>7.2f}  engine £{emv:>7.2f}  Δ {emv-(ln['total'] or 0):+.2f}")
    return "\n".join(L), cat_tot

def ledger_row(job, manual, engine, cat_tot):
    h = manual["headline"]
    return {
        "job": job, "date": datetime.date.today().isoformat(),
        "qty": h.get("quantity"), "drawing": h.get("drawing"), "rev": h.get("rev"),
        "manual_material": manual["material_total"], "manual_labour": manual["labour_total"],
        "manual_unit": h.get("unit_cost"),
        "engine_material": engine["material_total"], "engine_labour": engine["labour_total"],
        "engine_doc_total": engine["doc_total"], "engine_status": engine["estimate_status"],
        "miss_packing": cat_tot.get("packing", 0), "miss_tube": cat_tot.get("tube", 0),
        "miss_board": cat_tot.get("board", 0), "miss_fixings": cat_tot.get("fixings", 0),
        "miss_edging": cat_tot.get("edging", 0), "miss_powder": cat_tot.get("powder", 0),
        "miss_other": cat_tot.get("other", 0),
    }

def append_ledger(path, row):
    new = not os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        if new:
            w.writeheader()
        w.writerow(row)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("engine_json")
    ap.add_argument("manual_xls")
    ap.add_argument("--ledger", default="parity_ledger.csv")
    ap.add_argument("--job", default=None)
    a = ap.parse_args()
    job = a.job or os.path.splitext(os.path.basename(a.engine_json))[0]
    manual = parse_manual_xls(a.manual_xls)
    engine = parse_engine_json(a.engine_json)
    report, cat_tot = build_report(manual, engine, job)
    print(report)
    append_ledger(a.ledger, ledger_row(job, manual, engine, cat_tot))
    print(f"\n  -> ledger row appended to {a.ledger}")

if __name__ == "__main__":
    main()
