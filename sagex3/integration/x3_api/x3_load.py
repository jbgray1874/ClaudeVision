"""Load an Estimate -> X3 run into Sage X3: CREATE-ONLY, and ONLY into the test environments. Written 20 Nov 2026.
22 Nov: a run goes back into the environment it was checked against - SDI Mig (test) or We are SDI (the users' UAT).

James, 20 Nov: "We also need to be able to save estimates to Sage X3, not just load up files." This is the write half
of Estimate -> X3. It sends the same product, BOM and route as the run's three load files (run.json holds their rows),
through X3's GraphQL API as create mutations, in the order X3 needs: product -> BOM -> route.

    python x3_load.py setup                    # the WRITE connected application -> x3_load.json (private, never in git)
    python x3_load.py mutations [--env uat]    # read-only: what X3 lets us create for product / BOM / routing, and how
                                               # each load-file field maps onto X3's create input; saves the schema
    python x3_load.py status [--json]          # set up? which X3? what can be created? (no call to X3)
    python x3_load.py plan <run_folder> [--json]                      # dry run: what would be created, what exists
    python x3_load.py load <run_folder> --apply --confirm <part> [--by NAME] [--json]   # creates what doesn't exist

Safety, in the code (not settings):
  * TEST ONLY: refuses any site but the training site (sdi-displays-trn) and any endpoint but X3ERPV12_SDIMIG (SDI
    Mig) and X3ERPV12_ACUX3 (We are SDI, UAT).
    Production live data is never changed (James: "under any circumstances"). Live needs a code change and sign-off.
  * CREATE ONLY: the only mutation this file can send is `create`. No update, no delete. Before each create it reads X3
    (live) and skips the record if X3 already has it (a product with that code; any BOM or route for that part) -
    an existing part, BOM or route is never changed. A replace is a separate, explicit decision (Acuity B6).
  * Stops at the first failure; nothing is retried (a retry could double-create).
  * A separate connected application and settings file from the read-only Live Orders one (x3_api.json), so the
    read-only one stays read-only. Its X3 user should have create rights on products, BOMs and routings only.
  * Every load is logged: <run_folder>/x3_load.json (what was sent, X3's answer) and x3_load_history.jsonl.
  * The secret is never printed, logged or put in a plan.

The field names on X3's side are not guessed blind: `mutations` reads X3's own schema (a read-only introspection
query) and maps each load-file field (ITMREF, TCLCOD, CPNITMREF, WST ...) onto the create input's fields from the
candidate names in MAP. Anything that doesn't map, and every required X3 field not covered, is listed; `plan` STOPs
on them, so nothing half-mapped is sent. X3 local-menu numbers (use status 2, time unit 2 ...) are sent as X3's enum
value at that menu position; `plan` shows each one ("USESTA 2 -> availableToUse") to check before the first load.
"""
import argparse
import datetime as dt
import getpass
import json
import subprocess
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import x3_api  # noqa: E402  (token, http, read-only gql for the existence checks)

CONF = Path(os.environ.get("X3_LOAD_CONFIG", Path.home() / ".sdi" / "x3_load.json"))
READ_CONF = x3_api.CONF                                  # the read-only Live Orders settings (for `mutations` only)
SCHEMA = CONF.parent / "x3_load_schema.json"           # SDI Mig's (the first one); other endpoints: schema_file()
HISTORY = Path(os.environ.get("X3_LOAD_HISTORY", CONF.parent / "x3_load_history.jsonl"))

TEST_SITE = re.compile(r"^https://[\w-]*-trn\.[\w.-]*sagex3\.com$", re.I)   # the training site only
# SDI Mig (test) and, from 22 Nov, We are SDI (the users' UAT; James: "write the save-back of the estimate to the
# relevant environment ... set up on We are SDI also so that the users can test, as that's their UAT"). Both on the
# training site. Never production.
TEST_ENDPOINTS = {x3_api.ENVS["mig"]["endpoint"], x3_api.ENVS["uat"]["endpoint"]}

# the load files' columns (est_to_x3.py ITM_H2 / BOM_HEAD / ROU_H2) - run.json holds the rows in this order
ITM = ["TCLCOD", "ITMREF", "ITMDES1", "ITMDES2", "ITMDES3", "STU", "PUU", "PUUSTUCOE", "SAU", "SAUSTUCOE", "WEU",
       "ITMWEI", "BASPRI"]
BOM = ["ITMREF", "BOMALT", "USESTA", "BOHSTRDAT", "BOHENDDAT", "BASQTY", "QTYCOD", "BOMSEQ", "CPNITMREF", "CPNTYP",
       "LIKQTY"]
ROU = ["ITMREF", "ROUALT", "FCY", "USESTA", "TIMUOMCOD", "WORTYP", "OPENUM", "WST", "ROODES", "SETTIM", "OPETIM"]

# Where each record goes in X3 and the candidate GraphQL names for each load-file field (first that X3 has wins).
# Read-side names (x3_api LEAN) come first: X3's create inputs normally use the same names.
MAP = {
    "product": {
        "nodes": [["x3MasterData", "product"]],
        "find": r"^product$",
        "header": {
            "TCLCOD": ["productCategory", "category"],
            "ITMREF": ["code", "product"],
            "ITMDES1": ["description1", "localizedDescription1", "description"],
            "ITMDES2": ["description2", "localizedDescription2"],
            "ITMDES3": ["description3", "localizedDescription3"],
            "STU": ["stockUnit"],
            "PUU": ["purchaseUnit"],
            "PUUSTUCOE": ["purchaseUnitToStockUnitConversionFactor", "purchaseToStockConversionFactor",
                          "purchaseUnitToStockUnitConversion", "purchaseStockConversion"],
            "SAU": ["salesUnit"],
            "SAUSTUCOE": ["salesUnitToStockUnitConversionFactor", "salesToStockConversionFactor",
                          "salesUnitToStockUnitConversion", "salesStockConversion"],
            "WEU": ["weightUnit"],
            "ITMWEI": ["productWeight", "weight", "itemWeight"],
            "BASPRI": ["basePrice", "salesBasePrice"],
        },
        "required": ["ITMREF", "TCLCOD"],
    },
    "bom": {
        "nodes": [["x3ManufacturingData", "manufacturingBom"], ["x3ManufacturingData", "billOfMaterial"],
                  ["x3ManufacturingData", "bom"], ["x3ManufacturingData", "manufacturingBomLine"]],
        "find": r"bom|billofmaterial",
        "header": {
            "ITMREF": ["parentProduct", "product"],
            "BOMALT": ["bomCode", "alternative", "code"],
            "USESTA": ["useStatus", "status"],
            "BOHSTRDAT": ["validityStartDate", "startDate"],
            "BOHENDDAT": ["validityEndDate", "endDate"],
            "BASQTY": ["baseQuantity"],
            "QTYCOD": ["managementUnit", "quantityCode", "bomUnit"],
        },
        "lines": ["lines", "bomLines", "components", "manufacturingBomLines", "componentLines"],
        "line": {
            "BOMSEQ": ["sequence", "lineNumber", "bomSequence"],
            "CPNITMREF": ["componentProduct", "component", "product"],
            "CPNTYP": ["componentType"],
            "LIKQTY": ["linkQuantity"],
        },
        "required": ["ITMREF", "CPNITMREF", "LIKQTY"],
    },
    "route": {
        "nodes": [["x3Manufacturing", "routing"], ["x3ManufacturingData", "routing"],
                  ["x3Manufacturing", "routingOperation"]],
        "find": r"routing",
        "header": {
            "ITMREF": ["product", "routing"],
            "ROUALT": ["routingCode", "code", "alternative"],
            "FCY": ["site", "productionSite"],
            "USESTA": ["useStatus", "status"],
            "TIMUOMCOD": ["timeUnit", "timeUnitCode"],
            "WORTYP": ["workOrderManagementMode", "managementMode"],
        },
        "lines": ["operations", "routingOperations", "lines"],
        "line": {
            "OPENUM": ["operationNumber"],
            "WST": ["mainWorkCenter", "workCenter"],
            "ROODES": ["operationDescription", "description"],
            "SETTIM": ["setupTime"],
            "OPETIM": ["runTime", "operationTime"],
        },
        "required": ["ITMREF", "OPENUM", "WST"],
    },
}
# read nodes for the existence checks (x3_api NODES) and the filter forms tried, in order
EXISTS = {
    "product": (["x3MasterData", "product"], "code", ["{{code: '{c}'}}", "{{code: {{_eq: '{c}'}}}}"]),
    "bom": (["x3ManufacturingData", "manufacturingBomLine"], "parentProduct { code }",
            ["{{parentProduct: {{code: '{c}'}}}}", "{{parentProduct: '{c}'}}", "{{parentProduct: {{_id: '{c}'}}}}"]),
    "route": (["x3Manufacturing", "routingOperation"], "product { code }",
              ["{{product: {{code: '{c}'}}}}", "{{product: '{c}'}}", "{{product: {{_id: '{c}'}}}}"]),
}
WHAT = {"product": "the product (ZSDIITM)", "bom": "the BOM (YA00408BOM)", "route": "the route (ZSDIROU2)"}


# ---------------------------------------------------------------- settings and the test-only guard
def load_conf(path=CONF):
    if not path.exists():
        raise SystemExit(f"Loading into X3 isn't set up: no {path}. Run  python x3_load.py setup  (runbook, 20 Nov night)")
    return json.loads(path.read_text())


def guard(c):
    """Test environments only (SDI Mig, We are SDI UAT) - in code, so no settings file can point it at live."""
    site, ep = c.get("site", ""), c.get("endpoint", "")
    if not TEST_SITE.match(site) or ep not in TEST_ENDPOINTS:
        raise SystemExit(f"Refused: loads go only to the test environments (the -trn site, endpoints "
                         f"{', '.join(sorted(TEST_ENDPOINTS))}). These settings point at {site} / {ep}. "
                         "Production live data is never changed from here.")
    return c


def schema_file(endpoint):
    """X3's API set-up is per folder, so each endpoint's schema is read and kept on its own."""
    return SCHEMA if endpoint in (None, "", x3_api.ENVS["mig"]["endpoint"]) else CONF.parent / f"x3_load_schema_{endpoint}.json"


def run_env(run):
    """The X3 environment a run was checked against (run.json, 22 Nov); runs from before then are SDI Mig's."""
    k = (run.get("env") or {}).get("key") or "mig"
    return k if k in x3_api.ENVS else "mig"


def _clipboard():
    """The secret from the Windows clipboard (26 Nov: on the server's consoles typed answers didn't arrive - ISE held
    them back, remote desktop only moved on after Ctrl+C). The clipboard is cleared after reading."""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"], capture_output=True,
                           text=True, timeout=20)
        val = (r.stdout or "").strip()
        subprocess.run(["powershell", "-NoProfile", "-Command", "Set-Clipboard -Value ' '"], capture_output=True,
                       timeout=20)
        return val
    except (OSError, subprocess.SubprocessError):
        return ""


def setup(a):
    """Questions on screen, or none (26 Nov): with --client-id and --user given, nothing is asked - the other
    settings keep their saved / default values unless given, and the secret comes from the clipboard
    (--secret-from-clipboard) so it's never typed into the console or its history."""
    base = json.loads(READ_CONF.read_text()) if READ_CONF.exists() else {}
    c = json.loads(CONF.read_text()) if CONF.exists() else {
        k: base[k] for k in ("site", "folder", "endpoint", "connector", "graphql_path", "aud", "endpoint_header",
                             "token_seconds") if k in base}
    quiet = bool(getattr(a, "client_id", "") and getattr(a, "user", ""))
    def ask(k, q, d="", given=""):
        if given:
            return given
        if quiet:
            return c.get(k, d)
        return input(f"{q} [{c.get(k, d)}]: ").strip() or c.get(k, d)
    print("The WRITE connected application (not 'SDI Live Orders read-only'): see the runbook, 20 Nov night.")
    c["site"] = ask("site", "Site address (the TRAINING site)", "https://sdi-displays-trn.uk.sagex3.com",
                    getattr(a, "site", "")).rstrip("/")
    c["folder"] = ask("folder", "X3 folder", "SDIMIG", getattr(a, "folder", ""))
    c["endpoint"] = ask("endpoint", "Endpoint", "X3ERPV12_SDIMIG", getattr(a, "endpoint", ""))
    c["client_id"] = ask("client_id", "Write connected application client ID", "", getattr(a, "client_id", ""))
    c["user"] = ask("user", "X3 user it runs as (its login)", "", getattr(a, "user", ""))
    if getattr(a, "secret_from_clipboard", False):
        sec = _clipboard()
        if not sec or len(sec) < 16 or any(ch.isspace() for ch in sec):
            raise SystemExit("The clipboard doesn't hold a secret (copy the connected application's secret from Sage "
                             "X3 first, then run this again). Nothing saved.")
        c["secret"] = sec
        print(f"Secret read from the clipboard ({len(sec)} characters) and the clipboard cleared.")
    elif not quiet:
        sec = getpass.getpass("Its secret (typing is hidden; Enter keeps the saved one): ").strip()
        if sec:
            c["secret"] = sec
    if not c.get("secret"):
        raise SystemExit("No secret saved yet: run it again with --secret-from-clipboard. Nothing saved.")
    c["token_seconds"] = int(ask("token_seconds", "Token lifetime in seconds", 300))
    guard(c)
    CONF.parent.mkdir(parents=True, exist_ok=True)
    CONF.write_text(json.dumps(c, indent=2))
    try:
        os.chmod(CONF, 0o600)
    except OSError:
        pass
    print(f"Saved to {CONF} - private: never in git, email or chat. Next: python x3_load.py mutations --env mig "
          "(and --env uat)")


# ---------------------------------------------------------------- X3's schema: what can be created, and how
INTROSPECT = """query { __schema { queryType { name } mutationType { name } types { name kind
  fields { name args { name defaultValue type { ...T } } type { ...T } }
  inputFields { name defaultValue type { ...T } } enumValues { name } } } }
fragment T on __Type { name kind ofType { name kind ofType { name kind ofType { name kind ofType { name kind } } } } }"""


def _base(t):
    while t and t.get("ofType"):
        t = t["ofType"]
    return t or {}


def _sig(t):
    """GraphQL type text for a variable declaration: [Foo!]! etc."""
    if t["kind"] == "NON_NULL":
        return _sig(t["ofType"]) + "!"
    if t["kind"] == "LIST":
        return "[" + _sig(t["ofType"]) + "]"
    return t["name"]


def creates(schema):
    """Every create mutation X3 offers: {(root, node): {"arg": "data", "type": <arg type>, "returns": name}}."""
    s = schema["__schema"]
    types = {t["name"]: t for t in s["types"]}
    root = (s.get("mutationType") or {}).get("name")
    out = {}
    for top in (types.get(root, {}).get("fields") or []) if root else []:
        for node in types.get(_base(top["type"]).get("name"), {}).get("fields") or []:
            for op in types.get(_base(node["type"]).get("name"), {}).get("fields") or []:
                if op["name"] != "create":
                    continue
                arg = next((a for a in op.get("args") or [] if a["name"] == "data"), (op.get("args") or [None])[0])
                if arg:
                    out[(top["name"], node["name"])] = {"arg": arg["name"], "type": arg["type"],
                                                        "returns": _base(op["type"]).get("name")}
    return types, out


def _field(types, tname, cands):
    fs = {f["name"]: f for f in types.get(tname, {}).get("inputFields") or []}
    low = {k.lower(): k for k in fs}
    for c in cands:
        if c in fs:
            return fs[c]
        if c.lower() in low:
            return fs[low[c.lower()]]
    return None


def _map(types, tname, table):
    got, miss = {}, []
    for code, cands in table.items():
        f = _field(types, tname, cands)
        if f:
            got[code] = f
        else:
            miss.append(code)
    return got, miss


def resolve(schema):
    """For product / bom / route: which create to use, header + lines or one create per line, the field map, and the
    X3 fields that are required but not covered. Pure function of the schema (tested with a fake one)."""
    types, cr = creates(schema)
    res = {"has_mutations": bool(cr), "creates": sorted(f"{a}.{b}" for a, b in cr)}
    for what, m in MAP.items():
        cands = [tuple(n) for n in m["nodes"] if tuple(n) in cr]
        cands += [k for k in cr if re.search(m["find"], k[1], re.I) and k not in cands]
        r = {"node": None}
        for node in cands:
            itype = _base(cr[node]["type"]).get("name")
            head, miss_h = _map(types, itype, m["header"])
            lines = None
            if "lines" in m:
                lf = _field(types, itype, m["lines"])
                if lf and _base(lf["type"]).get("kind") == "INPUT_OBJECT":
                    lines = lf
            if "lines" in m and lines:                         # header + lines in one create (preferred)
                ltype = _base(lines["type"])["name"]
                line, miss_l = _map(types, ltype, m["line"])
                mode = "header+lines"
            elif "lines" in m:                                 # a line node: one create per line, header on each
                line, miss_l = _map(types, itype, m["line"])
                ltype, mode = itype, "per-line"
            else:
                line, miss_l, ltype, mode = {}, [], None, "single"
            covered = {f["name"] for f in head.values()} | ({lines["name"]} if lines else set())
            req_h = [f["name"] for f in types[itype].get("inputFields") or []
                     if f["type"]["kind"] == "NON_NULL" and f.get("defaultValue") is None and f["name"] not in covered
                     and not (mode == "per-line" and f["name"] in {x["name"] for x in line.values()})]
            req_l = [f["name"] for f in types.get(ltype, {}).get("inputFields") or []
                     if mode == "header+lines" and f["type"]["kind"] == "NON_NULL" and f.get("defaultValue") is None
                     and f["name"] not in {x["name"] for x in line.values()}]
            need = [c for c in m["required"] if c not in head and c not in line]
            r = {"node": list(node), "mode": mode, "input": itype, "input_sig": _sig(cr[node]["type"]),
                 "arg": cr[node]["arg"], "returns": cr[node]["returns"],
                 "header": {k: _fdesc(types, f) for k, f in head.items()},
                 "lines_field": lines["name"] if lines else None, "line_input": ltype,
                 "line": {k: _fdesc(types, f) for k, f in line.items()},
                 "unmapped": [c for c in miss_h + miss_l if not (mode == "per-line" and c in line)],
                 "required_not_covered": req_h + req_l, "missing_ours": need,
                 "return_fields": _ret_fields(types, cr[node]["returns"])}
            if not need:
                break
        res[what] = r
    return res


def _fdesc(types, f):
    b = _base(f["type"])
    d = {"name": f["name"], "kind": b.get("kind"), "type": b.get("name"), "list": "LIST" in json.dumps(f["type"])}
    if b.get("kind") == "ENUM":
        d["enum"] = [e["name"] for e in types.get(b["name"], {}).get("enumValues") or []]
    return d


def _ret_fields(types, tname):
    fs = [f["name"] for f in types.get(tname, {}).get("fields") or [] if _base(f["type"]).get("kind") in ("SCALAR", "ENUM")]
    pick = [f for f in ("_id", "code", "id", "number") if f in fs]
    return pick[:2] or ["__typename"]


def mutations(a):
    """Read-only: introspect X3, save the schema, print what can be created and how our fields map."""
    c = load_conf() if CONF.exists() else x3_api.load_conf()
    c = x3_api.for_env(c, a.env)
    sch = x3_api.gql(c, INTROSPECT)                     # a query - the read-only client sends it
    f = schema_file(c.get("endpoint"))
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"as_at": dt.datetime.now().isoformat(timespec="seconds"), "site": c.get("site"),
                             "endpoint": c.get("endpoint"), "schema": sch}))
    res = resolve(sch)
    if a.json:
        print(json.dumps(res, indent=1))
        return
    print(f"X3 endpoint: {c.get('endpoint')} - schema saved: {f}")
    print(f"Create mutations X3 offers: {len(res['creates'])}" + ("" if res["has_mutations"] else
          "  - NONE: X3's GraphQL has no create for us yet (see the runbook: X3 Builder -> API operations)"))
    for n in res["creates"]:
        if re.search(r"product|bom|billofmaterial|routing", n, re.I):
            print("   ", n)
    for what in MAP:
        r = res[what]
        print(f"\n{WHAT[what]}: " + (f"{'.'.join(r['node'])}.create ({r['mode']}, input {r['input']})" if r["node"]
                                    else "NO create found"))
        if not r["node"]:
            continue
        for k, f in list(r["header"].items()) + list(r["line"].items()):
            print(f"    {k:<10} -> {f['name']:<36} {f['type']}{' (enum: ' + ', '.join(f['enum'][:8]) + ')' if f.get('enum') else ''}")
        if r["unmapped"]:
            print("    not mapped (add the X3 name to MAP):", ", ".join(r["unmapped"]))
        if r["required_not_covered"]:
            print("    X3 REQUIRES, not in our files:", ", ".join(r["required_not_covered"]))
        if r["missing_ours"]:
            print("    STOP - can't place:", ", ".join(r["missing_ours"]))
    print("\nSend Claude this output (no secret in it).")


def load_schema(endpoint=None):
    f = schema_file(endpoint)
    if not f.exists():
        return None
    return json.loads(f.read_text())


# ---------------------------------------------------------------- values
def _value(f, v, notes, code):
    """A load-file value as X3's input wants it. Enums: the X3 local-menu number -> the enum value at that position."""
    if v is None or v == "":
        return None
    kind, t = f["kind"], (f["type"] or "")
    if kind == "ENUM":
        vals = f.get("enum") or []
        if isinstance(v, str) and v in vals:
            return v
        try:
            n = int(float(v))
        except (TypeError, ValueError):
            raise ValueError(f"{code} = {v!r}: not one of X3's {f['type']} values {vals}")
        if not 1 <= n <= len(vals):
            raise ValueError(f"{code} = {v}: X3's {f['type']} has {len(vals)} values {vals}")
        notes.append(f"{code} {v} -> {vals[n - 1]} (X3 menu position {n} of {', '.join(vals)})")
        return vals[n - 1]
    if kind == "INPUT_OBJECT":
        raise ValueError(f"{code}: X3 wants an object for {f['name']} ({t}) - send Claude the `mutations` output")
    if t in ("Int", "Integer", "Long"):
        return int(float(v))
    if t in ("Float", "Decimal", "BigDecimal", "Double"):
        return float(v)
    if t == "Boolean":
        return bool(v) and str(v) not in ("0", "False", "false", "N")
    if isinstance(v, float) and v == int(v):
        v = int(v)
    return str(v)


def _fill(table, row, cols, notes):
    out = {}
    for code, f in table.items():
        val = _value(f, row[cols.index(code)], notes, code)
        if val is not None:
            out[f["name"]] = val
    return out


def payloads(what, r, run):
    """The create data for one record, built from run.json's load-file rows (exactly what the .txt files hold)."""
    notes = []
    if what == "product":
        row = run.get("itm_row") or []
        return [_fill(r["header"], row, ITM, notes)], notes
    rows, cols, hcodes = ((run.get("bom_rows") or [], BOM, MAP["bom"]["header"]) if what == "bom"
                          else (run.get("rou_rows") or [], ROU, MAP["route"]["header"]))
    if not rows:
        return [], notes
    if r["mode"] == "header+lines":
        head = _fill(r["header"], rows[0], cols, notes)
        head[r["lines_field"]] = [_fill(r["line"], x, cols, notes) for x in rows]
        return [head], _uniq(notes)
    both = {**r["header"], **r["line"]}                                  # per-line: the header goes on every line
    return [_fill(both, x, cols, notes) for x in rows], _uniq(notes)


def _uniq(xs):
    return list(dict.fromkeys(xs))


# ---------------------------------------------------------------- reads: does X3 already have it?
def exists(c, what, code):
    """True / False from a live read of X3, or None if no filter form was accepted (then nothing is created)."""
    path, sel, forms = EXISTS[what]
    lit = code.replace("\\", "\\\\").replace("'", "\\'")
    for form in forms:
        flt = form.format(c=lit)
        q = ("query { " + " { ".join(path) + f" {{ query(first: 5, filter: {json.dumps(flt)}) "
             f"{{ edges {{ node {{ {sel} }} }} }} " + "}" * len(path) + " }")
        try:
            d = x3_api.gql(c, q)
        except SystemExit:                                              # GqlError too: try the next filter form
            continue
        for p in path + ["query", "edges"]:
            d = (d or {}).get(p) if isinstance(d, dict) else d
        edges = d or []
        def key(n):
            v = n.get("code") if what == "product" else (n.get("parentProduct") or n.get("product") or {})
            return v if isinstance(v, str) else (v or {}).get("code")
        return any(key(e.get("node") or {}) == code for e in edges)
    return None                                                  # no filter form accepted: don't guess


# ---------------------------------------------------------------- plan and load
def plan(run_dir, c=None):
    run_dir = Path(run_dir)
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    out = {"when": dt.datetime.now().isoformat(timespec="seconds"), "code": run.get("code"), "ok": False,
           "records": [], "stops": []}
    stop = out["stops"].append
    if not run.get("ok") or not run.get("ready"):
        stop("This run isn't READY TO LOAD: fix the STOP checks and run the estimate again.")
        return out
    env = run_env(run)
    out["env"] = dict(key=env, **x3_api.ENVS[env])
    try:
        c = c or guard(x3_api.for_env(load_conf(), env))     # the environment the estimate was checked against
    except SystemExit as e:
        stop(str(e))
        return out
    out["target"] = {"site": c["site"], "endpoint": c["endpoint"], "user": c.get("user"),
                     "label": x3_api.ENVS[env]["label"]}
    sch = load_schema(c["endpoint"])
    if not sch:
        stop(f"X3's API hasn't been read yet for {x3_api.ENVS[env]['label']}: run  python x3_load.py mutations "
             f"--env {env}  once (read-only).")
        return out
    out["schema_as_at"] = sch.get("as_at")
    res = resolve(sch["schema"])
    code = run["code"]
    for what in ("product", "bom", "route"):
        r = res[what]
        rec = {"what": what, "label": WHAT[what], "node": ".".join(r["node"]) if r["node"] else None,
               "mode": r.get("mode"), "action": "stop", "why": "", "send": [], "notes": []}
        out["records"].append(rec)
        if what != "product" and not (run.get("bom_rows") if what == "bom" else run.get("rou_rows")):
            rec.update(action="none", why="nothing in the estimate for this")
            continue
        if not r["node"] and what != "product":
            # 26 Nov: X3 (We are SDI) lets the connection create products but not BOMs or routings yet. Rather than
            # refuse the whole estimate, the product is created and the BOM / route is imported by hand from the
            # saved file - the same import Estimating does today (Usage -> Imports).
            tpl = {"bom": "YA00408BOM", "route": "ZSDIROU2"}[what]
            fname = next((f for f in run.get("load_files") or [] if tpl in f), f"..._{tpl}.txt")
            folder = (run.get("published") or {}).get("folder") or "the run's saved folder"
            rec.update(action="manual", template=tpl, file=fname, folder=folder,
                       why=f"X3 doesn't let the connection create this yet - import it by hand: Usage -> Imports, "
                           f"template {tpl}, file {fname} from {folder}")
            continue
        if not r["node"]:
            rec["why"] = "X3 offers no create for this yet (X3 Builder -> API operations; runbook 20 Nov night)"
            stop(f"{WHAT[what]}: {rec['why']}")
            continue
        if r["missing_ours"] or r["required_not_covered"]:
            rec["why"] = "; ".join(x for x in (
                f"our fields with no X3 place: {', '.join(r['missing_ours'])}" if r["missing_ours"] else "",
                f"X3 requires {', '.join(r['required_not_covered'])}, not in our files" if r["required_not_covered"] else "") if x)
            stop(f"{WHAT[what]}: {rec['why']}")
            continue
        try:
            rec["send"], rec["notes"] = payloads(what, r, run)
        except ValueError as e:
            rec["why"] = str(e)
            stop(f"{WHAT[what]}: {e}")
            continue
        if r["unmapped"]:
            rec["notes"].append("not sent (no X3 field found; X3's default applies): " + ", ".join(r["unmapped"]))
        have = exists(c, what, code)
        if have is None:
            rec["why"] = "couldn't check in X3 whether it already exists - not created"
            stop(f"{WHAT[what]}: {rec['why']}")
        elif have:
            rec.update(action="skip", why=f"X3 already has {'this product' if what == 'product' else 'one for ' + code}"
                                           " - left as it is (create-only)")
        else:
            n = len(rec["send"])
            rec.update(action="create", why=f"new in X3 - {n} create{'s' if n != 1 else ''}"
                                            + (f" ({r['mode']})" if what != "product" else ""))
    out["ok"] = not out["stops"]
    out["creates"] = sum(len(r["send"]) for r in out["records"] if r["action"] == "create")
    out["manual"] = [{k: r.get(k) for k in ("what", "label", "template", "file", "folder")}
                     for r in out["records"] if r["action"] == "manual"]
    (run_dir / "x3_load_plan.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    return out


CREATE_ONLY = re.compile(r"^mutation\s*\(\$data: [\w\[\]!]+\)\s*\{\s*\w+\s*\{\s*\w+\s*\{\s*create\(\w+: \$data\)"
                         r"\s*\{[\w\s]+\}\s*\}\s*\}\s*\}$")


def send_create(c, node, arg, sig, ret, data):
    """The one write this file makes: <root> { <node> { create(<arg>: $data) { id } } }. Checked against CREATE_ONLY."""
    q = f"mutation($data: {sig}) {{ {node[0]} {{ {node[1]} {{ create({arg}: $data) {{ {' '.join(ret)} }} }} }} }}"
    if not CREATE_ONLY.match(q):
        raise SystemExit("Refused: only a create mutation can be sent")
    guard(c)
    url = c["site"] + c.get("graphql_path", x3_api.GRAPHQL_PATHS[0])
    h = x3_api.headers(c, endpoint_header=c.get("endpoint_header", True))
    h["User-Agent"] = "sdi-x3-estimate-loader/1"
    code, text = x3_api.http("POST", url, h, {"query": q, "variables": {"data": data}}, timeout=120)  # no retry
    try:
        out = json.loads(text)
    except ValueError:
        return False, f"X3 answered {code}: {x3_api.redact(text)[:300]}"
    if code != 200 or out.get("errors"):
        return False, f"X3 answered {code}: {json.dumps(out.get('errors') or out)[:800]}"
    return True, out.get("data")


def load(run_dir, confirm, by=""):
    run_dir = Path(run_dir)
    run = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    log = {"when": dt.datetime.now().isoformat(timespec="seconds"), "by": by, "code": run.get("code"),
           "estimate": run.get("estimate"), "ok": False, "results": []}
    if confirm != run.get("code"):
        log["error"] = f"Not loaded: type the part code ({run.get('code')}) to confirm"
        return _save_log(run_dir, run, log)
    env = run_env(run)
    log["env"] = dict(key=env, **x3_api.ENVS[env])
    try:
        c = guard(x3_api.for_env(load_conf(), env))           # back into the environment it was checked against
    except SystemExit as e:
        log["error"] = f"Not loaded: {e}"
        return _save_log(run_dir, run, log)
    p = plan(run_dir, c)                                       # fresh: X3 is read again just before writing
    log["target"], log["plan"] = p.get("target"), {k: p[k] for k in ("ok", "stops", "creates") if k in p}
    if not p["ok"]:
        log["error"] = "Not loaded: " + " | ".join(p["stops"])
        return _save_log(run_dir, run, log)
    res = resolve(load_schema(c["endpoint"])["schema"])
    for rec in p["records"]:
        if rec["action"] != "create":
            log["results"].append({"what": rec["what"], "action": rec["action"], "why": rec["why"],
                                   **({k: rec.get(k) for k in ("template", "file", "folder")}
                                      if rec["action"] == "manual" else {})})
            continue
        r = res[rec["what"]]
        made = []
        for data in rec["send"]:
            ok, ans = send_create(c, r["node"], r["arg"], r["input_sig"], r["return_fields"], data)
            made.append({"ok": ok, "sent": data, "x3": ans})
            if not ok:
                break
            time.sleep(0.3)
        good = all(m["ok"] for m in made)
        log["results"].append({"what": rec["what"], "action": "create", "ok": good, "node": rec["node"],
                               "created": sum(m["ok"] for m in made), "of": len(rec["send"]), "calls": made})
        if not good:
            log["error"] = (f"{WHAT[rec['what']]}: X3 refused it - {made[-1]['x3']}. Stopped here: nothing after it "
                            f"was sent." + (f" {sum(m['ok'] for m in made)} of {len(rec['send'])} lines were created "
                                            "before the refusal - check them in X3." if len(made) > 1 else ""))
            return _save_log(run_dir, run, log)
    log["ok"] = True
    return _save_log(run_dir, run, log)


def _save_log(run_dir, run, log):
    text = json.dumps(log, indent=1, default=str)
    (run_dir / "x3_load.json").write_text(text, encoding="utf-8")
    pub = (run.get("published") or {}).get("path")
    if pub and Path(pub) != run_dir:
        try:
            (Path(pub) / "x3_load.json").write_text(text, encoding="utf-8")    # the saved folder shows it too
        except OSError:
            pass
    try:
        HISTORY.parent.mkdir(parents=True, exist_ok=True)
        with open(HISTORY, "a", encoding="utf-8") as f:
            f.write(json.dumps({k: log.get(k) for k in ("when", "by", "code", "estimate", "ok", "error", "target")}
                               | {"run": str(run_dir), "done": [(x["what"], x["action"], x.get("ok")) for x in
                                                                  log["results"]]}, default=str) + "\n")
    except OSError:
        pass
    return log


def status(env="mig"):
    ep = x3_api.ENVS[env]["endpoint"]
    out = {"setup": CONF.exists(), "config": str(CONF), "schema": None, "test_only": sorted(TEST_ENDPOINTS),
           "env": dict(key=env, **x3_api.ENVS[env])}
    if CONF.exists():
        try:
            c = x3_api.for_env(json.loads(CONF.read_text()), env)
            out.update(site=c.get("site"), endpoint=c.get("endpoint"), user=c.get("user"))
            guard(c)
            out["target_ok"] = True
        except (SystemExit, ValueError) as e:
            out["target_ok"], out["problem"] = False, str(e)
    sch = load_schema(ep)
    if sch:
        res = resolve(sch["schema"])
        out["schema"] = sch.get("as_at")
        out["can_create"] = {w: (".".join(res[w]["node"]) if res[w]["node"] else None) for w in MAP}
        out["gaps"] = {w: res[w].get("missing_ours", []) + res[w].get("required_not_covered", []) for w in MAP if res[w]["node"]}
    out["ready"] = bool(out.get("target_ok") and sch and all((out.get("can_create") or {}).values())
                        and not any((out.get("gaps") or {}).values()))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    su = sub.add_parser("setup", help="the write connection: questions, or none with --client-id and --user")
    su.add_argument("--client-id", dest="client_id", default="")
    su.add_argument("--user", default="")
    su.add_argument("--site", default="")
    su.add_argument("--folder", default="")
    su.add_argument("--endpoint", default="")
    su.add_argument("--secret-from-clipboard", dest="secret_from_clipboard", action="store_true",
                    help="read the secret from the clipboard (copy it first); never type it into the console")
    m = sub.add_parser("mutations")
    m.add_argument("--json", action="store_true")
    m.add_argument("--env", choices=sorted(x3_api.ENVS), default="mig", help="mig = SDI Mig, uat = We are SDI")
    s = sub.add_parser("status")
    s.add_argument("--json", action="store_true")
    s.add_argument("--env", choices=sorted(x3_api.ENVS), default="mig")
    p = sub.add_parser("plan")
    p.add_argument("run_folder")
    p.add_argument("--json", action="store_true")
    ld = sub.add_parser("load")
    ld.add_argument("run_folder")
    ld.add_argument("--apply", action="store_true", help="without it, load only plans")
    ld.add_argument("--confirm", default="", help="the part code, typed again")
    ld.add_argument("--by", default="")
    ld.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "setup":
        return setup(a)
    if a.cmd == "mutations":
        return mutations(a)
    if a.cmd == "status":
        st = status(a.env)
        print(json.dumps(st, indent=1) if a.json else "\n".join(f"{k}: {v}" for k, v in st.items()))
        return 0
    if a.cmd == "plan" or (a.cmd == "load" and not a.apply):
        out = plan(a.run_folder)
        if a.json:
            print(json.dumps(out, default=str))
        else:
            print(f"{out.get('code')}: {'OK to load' if out['ok'] else 'NOT loadable'} - {out.get('creates', 0)} create(s)")
            for r in out["records"]:
                print(f"  {r['label']:<28} {r['action'].upper():<7} {r['why']}")
                for n in r.get("notes") or []:
                    print(f"      {n}")
            for s_ in out["stops"]:
                print("  STOP", s_)
        return 0 if out["ok"] else 1
    out = load(a.run_folder, a.confirm, a.by)
    if a.json:
        print(json.dumps(out, default=str))
    else:
        print(f"{out.get('code')}: {'LOADED' if out['ok'] else 'NOT LOADED'} {out.get('error', '')}")
        for r in out["results"]:
            print(f"  {WHAT[r['what']]:<28} {r['action']} {'' if r.get('ok') is None else ('ok' if r['ok'] else 'FAILED')}")
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
