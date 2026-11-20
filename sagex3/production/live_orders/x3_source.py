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


def convert(rows, spec):
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
    for r in rows:
        if any(str(r.get(k, "")).strip().lower() in v for k, v in drop.items()):
            continue                                       # e.g. a closed PO line
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
            continue
        out.append(rec)
    return out, used, missing


def to_extract(folder, out_path, conf_path=HERE / "x3_columns.json", check=False):
    conf = json.loads(Path(conf_path).read_text())
    lines, report = [], []
    as_at = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines.append(f"CHECK\tas at\t{as_at}\tsource X3 {Path(folder).name}")
    used_instead = set()
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
        recs, used, missing = convert(rows, spec)
        if spec["grid"] == "WOR":
            recs = [r for r in recs if r.get("works_order")]
        if spec["grid"] == "SOH" or spec["grid"] == "POH":
            qf = "QTY" if spec["grid"] == "SOH" else "QTYUOM"
            recs = [r for r in recs if r.get("ITMREF") and (r.get(qf) == "" or float(r.get(qf) or 0) > 0)]
        cols = GRIDS[spec["grid"]]
        for r in recs:
            lines.append("\t".join([spec["grid"]] + [str(r.get(c, "")).replace("\t", " ") for c in cols[1:]]))
        report.append(f"{name} ({f.name}): {len(rows)} rows read, {len(recs)} kept -> {spec['grid']}")
        if check:
            for field, (kind, src, minus) in used.items():
                report.append(f"    {field:<14} <- {src if src else '** NOT FOUND **'}" + (f"  minus {minus}" if minus else ""))
        if missing:
            report.append(f"    not found: {', '.join(missing)}")
    if out_path:
        Path(out_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


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
