"""READ-ONLY. Dump how the assembly BOM table (pages 10-11) actually extracts, so we can
build a DETERMINISTIC parser for the electricals (junction box, mains cable, loom, etc.)
instead of relying on the non-deterministic LLM note-scan.

Shows: raw page text, any structured table rows the extractor already captured, and what
the ITEM/DWG NO./DESCRIPTION/QTY columns look like.

Run: C:\ClaudeVision\.venv\Scripts\python.exe _bom_table_probe.py
"""
import json, io, re
from pathlib import Path

P = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
data = json.load(io.open(P, encoding="utf-8"))

# 1. Find the assembly pages (10, 11) raw text
print("=" * 72)
print("1. RAW TEXT of assembly pages (where the electricals live)")
print("=" * 72)

def walk(o, path="root"):
    if isinstance(o, dict):
        yield path, o
        for k, v in o.items():
            yield from walk(v, f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from walk(v, f"{path}[{i}]")

# Look for page objects with a 'page_number'/'page'/'index' near 10-11 and text
pages_found = []
for path, d in walk(data):
    if isinstance(d, dict):
        pn = d.get("page_number") or d.get("page") or d.get("page_index") or d.get("index")
        txt = d.get("text") or d.get("raw_text") or d.get("page_text") or d.get("content")
        role = d.get("role") or d.get("page_role")
        if txt and isinstance(txt, str) and ("LOOM" in txt.upper() or "JUNCTION" in txt.upper() or "LIGHTING ELECTRICS" in txt.upper()):
            pages_found.append((path, pn, role, txt))

if not pages_found:
    print("  No page text field contained LOOM/JUNCTION directly.")
    print("  Searching for ANY field containing 'LIGHTING ELECTRICS'...")
    for path, d in walk(data):
        if isinstance(d, dict):
            for k, v in d.items():
                if isinstance(v, str) and "LIGHTING ELECTRICS" in v.upper():
                    print(f"    hit @ {path}.{k}  (len {len(v)})")
                    pages_found.append((f"{path}.{k}", None, None, v))
                    break
        if len(pages_found) >= 3:
            break

for path, pn, role, txt in pages_found[:3]:
    print(f"\n  --- {path}  (page={pn}, role={role}) ---")
    # print the slice around the electricals
    up = txt.upper()
    i = up.find("ITEM")
    seg = txt[max(0, i):i+900] if i >= 0 else txt[:900]
    print("  " + seg.replace("\n", "\n  "))

# 2. Show what deterministic recogniser + note-scan currently produced (bought_in parts)
print("\n" + "=" * 72)
print("2. Bought-in parts currently in the estimate (what made it through)")
print("=" * 72)
for p in data.get("parts", []):
    roles = p.get("page_roles") or []
    if "bought_in" in roles or str(p.get("part_number","")).startswith(("NOTE-","BI-","FIXING","VINYL","ELECTRICS")):
        print(f"  {p.get('part_number'):24} {p.get('description')}")

# 3. Is there a structured tables field anywhere for pages 10/11?
print("\n" + "=" * 72)
print("3. Any structured 'table'/'rows'/'bom' fields on assembly pages?")
print("=" * 72)
seen = set()
for path, d in walk(data):
    if isinstance(d, dict):
        for k in d.keys():
            if k.lower() in ("tables", "table", "rows", "bom_rows", "bom", "table_rows", "assembly_bom") and k not in seen:
                seen.add(k)
                print(f"  field '{k}' @ {path}  -> type {type(d[k]).__name__}, "
                      f"len {len(d[k]) if hasattr(d[k],'__len__') else '?'}")
if not seen:
    print("  (none — extractor does not currently emit a structured BOM table; text-parse needed)")
