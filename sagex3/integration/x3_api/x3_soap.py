"""Sage X3 classic SOAP web services - the route to BOMs and routes from the Estimate portal. Written 26 Nov 2026.

X3 (We are SDI) lets the API create products but not BOMs or routings; the JSON-template route stalled on X3
refusing the BOM nodes (26 Nov: ManufacturingBom / SalesBom "Invalid value" on a Json (API) template, "main node
name is required" on Operations). X3's standard SOAP web service AOWSIMPORT runs an EXISTING import template on the
file content it is sent - the same as Usage -> Imports by hand - so the portal can send the BOM and route files it
already makes through YA004BOMP and ZSDIROU2, which Ethan's migration loads ran with 0 errors.

    python x3_soap.py check --env uat [--pool ALIAS]
        Read-only. Can the "SDI Estimate loader" connection sign in to the SOAP service, and (with --pool) what
        does AOWSIMPORT take? Calls getDescription only - it describes the web service, it imports nothing.

    python x3_soap.py import <part>_YA00408BOM.txt --template YA004BOMP --env uat --pool SDIEST
        Dry run: reads X3 (is the product there? a BOM already?) and says what it would do. Nothing is sent.
    ... --apply --confirm <part> [--update] [--by NAME]
        Runs the template on the file (REALTIME) and logs it to x3_load_history.jsonl. One part per file; a BOM
        or route X3 already has is only changed with --update (estimators re-saving, James 26 Nov).

Test environments only (same guard as x3_load.py). Nothing secret is printed.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path
from xml.sax.saxutils import escape

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import x3_api  # noqa: E402
import x3_load  # noqa: E402

WSDL = "/soap-wsdl/syracuse/collaboration/syracuse/CAdxWebServiceXmlCC?wsdl"
SOAP = "/soap-generic/syracuse/collaboration/syracuse/CAdxWebServiceXmlCC"
UA = "sdi-x3-estimate/1"


def envelope(op, pool, public_name, lang="ENG", input_json=None):
    """CAdxWebServiceXmlCC call (rpc/encoded). op: getDescription (describes) or run."""
    inp = ""
    if input_json is not None:
        inp = f'<inputXml xsi:type="xsd:string"><![CDATA[{json.dumps(input_json)}]]></inputXml>'
    return ('<?xml version="1.0" encoding="utf-8"?>'
            '<soapenv:Envelope xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
            'xmlns:wss="http://www.adonix.com/WSS"><soapenv:Header/><soapenv:Body>'
            f'<wss:{op} soapenv:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
            '<callContext xsi:type="wss:CAdxCallContext">'
            f'<codeLang xsi:type="xsd:string">{escape(lang)}</codeLang>'
            f'<poolAlias xsi:type="xsd:string">{escape(pool)}</poolAlias>'
            '<poolId xsi:type="xsd:string"></poolId>'
            '<requestConfig xsi:type="xsd:string">adxwss.optreturn=JSON&amp;adxwss.beautify=true</requestConfig>'
            '</callContext>'
            f'<publicName xsi:type="xsd:string">{escape(public_name)}</publicName>{inp}'
            f'</wss:{op}></soapenv:Body></soapenv:Envelope>')


def _tag(xml, name):
    m = re.search(rf"<(?:\w+:)?{name}\b[^>]*>(.*?)</(?:\w+:)?{name}>", xml or "", re.S)
    if not m:
        return None
    v = m.group(1)
    v = re.sub(r"^<!\[CDATA\[(.*)\]\]>$", r"\1", v.strip(), flags=re.S)
    return v.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&apos;", "'").replace("&amp;", "&")


def parse(xml):
    """status (1 ok / 0 not), X3's messages, the result (JSON text when optreturn=JSON)."""
    # X3 puts messages either inline (<messages><message/><type/></messages>) or as SOAP multiRefs; read every
    # <message> / <type> pair wherever it is, in document order.
    texts = [re.sub(r"\s+", " ", _tag(m, "message") or "").strip()
             for m in re.findall(r"(<(?:\w+:)?message\b[^>]*>.*?</(?:\w+:)?message>)", xml or "", re.S)]
    types = [t.strip() for t in re.findall(r"<(?:\w+:)?type\b[^>]*>\s*(\d+)\s*</(?:\w+:)?type>", xml or "", re.S)]
    msgs = [(types[i] if i < len(types) else "", t) for i, t in enumerate(texts) if t]
    msgs += [("", re.sub(r"\s+", " ", m).strip()) for m in re.findall(r"<faultstring[^>]*>(.*?)</faultstring>", xml or "", re.S)]
    return {"status": _tag(xml, "status"), "messages": msgs, "result": _tag(xml, "resultXml")}


def call(c, op, pool, public_name, input_json=None, auth=True):
    h = {"Content-Type": "text/xml; charset=utf-8", "SOAPAction": '""', "User-Agent": UA}
    if auth:
        h["Authorization"] = "Bearer " + x3_api.bearer(c)
    body = envelope(op, pool, public_name, c.get("soap_lang", "ENG"), input_json).encode("utf-8")
    return x3_api.raw("POST", c["site"] + SOAP, h, body, timeout=120)


def check(a):
    c = x3_load.guard(x3_api.for_env(x3_load.load_conf(), a.env))
    print(f"X3: {c['site']} - endpoint {c.get('endpoint')} - connection user {c.get('user')}")
    print("\n1. Can the connection reach X3's SOAP service? (the service description, no data)")
    for label, auth in (("without signing in", False), ("signed in as the SDI Estimate loader", True)):
        h = {"User-Agent": UA}
        if auth:
            h["Authorization"] = "Bearer " + x3_api.bearer(c)
        code, _, text = x3_api.raw("GET", c["site"] + WSDL, h)
        ok = code == 200 and "definitions" in text[:2000]
        print(f"   {label:<40} {code}  {'service description received' if ok else x3_api.redact(text)[:160].strip()}")
    if not a.pool:
        print("\n2. Skipped: add --pool <alias> (Administration -> Web services -> Classic SOAP pools configuration)")
        print("\nSend Claude this output (no secret in it).")
        return 0
    print(f"\n2. AOWSIMPORT on pool {a.pool} - its description (getDescription: describes the web service, imports nothing)")
    for label, auth in (("without signing in", False), ("signed in as the SDI Estimate loader", True)):
        code, _, text = call(c, "getDescription", a.pool, "AOWSIMPORT", auth=auth)
        p = parse(text)
        print(f"   {label:<40} HTTP {code}, status {p['status']}")
        for t, m in p["messages"][:6]:
            print(f"      X3 says{(' (' + t + ')') if t else ''}: {x3_api.redact(m)[:300]}")
        if p["result"] and auth:
            print("      Description:")
            for line in p["result"].splitlines()[:80]:
                print("        " + line[:160])
        if auth and p["status"] != "1":
            # X3's whole answer (it holds no secret), tags on their own lines, so nothing it says is lost
            body = re.sub(r"<\?xml[^>]*>", "", text or "")
            body = re.sub(r"\s*xmlns(:\w+)?=\"[^\"]*\"", "", body)
            body = re.sub(r"\s*xsi:type=\"[^\"]*\"", "", body)
            print("      X3's full answer:")
            for line in re.sub(r">\s*<", ">\n<", body).splitlines()[:60]:
                if line.strip():
                    print("        " + line.strip()[:200])
        elif code != 200 and not p["messages"]:
            print("      " + x3_api.redact(text)[:300].strip())
    print("\nSend Claude this output (no secret in it).")
    return 0


# ---------------------------------------------------------------- the import (26 Nov: AOWSIMPORT published in We are SDI)
# AOWSIMPORT's own description (getDescription, 26 Nov): one group GRP1 - I_MODIMP template, I_AOWSTA storage,
# I_EXEC execution type, I_RECORDSEP record separator, I_FILE the file (clob); O_REQNUM, O_STATUS, O_MESSA back.
# Only these templates: the BOM and route load files the Estimate portal writes, in exactly the format Ethan's
# migration loads used (0 errors). template -> (what, the load file's name part)
TEMPLATES = {"ZSDIITM": ("product", "ZSDIITM"), "YA004BOMP": ("bom", "YA00408BOM"), "ZSDIROU2": ("route", "ZSDIROU2")}
BY_WHAT = {w: t for t, (w, _) in TEMPLATES.items()}
# The Classic SOAP pool for each endpoint (Administration -> Web services -> Classic SOAP pools configuration).
# 26 Nov: SDIEST, We are SDI, user SDIJG, 1 channel, auto start. SDI Mig has none: its BOMs / routes stay by hand.
POOLS = {"X3ERPV12_ACUX3": "SDIEST"}


def pool_for(c):
    return POOLS.get(c.get("endpoint"))
SEP = "|"                       # record separator sent with the file; refused if a line contains it
ENC = "cp850"                   # the load files' code page (migration/rebuild/common.py write_load)


def file_lines(path):
    text = Path(path).read_bytes().decode(ENC)
    return [ln for ln in text.replace("\r\n", "\n").split("\n") if ln.strip()]


def import_lines(c, pool, template, lines):
    """THE WRITE: run the X3 import template on these lines, now (REALTIME). Same as Usage -> Imports by hand."""
    if template not in TEMPLATES:
        raise SystemExit(f"Refused: only {', '.join(TEMPLATES)} can be imported from here")
    if any(SEP in ln for ln in lines):
        raise SystemExit(f"Refused: a line contains '{SEP}', the record separator - it would split the line")
    inp = {"GRP1": {"I_MODIMP": template, "I_AOWSTA": "NO", "I_EXEC": "REALTIME", "I_RECORDSEP": SEP,
                    "I_FILE": SEP.join(lines + ["END"])}}
    code, _, text = call(c, "run", pool, "AOWSIMPORT", inp)
    p = parse(text)
    try:
        res = json.loads(p["result"] or "{}")
    except ValueError:
        res = {}
    g = res.get("GRP1", res) if isinstance(res, dict) else {}
    ok = code == 200 and p["status"] == "1" and str(g.get("O_STATUS")) == "1"
    return {"ok": ok, "http": code, "status": p["status"], "o_status": g.get("O_STATUS"), "o_message": g.get("O_MESSA"),
            "messages": p["messages"], "raw": None if ok else text[:6000]}


def _num(v):
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _same(a, b):
    x, y = _num(a), _num(b)
    return abs(x - y) < 1e-6 if x is not None and y is not None else str(a or "").strip() == str(b or "").strip()


def current(c, what, part):
    """What X3 holds now for this part, read live: {sequence / operation: (component, qty) or (work centre, set-up,
    run, description)}, or None if X3 couldn't be read. Keyed by line / operation number (estimates use one BOM
    code and one routing code; X3's internal _id for the BOM code isn't the plain "10")."""
    path, _, forms = x3_load.EXISTS[what]
    sel = ("sequence componentProduct { code } linkQuantity parentProduct { code }" if what == "bom" else
           "operationNumber mainWorkCenter { code } setupTime runTime operationDescription product { code }")
    lit = part.replace("\\", "\\\\").replace("'", "\\'")
    for form in forms:
        q = ("query { " + " { ".join(path) + f" {{ query(first: 500, filter: {json.dumps(form.format(c=lit))}) "
             f"{{ edges {{ node {{ {sel} }} }} }} " + "}" * len(path) + " }")
        try:
            d = x3_api.gql(c, q)
        except SystemExit:
            continue
        for p in path + ["query", "edges"]:
            d = (d or {}).get(p) if isinstance(d, dict) else d
        out = {}
        for e in d or []:
            n = e.get("node") or {}
            if what == "bom":
                if ((n.get("parentProduct") or {}).get("code")) == part:
                    out[str(n.get("sequence"))] = ((n.get("componentProduct") or {}).get("code"), n.get("linkQuantity"))
            elif ((n.get("product") or {}).get("code")) == part:
                out[str(n.get("operationNumber"))] = ((n.get("mainWorkCenter") or {}).get("code"), n.get("setupTime"),
                                                      n.get("runTime"), n.get("operationDescription") or "")
        return out
    return None


def from_file(what, lines):
    out = {}
    for ln in lines:
        f = ln.split(";") + [""] * 12
        if what == "bom":       # ITMREF BOMALT USESTA BOHSTRDAT BOHENDDAT BASQTY QTYCOD BOMSEQ CPNITMREF CPNTYP LIKQTY
            out[f[7]] = (f[8], f[10])
        else:                   # ITMREF ROUALT FCY USESTA TIMUOMCOD WORTYP OPENUM WST ROODES SETTIM OPETIM
            out[f[6]] = (f[7], f[9], f[10], f[8])
    return out


def before_file(what, lines, now):
    """X3's lines as they are now, in the same load-file layout (the file's other fields), so an update can be put
    back by importing this file with --update."""
    if not lines or not now:
        return []
    f0 = lines[0].split(";")
    out = []
    for k in sorted(now, key=lambda k: int(k) if str(k).isdigit() else 0):
        f = list(f0)
        if what == "bom":
            f[7], f[8], f[10] = k, now[k][0] or "", _txt(now[k][1])
        else:
            f[6], f[7], f[9], f[10], f[8] = k, now[k][0] or "", _txt(now[k][1]), _txt(now[k][2]), (now[k][3] or "")[:30]
        out.append(";".join(f))
    return out


def _txt(v):
    x = _num(v)
    return ("%.6f" % x).rstrip("0").rstrip(".") if x is not None else str(v or "")


def differences(what, now, new):
    """What the import would change, line by line. Empty when the file matches X3."""
    out = []
    show = (lambda v: f"{v[0]} x {v[1]}") if what == "bom" else (lambda v: f"{v[0]} set-up {v[1]} run {v[2]}")
    for k in sorted(set(now) | set(new), key=lambda k: int(k) if str(k).isdigit() else 0):
        lab = f"line {k}" if what == "bom" else f"operation {k}"
        if k not in now:
            out.append(f"NEW      {lab}: {show(new[k])}")
        elif k not in new:
            out.append(f"X3 ONLY  {lab}: {show(now[k])}  (not in the file)")
        elif not all(_same(x, y) for x, y in zip(now[k][:3], new[k][:3])):
            out.append(f"CHANGE   {lab}: {show(now[k])}  ->  {show(new[k])}")
    return out


def align(lines, now):
    """26 Nov, first update test: X3 changed only 4 of 8 lines when the estimate numbered the same 8 components the
    other way round (line 10 SHEETMETAL11 -> UPCSTICKER001 ...) - an import that swaps components between line
    numbers isn't reliable. So an update keeps X3's line number for every component X3 already has (only its
    quantity changes), and a new component goes on the next free line number. A component X3 has that the estimate
    no longer has is reported, not removed. Returns (lines, notes)."""
    seq_of = {}
    for k, v in now.items():
        seq_of.setdefault(v[0], k)
    top = max([int(k) for k in now if str(k).isdigit()] or [0])
    out, notes, used = [], [], set()
    for ln in lines:
        f = ln.split(";")
        cpn, seq = f[8], f[7]
        if cpn in seq_of and seq_of[cpn] not in used:
            new = seq_of[cpn]
        else:
            top = (top // 10 + 1) * 10
            new = str(top)
        used.add(new)
        if new != seq:
            notes.append(f"{cpn}: estimate line {seq} -> X3 line {new}" + ("" if cpn in seq_of else " (new component)"))
        f[7] = new
        out.append(";".join(f))
    gone = [f"{v[0]} (X3 line {k})" for k, v in now.items() if k not in used]
    return out, notes, gone


def part_of(what, line):
    f = line.split(";")
    return (f[1] if what == "product" else f[0]) if len(f) > 1 else ""


def prepare(c, template, lines, keep_numbers=False, product_coming=False):
    """Read X3 (live) and decide, for one load file: action create / update / same / skip / stop, and what an update
    would change. Nothing is sent. product_coming: the product is created in this same publish, just before."""
    what = TEMPLATES[template][0]
    P = {"what": what, "template": template, "lines": list(lines), "notes": [], "gone": [], "diff": [], "stops": [],
         "now": None}
    parents = sorted({part_of(what, ln) for ln in lines})
    if len(parents) != 1 or not parents[0]:
        P.update(action="stop", part=", ".join(parents))
        P["stops"].append(f"the {what} file must be for exactly one part (it has {len(parents)})")
        return P
    part = P["part"] = parents[0]
    if any(SEP in ln for ln in lines):
        P["stops"].append(f"a line contains '{SEP}' - it can't be sent")
    has_it = x3_load.exists(c, what, part)
    has_product = has_it if what == "product" else x3_load.exists(c, "product", part)
    P.update(has_product=has_product, has_it=has_it)
    if has_it is None:
        P["stops"].append(f"couldn't read X3 to see whether it already has {'the product' if what == 'product' else 'a ' + what} for {part}")
    if what != "product" and not has_product and not product_coming:
        P["stops"].append(f"the product {part} isn't in X3 (it has to be created first)")
    if what == "product":
        P["action"] = "skip" if has_it else "create"
    elif has_it:
        now = P["now"] = current(c, what, part)
        if now is None:
            P["stops"].append(f"couldn't read X3's {what} for {part} to compare")
        else:
            if what == "bom" and not keep_numbers:
                P["lines"], P["notes"], P["gone"] = align(lines, now)
            P["diff"] = differences(what, now, from_file(what, P["lines"]))
        P["action"] = "update" if P["diff"] else "same"
    else:
        P["action"] = "create"
    if P["stops"]:
        P["action"] = "stop"
    return P


def apply(c, pool, P, by="", src=""):
    """THE WRITE for one prepared file (action create or update): snapshot X3 first if it's an update, import,
    re-read X3, log. Returns the result."""
    if P["action"] not in ("create", "update"):
        raise SystemExit(f"Refused: nothing to send for this {P['what']} ({P['action']})")
    what, part, lines = P["what"], P["part"], P["lines"]
    before = None
    if P["action"] == "update" and P.get("now"):
        before = x3_load.HISTORY.parent / "x3_before_update" / f"{part}_{what}_{dt.datetime.now():%Y%m%d-%H%M%S}.txt"
        before.parent.mkdir(parents=True, exist_ok=True)
        before.write_bytes("".join(ln + "\r\n" for ln in before_file(what, lines, P["now"])).encode(ENC, "replace"))
    t0 = time.time()
    r = import_lines(c, pool, P["template"], lines)
    after = x3_load.exists(c, what, part)
    left = None
    if what != "product" and after:
        now2 = current(c, what, part)
        left = differences(what, now2, from_file(what, lines)) if now2 is not None else None
    elif what == "product":
        left = [] if after else None
    # a component / operation X3 has that the estimate doesn't is left in X3 on purpose - not a failure
    ok = bool(r["ok"] and after and left is not None and not [d for d in left if not d.startswith("X3 ONLY")])
    res = {"what": what, "part": part, "action": P["action"], "template": P["template"], "lines": len(lines),
           "ok": ok, "x3_ok": r["ok"], "o_status": r["o_status"], "o_message": r["o_message"], "messages": r["messages"][:50],
           "in_x3_after": after, "left": left, "before_saved": str(before) if before else None,
           "seconds": round(time.time() - t0, 1), "raw": r["raw"]}
    entry = {"at": dt.datetime.now().isoformat(timespec="seconds"), "by": by or os.environ.get("USERNAME", ""),
             "via": "soap AOWSIMPORT", "endpoint": c.get("endpoint"), "pool": pool, "file": str(src),
             **{k: v for k, v in res.items() if k != "raw"}}
    x3_load.HISTORY.parent.mkdir(parents=True, exist_ok=True)
    with open(x3_load.HISTORY, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")
    return res


def show_result(res):
    print(("DONE" if res["ok"] else "X3 REPORTED ERRORS - some lines may have changed, see below" if str(res["o_status"]) == "0"
           else "NOT DONE") + f" - {res['what']} {res['part']} ({res['action']}): O_STATUS {res['o_status']}, "
          f"message {res['o_message']!r}, in X3 after: {res['in_x3_after']}")
    for t, m in res["messages"][:40]:
        print(f"   X3 says{(' (' + t + ')') if t else ''}: {m[:300]}")
    if res["left"]:
        print(f"   Re-read X3: {len(res['left'])} difference(s) left:")
        for d_ in res["left"]:
            print("      " + d_)
    elif res["left"] == []:
        print("   Re-read X3: matches the file")
    if res["before_saved"]:
        print(f"   X3's {res['what']} as it was: {res['before_saved']}  (to put it back: import that file with --update --keep-numbers)")
    if res["raw"] and not res["ok"]:
        print("   X3's answer:", re.sub(r"\s+", " ", res["raw"])[:1500])


def do_import(a):
    c = x3_load.guard(x3_api.for_env(x3_load.load_conf(), a.env))
    a.pool = a.pool or pool_for(c) or ""
    if not a.pool:
        print(f"STOP: no SOAP pool for {c.get('endpoint')} (x3_soap.POOLS)")
        return 1
    lines = file_lines(a.file)
    P = prepare(c, a.template, lines, keep_numbers=a.keep_numbers)
    what = P["what"]
    print(f"X3: {c['site']} - endpoint {c.get('endpoint')} - pool {a.pool} - template {a.template} ({what})")
    print(f"File: {a.file} - {len(lines)} line(s) for {P.get('part') or 'nothing'}")
    print(f"X3 now: product {'exists' if P.get('has_product') else 'NOT FOUND' if P.get('has_product') is False else '?'}"
          + ("" if what == "product" else f"; {what} {'EXISTS' if P.get('has_it') else 'none' if P.get('has_it') is False else '?'}"))
    if P["notes"]:
        print("Update: X3's own line numbers kept for the components it already has:")
        for n_ in P["notes"]:
            print("   " + n_)
    for g_ in P["gone"]:
        print(f"   NOT IN THE ESTIMATE: {g_} - left in X3 as it is (remove it in X3 if it should go)")
    if P.get("now") is not None:
        print(f"Compared with X3 ({len(P['now'])} in X3, {len(P['lines'])} in the file):")
        for d_ in P["diff"] or ["no difference - nothing to change"]:
            print("   " + d_)
    stops = list(P["stops"])
    if P["action"] == "skip":
        stops.append(f"the product {P['part']} is already in X3 - products are never changed from here")
    if P["action"] == "same":
        stops.append("X3 already matches the file - nothing to send")
    if P["action"] == "update" and not a.update:
        stops.append(f"X3 already has a {what} for {P['part']}; changing it needs --update (estimators re-saving)")
    for s_ in stops:
        print("STOP:", s_)
    if stops:
        return 1
    if not a.apply:
        print(f"Dry run - nothing sent. To {P['action']}: add  --apply --confirm {P['part']}")
        return 0
    if a.confirm != P["part"]:
        print(f"Refused: --confirm must be the part code, {P['part']}")
        return 1
    res = apply(c, a.pool, P, a.by, a.file)
    show_result(res)
    print(f"Logged: {x3_load.HISTORY}")
    return 0 if res["ok"] else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    ck = sub.add_parser("check", help="read-only: sign-in to SOAP, and AOWSIMPORT's description")
    ck.add_argument("--env", choices=sorted(x3_api.ENVS), default="uat", help="mig = SDI Mig, uat = We are SDI")
    ck.add_argument("--pool", default="", help="the Classic SOAP pool alias")
    im = sub.add_parser("import", help="import one part's BOM or route file through X3's template (dry run without --apply)")
    im.add_argument("file", help="the .txt load file (one part)")
    im.add_argument("--template", required=True, choices=sorted(TEMPLATES))
    im.add_argument("--env", choices=sorted(x3_api.ENVS), default="uat")
    im.add_argument("--pool", default="", help="default: the endpoint's pool (SDIEST for We are SDI)")
    im.add_argument("--apply", action="store_true", help="without it, nothing is sent")
    im.add_argument("--confirm", default="", help="the part code, typed again")
    im.add_argument("--update", action="store_true", help="allow changing a BOM / route X3 already has")
    im.add_argument("--by", default="")
    im.add_argument("--keep-numbers", dest="keep_numbers", action="store_true",
                    help="BOM update: use the file's line numbers as they are (default: keep X3's for its components)")
    # (the pool defaults to the endpoint's: SDIEST for We are SDI)
    a = ap.parse_args(argv)
    return check(a) if a.cmd == "check" else do_import(a)


if __name__ == "__main__":
    sys.exit(main())
