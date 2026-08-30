# -*- coding: utf-8 -*-
"""READ-ONLY. Fix A2 read region_text.bom/notes (which ARE populated ~1945 chars) but
extract_bom_rows found nothing there. So the CONTENT of region_text.bom must differ from the
clean 'ITEM ... 12532-02-03M FRONT PANEL 1 ...' string that worked in the earlier probe.

Dumps the RAW region_text.bom (and .notes) for page 4 (FRONT PANEL) and page 17 (SHELF BODY),
so we see whether the BOM text is clean or mangled, and can point extract_bom_rows / the fallback
at whatever field actually holds the clean 'partno DESC qty' rows.

Also checks: where in the JSON does the CLEAN BOM text live? (the pooled document_analysis.bom_rows
got 20 clean rows from SOMEWHERE — find that source field.)

Run from C:\\ClaudeVision\\src :
  C:\\ClaudeVision\\.venv\\Scripts\\python.exe _probe_bom_field_content.py
"""
import json
from pathlib import Path

JSON = Path(r"C:\ClaudeVision\output\json\12532-03RecipeCard.json")
data = json.loads(JSON.read_text(encoding="utf-8"))
pages = data.get("pages", [])

for idx, label in ((3, "page4 / FRONT PANEL"), (16, "page17 / SHELF BODY")):
    pg = pages[idx]
    rt = pg.get("region_text") or {}
    print(f"===== {label} (pages[{idx}]) =====")
    for key in ("bom", "notes"):
        val = str(rt.get(key) or "")
        print(f"\n--- region_text.{key} ({len(val)} chars) ---")
        print(repr(val[:600]))
    # does the clean part->desc appear ANYWHERE in this page's fields?
    print(f"\n--- which page fields contain 'FRONT PANEL' or 'SHELF BODY'? ---")
    def find(o, needle, path=""):
        out=[]
        if isinstance(o, dict):
            for k,v in o.items(): out+=find(v,needle,f"{path}.{k}")
        elif isinstance(o, list):
            for i,v in enumerate(o): out+=find(v,needle,f"{path}[{i}]")
        elif isinstance(o, str):
            if needle in o: out.append(path)
        return out
    for needle in ("FRONT PANEL","SHELF BODY"):
        hits = find(pg, needle)
        if hits:
            print(f"   '{needle}' found in: {hits}")
    print()

# where did the pooled 20 clean bom_rows come from?
print("===== pooled document_analysis.bom_rows source =====")
da = data.get("document_analysis") or {}
print(f"pooled bom_rows: {len(da.get('bom_rows') or [])} (these are CLEAN — but missing 02-03M/03-03M)")
print("The pooled rows were parsed from some source text. Fix should use THAT same clean source,")
print("or the field where 'FRONT PANEL'/'SHELF BODY' actually appears (see per-page hits above).")
