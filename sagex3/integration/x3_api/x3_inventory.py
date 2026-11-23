"""What's in a Sage X3 environment - every data set Live Orders reads, plus works-order headers / operations and work
centres - counted and checked, side by side for SDI Mig and We are SDI. READ ONLY: the same lean field lists and
paging as the Live Orders pull (x3_api.NODES / LEAN), never every field.

23 Nov (James): "an extract from Sage SDI Mig to check across all the data sets to see what's in there". Ethan says
works, purchase and sales orders are in Sage, but SDI Mig's Live Orders pull got no works orders and no stock.

    python x3_inventory.py                  # both environments (about 5-10 minutes)
    python x3_inventory.py --env mig        # one environment
    python x3_inventory.py --limit 200      # quick try: the first 200 rows of each

Prints the summary and writes  SDI_X3_inventory_<date>_<time>.xlsx  (Summary, Checks, one tab per data set and
environment) to your Downloads folder, or --out. The workbook holds business data: never in git or email."""
import argparse
import collections
import datetime as dt
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import x3_api  # noqa: E402

# the record key of each data set, to tell a repeated record (our read or X3) from two genuine lines
KEYS = {
    "works_orders": ["number"],
    "wo_products": ["workOrder.number", "lineNumber"],
    "so_lines": ["salesOrder.id", "lineNumber"],
    "po_lines": ["purchaseOrder.id", "lineNumber"],
    "products": ["code"],
    "work_centres": ["code"],
}
STATUS = re.compile(r"status|isClosed|isManufactured|isPurchased", re.I)
DATE = re.compile(r"date$|Date$|_createStamp", re.I)


def pull_env(c, env, limit, log):
    out = {}
    ce = x3_api.for_env(c, env)
    for n, path in x3_api.NODES.items():
        if n not in x3_api.LEAN:
            continue
        t0, notes = time.time(), []
        try:
            rows = x3_api.pull_graphql(ce, {"path": path, "fields": x3_api.LEAN[n]}, limit=limit, notes=notes)
            out[n] = dict(rows=rows, seconds=round(time.time() - t0, 1), notes=notes, error="")
            log(f"  {n}: {len(rows)} rows ({out[n]['seconds']} s)" + (f" - {'; '.join(notes)}" if notes else ""))
        except x3_api.X3Unavailable as e:
            out[n] = dict(rows=[], seconds=0, notes=[], error=f"X3 not answering: {e}")
            log(f"  {n}: X3 not answering - stopping {x3_api.ENVS[env]['label']}")
            break
        except (SystemExit, Exception) as e:  # noqa: BLE001 - one data set failing never stops the rest
            out[n] = dict(rows=[], seconds=round(time.time() - t0, 1), notes=[], error=str(e)[:300])
            log(f"  {n}: FAILED - {str(e)[:200]}")
    return out


def summarise(n, d):
    rows = d["rows"]
    cols = list(dict.fromkeys(k for r in rows for k in r))
    s = dict(rows=len(rows), seconds=d["seconds"], error=d["error"], notes="; ".join(d["notes"]))
    seen = collections.Counter(tuple(sorted((k, str(v)) for k, v in r.items())) for r in rows)
    s["exact_dupes"] = sum(v - 1 for v in seen.values() if v > 1)
    key = KEYS.get(n)
    if key and rows and all(k in cols for k in key):
        kc = collections.Counter(tuple(str(r.get(k)) for k in key) for r in rows)
        s["dupe_keys"] = f"{sum(1 for v in kc.values() if v > 1)} keys repeated ({' + '.join(key)})"
    else:
        s["dupe_keys"] = ""
    st = []
    for col in cols:
        if STATUS.search(col):
            vc = collections.Counter(str(r.get(col)) for r in rows)
            st.append(f"{col}: " + ", ".join(f"{v} ({c})" for v, c in vc.most_common(6)) + (" ..." if len(vc) > 6 else ""))
    s["statuses"] = " | ".join(st)
    dts = []
    for col in cols:
        if DATE.search(col):
            vals = [str(r.get(col))[:10] for r in rows if r.get(col) not in (None, "")]
            if vals:
                vc = collections.Counter(vals)
                top, cnt = vc.most_common(1)[0]
                dts.append(f"{col}: {min(vals)} to {max(vals)}, {len(vc)} different"
                           + (f" (most common {top} on {cnt})" if cnt > 1 else ""))
            else:
                dts.append(f"{col}: all blank")
    s["dates"] = " | ".join(dts)
    s["columns"] = ", ".join(cols)
    return s


def checks(n, rows):
    """Specific questions from the SDI Mig test (23 Nov)."""
    out = []
    if n == "so_lines" and rows:
        grp = collections.Counter((r.get("salesOrder.id"), r.get("product.code"), r.get("quantityInSalesUnitOrdered"))
                                  for r in rows)
        rep = [(k, v) for k, v in grp.items() if v > 1]
        out.append(("Same order, part and quantity on more than one line", f"{len(rep)} cases",
                    "; ".join(f"{k[0]} {k[1]} x{k[2]} ({v} lines)" for k, v in rep[:15])))
        dd = collections.Counter(str(r.get("requestedDeliveryDate"))[:10] for r in rows)
        top, cnt = dd.most_common(1)[0]
        out.append(("Requested delivery date: lines on the most common date", f"{cnt} of {len(rows)} on {top}",
                    ", ".join(f"{k} ({v})" for k, v in dd.most_common(8))))
    if n in ("wo_products", "works_orders"):
        out.append(("Works orders sent by X3", str(len(rows)), "0 = none in this environment, or not visible to our "
                                                              "connection's user / site"))
    if n == "stock":
        sites = collections.Counter(str(r.get("stockSite.code")) for r in rows)
        out.append(("Stock by site", f"{len(rows)} rows", ", ".join(f"{k} ({v})" for k, v in sites.most_common(8))))
    return out


def write_xlsx(path, envs, data, summ, chk):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    head = ["Environment", "Data set", "X3 node", "Rows", "Seconds", "Identical rows repeated", "Repeated keys",
            "Statuses (value: count)", "Dates (from to, how many different)", "Notes / errors", "Columns"]
    hf, hfill = Font(name="Arial", bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1F4E78")
    ws.append(head)
    for c in ws[1]:
        c.font, c.fill = hf, hfill
    for env in envs:
        for n, s in summ[env].items():
            ws.append([x3_api.ENVS[env]["label"], n, ".".join(x3_api.NODES[n]), s["rows"], s["seconds"],
                       s["exact_dupes"], s["dupe_keys"], s["statuses"], s["dates"],
                       (s["error"] + " " + s["notes"]).strip(), s["columns"]])
    for col, w in zip("ABCDEFGHIJK", (18, 14, 34, 8, 8, 10, 26, 60, 70, 40, 60)):
        ws.column_dimensions[col].width = w
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "C2"
    cs = wb.create_sheet("Checks")
    cs.append(["Environment", "Data set", "Check", "Result", "Detail"])
    for c in cs[1]:
        c.font, c.fill = hf, hfill
    for env in envs:
        for n, items in chk[env].items():
            for item in items:
                cs.append([x3_api.ENVS[env]["label"], n, *item])
    for col, w in zip("ABCDE", (18, 14, 48, 22, 110)):
        cs.column_dimensions[col].width = w
    for env in envs:
        tag = x3_api.ENVS[env]["tag"]
        for n, d in data[env].items():
            rows = d["rows"]
            if not rows:
                continue
            sh = wb.create_sheet(f"{tag} {n}"[:31])
            cols = list(dict.fromkeys(k for r in rows for k in r))
            sh.append(cols)
            for c in sh[1]:
                c.font, c.fill = hf, hfill
            for r in rows:
                sh.append([r.get(k) if not isinstance(r.get(k), (dict, list)) else str(r.get(k)) for k in cols])
            sh.freeze_panes = "A2"
            sh.auto_filter.ref = sh.dimensions
    wb.save(path)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--env", choices=sorted(x3_api.ENVS), help="one environment (default: both)")
    ap.add_argument("--limit", type=int, default=0, help="quick try: only this many rows of each data set")
    ap.add_argument("--out", default="", help="the workbook (default: Downloads\\SDI_X3_inventory_<date>_<time>.xlsx)")
    a = ap.parse_args(argv)
    c = x3_api.load_conf()
    envs = [a.env] if a.env else ["mig", "uat"]
    data, summ, chk = {}, {}, {}
    for env in envs:
        print(f"{x3_api.ENVS[env]['label']} (endpoint {x3_api.ENVS[env]['endpoint']}):", flush=True)
        data[env] = pull_env(c, env, a.limit, lambda s: print(s, flush=True))
        summ[env] = {n: summarise(n, d) for n, d in data[env].items()}
        chk[env] = {n: checks(n, d["rows"]) for n, d in data[env].items()}
    print("\nSUMMARY (rows read)")
    names = list(dict.fromkeys(n for env in envs for n in summ[env]))
    print(f"{'data set':<14}" + "".join(f"{x3_api.ENVS[e]['label']:>22}" for e in envs))
    for n in names:
        cell = lambda e: "-" if n not in summ[e] else ("FAILED" if summ[e][n]["error"] else summ[e][n]["rows"])
        print(f"{n:<14}" + "".join(f"{cell(e):>22}" for e in envs))
    for env in envs:
        for n, items in chk[env].items():
            for item in items:
                print(f"{x3_api.ENVS[env]['tag']} {n}: {item[0]}: {item[1]}")
    out = Path(a.out) if a.out else Path.home() / "Downloads" / f"SDI_X3_inventory_{dt.datetime.now():%Y-%m-%d_%H%M}.xlsx"
    try:
        write_xlsx(out, envs, data, summ, chk)
        print(f"\nWorkbook: {out}  (business data - not for git or email)")
    except ImportError:
        print("\n(openpyxl isn't installed here, so no workbook - the summary above is the result. "
              "python -m pip install openpyxl  to get the workbook next time.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
