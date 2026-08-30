#!/usr/bin/env python3
r"""
_probe_phantom_boughtin.py  —  READ-ONLY. No writes, no patches.

DEFECT (job 1310, Drill Stud Holder):
    The workbook carries a bought-in line:
        BI-DRILLSTUDHOLDER  "Drill Stud Holder"   £105.00  ->  £109.20 with scrap
    against a whole-job manual estimate of £6.90.

    There is NO such purchased component. "Drill Stud Holder" is the JOB TITLE —
    the thing we are fabricating from two parts (1310-01 HOOK PLATE + 1310-02 STUD).
    The engine has invented a £105 purchased part out of the drawing's title block.

    It arrived with NO flag and NO low-confidence marker. That is the dangerous part:
    a silent, confident, wildly wrong number on the deliverable.

QUESTION THIS PROBE ANSWERS: where does BI-DRILLSTUDHOLDER come from?
    Candidate sources, in the order the pipeline touches them:
      1. BOM parser        — invented a row from the title block / project title
      2. note_scan         — LLM read "DRILL STUD HOLDER" as a purchasable item
      3. web price lookup  — searched the web for "drill stud holder" and found £105
      4. bought_in catalogue / RAG fallback — matched a historical junk row
      5. job_bought_in_materials.json — a learned per-job override

    The £105 figure is the tell. A round-ish web/catalogue price, not a geometry
    derivation. But we PROVE it rather than assume it.

WHAT IT READS (all read-only):
    - the job JSON            (the part record + any provenance/source fields)
    - job_bought_in_materials.json  (learned overrides — is 1310 in there?)
    - the note_scan cache      (did the LLM emit this item?)
    - the BoughtInCatalogue / price tables in SDILive (is BI-DRILLSTUDHOLDER a row?)
    - the run log              (which stage first mentions it?)

Usage (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _probe_phantom_boughtin.py
"""
from __future__ import annotations
import os, json, glob, re, sys

TARGET = "BI-DRILLSTUDHOLDER"
TARGET_LOOSE = "DRILLSTUDHOLDER"
JOB_HINT = "1310"

SRC = r"C:\ClaudeVision\src"
OUT = r"C:\ClaudeVision\output"


def hr(t=""):
    print("\n" + "=" * 96)
    if t:
        print(t)
        print("=" * 96)


def show(obj, indent=2):
    print(json.dumps(obj, indent=indent, default=str)[:4000])


# ---------------------------------------------------------------- 1. the JSON
def probe_json():
    hr("1. JOB JSON — the part record and any provenance fields")
    cands = glob.glob(os.path.join(OUT, "json", "*1310*.json"))
    if not cands:
        print("  !! no 1310 JSON found in", os.path.join(OUT, "json"))
        return
    path = max(cands, key=os.path.getmtime)
    print("  file:", path)
    data = json.load(open(path, "r", encoding="utf-8"))

    parts = data.get("parts") or data.get("part_estimates") or []
    print(f"  parts in JSON: {len(parts)}")

    for p in parts:
        pn = str(p.get("part_number") or p.get("partNumber") or "")
        if TARGET_LOOSE in pn.upper().replace("-", "").replace(" ", ""):
            print("\n  >>> FOUND THE PHANTOM PART RECORD <<<")
            show(p)
            print("\n  --- keys that may carry provenance ---")
            for k in p:
                if any(h in k.lower() for h in
                       ("source", "prov", "origin", "conf", "price", "cost",
                        "lookup", "catalog", "rag", "note", "learned", "web")):
                    print(f"    {k!r}: {p[k]!r}")
            return
    print("  (not found as a part record — check other JSON sections)")

    # sweep the whole doc for the string
    blob = json.dumps(data)
    if TARGET_LOOSE in blob.upper().replace("-", "").replace(" ", ""):
        print("\n  string IS present elsewhere in the JSON — dumping context:")
        for m in re.finditer(TARGET_LOOSE, blob.upper()):
            s = max(0, m.start() - 400)
            print("   ...", blob[s:m.start() + 400].replace("\\n", " "), "...")
            print("   ---")
            break


# --------------------------------------------- 2. learned per-job overrides
def probe_learned_overrides():
    hr("2. job_bought_in_materials.json — a learned per-job override?")
    path = os.path.join(SRC, "job_bought_in_materials.json")
    if not os.path.exists(path):
        print("  (file not present)")
        return
    data = json.load(open(path, "r", encoding="utf-8"))
    print("  top-level keys:", list(data)[:40])
    hit = False
    blob = json.dumps(data).upper()
    if JOB_HINT in blob:
        print(f"\n  '{JOB_HINT}' APPEARS in this file — dumping matching entries:")
        for k, v in (data.items() if isinstance(data, dict) else []):
            if JOB_HINT in str(k).upper() or JOB_HINT in json.dumps(v).upper():
                print(f"\n   key: {k!r}")
                show(v, indent=4)
                hit = True
    if TARGET_LOOSE in blob.replace("-", "").replace(" ", ""):
        print(f"\n  !! '{TARGET}' APPEARS in the learned overrides — THIS IS THE SOURCE")
        hit = True
    if not hit:
        print("  no 1310 / phantom entry here — NOT the source")


# --------------------------------------------------- 3. note-scan LLM output
def probe_note_scan():
    hr("3. NOTE-SCAN / LLM cache — did the model emit this as an item?")
    pats = [
        os.path.join(OUT, "**", "*note*scan*"),
        os.path.join(OUT, "**", "*notes*"),
        os.path.join(SRC, "**", "*note_scan*cache*"),
        os.path.join(SRC, ".cache", "**", "*"),
    ]
    seen = set()
    for pat in pats:
        for f in glob.glob(pat, recursive=True):
            if not os.path.isfile(f) or f in seen:
                continue
            seen.add(f)
            try:
                txt = open(f, "r", encoding="utf-8", errors="ignore").read()
            except Exception:
                continue
            if TARGET_LOOSE in txt.upper().replace("-", "").replace(" ", ""):
                print(f"\n  HIT in: {f}")
                i = txt.upper().replace("-", "").replace(" ", "").find(TARGET_LOOSE)
                print("   ...", txt[max(0, i - 500):i + 500], "...")
    if not seen:
        print("  (no note-scan artefacts found on disk — may be in-memory only)")
    else:
        print(f"  scanned {len(seen)} cache/artefact file(s)")


# ------------------------------------------------------------ 4. the run log
def probe_log():
    hr("4. RUN LOG — which stage first mentions it?")
    cands = glob.glob(os.path.join(OUT, "logs", "*1310*.log"))
    if not cands:
        print("  !! no 1310 log found")
        return
    path = max(cands, key=os.path.getmtime)
    print("  file:", path)
    lines = open(path, "r", encoding="utf-8", errors="ignore").read().splitlines()
    for i, ln in enumerate(lines):
        if TARGET_LOOSE in ln.upper().replace("-", "").replace(" ", "") \
           or "105" in ln and "DRILL" in ln.upper():
            lo, hi = max(0, i - 6), min(len(lines), i + 7)
            print(f"\n  --- log lines {lo}-{hi} ---")
            for j in range(lo, hi):
                mark = ">>" if j == i else "  "
                print(f"  {mark} {lines[j]}")
            print("  ---")


# --------------------------------------------------- 5. the price source (DB)
def probe_db():
    hr("5. SDILive — is BI-DRILLSTUDHOLDER a catalogue row? where does £105 live?")
    try:
        import pyodbc
    except ImportError:
        print("  pyodbc not importable here — skipping DB probe")
        return
    try:
        from config import SQL_CONN_STR  # type: ignore
        cn = pyodbc.connect(SQL_CONN_STR, autocommit=True)
    except Exception as e:
        print("  could not connect using config.SQL_CONN_STR:", e)
        print("  (skip — but check BoughtInCatalogue manually for the SKU)")
        return

    cur = cn.cursor()
    queries = [
        ("BoughtInCatalogue exact/like",
         "SELECT TOP 20 * FROM dbo.BoughtInCatalogue "
         "WHERE sku LIKE ? OR description LIKE ?",
         ("%DRILLSTUD%", "%DRILL STUD%")),
        ("any table row priced 105",
         "SELECT TOP 20 * FROM dbo.BoughtInCatalogue WHERE price = 105.0", ()),
    ]
    for label, sql, args in queries:
        print(f"\n  -- {label} --")
        try:
            cur.execute(sql, *args) if args else cur.execute(sql)
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
            if not rows:
                print("     (no rows)")
            for r in rows:
                print("     ", dict(zip(cols, r)))
        except Exception as e:
            print("     query failed:", e)
    cn.close()


def main():
    print("PHANTOM BOUGHT-IN PROVENANCE PROBE  (read-only)")
    print(f"target: {TARGET}   job: {JOB_HINT}   observed price: £105.00")
    print("Question: which stage invented a purchased part out of the drawing TITLE?")
    probe_json()
    probe_learned_overrides()
    probe_note_scan()
    probe_log()
    probe_db()
    hr("READ THE ABOVE")
    print("""
The stage that FIRST names BI-DRILLSTUDHOLDER is the culprit. Expect one of:

  * note_scan / LLM       -> it read the title block as a purchasable item.
                             Fix: never mint a bought-in from the project title /
                             drawing title; require an explicit BOM row or note.

  * web price lookup      -> it searched "drill stud holder" and priced it.
                             Fix: gate the lookup — no web price for a part whose
                             name equals the job/assembly title.

  * bought_in catalogue   -> a junk historical row matched on fuzzy description.
                             Fix: price hygiene + require SKU-level confidence.

  * job_bought_in_materials.json -> a learned override polluted from a manual sheet.
                             Fix: remove the entry; re-check the learning source.

WHATEVER the source: the deeper defect is that a part whose name IS THE JOB TITLE,
with no drawing, no geometry, no BOM row and no DXF, was priced at £105 and put on
the deliverable with NO FLAG. Even after we fix the source, a guard belongs here:

    if a bought-in's name/description matches the assembly or project title
    AND it has no BOM row and no geometry -> DO NOT COST IT. Flag it loudly.
""")


if __name__ == "__main__":
    main()
