"""Estimate -> Sage X3: a small web page for the estimating import (EST-10 stage 1, Jira SCRUM-210).

Drop in an estimate (the estimators' template, or Dave's IMPORT layout), press Check. The page runs
est_to_x3.py, shows READY / NOT READY with every check by cell, what it read (BOM and route), and gives the
X3 load files to download (ZSDIITM if the part is new, YA00408BOM, ZSDIROU2). Every run is kept.
Nothing is written to Sage X3: the files are loaded by hand in Usage > Imports (TEST first). Sending
straight to X3 is stage 2 and needs the API client from Acuity (runbook 21.2 / 22.10).

Python's own web server, nothing to install but openpyxl, plus LibreOffice for old .xls estimates.

    set EST_PRODUCTS=<path to the current X3 product list: the latest ZSDIITM file or an X3 product export>
    python est_app.py                    ->  http://localhost:8766
    python est_app.py --host 0.0.0.0     ->  shared on the SDI network (no login - keep it inside SDI)

A newer product list can also be uploaded with an estimate; it is used for that run only.
"""
import argparse
import datetime as dt
import email.parser
import email.policy
import html
import io
import json
import os
import re
import sys
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from openpyxl import load_workbook

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
import est_to_x3 as est  # noqa: E402

RUNS = Path(os.environ.get("EST_RUNS", HERE / "runs"))
PRODUCTS = os.environ.get("EST_PRODUCTS", "")
MAX_UPLOAD = 40 * 1024 * 1024
e = html.escape
RUN_ID = re.compile(r"[\w\-]+")


def safe_name(name, default="file"):
    name = Path(name or default).name
    return re.sub(r"[^\w\-. ]+", "_", name).strip(" .") or default


def products_info(path):
    if not path:
        return "no product list set (EST_PRODUCTS) - upload one with the estimate"
    p = Path(path)
    if not p.exists():
        return f"product list not found: {p}"
    return f"{p.name}, dated {dt.datetime.fromtimestamp(p.stat().st_mtime):%d %b %Y %H:%M}"


def parse_multipart(headers, body):
    """Form fields and files from a multipart/form-data POST, without the deprecated cgi module."""
    msg = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
        b"Content-Type: " + headers["Content-Type"].encode() + b"\r\n\r\n" + body)
    fields, files = {}, {}
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        fname = part.get_filename()
        data = part.get_payload(decode=True) or b""
        if fname is not None:
            if data:
                files[name] = (safe_name(fname), data)
        else:
            fields[name] = data.decode("utf-8", "replace").strip()
    return fields, files


def runs():
    if not RUNS.exists():
        return []
    out = []
    for d in sorted(RUNS.iterdir(), reverse=True):
        f = d / "run.json"
        if f.exists():
            out.append((d.name, json.loads(f.read_text(encoding="utf-8"))))
    return out[:40]


def sheet_rows(path, title):
    try:
        ws = load_workbook(path, read_only=True)[title]
    except (KeyError, FileNotFoundError):
        return [], []
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    return (rows[0], rows[1:]) if rows else ([], [])


CSS = """
:root{--y:#F5D947;--ink:#282928;--t:#1f2321;--muted:#6b6f6c;--line:#e6e7e4;--bg:#f4f4f1;--card:#fff;
--stop:#b42318;--stopbg:#fde8e8;--warn:#8a5a00;--warnbg:#fff4d6;--ok:#146c2e;--okbg:#e3f4e8}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--t:#ececea;--muted:#a3a7a4;--line:#3a3c3b;
--bg:#151615;--card:#1c1d1c;--stopbg:#3a1d1b;--stop:#ff9b8f;--warnbg:#3a2f12;--warn:#f5d27a;--okbg:#16301f;--ok:#8fd9a5}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--t);font:15px/1.5 'Segoe UI','Helvetica Neue',Arial,sans-serif}
header{background:var(--ink);color:#fff;border-bottom:6px solid var(--y)}.w{max-width:1040px;margin:0 auto;padding:0 16px}
.hd{padding:22px 0 18px}.brand{color:var(--y);font-weight:700}h1{margin:4px 0 0;font-size:26px}
main{padding:20px 0 40px}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:18px 20px;margin-bottom:16px}
h2{font-size:17px;margin:0 0 12px}label{display:block;font-size:13px;color:var(--muted);margin-bottom:4px}
.row{display:flex;flex-wrap:wrap;gap:14px;align-items:flex-end}input,select{font:inherit;padding:8px 10px;border:1px solid var(--line);border-radius:6px;background:var(--card);color:var(--t);max-width:100%}
button,.btn{font:inherit;font-weight:600;background:var(--ink);color:#fff;border:0;border-radius:6px;padding:9px 18px;cursor:pointer;border-bottom:3px solid var(--y);text-decoration:none;display:inline-block}
button[disabled]{opacity:.45;cursor:not-allowed}.note{color:var(--muted);font-size:13px}
.err{background:var(--stopbg);color:var(--stop);border-radius:8px;padding:10px 14px;margin-bottom:16px}
.tw{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:7px 8px;border-top:1px solid var(--line);text-align:left;vertical-align:top}
th{background:var(--ink);color:#fff;font-weight:600}a{color:#2b6cb0}.n{text-align:right;font-variant-numeric:tabular-nums}
.banner{border-radius:10px;padding:16px 20px;margin-bottom:16px;font-size:20px;font-weight:700}
.ready{background:var(--okbg);color:var(--ok)}.notready{background:var(--stopbg);color:var(--stop)}
.tag{display:inline-block;font-size:12px;font-weight:700;border-radius:4px;padding:1px 7px}
.STOP{background:var(--stopbg);color:var(--stop)}.WARN{background:var(--warnbg);color:var(--warn)}.INFO{color:var(--muted);border:1px solid var(--line)}
.kv{display:grid;grid-template-columns:max-content 1fr;gap:4px 18px}.kv b{color:var(--muted);font-weight:600}
ol.steps li{margin-bottom:4px}
"""


def page(body, title="Estimate → Sage X3"):
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title><style>{CSS}</style></head><body><header><div class="w hd"><div class="brand">we.are.sdi</div>
<h1>{e(title)}</h1></div></header><main class="w">{body}</main></body></html>"""


def home(msg=""):
    hist = "".join(
        f"<tr><td><a href='/run/{e(n)}'>{e(m.get('when', n))}</a></td><td>{e(m.get('estimate', ''))}</td>"
        f"<td>{e(m.get('code', ''))}</td><td><span class='tag {'STOP' if m.get('stop') else 'INFO'}'>"
        f"{'NOT READY' if m.get('stop') else 'READY'}</span></td></tr>" for n, m in runs())
    return page(f"""{f'<div class="err">{e(msg)}</div>' if msg else ''}
<form class="card" method="post" action="/run" enctype="multipart/form-data">
<h2>Check an estimate and make the Sage X3 files</h2>
<div class="row">
 <div><label>Estimate (.xls or .xlsx)</label><input type="file" name="estimate" accept=".xls,.xlsx" required></div>
 <div><label>Part code (leave blank to take it from the estimate)</label><input name="parent" placeholder="e.g. IMPORT for the test part"></div>
</div><div class="row" style="margin-top:12px">
 <div><label>Category if the part is new</label><select name="category"><option>FGML</option><option>FGSL</option></select></div>
 <div><label>Sheet steel material</label><select name="sheet_material"><option>CR4</option><option>ZINTEC</option><option>Galvanised</option></select></div>
 <div><label><input type="checkbox" name="rev_in_code" value="1"> Revision in the part code (IMPORT layout)</label></div>
</div>
<details style="margin-top:12px"><summary class="note">Use a newer product list for this run</summary>
<p class="note">Current list: {e(products_info(PRODUCTS))}. Upload the latest ZSDIITM file or an X3 product export in the same layout.</p>
<input type="file" name="products" accept=".xlsx"></details>
<p><button>Check the estimate</button></p>
<p class="note">Nothing is sent to Sage X3. The page writes the import files; you load them in Usage → Imports, in TEST first.</p>
</form>
<section class="card"><h2>Previous runs</h2>{'<div class="tw"><table><tr><th>When</th><th>Estimate</th><th>Part</th><th>Result</th></tr>' + hist + '</table></div>' if hist else '<p class="note">None yet.</p>'}</section>
<p class="note">Product list: {e(products_info(PRODUCTS))} · Jira SCRUM-210 · runs kept in {e(str(RUNS))}</p>""")


def table(head, rows, num_cols=()):
    if not rows:
        return "<p class='note'>Nothing read.</p>"
    th = "".join(f"<th>{e(str(h or ''))}</th>" for h in head)
    body = "".join("<tr>" + "".join(
        f"<td class='{'n' if i in num_cols else ''}'>{e('' if v is None else str(v))}</td>" for i, v in enumerate(r))
        + "</tr>" for r in rows)
    return f"<div class='tw'><table><tr>{th}</tr>{body}</table></div>"


def result_page(run_id):
    d = RUNS / run_id
    meta = json.loads((d / "run.json").read_text(encoding="utf-8"))
    out = d / "out"
    checks_x = next(iter(sorted(out.glob("*_CHECKS.xlsx"))), None)
    ready = not meta["stop"]
    checks = "".join(
        f"<tr><td><span class='tag {e(c[0])}'>{e(c[0])}</span></td><td>{e(str(c[1]))}</td><td>{e(str(c[2]))}</td>"
        f"<td class='note'>{e(str(c[3]))}</td></tr>"
        for c in sorted(meta["checks"], key=lambda c: {"STOP": 0, "WARN": 1}.get(c[0], 2)))
    bh, br = sheet_rows(checks_x, "BOM read") if checks_x else ([], [])
    rh, rr = sheet_rows(checks_x, "Route read") if checks_x else ([], [])
    files = sorted(p.name for p in out.iterdir() if p.is_file())
    loads = [f for f in files if f.endswith(".txt")]
    links = "".join(f"<li><a href='/run/{e(run_id)}/file/{e(f)}'>{e(f)}</a></li>" for f in files)
    order = [n for n in ("ZSDIITM", "YA00408BOM", "ZSDIROU2") if any(n in f for f in loads)]
    steps = "".join(f"<li>Usage → Imports, template <b>{e(n)}</b>, file <code>{e(next(f for f in loads if n in f))}</code></li>"
                    for n in order)
    return page(f"""<p><a href="/">← Check another estimate</a></p>
<div class="banner {'ready' if ready else 'notready'}">{'READY TO LOAD' if ready else f'NOT READY – {meta["stop"]} problem(s) to fix'}</div>
<section class="card"><h2>{e(meta['estimate'])}</h2><div class="kv">
<b>Part</b><span>{e(meta['code'])} – {'new product' if meta['new'] else 'already in Sage X3: its BOM and route are written'}</span>
<b>Layout</b><span>{e(meta.get('layout', ''))}</span>
<b>BOM</b><span>{meta['bom']} lines</span><b>Route</b><span>{meta['ops']} operations</span>
<b>Checks</b><span>{meta['stop']} stop · {meta['warn']} warning(s)</span>
<b>Product list</b><span>{e(meta.get('products', ''))}</span><b>Run</b><span>{e(meta['when'])}</span></div></section>
<section class="card"><h2>Checks</h2><p class="note">STOP must be fixed in the estimate before loading. WARN: check it. INFO: what the converter did.</p>
<div class="tw"><table><tr><th>Level</th><th>Cell</th><th>Check</th><th>Detail</th></tr>{checks}</table></div></section>
<section class="card"><h2>Files</h2><ul>{links}</ul>
<p><a class="btn" href="/run/{e(run_id)}/zip">Download all (zip)</a></p>
{f'<h2 style="margin-top:16px">Load in Sage X3 (TEST first), in this order</h2><ol class="steps">{steps}</ol><p class="note">Then open the part in X3 and compare its BOM and route with the estimate.</p>' + ('<p class="err"><b>This part already exists in Sage X3 with its own BOM and route.</b> Until Acuity confirm whether the import replaces or adds lines, load it in TEST only, or check it as the IMPORT test part (part code IMPORT).</p>' if not meta['new'] else '') if ready else '<p class="note">Fix the STOP checks in the estimate and check it again before loading anything.</p>'}
<p><button disabled title="Needs the API client from Acuity">Send to Sage X3</button>
<span class="note">Stage 2: needs API access from Acuity.</span></p></section>
<section class="card"><h2>BOM read from the estimate</h2>{table(bh, br, (3, 4, 5))}</section>
<section class="card"><h2>Route read from the estimate</h2>{table(rh, rr, (4, 5))}</section>""",
                title=f"Estimate → Sage X3 · {meta['code']}")


def do_run(fields, files):
    if "estimate" not in files:
        raise ValueError("Choose an estimate file (.xls or .xlsx).")
    fname, data = files["estimate"]
    if Path(fname).suffix.lower() not in (".xls", ".xlsx"):
        raise ValueError("The estimate must be an .xls or .xlsx file.")
    stamp = dt.datetime.now()
    d = RUNS / f"{stamp:%Y%m%d-%H%M%S}_{re.sub(r'[^A-Za-z0-9]+', '-', Path(fname).stem)[:40]}"
    d.mkdir(parents=True)
    src = d / fname
    src.write_bytes(data)
    products = PRODUCTS
    if "products" in files:
        products = str(d / files["products"][0])
        Path(products).write_bytes(files["products"][1])
    if not products or not Path(products).exists():
        raise ValueError("No product list: set EST_PRODUCTS or upload the latest ZSDIITM / X3 product export.")
    res = est.build(src, d / "out", products, fields.get("parent") or None, fields.get("category", "FGML"),
                    bool(fields.get("rev_in_code")), fields.get("sheet_material", "CR4"))
    layout = ""
    checks_x = next(iter(sorted((d / "out").glob("*_CHECKS.xlsx"))), None)
    if checks_x:
        notes = load_workbook(checks_x, read_only=True).worksheets[0]
        layout = next((r[1] for r in notes.iter_rows(values_only=True) if r and r[0] == "Layout"), "")
    meta = dict(when=f"{stamp:%d %b %Y %H:%M}", estimate=fname, code=res["code"], new=res["new"], bom=res["bom"],
                ops=res["ops"], stop=res["stop"], warn=res["warn"], checks=res["checks"], layout=layout,
                products=products_info(products), options={k: fields.get(k) for k in
                                                           ("parent", "category", "sheet_material", "rev_in_code")})
    (d / "run.json").write_text(json.dumps(meta, indent=1, default=str), encoding="utf-8")
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

    def run_dir(self, run_id):
        d = RUNS / run_id
        return d if RUN_ID.fullmatch(run_id) and (d / "run.json").exists() else None

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            return self.send(home())
        m = re.fullmatch(r"/run/([\w\-]+)(?:/(zip|file/([^/]+)))?", path)
        d = m and self.run_dir(m.group(1))
        if d:
            out = d / "out"
            if m.group(2) == "zip":
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                    for f in sorted(out.iterdir()):
                        z.write(f, f.name)
                return self.send(buf.getvalue(), "application/zip",
                                 extra={"Content-Disposition": f'attachment; filename="{m.group(1)}.zip"'})
            if m.group(3):
                f = out / safe_name(m.group(3))
                if f.is_file() and f.parent == out:
                    ctype = ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" if f.suffix == ".xlsx"
                             else "text/plain; charset=cp850")
                    return self.send(f.read_bytes(), ctype,
                                     extra={"Content-Disposition": f'attachment; filename="{f.name}"'})
            else:
                return self.send(result_page(m.group(1)))
        self.send(page("<div class='card'>Not found. <a href='/'>Back</a></div>"), code=404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        if self.path != "/run":
            return self.send(page("Not found"), code=404)
        if n > MAX_UPLOAD:
            return self.send(home("The upload is too large."), code=413)
        try:
            if "multipart/form-data" not in self.headers.get("Content-Type", ""):
                raise ValueError("Upload the estimate with the form.")
            fields, files = parse_multipart(self.headers, self.rfile.read(n))
            name = do_run(fields, files)
        except SystemExit as ex:                                  # est_to_x3 stops with a message
            return self.send(home(str(ex)), code=400)
        except Exception as ex:                                   # show the reason on the page
            return self.send(home(f"{type(ex).__name__}: {ex}"), code=400)
        self.send(b"", code=303, extra={"Location": f"/run/{name}"})

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (dt.datetime.now().strftime("%H:%M:%S"), fmt % args))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8766)
    a = ap.parse_args()
    RUNS.mkdir(parents=True, exist_ok=True)
    print(f"Estimate -> Sage X3: http://{'localhost' if a.host == '127.0.0.1' else a.host}:{a.port}   "
          f"(product list: {products_info(PRODUCTS)}; runs in {RUNS})")
    ThreadingHTTPServer((a.host, a.port), App).serve_forever()
