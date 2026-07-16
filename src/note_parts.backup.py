# -*- coding: utf-8 -*-
"""Does the engine CAPTURE the note-described bought-in mentions (cable clips, earth strap,
mains cable) in extracted text — even though it doesn't turn them into BOM lines?
Shows: (1) the note text IS captured, (2) it's not in any BOM row. Reads PRECACHE, no re-run.
  C:\\ClaudeVision\\.venv\\Scripts\\python.exe _note_parts.py"""
import json, re
PATH = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.PRECACHE.json"
with open(PATH, encoding="utf-8") as fh:
    d = json.load(fh)

NOTE_PHRASES = ["CABLE CLIP", "ADHESIVE CABLE", "EARTH STRAP", "MAINS CABLE",
                "CABLE TIE", "JUNCTION BOX", "LED LINK", "GU10"]

# 1. Is the note text captured anywhere in the extracted page text?
blob = json.dumps(d).upper()
print("=== are these note phrases CAPTURED in extracted text? ===")
for ph in NOTE_PHRASES:
    n = blob.count(ph)
    print("  %-16s %s" % (ph, ("CAPTURED x%d" % n) if n else "NOT in text"))

# 2. Are any of them in a BOM row (i.e. turned into a part)?
da = d.get("document_analysis") or {}
rows = (da.get("bom_rows") or []) + (da.get("bay_bom_rows") or [])
row_blob = " ".join(str(r.get("description","")) + " " + str(r.get("part_number","")) for r in rows).upper()
print("\n=== are any in a BOM ROW (turned into a part)? ===")
for ph in NOTE_PHRASES:
    print("  %-16s %s" % (ph, "in BOM" if ph in row_blob else "NOT a BOM line"))