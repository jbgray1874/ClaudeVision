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
TEMPLATES = {"YA004BOMP": ("bom", "YA00408BOM"), "ZSDIROU2": ("route", "ZSDIROU2")}
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
            "messages": p["messages"], "raw": None if p["status"] == "1" else text[:4000]}


def _num(v):
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _same(a, b):
    x, y = _num(a), _num(b)
    return abs(x - y) < 1e-6 if x is not None and y is not None else str(a or "").strip() == str(b or "").strip()


def current(c, what, part):
    """What X3 holds now for this part, read live: {key: (component / work centre, qty / times...)}, or None."""
    path, _, forms = x3_load.EXISTS[what]
    sel = ("bomCode { _id } sequence componentProduct { code } linkQuantity parentProduct { code }" if what == "bom" else
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
                if ((n.get("parentProduct") or {}).get("code")) != part:
                    continue
                alt = str((n.get("bomCode") or {}).get("_id") or "").split("|")[-1].split("~")[-1]
                out[(alt, str(n.get("sequence")))] = ((n.get("componentProduct") or {}).get("code"), n.get("linkQuantity"))
            else:
                if ((n.get("product") or {}).get("code")) != part:
                    continue
                out[str(n.get("operationNumber"))] = ((n.get("mainWorkCenter") or {}).get("code"), n.get("setupTime"),
                                                      n.get("runTime"))
        return out
    return None


def from_file(what, lines):
    out = {}
    for ln in lines:
        f = ln.split(";") + [""] * 12
        if what == "bom":       # ITMREF BOMALT USESTA BOHSTRDAT BOHENDDAT BASQTY QTYCOD BOMSEQ CPNITMREF CPNTYP LIKQTY
            out[(f[1], f[7])] = (f[8], f[10])
        else:                   # ITMREF ROUALT FCY USESTA TIMUOMCOD WORTYP OPENUM WST ROODES SETTIM OPETIM
            out[f[6]] = (f[7], f[9], f[10])
    return out


def differences(what, now, new):
    """Lines: what the import would change, in words. Empty when the file matches X3."""
    out = []
    for k in sorted(set(now) | set(new), key=lambda k: [int(x) if str(x).isdigit() else 0 for x in (k if isinstance(k, tuple) else (k,))]):
        lab = f"line {k[1]}" if what == "bom" else f"operation {k}"
        if k not in now:
            out.append(f"NEW      {lab}: {' / '.join(str(x) for x in new[k])}")
        elif k not in new:
            out.append(f"X3 ONLY  {lab}: {' / '.join(str(x) for x in now[k])}  (not in the file - X3 may keep it)")
        elif not all(_same(x, y) for x, y in zip(now[k], new[k])):
            out.append(f"CHANGE   {lab}: {' / '.join(str(x) for x in now[k])}  ->  {' / '.join(str(x) for x in new[k])}")
    return out


def do_import(a):
    c = x3_load.guard(x3_api.for_env(x3_load.load_conf(), a.env))
    what, stem = TEMPLATES[a.template]
    lines = file_lines(a.file)
    parents = sorted({ln.split(";")[0] for ln in lines})
    print(f"X3: {c['site']} - endpoint {c.get('endpoint')} - pool {a.pool} - template {a.template} ({what})")
    print(f"File: {a.file} - {len(lines)} line(s) for {', '.join(parents) or 'nothing'}")
    if len(parents) != 1:
        print("STOP: the file must be for exactly one part")
        return 1
    part = parents[0]
    has_product, has_it = x3_load.exists(c, "product", part), x3_load.exists(c, what, part)
    print(f"X3 now: product {part} {'exists' if has_product else 'NOT FOUND' if has_product is False else 'could not check'}; "
          f"{what} {'EXISTS' if has_it else 'none' if has_it is False else 'could not check'}")
    if has_it:
        now = current(c, what, part)
        if now is None:
            print("   (couldn't read X3's lines to compare)")
        else:
            diff = differences(what, now, from_file(what, lines))
            print(f"Compared with X3 ({len(now)} {'lines' if what == 'bom' else 'operations'} in X3, {len(lines)} in the file; "
                  f"{'component / link qty' if what == 'bom' else 'work centre / set-up / run'}):")
            for d_ in diff or ["no difference - an --update would re-save the same values"]:
                print("   " + d_)
    stop = []
    if not has_product:
        stop.append(f"the product {part} must be in X3 first (the portal creates it before the BOM and route)")
    if has_it is None:
        stop.append(f"couldn't read X3 to see whether {part} already has a {what}")
    if has_it and not a.update:
        stop.append(f"X3 already has a {what} for {part}; changing it needs --update (estimators re-saving an estimate)")
    for s_ in stop:
        print("STOP:", s_)
    if stop:
        return 1
    if not a.apply:
        print(f"Dry run - nothing sent. To import: add  --apply --confirm {part}")
        return 0
    if a.confirm != part:
        print(f"Refused: --confirm must be the part code, {part}")
        return 1
    t0 = time.time()
    r = import_lines(c, a.pool, a.template, lines)
    after = x3_load.exists(c, what, part)
    entry = {"at": dt.datetime.now().isoformat(timespec="seconds"), "by": a.by or os.environ.get("USERNAME", ""),
             "via": "soap AOWSIMPORT", "endpoint": c.get("endpoint"), "pool": a.pool, "template": a.template,
             "part": part, "what": what, "lines": len(lines), "update": bool(has_it), "file": str(a.file),
             "ok": r["ok"], "o_status": r["o_status"], "o_message": r["o_message"], "messages": r["messages"][:50],
             "in_x3_after": after, "seconds": round(time.time() - t0, 1)}
    x3_load.HISTORY.parent.mkdir(parents=True, exist_ok=True)
    with open(x3_load.HISTORY, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")
    print(f"{'IMPORTED' if r['ok'] else 'NOT IMPORTED'} - HTTP {r['http']}, status {r['status']}, "
          f"O_STATUS {r['o_status']}, message {r['o_message']!r}")
    for t, m in r["messages"][:40]:
        print(f"   X3 says{(' (' + t + ')') if t else ''}: {m[:300]}")
    print(f"X3 after: {what} for {part} {'found' if after else 'NOT found' if after is False else 'could not check'}")
    if r["raw"]:
        print("X3's answer:", re.sub(r"\s+", " ", r["raw"])[:1500])
    print(f"Logged: {x3_load.HISTORY}")
    return 0 if r["ok"] else 1


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
    im.add_argument("--pool", required=True)
    im.add_argument("--apply", action="store_true", help="without it, nothing is sent")
    im.add_argument("--confirm", default="", help="the part code, typed again")
    im.add_argument("--update", action="store_true", help="allow changing a BOM / route X3 already has")
    im.add_argument("--by", default="")
    a = ap.parse_args(argv)
    return check(a) if a.cmd == "check" else do_import(a)


if __name__ == "__main__":
    sys.exit(main())
