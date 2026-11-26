"""X3 source adapter for Live Orders. Written 20 Nov 2026.

Turns the X3 data sets (from the X3 screens' exports, x3_ui.py, or from the API, x3_api.py) into the
same tab-separated extract live_orders.sql gives today. build_live_orders.py then runs unchanged, so the
board, the .json data contract, the dashboard and the portal all work on X3 data.

    python x3_source.py <exports folder> <extract.txt>          # write the extract
    python x3_source.py <exports folder> --check                # show which X3 column fed each field

The exports folder holds works_orders, so_lines, po_lines and stock, each as .csv, .xlsx or .json (the
names x3_ui.py and x3_api.py write). Column names are matched through x3_columns.json, which is
PROVISIONAL until the first real exports: --check shows anything it couldn't find.
"""
import argparse
import collections
import csv
import datetime as dt
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from build_live_orders import POH, SMR, SOH, WOR  # noqa: E402

GRIDS = {"WOR": WOR, "SOH": SOH, "POH": POH, "SMR": SMR}
ORDER = ["wo_products", "works_orders", "so_lines", "po_lines", "stock"]   # wo_products (API) wins over works_orders


def norm(s):
    return re.sub(r"[^a-z0-9.]", "", str(s).lower()).replace(".", "") if s is not None else ""


# ---------------------------------------------------------------- reading the exports
def _num(v):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def read_rows(path):
    p = Path(path)
    if p.suffix.lower() == ".json":
        rows = json.loads(p.read_text(encoding="utf-8-sig"))
        return rows if isinstance(rows, list) else rows.get("rows", [])
    if p.suffix.lower() in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook
        ws = load_workbook(p, read_only=True, data_only=True).worksheets[0]
        it = ws.iter_rows(values_only=True)
        head = None
        for r in it:                                   # the heading row: the first with 3+ text cells
            if r and sum(isinstance(c, str) and c.strip() != "" for c in r) >= 3:
                head = [str(c or "").strip() for c in r]
                break
        return [dict(zip(head, r)) for r in it if r and any(c not in (None, "") for c in r)] if head else []
    raw = p.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", "replace")
    first = text.splitlines()[0] if text else ""
    delim = max([",", ";", "\t", "|"], key=first.count)
    return list(csv.DictReader(text.splitlines(), delimiter=delim))


def find(folder, name):
    for ext in (".json", ".csv", ".xlsx", ".txt"):
        f = Path(folder) / f"{name}{ext}"
        if f.exists():
            return f
    return None


# ---------------------------------------------------------------- values
def date_txt(v):
    """Any X3 / Excel date -> yyyy-mm-dd (the engine reads that)."""
    if v in (None, ""):
        return ""
    if isinstance(v, (dt.datetime, dt.date)):
        return v.strftime("%Y-%m-%d")
    s = str(v).strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return m.group(0)
    if re.fullmatch(r"\d{8}", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{2,4})$", s.split(" ")[0])
    if m:                                               # UK screens: dd/mm/yy
        y = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
        try:
            return dt.date(y, int(m[2]), int(m[1])).isoformat()
        except ValueError:
            return ""
    return ""


def num_txt(v):
    if v in (None, ""):
        return ""
    if isinstance(v, (int, float)):
        return f"{v:g}"
    s = str(v).strip().replace(",", "").replace(" ", "").replace(" ", "")
    try:
        return f"{float(s):g}"
    except ValueError:
        return ""


DATES = {"created", "first_date", "scheduled", "mrp_date", "last_mat_due", "done_date", "ORDDAT", "DEMDLVDAT",
         "SHIDAT", "EXTRCPDAT", "IPTDAT"}
NUMS = {"orig_qty", "amd_qty", "good_qty", "rejected_qty", "scrap_qty", "booked_mat", "booked_lab", "booked_subcon",
        "QTY", "GROPRI", "QTYUOM", "QTYSTU", "QTYPCU", "PRI", "INVDTAAMT"}


def clean(field, v):
    if field in DATES:
        return date_txt(v)
    if field in NUMS:
        return num_txt(v)
    if v is None:
        return ""
    s = str(v).strip()
    return s[:-2] if re.fullmatch(r"\d+\.0", s) and field in ("SOPLIN", "POPLIN") else s


# ---------------------------------------------------------------- mapping
def column_for(cols, names):
    by = {norm(c): c for c in cols}
    for n in names:
        if norm(n) in by:
            return by[norm(n)]
    return None


def _contains(value, word):
    """'closed' in 'closed' / 'Closed' / 'isClosed', but not in 'notClosed' / 'unclosed' (22 Nov: never drop an open
    line because its status names the opposite)."""
    v = str(value or "").strip().lower()
    return word in v and not re.match(r"^(not|un|non)[_ -]?" + re.escape(word), v)


def convert(rows, spec, why=None, seen=None):
    """why / seen (Counters, optional): why each row was left out, and the status values X3 sent - for the report
    (22 Nov, James: "the sheet was blank despite us having some data in Sage X3")."""
    why = why if why is not None else collections.Counter()
    seen = seen if seen is not None else collections.Counter()
    cols = list(dict.fromkeys(k for r in rows[:200] for k in r))
    used, missing = {}, []
    for field, rule in spec["fields"].items():
        rule = rule if isinstance(rule, dict) else {"from": rule}
        if "const" in rule:
            used[field] = ("const", rule["const"], None)
            continue
        net = column_for(cols, rule.get("net", []))      # already the open quantity: used alone
        src = net or column_for(cols, rule["from"])
        minus = None if net else column_for(cols, rule.get("minus", []))
        used[field] = ("col", src, minus)
        if not src:
            missing.append(field)
    out = []
    keep = spec.get("keep", {})
    drop = {column_for(cols, [k]): {str(v).lower() for v in vals} for k, vals in spec.get("drop_if", {}).items()}
    drop = {k: v for k, v in drop.items() if k}
    # drop_if_contains: a status whose value contains a word, whatever X3 calls it ("closed", "Closed", "isClosed")
    # - X3 work-order and sales-order lines include closed ones; Access's extract only ever held open ones (20 Nov)
    dropc = {column_for(cols, [k]): [str(v).lower() for v in vals] for k, vals in spec.get("drop_if_contains", {}).items()}
    dropc = {k: v for k, v in dropc.items() if k}
    for r in rows:
        for k in list(drop) + [k for k in dropc if k not in drop]:
            seen[f"{k}={str(r.get(k, '')).strip() or '(blank)'}"] += 1
        hit = next((f"{k}={str(r.get(k, '')).strip()}" for k, v in drop.items()
                    if str(r.get(k, "")).strip().lower() in v), None)
        if hit:
            why[hit] += 1
            continue                                       # e.g. a closed PO line, a planned works order
        hit = next((f"{k}={str(r.get(k, '')).strip()}" for k, ws in dropc.items() for w in ws if _contains(r.get(k), w)),
                   None)
        if hit:
            why[hit] += 1
            continue                                       # a closed works order / sales-order line
        rec = {}
        for field, (kind, src, minus) in used.items():
            if kind == "const":
                rec[field] = src
            elif src:
                v = clean(field, r.get(src))
                if minus and v != "":
                    v = num_txt(float(v) - float(num_txt(r.get(minus)) or 0))
                rec[field] = v
        if any(str(rec.get(f, "")) not in ok for f, ok in keep.items() if f in rec):
            why["not in keep"] += 1
            continue
        bad = next((f for f in spec.get("drop_if_not_positive", []) if f in rec and _num(rec.get(f)) <= 0), None)
        if bad:
            why[f"{bad} 0 or less"] += 1
            continue                                       # nothing left to deliver / receive (as Access's views)
        out.append(rec)
    return out, used, missing


def to_extract(folder, out_path, conf_path=HERE / "x3_columns.json", check=False):
    conf = json.loads(Path(conf_path).read_text())
    lines, report = [], []
    as_at = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines.append(f"CHECK\tas at\t{as_at}\tsource X3 {Path(folder).name}")
    used_instead = set()
    kept, read_n, src_of = {}, {}, {}                     # for the stock check below (25 Nov)
    for name in ORDER:
        spec = conf.get(name)
        if not spec:
            continue
        f = find(folder, name)
        if name in used_instead:
            if f:
                report.append(f"{name}: skipped - read from {', '.join(k for k in ORDER if conf.get(k, {}).get('instead_of') == name)} instead")
            continue
        if not f:
            if not spec.get("instead_of"):
                report.append(f"{name}: no file in {folder} - that grid is empty")
            continue
        if spec.get("instead_of"):
            used_instead.add(spec["instead_of"])
        rows = read_rows(f)
        why, seen = collections.Counter(), collections.Counter()
        recs, used, missing = convert(rows, spec, why, seen)
        n0 = len(recs)
        if spec["grid"] == "WOR":
            recs = [r for r in recs if r.get("works_order")]
        if spec["grid"] == "SOH" or spec["grid"] == "POH":
            qf = "QTY" if spec["grid"] == "SOH" else "QTYUOM"
            recs = [r for r in recs if r.get("ITMREF") and (r.get(qf) == "" or float(r.get(qf) or 0) > 0)]
        if n0 > len(recs):
            why["no order number / product / quantity"] += n0 - len(recs)
        kept[spec["grid"]], read_n[spec["grid"]] = recs, len(rows)
        src_of[spec["grid"]] = {k: v[1] for k, v in used.items()}
        cols = GRIDS[spec["grid"]]
        for r in recs:
            lines.append("\t".join([spec["grid"]] + [str(r.get(c, "")).replace("\t", " ") for c in cols[1:]]))
        report.append(f"{name} ({f.name}): {len(rows)} rows read, {len(recs)} kept -> {spec['grid']}"
                      + (f"; left out: {', '.join(f'{n} {w}' for w, n in why.most_common(6))}" if why else ""))
        if seen:                                           # the status values X3 sent, to check the filters against
            report.append(f"    statuses from X3: {', '.join(f'{k} ({n})' for k, n in seen.most_common(8))}")
        if check:
            for field, (kind, src, minus) in used.items():
                report.append(f"    {field:<14} <- {src if src else '** NOT FOUND **'}" + (f"  minus {minus}" if minus else ""))
        if missing:
            report.append(f"    not found: {', '.join(missing)}")
    report += stock_check(kept, read_n, src_of)
    if out_path:
        Path(out_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def stock_check(kept, read_n, src_of):
    """Does the stock's part code match the part codes on the orders? (25 Nov, fix 1: on We are SDI 17 of 20 works
    orders were red and none green - if X3's stock comes through under an internal id instead of the part code, no
    stock is ever found and everything shows red.) A line starting WARNING opens What X3 sent on the page."""
    if "SMR" not in kept:
        return []
    stock = {str(r.get("ITMREF")) for r in kept["SMR"] if r.get("ITMREF")}
    other = ({str(r.get("ITMREF")) for g in ("POH", "SOH") for r in kept.get(g, []) if r.get("ITMREF")}
             | {str(r.get("product")) for r in kept.get("WOR", []) if r.get("product")})
    col = (src_of.get("SMR") or {}).get("ITMREF") or "none"
    if not stock:
        if read_n.get("SMR"):
            return [f"WARNING: X3 sent {read_n['SMR']} stock lines but none were kept (stock status not A, or no part "
                    f"code - X3 column {col}): every works order with a BOM will show RED until this is fixed."]
        return ["stock check: X3 sent no stock for this environment."]
    hit = stock & other
    out = [f"stock check: {len(stock)} parts in stock (part code from X3 column {col}); {len(hit)} of them are on the "
           f"PO, SO or works-order lines."]
    if other and not hit:
        out.append(f"WARNING: none of the stock's part codes match a part on the PO, SO or works-order lines, so no "
                   f"stock is found and works orders show RED. The stock's part code is probably coming through as "
                   f"an internal id (X3 column {col}). For example stock {', '.join(sorted(stock)[:2])} against order "
                   f"lines {', '.join(sorted(other)[:2])}. Tell James.")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("folder")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--columns", default=str(HERE / "x3_columns.json"))
    a = ap.parse_args(argv)
    if not a.out and not a.check:
        ap.error("give an output file, or --check")
    print("\n".join(to_extract(a.folder, a.out, a.columns, a.check)))


if __name__ == "__main__":
    main()
