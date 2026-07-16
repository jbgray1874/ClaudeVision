# -*- coding: utf-8 -*-
"""Show every BOM row the engine extracted, per page/source, vs the pooled bay BOM.
Reveals whether any BOM-table rows were dropped between extraction and the bay rollup.
Reads PRECACHE, no re-run.  C:\\ClaudeVision\\.venv\\Scripts\\python.exe _bom_audit.py"""
import json
PATH = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.PRECACHE.json"
with open(PATH, encoding="utf-8") as fh:
    d = json.load(fh)

# 1. Raw BOM rows from document_analysis (what the BOM parser found)
da = d.get("document_analysis") or {}
rows = da.get("bom_rows") or []
print("=== document_analysis.bom_rows (raw extracted) : %d rows ===" % len(rows))
for r in rows:
    pn = r.get("part_number") or r.get("part_code") or r.get("code") or ""
    desc = r.get("description") or ""
    qty = r.get("quantity") or r.get("qty") or ""
    src = r.get("source") or r.get("source_page") or ""
    print("  %-18s %-38s qty=%-4s %s" % (str(pn)[:18], str(desc)[:38], qty, src))

# 2. The synthesized bay BOM rows (post folder-as-job merge)
bb = da.get("bay_bom_rows") or []
if bb:
    print("\n=== document_analysis.bay_bom_rows (synthesized) : %d rows ===" % len(bb))
    for r in bb:
        pn = r.get("part_number") or r.get("code") or ""
        desc = r.get("description") or ""
        print("  %-18s %-38s" % (str(pn)[:18], str(desc)[:38]))

# 3. Final bay_estimate lines (what got costed/shown)
be = d.get("bay_estimate") or {}
lines = be.get("lines") or []
print("\n=== bay_estimate.lines (final) : %d lines ===" % len(lines))
for ln in lines:
    print("  %-18s %-30s kind=%-9s costed=%s" % (
        str(ln.get("code"))[:18], str(ln.get("description"))[:30],
        ln.get("kind"), ln.get("costed")))

# 4. Per-page: how many BOM-looking rows did each page's raw text contain vs extract?
print("\n=== pages with an ITEM/DWG NO/DESCRIPTION/QTY table header ===")
pages = (d.get("pages") or []) or (da.get("pages") or [])
for i, pg in enumerate(pages):
    txt = ""
    for k in ("normalized_text","pdfplumber_text","text_preview","text"):
        if isinstance(pg, dict) and pg.get(k):
            txt = pg[k]; break
    U = txt.upper()
    if "DWG NO" in U or ("ITEM" in U and "DESCRIPTION" in U and "QTY" in U):
        # count rows that look like "<n> <code> <desc> <qty>"
        print("  page idx %d: HAS BOM TABLE  (len %d)" % (i, len(txt)))