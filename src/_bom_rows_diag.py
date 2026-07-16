# -*- coding: utf-8 -*-
r"""Inspect the structured bom_rows in the 1282 JSON — do the FIXING/VINYL codes appear
as rows with a quantity column? This decides whether Issue 3 (qty) can be read genuinely
from the structured BOM (Option B) rather than text-scraped.
READ ONLY.
  C:\ClaudeVision\.venv\Scripts\python.exe _bom_rows_diag.py
"""
import json, sys
from pathlib import Path

p = Path(r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json")
if not p.exists():
    print(f"JSON not found: {p}"); sys.exit(1)

data = json.loads(p.read_text(encoding="utf-8"))
rows = (data.get("document_analysis") or {}).get("bom_rows") or []
print(f"=== {len(rows)} bom_rows ===")
for r in rows:
    pn = r.get("part_number")
    dsc = r.get("description")
    qty = r.get("quantity")
    keys = sorted(r.keys())
    print(f"  pn={pn!r:18} qty={qty!r:5} desc={str(dsc)[:42]!r}")
print()
print("=== keys present on a bom_row (first row) ===")
if rows:
    print("  ", sorted(rows[0].keys()))
print()
# Specifically: any row whose part_number or description carries a FIXING/VINYL code?
import re
RE = re.compile(r"(FIXING|VINYL|PRINT|SUBPLAS|POWDER)[ \-]?(\d{1,5})", re.IGNORECASE)
print("=== rows mentioning a FIXING/VINYL/etc code (pn or desc) ===")
for r in rows:
    blob = f"{r.get('part_number','')} {r.get('description','')}"
    m = RE.search(blob)
    if m:
        print(f"  code={m.group(1).upper()}{m.group(2)}  qty={r.get('quantity')!r}  pn={r.get('part_number')!r}  desc={str(r.get('description'))[:40]!r}")
