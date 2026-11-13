"""Live Orders board - a small web page to refresh it on demand inside SDI (LO-00..05, Jira SCRUM-241).

Press Refresh: the page reads Access (read-only, live_orders.sql), builds the board and the Excel workbook,
and keeps every run. Without a database connection, upload a saved result of live_orders.sql (or the
migration's extract_transactions.txt) instead. After go-live the same page reads X3 (export or API).

    set SDI_SQL_CONN=DRIVER={ODBC Driver 17 for SQL Server};SERVER=<server>;DATABASE=SDILive;Trusted_Connection=yes;ApplicationIntent=ReadOnly
    set LO_PRODUCTS=<ZSDIITM products file .xlsx>   LO_BOMS=<YA00408BOM .txt>   LO_ROUTES=<ZSDIROU2 .txt>
    python live_orders_app.py                   ->  http://localhost:8767
    python live_orders_app.py --host 0.0.0.0    ->  shared on the SDI network (no login - keep it inside SDI)
"""
import argparse
import datetime as dt
import email.parser
import email.policy
import html
import json
import os
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import build_live_orders as lo  # noqa: E402

RUNS = Path(os.environ.get("LO_RUNS", HERE / "runs"))
CONN = os.environ.get("SDI_SQL_CONN", "")
MASTER = {k: os.environ.get(f"LO_{k.upper()}", "") for k in ("products", "boms", "routes")}
DAVE = os.environ.get("LO_DAVE", "")              # optional: Dave's workbook, to compare against
e = html.escape


def master_ready():
    missing = [k for k, v in MASTER.items() if not v or not Path(v).exists()]
    return f"master data not set: {', '.join('LO_' + k.upper() for k in missing)}" if missing else ""


def db_ready():
    if not CONN:
        return "no connection set (SDI_SQL_CONN)"
    try:
        import pyodbc  # noqa: F401
    except ImportError:
        return "pyodbc is not installed"
    return ""


def from_access():
    """Run live_orders.sql read-only; write every grid row as the SQL Server grid would be saved."""
    import pyodbc
    sql = (HERE / "live_orders.sql").read_text(encoding="utf-8")
    sql = "\n".join(l for l in sql.splitlines() if l.strip().upper() not in ("GO", "USE SDILIVE;"))
    out = []
    with pyodbc.connect(CONN, readonly=True, timeout=60) as cn:
        cur = cn.cursor()
        cur.execute(sql)
        while True:
            if cur.description:
                out += ["\t".join("NULL" if v is None else str(v) for v in r) for r in cur.fetchall()]
            if not cur.nextset():
                break
    return "\n".join(out) + "\n"


def runs():
    if not RUNS.exists():
        return []
    res = []
    for d in sorted(RUNS.iterdir(), reverse=True):
        f = d / "run.json"
        if f.exists():
            res.append((d.name, json.loads(f.read_text(encoding="utf-8"))))
    return res[:30]


def page(body, title="Live Orders"):
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title><style>
:root{{--y:#F5D947;--ink:#282928;--t:#1f2321;--muted:#6b6f6c;--line:#e6e7e4;--bg:#f4f4f1;--card:#fff;--r:#b42318;--rb:#fde2e1}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--t:#ececea;--muted:#a3a7a4;--line:#3a3c3b;--bg:#151615;--card:#1c1d1c;--r:#ff9b8f;--rb:#3a1d1b}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--t);font:15px/1.5 'Segoe UI','Helvetica Neue',Arial,sans-serif}}
header{{background:var(--ink);color:#fff;border-bottom:6px solid var(--y)}}.w{{max-width:980px;margin:0 auto;padding:0 16px}}
.hd{{padding:22px 0 18px}}.brand{{color:var(--y);font-weight:700}}h1{{margin:4px 0 0;font-size:26px}}
main{{padding:20px 0 40px}}.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px 20px;margin-bottom:16px;overflow-x:auto}}
h2{{font-size:17px;margin:0 0 12px}}input{{font:inherit;max-width:100%}}
button{{font:inherit;font-weight:600;background:var(--ink);color:#fff;border:0;border-radius:6px;padding:9px 18px;cursor:pointer;border-bottom:3px solid var(--y)}}
button[disabled]{{opacity:.45;cursor:not-allowed}}.note{{color:var(--muted);font-size:13px}}.err{{background:var(--rb);color:var(--r);border-radius:8px;padding:10px 14px;margin-bottom:16px}}
table{{border-collapse:collapse;width:100%;font-size:14px}}td,th{{padding:7px 8px;border-top:1px solid var(--line);text-align:left}}th{{background:var(--ink);color:#fff}}a{{color:#2b6cb0}}
</style></head><body><header><div class="w hd"><div class="brand">we.are.sdi</div><h1>{e(title)}</h1></div></header><main class="w">{body}</main></body></html>"""


def home(msg=""):
    why_db, why_m = db_ready(), master_ready()
    hist = "".join(f"<tr><td><a href='/board/{e(n)}'>{e(m['as_at'])}</a></td><td>{e(m['source'])}</td>"
                   f"<td>{m['wos']} WOs · {m['red']} red · {m['amber']} amber · {m['green']} green</td>"
                   f"<td><a href='/board/{e(n)}/xlsx'>Excel</a></td></tr>" for n, m in runs())
    return page(f"""{f'<div class="err">{e(msg)}</div>' if msg else ''}
{f'<div class="err">Not ready: {e(why_m)}.</div>' if why_m else ''}
<form class="card" method="post" action="/refresh"><h2>Refresh from Access</h2>
<p class="note">Reads Access SupplyChain (read-only): open works orders, sales-order lines, purchase-order lines and stock.
{'' if not why_db else f'<b>Not available here:</b> {e(why_db)}.'}</p>
<button {'disabled' if why_db or why_m else ''}>Refresh the board</button></form>
<form class="card" method="post" action="/upload" enctype="multipart/form-data"><h2>…or upload a saved result</h2>
<p class="note">Run <code>live_orders.sql</code> in SQL Server with results to file (tab delimited), or use the migration's extract_transactions.txt.</p>
<p><input type="file" name="extract" accept=".txt,.tsv" required></p><button {'disabled' if why_m else ''}>Build the board</button></form>
<section class="card"><h2>Boards</h2>{'<table><tr><th>As at</th><th>Source</th><th>Result</th><th></th></tr>' + hist + '</table>' if hist else '<p class="note">None yet.</p>'}</section>
<p class="note">Master data: {' · '.join(f'{k}: {e(Path(v).name) if v else "not set"}' for k, v in MASTER.items())} · Jira SCRUM-241 · boards kept in {e(str(RUNS))}</p>""")


def build_run(text, source):
    d = RUNS / dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    d.mkdir(parents=True)
    (d / "live_orders_extract.txt").write_text(text, encoding="utf-8")
    res = lo.build(d / "live_orders_extract.txt", d, MASTER["products"], MASTER["boms"], MASTER["routes"],
                   DAVE if DAVE and Path(DAVE).exists() else None)
    meta = dict(res["meta"], source=source, files=res["files"])
    if not meta["wos"]:
        raise ValueError("No open works orders were found - is this the result of live_orders.sql?")
    (d / "run.json").write_text(json.dumps(meta), encoding="utf-8")
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
        if path == "/":
            return self.send(home())
        m = re.fullmatch(r"/board/([\w\-]+)(/xlsx)?", path)
        if m and (RUNS / m.group(1) / "run.json").exists():
            d = RUNS / m.group(1)
            f = next(iter(sorted(d.glob("*.xlsx" if m.group(2) else "SDI_Live_Orders_*.html"))), None)
            if f:
                if m.group(2):
                    return self.send(f.read_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                     extra={"Content-Disposition": f'attachment; filename="{f.name}"'})
                back = ('<div style="background:#282928;padding:8px 16px;font:14px Segoe UI,Arial">'
                        f'<a style="color:#F5D947" href="/">← All boards / refresh</a> &nbsp; '
                        f'<a style="color:#F5D947" href="/board/{m.group(1)}/xlsx">Download Excel</a></div>')
                return self.send(f.read_text(encoding="utf-8").replace("<body>", "<body>" + back, 1))
        self.send(page("<div class='card'>Not found. <a href='/'>Back</a></div>"), code=404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(n) if n else b""
        try:
            if master_ready():
                raise ValueError(master_ready())
            if self.path == "/refresh":
                if db_ready():
                    raise ValueError(f"Refresh from Access is not available: {db_ready()}.")
                name = build_run(from_access(), "Access (live)")
            elif self.path == "/upload":
                msg = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
                    b"Content-Type: " + self.headers["Content-Type"].encode() + b"\r\n\r\n" + body)
                part = next((p for p in msg.iter_parts() if p.get_param("name", header="content-disposition") == "extract"), None)
                data = part.get_payload(decode=True) if part else b""
                if not data:
                    raise ValueError("Choose the saved result file.")
                name = build_run(data.decode("utf-8-sig", "replace"), f"upload: {Path(part.get_filename() or 'file').name}")
            else:
                return self.send(page("Not found"), code=404)
        except Exception as ex:                                    # show the reason on the page
            return self.send(home(f"{type(ex).__name__}: {ex}"), code=400)
        self.send(b"", code=303, extra={"Location": f"/board/{name}"})

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (dt.datetime.now().strftime("%H:%M:%S"), fmt % args))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8767)
    a = ap.parse_args()
    RUNS.mkdir(parents=True, exist_ok=True)
    print(f"Live Orders: http://{'localhost' if a.host == '127.0.0.1' else a.host}:{a.port}   (boards in {RUNS})")
    ThreadingHTTPServer((a.host, a.port), App).serve_forever()
