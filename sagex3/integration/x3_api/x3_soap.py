"""Sage X3 classic SOAP web services - the route to BOMs and routes from the Estimate portal. Written 26 Nov 2026.

X3 (We are SDI) lets the API create products but not BOMs or routings; the JSON-template route stalled on X3
refusing the BOM nodes (26 Nov: ManufacturingBom / SalesBom "Invalid value" on a Json (API) template, "main node
name is required" on Operations). X3's standard SOAP web service AOWSIMPORT runs an EXISTING import template on the
file content it is sent - the same as Usage -> Imports by hand - so the portal can send the BOM and route files it
already makes through YA004BOMP and ZSDIROU2, which Ethan's migration loads ran with 0 errors.

    python x3_soap.py check --env uat [--pool ALIAS]
        Read-only. Can the "SDI Estimate loader" connection sign in to the SOAP service, and (with --pool) what
        does AOWSIMPORT take? Calls getDescription only - it describes the web service, it imports nothing.

The import call itself is added once `check` has shown X3's exact parameter layout (no guessing at a write).
Test environments only (same guard as x3_load.py). Nothing secret is printed.
"""
import argparse
import json
import re
import sys
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
    msgs = []
    for blk in re.findall(r"<messages\b[^>]*>(.*?)</messages>", xml or "", re.S):
        msgs.append(((_tag(blk, "type") or "").strip(), re.sub(r"\s+", " ", _tag(blk, "message") or "").strip()))
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
        elif code != 200 and not p["messages"]:
            print("      " + x3_api.redact(text)[:300].strip())
    print("\nSend Claude this output (no secret in it).")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    ck = sub.add_parser("check", help="read-only: sign-in to SOAP, and AOWSIMPORT's description")
    ck.add_argument("--env", choices=sorted(x3_api.ENVS), default="uat", help="mig = SDI Mig, uat = We are SDI")
    ck.add_argument("--pool", default="", help="the Classic SOAP pool alias")
    a = ap.parse_args(argv)
    return check(a)


if __name__ == "__main__":
    sys.exit(main())
