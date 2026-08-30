#!/usr/bin/env python3
r"""
mine_cross_section.py
=====================
Mine the loaded RAG corpus (the *.formula_parse.json files) for candidate
TEST jobs by client, bucketed by material / process / complexity / value --
the same way the Boots/M&S cross-section was built, but pointed at any client.

Default target: TTI + Tesco.

It reads the parse JSONs directly (these ARE the RAG import source), using the
same fields load_historical_quotes.py reads:
    client      <- workbook_path  (the folder segment: ...\TTI\... etc.)
    job number  <- the filename's leading token (sidesteps the job_no='Rev'
                    misparse, exactly as estimating did for Boots)
    process     <- key_cells.operation_rows[].operation_code   (LASM/FOLD/WELD/P-C/CNC...)
    materials   <- parsed_entries[].value  (keyword scan of the line text)
    value       <- max(key_cells.totals[].value)               (approx job total)
    complexity  <- #operation rows + #parsed entries

Everything here is a HEURISTIC shortlisting aid (for picking which jobs to run
the AI against) -- not a pricing path. Verify figures against the real workbooks.

Run from C:\ClaudeVision\src:
    python mine_cross_section.py
    python mine_cross_section.py --root output\formula_parse --clients TTI Tesco --max 8
    python mine_cross_section.py --all            # summarise every client found
    python mine_cross_section.py --json picks.json

IMPORTANT: read the per-client FILE COUNTS printed at the top. If a client shows
0 files, the path format differs from the patterns below -- adjust CLIENT_PATTERNS.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
from collections import defaultdict

# --------------------------------------------------------------------------- #
# Vocabularies (raw codes / keywords  ->  matrix categories)                  #
# --------------------------------------------------------------------------- #

# Department / operation codes -> process fingerprint (token-exact, '/' as substr)
PROCESS_CODES = {
    "LASER":      ["LAS", "LASM", "LASA", "LASER", "LC"],
    "FOLD":       ["FOLD", "PB", "BRAKE"],
    "WELD":       ["WELD", "MIG", "TIG", "FAB", "FW"],
    "SPOT":       ["SPOT", "SPW"],
    "POWDER":     ["P/C", "PC", "POWDER", "PWD"],
    "WETSPRAY":   ["SPRAY", "WS", "PAINT"],
    "CNC":        ["CNC", "ROUT", "ROUTE", "MILL"],
    "PUNCH":      ["PUNC", "PUNCH", "TURRET", "PU"],
    "SAW":        ["SAW", "MITRE"],
    "TUBE":       ["TUBE", "RHS", "SHS", "CHS", "SECTION"],
    "GUILLOTINE": ["GUIL", "SHEAR"],
    "ROLL":       ["ROLL"],
    "EDGE":       ["EDGE", "LIPP"],
    "ASSEMBLY":   ["ASSEM", "ASSY", "BUILD"],
    "PACK":       ["PACK", "CRATE"],
}

# Process words that may appear in the line text (word-boundary scan of blob)
PROCESS_BLOB_WORDS = {
    "LASER":      ["LASER", "LASE", "LASERED"],
    "FOLD":       ["FOLD", "FOLDED", "FOLDING", "PRESS BRAKE"],
    "WELD":       ["WELD", "WELDED", "WELDING", "WELDMENT"],
    "SPOT":       ["SPOT WELD"],
    "POWDER":     ["POWDER", "POWDER COAT", "POWDERCOAT"],
    "WETSPRAY":   ["WET SPRAY", "SPRAY PAINT"],
    "CNC":        ["CNC", "ROUTED", "ROUTER", "ROUT"],
    "PUNCH":      ["PUNCH", "PUNCHED"],
    "SAW":        ["SAWN", "SAW CUT"],
    "TUBE":       ["TUBE", "RHS", "SHS", "CHS"],
    "GUILLOTINE": ["GUILLOTINE", "GUILLOTINED"],
    "ROLL":       ["ROLLED", "ROLLING"],
    "EDGE":       ["EDGEBAND", "EDGE BAND", "LIPPING"],
    "ASSEMBLY":   ["ASSEMBLY", "ASSEMBLE", "SUB ASSEMBLY", "SUB-ASSEMBLY"],
}

# Material keywords -> family (word-boundary matched against the line text)
MATERIAL_KEYWORDS = {
    "Mild steel":   ["MILD STEEL", "CR4", "DC01", "ZINTEC", "HR4", "S275", "MS"],
    "Stainless":    ["STAINLESS", "304", "316", "S/STEEL", "SS", "BRUSHED"],
    "Acrylic":      ["ACRYLIC", "PERSPEX", "PMMA", "PLEXI"],
    "MDF/timber":   ["MDF", "MFMDF", "TIMBER", "PLYWOOD", "PLY", "OAK", "VENEER",
                     "BIRCH", "CHIPBOARD", "MELAMINE", "WOODEN"],
    "Aluminium":    ["ALUMINIUM", "ALUMINUM", "ALI", "ALLOY"],
    "Tube/section": ["TUBE", "RHS", "SHS", "CHS", "BOX SECTION"],
    "Wire/mesh":    ["WIRE", "MESH", "WANZL", "BASKET"],
}

FLATPACK_MARKERS = ["FLAT PACK", "FLATPACK", "FLAT-PACK", "KNOCK DOWN",
                    "KNOCKDOWN", "KD V", " KD ", "SELF ASSEMBLY", "SELF-ASSEMBLY"]

# Filenames that are NOT real priced jobs -> skip
SKIP_MARKERS = ["BLANK", "TEMPLATE", "PRICE LIST", "PRICELIST", "QUOTE REQUEST",
                "STANDARD LINE QUOTE", "STANDARD LINE", "RATE CARD", "EXAMPLE SHEET",
                "TEST SHEET"]

# Client detection against the workbook_path (folder-delimited first, then loose)
CLIENT_PATTERNS = [
    ("M&S",   [r"[\\/](?:m&s|mands|m and s)[\\/]", r"marks.?and.?spencer", r"\bm&s\b"]),
    ("Tesco", [r"[\\/]tesco[\\/]", r"\btesco\b"]),
    ("Boots", [r"[\\/]boots[\\/]", r"\bboots\b"]),
    ("TTI",   [r"[\\/]tti[\\/]", r"\btti\b", r"milwaukee", r"ryobi", r"techtronic"]),
]

# Full target matrix (James's coverage axes)
FULL_MATRIX = [
    "MAT:Mild steel", "MAT:Stainless", "MAT:Acrylic", "MAT:MDF/timber",
    "MAT:Mixed", "MAT:Tube/section", "MAT:Bought-in/Wire",
    "PROC:Laser+fold (simple)", "PROC:Laser+weld+powder", "PROC:CNC rout",
    "PROC:Complex multi-assembly", "PROC:Wire/mesh", "PROC:Flat-pack",
    "CX:Simple", "CX:Medium", "CX:Complex", "CX:High-value",
]

_MONEY_RE = re.compile(r"-?\d+(?:\.\d+)?")
_HASH_SUFFIX = re.compile(r"__[0-9a-f]{6,}\.formula_parse\.json$", re.I)
_PARSE_SUFFIX = re.compile(r"\.formula_parse\.json$", re.I)
_JOB_RE = re.compile(r"^([0-9]{3,7}(?:-[0-9A-Za-z]+){0,3})")


# --------------------------------------------------------------------------- #
# Extraction helpers                                                          #
# --------------------------------------------------------------------------- #

def money(x):
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).replace("£", "").replace(",", "").strip()
    m = _MONEY_RE.search(s)
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def client_of(path):
    p = (path or "").lower()
    for name, pats in CLIENT_PATTERNS:
        if any(re.search(pat, p) for pat in pats):
            return name
    return None


def _strip_parse_name(filename):
    base = os.path.basename(filename)
    base = _HASH_SUFFIX.sub("", base)
    base = _PARSE_SUFFIX.sub("", base)
    return base


def job_of(filename):
    base = _strip_parse_name(filename)
    head = re.split(r"_-_|\s-\s|\s+-\s+", base)[0].strip("_- ")
    m = _JOB_RE.match(head.replace(" ", ""))
    if m:
        return m.group(1)
    tok = re.split(r"[ _]", head)[0]
    if len(tok) >= 2 and any(c.isdigit() for c in tok) and re.match(r"^[0-9A-Za-z\-]+$", tok):
        return tok
    return None  # template / non-job


def desc_of(filename):
    base = _strip_parse_name(filename)
    parts = re.split(r"_-_|\s-\s", base, maxsplit=1)
    tail = parts[1] if len(parts) > 1 else base
    return re.sub(r"[_]+", " ", tail).strip()[:46]


def _code_tokens(code):
    return [t for t in re.split(r"[^A-Z0-9/]+", code.upper()) if t]


def signals(data):
    """Return (codes:set, blob:str, value:float|None, n_ops:int, n_entries:int)."""
    key_cells = data.get("key_cells") or {}
    op_rows = key_cells.get("operation_rows") or []

    codes = set()
    for r in op_rows:
        if isinstance(r, dict):
            oc = (r.get("operation_code") or r.get("department_code")
                  or r.get("code") or r.get("op_code"))
            if oc:
                codes.add(str(oc).upper().strip())
            else:
                for vv in r.values():
                    s = str(vv).upper().strip()
                    if re.match(r"^[A-Z][A-Z0-9/]{1,7}$", s):
                        codes.add(s)
        elif r is not None:
            codes.add(str(r).upper().strip())

    text_parts = []
    for e in data.get("parsed_entries") or []:
        if isinstance(e, dict) and e.get("value") is not None:
            text_parts.append(str(e.get("value")))
    blob = (" ".join(text_parts)).upper()

    totals = key_cells.get("totals") or []
    tvals = [money(t.get("value")) for t in totals if isinstance(t, dict)]
    tvals = [v for v in tvals if v is not None]
    value = max(tvals) if tvals else None
    if value is None:
        fvals = []
        for f in ((data.get("estimate_sheet") or {}).get("formulas")) or []:
            if isinstance(f, dict):
                mv = money(f.get("value"))
                if mv is not None:
                    fvals.append(mv)
        value = max(fvals) if fvals else None

    return codes, blob, value, len(op_rows), len(data.get("parsed_entries") or [])


def process_categories(codes, blob):
    cats = set()
    toks = set()
    for c in codes:
        toks.update(_code_tokens(c))
    for cat, keys in PROCESS_CODES.items():
        if any(k in toks or ("/" in k and any(k in c for c in codes)) for k in keys):
            cats.add(cat)
    for cat, words in PROCESS_BLOB_WORDS.items():
        if any(re.search(r"(?<![A-Z])" + re.escape(w) + r"(?![A-Z])", blob) for w in words):
            cats.add(cat)
    return cats


def material_families(blob):
    fams = set()
    for fam, kws in MATERIAL_KEYWORDS.items():
        for kw in kws:
            if re.search(r"(?<![A-Z0-9])" + re.escape(kw) + r"(?![A-Z0-9])", blob):
                fams.add(fam)
                break
    return fams


def is_flatpack(blob, filename):
    hay = (blob + " " + os.path.basename(filename)).upper().replace("_", " ")
    return any(m in hay for m in FLATPACK_MARKERS)


def is_skip(blob, filename):
    hay = (os.path.basename(filename) + " " + blob[:200]).upper().replace("_", " ")
    return any(m in hay for m in SKIP_MARKERS)


# --------------------------------------------------------------------------- #
# Job aggregation + matrix mapping                                            #
# --------------------------------------------------------------------------- #

class Job:
    __slots__ = ("client", "job", "files", "value", "n_ops", "n_entries",
                 "proc", "mats", "flatpack", "desc")

    def __init__(self, client, job):
        self.client = client
        self.job = job
        self.files = 0
        self.value = None
        self.n_ops = 0
        self.n_entries = 0
        self.proc = set()
        self.mats = set()
        self.flatpack = False
        self.desc = ""

    def add(self, value, n_ops, n_entries, proc, mats, flatpack, desc):
        self.files += 1
        if value is not None:
            self.value = value if self.value is None else max(self.value, value)
        self.n_ops = max(self.n_ops, n_ops)
        self.n_entries = max(self.n_entries, n_entries)
        self.proc |= proc
        self.mats |= mats
        self.flatpack = self.flatpack or flatpack
        if desc and len(desc) > len(self.desc):
            self.desc = desc

    @property
    def score(self):
        return self.n_ops + self.n_entries


def matrix_cells(job):
    cells = set()
    fam = job.mats
    structural = {m for m in fam if m in
                  {"Mild steel", "Stainless", "Acrylic", "MDF/timber", "Aluminium"}}
    if "Mild steel" in fam:
        cells.add("MAT:Mild steel")
    if "Stainless" in fam:
        cells.add("MAT:Stainless")
    if "Acrylic" in fam:
        cells.add("MAT:Acrylic")
    if "MDF/timber" in fam:
        cells.add("MAT:MDF/timber")
    if "Tube/section" in fam or "TUBE" in job.proc:
        cells.add("MAT:Tube/section")
    if "Wire/mesh" in fam:
        cells.add("MAT:Bought-in/Wire")
    if len(structural) >= 2:
        cells.add("MAT:Mixed")

    p = job.proc
    if "LASER" in p and "FOLD" in p and not ({"WELD", "POWDER", "WETSPRAY"} & p):
        cells.add("PROC:Laser+fold (simple)")
    if "WELD" in p and ({"POWDER", "WETSPRAY"} & p):
        cells.add("PROC:Laser+weld+powder")
    if "CNC" in p:
        cells.add("PROC:CNC rout")
    if "Wire/mesh" in fam:
        cells.add("PROC:Wire/mesh")
    if job.flatpack:
        cells.add("PROC:Flat-pack")
    if ("ASSEMBLY" in p and len(structural) >= 2) or job.score >= 60:
        cells.add("PROC:Complex multi-assembly")

    if job.score >= 50 or len(p) >= 4:
        cells.add("CX:Complex")
    elif job.score >= 20:
        cells.add("CX:Medium")
    else:
        cells.add("CX:Simple")
    if job.value is not None and job.value >= 500:
        cells.add("CX:High-value")
    return cells


def suggest(jobs, cap):
    cellmap = {id(j): matrix_cells(j) for j in jobs}
    chosen, covered = [], set()
    pool = list(jobs)
    while pool and len(chosen) < cap:
        pool.sort(key=lambda j: (len(cellmap[id(j)] - covered), j.value or 0.0),
                  reverse=True)
        best = pool.pop(0)
        gain = cellmap[id(best)] - covered
        if not gain and chosen:
            break
        chosen.append(best)
        covered |= cellmap[id(best)]
    return chosen, covered


# --------------------------------------------------------------------------- #
# Reporting                                                                   #
# --------------------------------------------------------------------------- #

def _fmt_val(v):
    return f"£{v:,.0f}" if v is not None else "  —"


def print_client(client, jobs, cap):
    if not jobs:
        print(f"\n[{client}]  no priced jobs detected.\n")
        return set()

    jobs_sorted = sorted(jobs, key=lambda j: (j.value or 0.0), reverse=True)
    print(f"\n{'=' * 78}\n[{client}]  {len(jobs)} distinct priced jobs"
          f"  (showing all, sorted by approx value)\n{'-' * 78}")
    print(f"{'Job':<16}{'~£':>9}  {'ops':>3} {'ent':>3}  "
          f"{'Materials':<26}{'Process'}")
    for j in jobs_sorted:
        mats = ", ".join(sorted(j.mats)) or "—"
        proc = ", ".join(sorted(j.proc)) or "—"
        fp = "  [flat-pack]" if j.flatpack else ""
        print(f"{j.job:<16}{_fmt_val(j.value):>9}  {j.n_ops:>3} {j.n_entries:>3}  "
              f"{mats[:25]:<26}{(proc + fp)[:60]}")

    picks, covered = suggest(jobs, cap)
    print(f"\n  Suggested {client} coverage spread ({len(picks)} jobs):")
    for j in picks:
        adds = ", ".join(sorted(c.split(':', 1)[1] for c in matrix_cells(j)))
        print(f"    • {j.job:<14} {(_fmt_val(j.value)):>8}  {j.desc or ''}")
        print(f"        covers: {adds}")
    return covered


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=os.path.join("output", "formula_parse"),
                    help=r"folder of *.formula_parse.json (default output\formula_parse)")
    ap.add_argument("--clients", nargs="*", default=["TTI", "Tesco"])
    ap.add_argument("--max", type=int, default=8, help="max jobs in each suggested spread")
    ap.add_argument("--all", action="store_true", help="report every client found")
    ap.add_argument("--json", default=None, help="also write picks to this JSON file")
    args = ap.parse_args()

    paths = glob.glob(os.path.join(args.root, "*.formula_parse.json"))
    if not paths:
        print(f"No *.formula_parse.json found under {args.root!r}.")
        print(r"Point --root at your parse folder, e.g. --root output\formula_parse")
        return

    by_client_files = defaultdict(int)
    skipped = noclient = nojob = bad = 0
    jobs = {}  # (client, job) -> Job

    for p in paths:
        try:
            with open(p, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            bad += 1
            continue
        wp = data.get("workbook_path") or ""
        client = client_of(wp) or client_of(p)
        if not client:
            noclient += 1
            continue
        by_client_files[client] += 1
        codes, blob, value, n_ops, n_entries = signals(data)
        if is_skip(blob, p):
            skipped += 1
            continue
        job = job_of(p)
        if not job:
            nojob += 1
            continue
        proc = process_categories(codes, blob)
        mats = material_families(blob)
        fp = is_flatpack(blob, p)
        key = (client, job)
        jobs.setdefault(key, Job(client, job)).add(
            value, n_ops, n_entries, proc, mats, fp, desc_of(p))

    distinct = defaultdict(int)
    for (c, _j) in jobs:
        distinct[c] += 1

    print("=" * 78)
    print(f"RAG corpus scan — {len(paths)} parse files under {args.root!r}")
    print(f"  files matched to a client : {dict(by_client_files)}")
    print(f"  distinct priced jobs      : {dict(distinct)}")
    print(f"  skipped templates/lists   : {skipped}"
          f"   |  no client in path: {noclient}"
          f"   |  no job number: {nojob}"
          f"   |  unreadable: {bad}")
    if noclient and not by_client_files:
        print("  !! 0 files matched a client — your path layout differs; "
              "edit CLIENT_PATTERNS at the top of this script.")

    targets = sorted(distinct) if args.all else args.clients
    combined = set()
    spread_out = {}
    for client in targets:
        cj = [v for (c, _j), v in jobs.items() if c == client]
        covered = print_client(client, cj, args.max)
        combined |= covered
        picks, _ = suggest(cj, args.max)
        spread_out[client] = [
            {"job": j.job, "approx_value": j.value, "materials": sorted(j.mats),
             "process": sorted(j.proc), "flatpack": j.flatpack,
             "ops": j.n_ops, "entries": j.n_entries, "desc": j.desc}
            for j in picks
        ]

    print(f"\n{'=' * 78}\nMatrix coverage from the suggested {' + '.join(targets)} spread")
    print("-" * 78)
    missing = [c for c in FULL_MATRIX if c not in combined]
    print("  COVERED :", ", ".join(sorted(c.split(':', 1)[1] for c in combined)) or "none")
    if missing:
        print("  MISSING :", ", ".join(m.split(':', 1)[1] for m in missing))
        print("            (top these up from Boots/M&S, or chase estimating for a"
              " matching job)")
    else:
        print("  MISSING : none — full matrix covered by these clients.")
    print("=" * 78)
    print("Note: figures and tags are heuristic shortlisting aids from the parse —"
          " verify against the real workbooks before quoting parity.")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(spread_out, fh, indent=2)
        print(f"\nWrote suggested picks to {args.json}")


if __name__ == "__main__":
    main()
