"""Read-only Sage X3 API client: GraphQL (Sage X3 Services) and REST (Syracuse $query). Written 20 Nov 2026.

It reads the data sets Live Orders needs straight from X3, with no browser and no Sage ID check. It
authenticates as a **connected application**: X3 Administration -> Authentication -> Connected
applications gives a client ID and a secret, and each request carries a short-lived token (a JWT
signed with that secret).

    python x3_api.py setup             # asks for the site, client ID, secret, user, endpoint; saves them privately
    python x3_api.py probe             # tries the URL / token forms and saves the one X3 accepts
    python x3_api.py diagnose          # if probe fails: how X3 answers each sign-in, and finds the token exchange
    python x3_api.py claims            # changes one thing in the token at a time, to see what X3 checks first
    python x3_api.py schema            # lists what the GraphQL API offers (works orders, stock, orders ...)
    python x3_api.py draft             # writes api_datasets.json for the pinned nodes (NODES) from the schema
    python x3_api.py pull --limit 3    # trial: 3 rows per data set to SDI_X3_samples, prints the column names
    python x3_api.py columns [names]   # the column names each data set will produce (no call to X3)
    python x3_api.py pull [names]      # pulls the data sets in api_datasets.json to the exports folder
    python x3_api.py rest ITMMASTER ITMMASTER --count 5          # one REST query
    python x3_api.py query my.graphql                            # one GraphQL query

**Read-only by design:** GraphQL mutations are refused, REST is GET only, and nothing here writes to X3.
Give the connected application's user an X3 profile with enquiry rights only, so X3 enforces it too.

**Private:** the settings file (%USERPROFILE%\\.sdi\\x3_api.json) holds the secret. Never in git or email.
The secret is never printed or logged.

Sage's documentation (developer.sage.com) could not be read from where this was written, so the exact
URL and token form are found by `probe` on the site itself, not assumed. Confirmed in public sources:
client ID + secret (shown once), a JWT signed with the secret (iss = client ID, iat / exp within the
connected application's token validity), sent as a Bearer token with an x-xtrem-endpoint header.
Found on our training site (20 Nov, `claims` test): endpoint X3ERPV12_SDIMIG, aud present but EMPTY, sub = the
allowed user's login; GraphQL at /xtrem/api.
"""
import argparse
import base64
import csv
import datetime as dt
import getpass
import hashlib
import hmac
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

HERE = Path(__file__).parent
CONF = Path(os.environ.get("X3_API_CONFIG", Path.home() / ".sdi" / "x3_api.json"))
DATASETS = HERE / "api_datasets.json"
EXPORTS = Path(os.environ.get("X3_EXPORT_DIR", Path.home() / "SDI_X3_exports"))
GRAPHQL_PATHS = ["/xtrem/api", "/api", "/xtrem/graphql", "/graphql"]
MUTATION = re.compile(r"(^|[}\s])mutation\b\s*\w*\s*[({]", re.I)
PAUSE = 1.0                                       # seconds between pages: keep it gentle
PAGE = 50                                         # rows per request (200 x 159 fields knocked X3 Services over, 20 Nov)
RETRY_WAITS = (15, 45, 120)                       # back off on 5xx / connection errors, then give that data set up


# ---------------------------------------------------------------- settings
def load_conf():
    if not CONF.exists():
        sys.exit(f"No settings yet: run  python x3_api.py setup   (they go in {CONF})")
    return json.loads(CONF.read_text())


def save_conf(c):
    CONF.parent.mkdir(parents=True, exist_ok=True)
    CONF.write_text(json.dumps(c, indent=2))
    try:
        os.chmod(CONF, 0o600)
    except OSError:
        pass


def setup(_):
    c = json.loads(CONF.read_text()) if CONF.exists() else {}
    ask = lambda k, q, d="": input(f"{q} [{c.get(k, d)}]: ").strip() or c.get(k, d)
    c["site"] = ask("site", "Site address", "https://sdi-displays-trn.uk.sagex3.com").rstrip("/")
    c["folder"] = ask("folder", "X3 folder", "SDIMIG")
    c["endpoint"] = ask("endpoint", "Endpoint name (Administration -> Endpoints, the one for that folder)", c["folder"])
    c["connector"] = ask("connector", "X3 Connector chosen on the connected application", "x3-services_X3ERPV12")
    c["client_id"] = ask("client_id", "Connected application client ID")
    c["user"] = ask("user", "X3 user the connected application runs as (its login)")
    s = getpass.getpass("Connected application secret (typing is hidden; Enter keeps the saved one): ").strip()
    if s:
        c["secret"] = s
    c["token_seconds"] = int(ask("token_seconds", "Token lifetime in seconds (<= the app's token validity)", 300))
    save_conf(c)
    print(f"Saved to {CONF} - private: never in git or email. Next: python x3_api.py probe")


# ---------------------------------------------------------------- token
def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def make_jwt(c, aud=None):
    """HS256 JWT signed with the connected application's secret (no third-party library needed)."""
    now = int(time.time())
    # NO jti: with a token ID, X3 looks the token up in its own issued-token list, finds nothing and fails with
    # "Cannot read properties of null (reading 'info')" (20 Nov, training). The claims test without jti got in.
    # The whole life (exp - iat) must stay inside the connected application's "Tokens validity" (300 s here):
    # iat now-30 / exp now+300 = 330 s got "Error 27: Invalid token"; the claims test's 270 s got in (20 Nov).
    life = max(60, int(c.get("token_seconds", 300)) - 30)
    claims = {"iss": c["client_id"], "sub": c["user"], "iat": now - 30, "exp": now - 30 + life}
    aud = c.get("aud", "empty") if aud is None else aud
    if aud == "empty":                       # what X3 accepts (20 Nov, training): aud present but empty
        claims["aud"] = ""
    elif aud == "endpoint":
        claims["aud"] = c["endpoint"]
    elif aud == "connector":
        claims["aud"] = c.get("connector", "")
    elif aud == "url":
        claims["aud"] = c["site"] + c.get("graphql_path", GRAPHQL_PATHS[0])
    elif aud:
        claims["aud"] = aud
    head = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64(json.dumps(claims, separators=(",", ":")).encode())
    sig = hmac.new(c["secret"].encode(), f"{head}.{body}".encode(), hashlib.sha256).digest()
    return f"{head}.{body}.{_b64(sig)}"


_TOKEN = {}


def bearer(c, aud=None):
    """The token to send. If diagnose found an exchange (token_url), swap our signed JWT for X3's access token
    (cached until shortly before it expires); otherwise send the signed JWT itself."""
    if not c.get("token_url"):
        return make_jwt(c, aud)
    if _TOKEN.get("exp", 0) > time.time() + 20:
        return _TOKEN["tok"]
    code, _, text = exchange(c, c["token_url"], c["token_mode"])
    try:
        out = json.loads(text)
        tok = out["access_token"]
    except (ValueError, KeyError, TypeError):
        raise SystemExit(f"Token exchange {code}: {redact(text)[:300]}")
    _TOKEN.update(tok=tok, exp=time.time() + int(out.get("expires_in") or c.get("token_seconds", 300)))
    return tok


TOKEN_PATHS = ["/auth/oauth2/token", "/oauth2/token", "/auth/token", "/xtrem/auth/token", "/api/auth/token",
               "/auth/oauth/token", "/oauth/token", "/token", "/xtrem/token", "/syracuse-main/token"]
TOKEN_MODES = ["jwt-bearer", "client-credentials", "client-credentials-basic", "json-credentials"]


def exchange(c, path, mode):
    url = c["site"] + path
    h = {"Accept": "application/json", "User-Agent": "sdi-x3-readonly/1"}
    if mode == "jwt-bearer":
        data = urllib.parse.urlencode({"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                       "assertion": make_jwt(c)}).encode()
        h["Content-Type"] = "application/x-www-form-urlencoded"
    elif mode == "client-credentials":
        data = urllib.parse.urlencode({"grant_type": "client_credentials", "client_id": c["client_id"],
                                       "client_secret": c["secret"]}).encode()
        h["Content-Type"] = "application/x-www-form-urlencoded"
    elif mode == "client-credentials-basic":
        data = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode()
        h["Content-Type"] = "application/x-www-form-urlencoded"
        h["Authorization"] = "Basic " + base64.b64encode(f"{c['client_id']}:{c['secret']}".encode()).decode()
    else:
        data = json.dumps({"grant_type": "client_credentials", "client_id": c["client_id"],
                           "client_secret": c["secret"], "user": c["user"]}).encode()
        h["Content-Type"] = "application/json"
    return raw("POST", url, h, data)


def redact(text):
    """Hide anything token-like before printing (access tokens, JWTs, secrets)."""
    return re.sub(r"[A-Za-z0-9_\-+/=.]{24,}", lambda m: f"<{len(m.group(0))} chars hidden>", text or "")


def raw(method, url, hdrs, data=None, timeout=60):
    if method not in ("GET", "POST"):
        raise ValueError("read-only client")
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as e:
        return 0, {}, str(e)


def diagnose(_):
    """Work out how X3 wants to be signed in to. Prints status codes and X3's messages, never a secret or token."""
    c = load_conf()
    gq = c["site"] + "/xtrem/api"
    body = json.dumps({"query": "{ __typename }"}).encode()
    base = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "sdi-x3-readonly/1",
            "x-xtrem-endpoint": c.get("endpoint", "")}

    def show(label, code, hd, text):
        www = hd.get("WWW-Authenticate") or hd.get("www-authenticate") or ""
        loc = hd.get("Location") or hd.get("location") or ""
        print(f"  {label:<44} {code}  {redact(text)[:140].strip()}" + (f"  [WWW-Authenticate: {redact(www)}]" if www else "")
              + (f"  [-> {loc[:80]}]" if loc else ""))

    print("A. How X3 answers different sign-ins on /xtrem/api:")
    show("no sign-in", *raw("POST", gq, base, body))
    show("Bearer not-a-token", *raw("POST", gq, dict(base, Authorization="Bearer abc"), body))
    show("JWT signed with a WRONG secret", *raw("POST", gq, dict(base, Authorization="Bearer " + make_jwt(dict(c, secret="wrong"))), body))
    show("JWT with an unknown client ID", *raw("POST", gq, dict(base, Authorization="Bearer " + make_jwt(dict(c, client_id="unknown"))), body))
    show("JWT, our client ID and secret", *raw("POST", gq, dict(base, Authorization="Bearer " + make_jwt(c)), body))
    print("B. Looking for the token exchange (where X3 issues its own access token):")
    for path in TOKEN_PATHS:
        for mode in TOKEN_MODES:
            code, hd, text = exchange(c, path, mode)
            if code == 404 and mode != TOKEN_MODES[0]:
                continue
            show(f"{path} {mode}", code, hd, text)
            try:
                tok = json.loads(text).get("access_token")
            except (ValueError, AttributeError):
                tok = None
            if code == 200 and tok:
                for eh in (True, False):
                    h = dict(base, Authorization="Bearer " + tok)
                    if not eh:
                        h.pop("x-xtrem-endpoint")
                    for gpath in ("/xtrem/api", "/xtrem/graphql"):
                        code2, hd2, text2 = raw("POST", c["site"] + gpath, h, body)
                        show(f"   access token -> {gpath} {'with' if eh else 'no'} endpoint", code2, hd2, text2)
                        if code2 == 200 and '"data"' in text2:
                            c.update(token_url=path, token_mode=mode, graphql_path=gpath, endpoint_header=eh)
                            save_conf(c)
                            print(f"\nSIGNED IN: token from {path} ({mode}), GraphQL {gpath}. Saved. Next: python x3_api.py schema")
                            return
    print("\nNot signed in yet. Send Claude everything above (no secret or token is shown).")


def _jwt(claims, secret, head=None, alg="HS256"):
    h = _b64(json.dumps(head or {"alg": alg, "typ": "JWT"}, separators=(",", ":")).encode())
    b = _b64(json.dumps(claims, separators=(",", ":")).encode())
    dig = {"HS256": hashlib.sha256, "HS512": hashlib.sha512}.get(alg, hashlib.sha256)
    return f"{h}.{b}.{_b64(hmac.new(secret.encode(), f'{h}.{b}'.encode(), dig).digest())}"


def claims_test(_):
    """Change one thing in the token at a time; a different message from X3 shows what it checks first.
    Prints status codes and X3's messages only - never the secret or a token."""
    c = load_conf()
    now = int(time.time())
    base = {"iss": c["client_id"], "sub": c["user"], "aud": c["endpoint"], "iat": now - 30, "exp": now + 240}   # 270 s life
    gq = c["site"] + "/xtrem/api"
    rest = f"{c['site']}/api1/x3/erp/{c['folder']}/ITMMASTER?representation=ITMMASTER.$query&count=1"
    body = json.dumps({"query": "{ __typename }"}).encode()
    hdr = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "sdi-x3-readonly/1",
           "x-xtrem-endpoint": c["endpoint"]}
    drop = lambda k: {x: v for x, v in base.items() if x != k}
    cases = [
        ("baseline (iss, sub, aud=endpoint, iat, exp)", base, {}),
        ("sub = a user that doesn't exist", dict(base, sub="NOSUCHUSER"), {}),
        ("no sub", drop("sub"), {}),
        ("no aud", drop("aud"), {}),
        ("aud empty", dict(base, aud=""), {}),
        ("no iss", drop("iss"), {}),
        ("client_id claim instead of iss", dict(drop("iss"), client_id=c["client_id"]), {}),
        ("iat / exp in milliseconds", dict(base, iat=(now - 30) * 1000, exp=(now + 240) * 1000), {}),
        ("expired token", dict(base, iat=now - 900, exp=now - 600), {}),
        ("header without typ", base, {"head": {"alg": "HS256"}}),
        ("header with kid = client ID", base, {"head": {"alg": "HS256", "typ": "JWT", "kid": c["client_id"]}}),
        ("signed HS512", base, {"alg": "HS512"}),
    ]
    print("Each line: what was changed -> X3's status and message (GraphQL /xtrem/api)")
    for label, cl, kw in cases:
        tok = _jwt(cl, c["secret"], **kw)
        code, hd, text = raw("POST", gq, dict(hdr, Authorization="Bearer " + tok), body)
        print(f"  {label:<46} {code}  {redact(text)[:130].strip()}")
    tok = _jwt(base, c["secret"])
    for label, url, h in [
        ("token as ?access_token= (no header)", gq + "?access_token=" + tok, hdr),
        ("REST GET with the baseline token", rest, {k: v for k, v in hdr.items() if k != "x-xtrem-endpoint"}),
        ("lower-case 'bearer'", gq, dict(hdr, Authorization="bearer " + tok)),
    ]:
        if "Authorization" not in h and "access_token" not in url:
            h = dict(h, Authorization="Bearer " + tok)
        code, hd, text = raw("GET" if "api1" in url else "POST", url, h, None if "api1" in url else body)
        print(f"  {label:<46} {code}  {redact(text)[:130].strip()}")
    print("\nSend Claude everything above (no secret or token is shown).")


def headers(c, aud=None, endpoint_header=True):
    h = {"Authorization": "Bearer " + bearer(c, aud), "Accept": "application/json",
         "Content-Type": "application/json", "User-Agent": "sdi-x3-readonly/1"}
    if endpoint_header and c.get("endpoint"):
        h["x-xtrem-endpoint"] = c["endpoint"]
    return h


def http(method, url, hdrs, body=None, timeout=60):
    if method != "POST" and method != "GET":
        raise ValueError("read-only client: GET / POST (GraphQL queries) only")
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                 headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as e:
        return 0, str(e)


# ---------------------------------------------------------------- GraphQL
class GqlError(SystemExit):
    """X3 answered with GraphQL errors. Keeps X3's error list (with each error's path) and any partial data."""
    def __init__(self, msg, errors=None, data=None):
        super().__init__(msg)
        self.errors, self.data = errors or [], data


def gql(c, query, variables=None):
    if MUTATION.search(query):
        raise SystemExit("Refused: this client is read-only (no GraphQL mutations).")
    url = c["site"] + c.get("graphql_path", GRAPHQL_PATHS[0])
    for wait in RETRY_WAITS + (None,):
        code, text = http("POST", url, headers(c, endpoint_header=c.get("endpoint_header", True)),
                          {"query": query, "variables": variables or {}}, timeout=120)
        if (code == 0 or code >= 500) and wait is not None:   # X3 struggling: back off, don't push on
            print(f"   X3 answered {code} ({redact(text)[:80]}) - waiting {wait}s before one more try")
            time.sleep(wait)
            continue
        break
    try:
        out = json.loads(text)
    except ValueError:
        raise SystemExit(f"GraphQL {code}: not JSON - {text[:300]}")
    if not isinstance(out, dict):
        raise SystemExit(f"GraphQL {code}: {text[:300]}")
    if code != 200 or out.get("errors"):
        raise GqlError(f"GraphQL {code}: {json.dumps(out.get('errors') or out)[:600]}", out.get("errors"), out.get("data"))
    return out["data"]


def probe(_):
    """Try each URL / audience / header form with a harmless query; save the first one X3 accepts."""
    c = load_conf()
    tried, found = [], None
    forms = [(p, a, e) for p in ([c["graphql_path"]] if c.get("graphql_path") else []) + GRAPHQL_PATHS
             for a in ("empty", "endpoint", "connector", "url", "") for e in (True, False)]
    for path, aud, eh in dict.fromkeys(forms):
        cc = dict(c, graphql_path=path)
        code, text = http("POST", c["site"] + path, headers(cc, aud, eh), {"query": "{ __typename }"})
        tried.append((path, aud or "none", "x-xtrem-endpoint" if eh else "-", code, text[:160].replace("\n", " ")))
        if code == 200 and '"data"' in text and '"errors"' not in text:
            found = (path, aud, eh)
            break
    if found:
        c.update(graphql_path=found[0], aud=found[1], endpoint_header=found[2])
        save_conf(c)
        print(f"GraphQL OK: {c['site']}{found[0]}  (aud={found[1] or 'none'}, "
              f"endpoint header={'yes' if found[2] else 'no'}) - saved")
    else:
        print("GraphQL: no form accepted. What X3 said (send this to Claude; it holds no secret):")
        for t in tried:
            print("  ", *t)
    # REST, with the same token
    url = f"{c['site']}/api1/x3/erp/{c['folder']}/ITMMASTER?representation=ITMMASTER.$query&count=1"
    code, text = http("GET", url, headers(c, endpoint_header=False))
    print(f"REST {code}: {'OK' if code == 200 else text[:200]}")
    if code == 200:
        c["rest_ok"] = True
        save_conf(c)


INTROSPECT = """{ __schema { queryType { name } types { name kind fields { name
  type { name kind ofType { name kind ofType { name kind ofType { name kind } } } } } } } }"""


def _base(t):
    while t.get("ofType"):
        t = t["ofType"]
    return t


def load_schema(c, refresh=False):
    f = CONF.parent / "x3_schema.json"
    if refresh or not f.exists():
        f.write_text(json.dumps(gql(c, INTROSPECT)))
    s = json.loads(f.read_text())["__schema"]
    return s["queryType"]["name"], {t["name"]: t for t in s["types"]}


def schema(a):
    c = load_conf()
    root, types = load_schema(c, refresh=True)
    words = [w.lower() for w in (a.words or ["work", "manuf", "mfg", "stock", "salesorder", "purchaseorder",
                                             "product", "item", "billofmaterial", "bom", "routing", "operation"])]
    print(f"Schema saved ({len(types)} types). Data reachable from the root:")
    for top in types[root]["fields"] or []:
        tt = types.get(_base(top["type"])["name"], {})
        for f in tt.get("fields") or []:
            hit = any(w in f["name"].lower() for w in words)
            print(f"  {'*' if hit else ' '} {top['name']}.{f['name']}")
    print("* = matches", ", ".join(words))


# ---------------------------------------------------------------- draft data sets from the schema
SCALAR = {"SCALAR", "ENUM"}


def selection(types, tname, depth, seen=()):
    """Scalars of a type; object references one level deeper (their scalars only); connections skipped."""
    out = []
    for f in types.get(tname, {}).get("fields") or []:
        b = _base(f["type"])
        if b["kind"] in SCALAR:
            out.append(f["name"])
        elif b["kind"] == "OBJECT" and depth > 0 and b["name"] not in seen and not _is_conn(types, b["name"]):
            plain = [x for x in selection(types, b["name"], 0, seen + (tname,)) if "{" not in x]
            sub = [x for x in ("code", "id", "_id", "number", "name", "description", "localizedDescription") if x in plain][:3] or plain[:2]
            if sub:
                out.append(f"{f['name']} {{ {' '.join(sub)} }}")
    return out


def _is_conn(types, tname):
    fs = {f["name"] for f in types.get(tname, {}).get("fields") or []}
    return "query" in fs or "edges" in fs


# The X3 GraphQL nodes Live Orders reads, as listed by `schema` on our training site (20 Nov). Pinned, because
# matching by name picks the wrong ones (workOrderMaterialLine before workOrder). Line nodes are read directly.
NODES = {
    "works_orders":  ["x3Manufacturing", "workOrder"],
    "wo_products":   ["x3Manufacturing", "workOrderProductLine"],
    "wo_materials":  ["x3Manufacturing", "workOrderMaterialLine"],
    "wo_operations": ["x3Manufacturing", "workOrderOperationLine"],
    "stock":         ["x3StockData", "stock"],
    "so_lines":      ["x3Sales", "salesOrderLine"],
    "po_lines":      ["x3Purchasing", "purchaseOrderLine"],
    "products":      ["x3MasterData", "product"],
    "boms":          ["x3ManufacturingData", "manufacturingBomLine"],
    "routes":        ["x3Manufacturing", "routingOperation"],
    "work_centres":  ["x3ManufacturingData", "workCenter"],
}
LIVE_ORDERS = {"works_orders", "wo_products", "wo_materials", "stock", "so_lines", "po_lines", "products", "boms", "routes"}
# Only the fields Live Orders uses (x3_columns.json) - asking for all 159-182 fields with their linked records
# overloaded X3 Services on 20 Nov. `draft --all` writes every field instead (for exploring, with --limit).
LEAN = {
    "works_orders":  "number orderStatus productionSite { code } startDate endDate plannedQuantity totalCompletedQuantity "
                     "remainingQuantity allocationStatus _createStamp",
    "wo_products":   "workOrder { number } lineNumber product { code } majorProductVersion { code } salesOrder customer { code } "
                     "workOrderStatus lineStatus expectedQuantity releaseQuantity totalCompletedQuantity actualRejectedQuantity "
                     "remainingQuantity _createStamp startDate endDate",
    "wo_materials":  "number { number } lineNumber { _id } bomSequence product { code } requirementDate requiredQuantity "
                     "consumedQuantity allocatedQuantity shortageQuantity materialStatus allocationStatus",
    "wo_operations": "workOrder { number } operationNumber expectedWorkCenter { code } operationStatus startDate endDate "
                     "setupTime runTime unitTime expectedQuantity completedQuantity",
    "stock":         "stockSite { code } product { _id } lot location { code } status { code } quantityInStockUnit "
                     "allocatedQuantity availableQuantity",
    "so_lines":      "salesOrder { id } lineNumber salesSite { code } shippingSite { code } soldToCustomer { _id } orderDate "
                     "requestedDeliveryDate product { code } productDescriptionInUserLanguage salesUnit { code } "
                     "quantityInSalesUnitOrdered quantityInSalesUnitDelivered grossPrice lineStatus",
    "po_lines":      "purchaseOrder { id } lineNumber purchaseSite { code } receiptSite { code } orderFromSupplier { _id } "
                     "orderDate product { code } productDescriptionInUserLanguage purchaseUnit { code } "
                     "quantityInPurchaseUnitOrdered quantityInPurchaseUnitReceived remainingQuantityToReceiveInPurchaseUnit "
                     "expectedReceiptDate grossPrice currency { code } isClosed lineStatus",
    "products":      "code productCategory { code } localizedDescription1 localizedDescription2 localizedDescription3 "
                     "stockUnit { code } productStatus isManufactured isPurchased",
    "boms":          "parentProduct { code } bomCode { _id } sequence componentProduct { code } linkQuantity "
                     "linkQuantityInBomUnit unit { code } validityStartDate validityEndDate",
    "routes":        "product { code } site { code } routing { _id } operationNumber alternateIndex mainWorkCenter { code } "
                     "operationDescription setupTime runTime rate baseQuantity managementUnit runTimeType",
    "work_centres":  "code description manufacturingSite { code } workCenterGroup { code }",
}


def draft(a):
    """Write api_datasets.json from the schema: every pinned node with all its plain fields, and the code of each
    linked record (product.code, site.code ...). Live Orders' own data sets are enabled. Read-only queries only."""
    c = load_conf()
    root, types = load_schema(c)
    tops = {f["name"]: _base(f["type"])["name"] for f in types[root]["fields"] or []}
    found, missing = {}, []
    for name, (top, node) in NODES.items():
        holder = types.get(tops.get(top, ""), {})
        f = next((x for x in holder.get("fields") or [] if x["name"] == node), None)
        node_t = _node_type(types, _base(f["type"])["name"]) if f else None
        if not node_t:
            missing.append(f"{top}.{node}")
            continue
        sel = " ".join(selection(types, node_t, 1)) if a.all or name not in LEAN else LEAN[name]
        found[name] = {"path": [top, node], "fields": sel, "filter": "", "enabled": name in LIVE_ORDERS}
        print(f"  {name:<14} {top}.{node}: {len(flat_names(sel))} fields")
    out = DATASETS if not DATASETS.exists() or a.force else HERE / "api_datasets.draft.json"
    out.write_text(json.dumps(found, indent=2))
    print(f"Wrote {out}" + (f"; not in this site's schema: {', '.join(missing)}" if missing else ""))
    if out != DATASETS:
        print("api_datasets.json already exists - kept. Use  draft --force  to replace it.")


def _node_type(types, conn_t):
    """X3 node -> query(...) -> edges -> node: return the node's type name."""
    t = types.get(conn_t, {})
    for f in t.get("fields") or []:
        if f["name"] == "query":
            return _node_type(types, _base(f["type"])["name"])
        if f["name"] == "edges":
            edge = types.get(_base(f["type"])["name"], {})
            return next((_base(x["type"])["name"] for x in edge.get("fields") or [] if x["name"] == "node"), None)
    return conn_t if t.get("fields") else None


def _first_lines(types, node_t):
    for f in types.get(node_t, {}).get("fields") or []:
        if f["name"].lower() in ("lines", "orderlines", "detail", "details") and _is_conn(types, _base(f["type"])["name"]):
            return f["name"]
    return ""


# ---------------------------------------------------------------- pull
def flatten(d, pre=""):
    out = {}
    for k, v in (d or {}).items():
        key = f"{pre}{k}"
        if isinstance(v, dict) and "edges" not in v and "query" not in v:
            out.update(flatten(v, key + "."))
        elif not isinstance(v, (dict, list)):
            out[key] = v
    return out


def _edges(v):
    if isinstance(v, dict) and "query" in v:
        v = v["query"]
    return [e["node"] for e in (v or {}).get("edges", [])]


def _bad_edge(errors):
    """The first record X3 couldn't return, from its errors' paths [..., "edges", 21, "node", ...] -> (21, message)."""
    hits = []
    for e in errors or []:
        p = e.get("path") or []
        if "edges" in p:
            i = p.index("edges")
            if i + 1 < len(p) and isinstance(p[i + 1], int):
                hits.append((p[i + 1], e.get("message", "")))
    return min(hits) if hits else (None, "")


def pull_graphql(c, ds, page=PAGE, limit=0, notes=None):
    """Page through one X3 node. A record X3 can't return (20 Nov: routing operations with no main work centre -
    "RoutingOperation.mainWorkCenter: Mandatory property") fails its whole page, so: take the records before it,
    step over it by its cursor, carry on - and count what was skipped in  notes  (never silently)."""
    if limit:
        page = limit
    path, fields, flt, explode = ds["path"], ds["fields"], ds.get("filter", ""), ds.get("explode", "")
    sel = fields + (f" {explode} {{ query(first: 500) {{ edges {{ node {{ {ds.get('line_fields', '')} }} }} }} }}"
                    if explode and ds.get("line_fields") else "")

    def q(first, edge):
        args = f"first: {first}, after: $after" + (f", filter: {json.dumps(flt)}" if flt else "")
        return ("query($after: String) { " + " { ".join(path) + f" {{ query({args}) {{ edges {{ {edge} }} "
                "pageInfo { endCursor hasNextPage } } " + "}" * len(path) + " }")

    def conn_of(data):
        for p in path + ["query"]:
            data = (data or {}).get(p)
        return data

    rows, after, skipped, why = [], None, 0, ""

    def take(conn):
        nonlocal skipped
        for e in conn.get("edges") or []:
            node = (e or {}).get("node")
            if node is None:                                   # partial answer: X3 nulled this record
                skipped += 1
                continue
            head = flatten(node)
            lines = _edges(node.get(explode)) if explode else []
            rows.extend([dict(head, **{f"{explode}.{k}": v for k, v in flatten(l).items()}) for l in lines] or [head])

    def done():
        if skipped and notes is not None:
            notes.append(f"skipped {skipped} record(s) X3 couldn't return: {why[:200]}")
        return rows

    while True:
        try:
            conn = conn_of(gql(c, q(page, f"node {{ {sel} }}"), {"after": after}))
        except GqlError as e:
            idx, msg = _bad_edge(e.errors)
            part = conn_of(e.data)
            if part and part.get("edges") is not None and part.get("pageInfo"):
                why = why or msg                               # X3 sent the rest of the page: use it
                conn = part
            elif idx is None or limit:
                raise
            else:                                              # the whole page refused: step over record idx
                why = why or msg
                if idx:
                    take(conn_of(gql(c, q(idx, f"node {{ {sel} }}"), {"after": after})))
                cc = conn_of(gql(c, q(idx + 1, "cursor"), {"after": after}))
                edges = cc.get("edges") or []
                skipped += 1
                if len(edges) <= idx:                          # nothing after it
                    return done()
                after = edges[idx]["cursor"]
                if not cc["pageInfo"]["hasNextPage"] and len(edges) == idx + 1:
                    return done()
                time.sleep(PAUSE)
                continue
        take(conn)
        if limit or not conn["pageInfo"]["hasNextPage"]:
            return done()
        after = conn["pageInfo"]["endCursor"]
        if not limit and len(rows) % (page * 10) < page:      # a progress line every 10 pages
            print(f"   ... {len(rows)} rows so far", flush=True)
        time.sleep(PAUSE)


def pull_rest(c, ds):
    url = (f"{c['site']}/api1/x3/erp/{c['folder']}/{ds['class']}?representation={ds['representation']}.$query"
           f"&count={ds.get('count', 200)}" + (f"&where={urllib.parse.quote(ds['where'])}" if ds.get("where") else ""))
    rows = []
    while url:
        code, text = http("GET", url, headers(c, endpoint_header=False))
        if code != 200:
            raise SystemExit(f"REST {code}: {text[:300]}")
        out = json.loads(text)
        rows += [flatten(r) for r in out.get("$resources", [])]
        url = ((out.get("$links") or {}).get("$next") or {}).get("$url")
        time.sleep(PAUSE)
    return rows


def write_rows(rows, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.with_suffix(".json").write_text(json.dumps(rows, indent=1, default=str))
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(path.with_suffix(".csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, keys)
        w.writeheader()
        w.writerows(rows)


def load_datasets():
    """api_datasets.json if there (written by  draft , may be edited); otherwise the Live Orders data sets straight from
    NODES / LEAN above - so a fresh copy of the repo (e.g. on the portal server, 20 Nov) can pull without a draft."""
    if DATASETS.exists():
        return json.loads(DATASETS.read_text())
    return {n: {"path": NODES[n], "fields": LEAN[n], "filter": "", "enabled": n in LIVE_ORDERS} for n in NODES if n in LEAN}


def pull(a):
    c = load_conf()
    sets = load_datasets()
    if a.endpoint:                                   # another X3 folder (e.g. Sage's demo SEED): trials only
        if not a.limit:
            sys.exit("--endpoint is only for trials (with --limit): another folder's data never goes to the exports")
        c = dict(c, endpoint=a.endpoint)               # this run only; the saved settings are not changed
    names = a.names or [n for n, d in sets.items() if not n.startswith("_") and d.get("enabled")]
    # a trial (--limit) goes to SDI_X3_samples, never the exports folder run_x3.py reads
    day = (EXPORTS.parent / "SDI_X3_samples" if a.limit else EXPORTS) / dt.date.today().isoformat()
    if a.endpoint:
        day = day.with_name(day.name + "_" + a.endpoint)
    log = []
    for n in names:
        if n not in sets:
            log.append(dict(name=n, ok=False, error="not a data set in api_datasets.json / the code"))
            print(f"{n}: FAILED - not a data set (api_datasets.json has no '{n}': run  draft --force  or delete the file)")
            continue
        ds = sets[n]
        t0 = time.time()
        try:
            notes = []
            rows = pull_rest(c, ds) if ds.get("class") else pull_graphql(c, ds, limit=a.limit, notes=notes)
            write_rows(rows, day / n)
            log.append(dict(name=n, ok=True, rows=len(rows), seconds=round(time.time() - t0, 1), notes=notes))
            print(f"{n}: {len(rows)} rows" + (f" ({'; '.join(notes)})" if notes else ""), flush=True)
            if a.limit and rows:                       # column names only - no values printed
                cols = list(dict.fromkeys(k for r in rows for k in r))
                print("   columns:", ", ".join(cols))
        except (SystemExit, Exception) as e:            # noqa: BLE001 - one data set failing never stops the
            err = f"{e.__class__.__name__}: {e}" if not isinstance(e, SystemExit) else str(e)   # rest (20 Nov)
            log.append(dict(name=n, ok=False, error=err[:400]))
            print(f"{n}: FAILED - {err[:400]}", flush=True)
    day.mkdir(parents=True, exist_ok=True)           # even when every data set failed (20 Nov)
    (day / "api_log.json").write_text(json.dumps(dict(at=dt.datetime.now().isoformat(timespec="seconds"), runs=log), indent=1))
    print(f"Files in {day}")
    return 0 if all(l["ok"] for l in log) else 1


def flat_names(fields):
    """'a b c { x y } d' -> a, b, c.x, c.y, d : the column names a pull of these fields produces."""
    out, stack, prev = [], [], None
    for tok in re.findall(r"[{}]|[^\s{}]+", fields):
        if tok == "{":
            stack.append(prev)
            if out and out[-1] == ".".join(stack):
                out.pop()                              # the parent itself is not a column
        elif tok == "}":
            stack.pop()
        else:
            prev = tok
            out.append(".".join(stack + [tok]))
    return out


def columns_cmd(a):
    """Print the column names each data set will produce - from api_datasets.json, no call to X3."""
    sets = load_datasets()
    for n in a.names or [n for n in sets if not n.startswith("_")]:
        print(f"{n} ({'.'.join(sets[n]['path'])}):")
        print("   " + ", ".join(flat_names(sets[n]["fields"])))


def rest_cmd(a):
    c = load_conf()
    rows = pull_rest(c, {"class": a.cls, "representation": a.rep, "count": a.count, "where": a.where})
    print(json.dumps(rows[: a.count], indent=1, default=str))


def query_cmd(a):
    print(json.dumps(gql(load_conf(), Path(a.file).read_text()), indent=1, default=str))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Read-only Sage X3 API client")
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("setup").set_defaults(fn=setup)
    sp.add_parser("probe").set_defaults(fn=probe)
    sp.add_parser("diagnose").set_defaults(fn=diagnose)
    sp.add_parser("claims").set_defaults(fn=claims_test)
    s = sp.add_parser("schema")
    s.add_argument("words", nargs="*")
    s.set_defaults(fn=schema)
    d = sp.add_parser("draft")
    d.add_argument("--force", action="store_true")
    d.add_argument("--all", action="store_true", help="every field (exploring only, with pull --limit)")
    d.set_defaults(fn=draft)
    p = sp.add_parser("pull")
    p.add_argument("names", nargs="*")
    p.add_argument("--limit", type=int, default=0, help="trial: only this many rows per data set, to SDI_X3_samples")
    p.add_argument("--endpoint", help="trial only: read another X3 folder's endpoint (e.g. X3ERPV12_SEED) for column names")
    p.set_defaults(fn=pull)
    cc = sp.add_parser("columns")
    cc.add_argument("names", nargs="*")
    cc.set_defaults(fn=columns_cmd)
    r = sp.add_parser("rest")
    r.add_argument("cls")
    r.add_argument("rep")
    r.add_argument("--count", type=int, default=20)
    r.add_argument("--where", default="")
    r.set_defaults(fn=rest_cmd)
    q = sp.add_parser("query")
    q.add_argument("file")
    q.set_defaults(fn=query_cmd)
    a = ap.parse_args(argv)
    return a.fn(a) or 0


if __name__ == "__main__":
    sys.exit(main())
