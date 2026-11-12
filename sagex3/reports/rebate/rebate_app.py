"""Rebate rolling report - a small web app to run it on demand inside SDI (REP-22, SCRUM-275).

Python's own web server: no Flask, nothing to install except openpyxl, plus pyodbc for "Run from
Access". Open the page, pick the month and press Run. The app reads Access (read-only, the same
rebate_rolling.sql), builds the HTML report and the Excel workbook, and keeps every run.

    set SDI_SQL_CONN=DRIVER={ODBC Driver 17 for SQL Server};SERVER=<server>;DATABASE=SDILive;Trusted_Connection=yes;ApplicationIntent=ReadOnly
    python rebate_app.py                     ->  http://localhost:8765
    python rebate_app.py --host 0.0.0.0      ->  shared on the SDI network (no login - keep it inside SDI)

Without a database connection the page still works: paste the results of rebate_rolling.sql
(with or without the heading row) and press Build.
"""
import argparse
import datetime as dt
import html
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import build_rebate_report as rb  # noqa: E402

RUNS = Path(os.environ.get("REBATE_RUNS", HERE / "runs"))
CONN = os.environ.get("SDI_SQL_CONN", "")
COLS = ["customer_code", "customer_name", "part_code", "description", "price_per", "quantity", "invoice_no",
        "invoice_date", "due_date", "order_no", "order_date", "project_no", "customer_rebate_pct"]
e = html.escape


def db_ready():
    if not CONN:
        return "no connection set (SDI_SQL_CONN)"
    try:
        import pyodbc  # noqa: F401
    except ImportError:
        return "pyodbc is not installed"
    return ""


def sql_for(end):
    sql = (HERE / "rebate_rolling.sql").read_text(encoding="utf-8")
    old = "DATEFROMPARTS(YEAR(GETDATE()), MONTH(GETDATE()), 1)"
    assert old in sql, "rebate_rolling.sql has changed - the end month can no longer be set"
    return sql.replace(old, f"'{end[0]:04d}-{end[1]:02d}-01'", 1)


def from_access(end):
    import pyodbc
    with pyodbc.connect(CONN, readonly=True, timeout=30) as cn:
        cur = cn.cursor()
        cur.execute(sql_for(end))
        while cur.description is None and cur.nextset():   # skip the SET / DECLARE results
            pass
        names = [d[0] for d in cur.description]
        rows = cur.fetchall()
    out = ["\t".join(names)]
    out += ["\t".join("" if v is None else str(v) for v in r) for r in rows]
    return "\n".join(out) + "\n", len(rows)


def from_paste(text):
    lines = [l.rstrip("\r") for l in text.replace("\r\n", "\n").split("\n") if l.strip()]
    if not lines:
        raise ValueError("Nothing was pasted.")
    if lines[0].split("\t")[0].strip().lower() != "customer_code":    # pasted without the heading row
        lines.insert(0, "\t".join(COLS))
    width = len(lines[0].split("\t"))
    bad = [i for i, l in enumerate(lines[1:], 2) if len(l.split("\t")) < 11]
    if bad:
        raise ValueError(f"Rows {bad[:5]} have too few columns - paste the grid from SQL Server with tabs between columns.")
    return "\n".join(lines) + "\n", len(lines) - 1, width


def parts_count():
    return sum(1 for r in rb.csv.DictReader(open(HERE / "rebate_parts.csv")) if r["part_code"].strip())


def runs():
    if not RUNS.exists():
        return []
    out = []
    for d in sorted(RUNS.iterdir(), reverse=True):
        meta = d / "run.txt"
        if meta.exists():
            out.append((d.name, meta.read_text(encoding="utf-8")))
    return out[:30]


def page(body, title="Rebate rolling report"):
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title><style>
:root{{--y:#F5D947;--ink:#282928;--t:#1f2321;--muted:#6b6f6c;--line:#e6e7e4;--bg:#f4f4f1;--card:#fff}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--t:#ececea;--muted:#a3a7a4;--line:#3a3c3b;--bg:#151615;--card:#1c1d1c}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--t);font:15px/1.5 'Segoe UI','Helvetica Neue',Arial,sans-serif}}
header{{background:var(--ink);color:#fff;border-bottom:6px solid var(--y)}}.w{{max-width:980px;margin:0 auto;padding:0 16px}}
.hd{{padding:22px 0 18px}}.brand{{color:var(--y);font-weight:700}}h1{{margin:4px 0 0;font-size:26px}}
main{{padding:20px 0 40px}}.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px 20px;margin-bottom:16px}}
h2{{font-size:17px;margin:0 0 12px}}label{{display:block;font-size:13px;color:var(--muted);margin-bottom:4px}}
.row{{display:flex;flex-wrap:wrap;gap:14px;align-items:flex-end}}input,select,textarea{{font:inherit;padding:8px 10px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--t)}}
textarea{{width:100%;min-height:150px;font-family:Consolas,monospace;font-size:12.5px}}
button{{font:inherit;font-weight:600;background:var(--ink);color:#fff;border:0;border-radius:6px;padding:9px 18px;cursor:pointer;border-bottom:3px solid var(--y)}}
button[disabled]{{opacity:.45;cursor:not-allowed}}.note{{color:var(--muted);font-size:13px}}.err{{background:#fde8e8;color:#8a1c1c;border:1px solid #f5b5b5;border-radius:8px;padding:10px 14px;margin-bottom:16px}}
table{{border-collapse:collapse;width:100%;font-size:14px}}td,th{{padding:7px 8px;border-top:1px solid var(--line);text-align:left}}th{{background:var(--ink);color:#fff}}
a{{color:#2b5c99}}.n{{text-align:right;font-variant-numeric:tabular-nums}}
</style></head><body><header><div class="w hd"><div class="brand">we.are.sdi</div><h1>{e(title)}</h1></div></header>
<main class="w">{body}</main></body></html>"""


def home(msg=""):
    today = dt.date.today()
    why = db_ready()
    hist = "".join(f"<tr><td><a href='/report/{e(n)}'>{e(n)}</a></td><td>{e(m)}</td>"
                   f"<td><a href='/report/{e(n)}/xlsx'>Excel</a></td></tr>" for n, m in runs())
    form = f"""<div class="row">
<div><label>Last month of the 12</label><input type="month" name="end" value="{today:%Y-%m}" required></div>
<div><label>Month by</label><select name="basis"><option value="due" selected>Due date (as the Access report)</option>
<option value="invoice">Invoice date</option><option value="order">Order date</option></select></div>
<div><label>Rebate %</label><input type="number" name="rate" value="6" step="0.1" min="0" max="100" style="width:90px"></div></div>"""
    return page(f"""{f'<div class="err">{e(msg)}</div>' if msg else ''}
<form class="card" method="post" action="/run"><h2>Run from Access</h2>{form}
<p class="note">Reads Access SupplyChain (read-only) and builds the report and the Excel workbook.
{'' if not why else f'<b>Not available here:</b> {e(why)}.'}</p>
<button {'disabled' if why else ''}>Run the report</button></form>
<form class="card" method="post" action="/paste"><h2>…or paste the results of rebate_rolling.sql</h2>{form}
<p class="note">Run <code>rebate_rolling.sql</code> in SQL Server, select the whole grid and copy (with or without headers), paste here.</p>
<textarea name="grid" placeholder="customer_code	customer_name	part_code	…"></textarea><p><button>Build the report</button></p></form>
<section class="card"><h2>Previous runs</h2>{'<table><tr><th>Run</th><th>Result</th><th></th></tr>' + hist + '</table>' if hist else '<p class="note">None yet.</p>'}</section>
<p class="note">{parts_count()} part codes in rebate_parts.csv · Jira SCRUM-275 · runs kept in {e(str(RUNS))}</p>""")


def build_run(tsv, form, source):
    end = tuple(int(x) for x in form["end"].split("-"))
    rate = str(float(form.get("rate", "6")) / 100)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    d = RUNS / f"{stamp}_{end[0]}-{end[1]:02d}"
    d.mkdir(parents=True)
    (d / "rebate_lines.txt").write_text(tsv, encoding="utf-8")
    res = rb.build(d / "rebate_lines.txt", d, end, rate, form.get("basis", "due"))
    (d / "run.txt").write_text(f"{source} · {res['meta']['period']} · by {form.get('basis', 'due')} date · "
                               f"sales £{res['grand']:,.2f} · rebate £{res['rebate']:,.2f}", encoding="utf-8")
    return d.name


class App(BaseHTTPRequestHandler):
    def send(self, body, ctype="text/html; charset=utf-8", code=200, extra=None):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        m = re.fullmatch(r"/report/([\w\-]+)(/xlsx)?", path)
        if path == "/":
            return self.send(home())
        if m and (RUNS / m.group(1)).is_dir():
            d = RUNS / m.group(1)
            want = "*.xlsx" if m.group(2) else "*.html"
            f = next(iter(sorted(d.glob(want))), None)
            if f:
                if m.group(2):
                    return self.send(f.read_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                     extra={"Content-Disposition": f'attachment; filename="{f.name}"'})
                back = ('<div style="background:#282928;padding:8px 16px;font:14px Segoe UI,Arial">'
                        f'<a style="color:#F5D947" href="/">← All runs</a> &nbsp; <a style="color:#F5D947" href="/report/{m.group(1)}/xlsx">Download Excel</a></div>')
                return self.send(f.read_text(encoding="utf-8").replace("<body>", "<body>" + back, 1))
        self.send(page("<div class='card'>Not found. <a href='/'>Back</a></div>"), code=404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        form = {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode("utf-8"), keep_blank_values=True).items()}
        try:
            if self.path == "/run":
                why = db_ready()
                if why:
                    raise ValueError(f"Run from Access is not available: {why}.")
                end = tuple(int(x) for x in form["end"].split("-"))
                tsv, count = from_access(end)
                name = build_run(tsv, form, f"Access, {count} lines")
            elif self.path == "/paste":
                tsv, count, _ = from_paste(form.get("grid", ""))
                name = build_run(tsv, form, f"pasted, {count} lines")
            else:
                return self.send(page("Not found"), code=404)
        except Exception as ex:                                   # show the reason on the page
            return self.send(home(f"{type(ex).__name__}: {ex}"), code=400)
        self.send(b"", code=303, extra={"Location": f"/report/{name}"})

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (dt.datetime.now().strftime("%H:%M:%S"), fmt % args))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    RUNS.mkdir(parents=True, exist_ok=True)
    print(f"Rebate report: http://{'localhost' if a.host == '127.0.0.1' else a.host}:{a.port}   (runs in {RUNS})")
    ThreadingHTTPServer((a.host, a.port), App).serve_forever()
