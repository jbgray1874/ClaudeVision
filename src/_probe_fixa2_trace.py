# -*- coding: utf-8 -*-
"""READ-ONLY DIAGNOSTIC. Fix A2 is in the file (fingerprint confirmed) but 12532-02-03M /
12532-03-03M still show Description=None. Find out WHY: does Fix A2 fire, does extract_bom_rows
find these parts in the per-page text at runtime, and is the description set then LOST downstream?

Rather than patch, this reads the persisted JSON and checks:
  1. What region_text keys each page actually has (is 'notes' populated, or empty at runtime?)
  2. Whether the page-4 / page-17 region_text.notes contains the BOM text with these parts
  3. Runs extract_bom_rows on the ACTUAL persisted region_text (not a hardcoded string)

This tells us if Fix A2's INPUT (region_text.notes) is actually populated in the real run, or
if the field is empty at that point (explaining why the fix found nothing).

Run from C:\\ClaudeVision\\src :
  C:\\ClaudeVision\\.venv\\Scripts\\python.exe _probe_fixa2_trace.py
"""
import json
from pathlib import Path

JSON = Path(r"C:\ClaudeVision\output\json\12532-03RecipeCard.json")
data = json.loads(JSON.read_text(encoding="utf-8"))
pages = data.get("pages", [])
print(f"pages in JSON: {len(pages)}\n")

# 1. what region_text keys exist per page, and are they populated?
print("=== region_text presence per page (which keys have content) ===")
for i, pg in enumerate(pages):
    rt = pg.get("region_text") or {}
    if not rt:
        print(f"  page[{i}]: NO region_text key at all")
        continue
    keys_with_content = {k: len(str(v)) for k, v in rt.items() if v}
    if keys_with_content:
        print(f"  page[{i}]: {keys_with_content}")
    else:
        print(f"  page[{i}]: region_text present but ALL keys empty")

# 2/3. for the pages that should carry FRONT PANEL / SHELF BODY, run extract_bom_rows live
print("\n=== run extract_bom_rows on the ACTUAL persisted region_text (bom/notes/general) ===")
try:
    from extractor_patterns import extract_bom_rows
    for i, pg in enumerate(pages):
        rt = pg.get("region_text") or {}
        bom_text = " ".join(str(rt.get(k) or "") for k in ("bom","notes","general")).strip()
        if not bom_text:
            continue
        rows = extract_bom_rows(bom_text)
        hits = [(r.get("part_number"), r.get("description")) for r in (rows or [])
                if str(r.get("part_number") or "") in ("12532-02-03M","12532-03-03M")]
        if hits:
            print(f"  page[{i}]: extract_bom_rows FOUND {hits}")
except Exception as e:
    print("  error:", e)

print("\nVERDICT:")
print("  - If region_text.notes is EMPTY at runtime (section 1) -> Fix A2 had no input; the BOM")
print("    text the earlier probe used came from a DIFFERENT field (page_analysis.title_block or")
print("    a raw text field), not region_text. Fix A2 targets the wrong field.")
print("  - If extract_bom_rows FINDS the parts here (section 3) but descriptions are still None on")
print("    the sheet -> Fix A2's parts-list write is being overwritten downstream (wrong timing).")
