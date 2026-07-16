# -*- coding: utf-8 -*-
"""Reproduce the EXACT all_text the live hook builds, and run the scan on THAT.
Catches: text too long (cable-clip notes beyond 6000-char cap), upper-case, or empty.
  C:\\ClaudeVision\\.venv\\Scripts\\python.exe C:\\ClaudeVision\\src\\_notescan_live.py"""
import json, re
PATH = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
with open(PATH, encoding="utf-8") as fh:
    d = json.load(fh)

# Rebuild all_text exactly as extract_bought_in_from_pages does
pages = d.get("pages", [])
def _page_text(p):
    chunks=[]
    rt=p.get("region_text") or {}
    if isinstance(rt,dict):
        for v in rt.values():
            if v: chunks.append(str(v))
    for k in ("pdfplumber_text","normalized_text","pypdf_text","text","text_preview"):
        v=p.get(k)
        if v: chunks.append(str(v))
    ps=p.get("pattern_summary") or {}
    if isinstance(ps,dict) and ps.get("raw_text"): chunks.append(str(ps["raw_text"]))
    return " ".join(chunks)
primary = " ".join(str(p.get("pdfplumber_text","") or "")+" "+str(p.get("normalized_text","") or "") for p in pages)
secondary = " ".join(_page_text(p) for p in pages)
all_text = (primary+" "+secondary).upper()

print("all_text length:", len(all_text))
print("contains 'CABLE CLIP'? ", "CABLE CLIP" in all_text)
print("contains 'ADHESIVE CABLE'?", "ADHESIVE CABLE" in all_text)
print("contains 'EARTH STRAP'?  ", "EARTH STRAP" in all_text)
print("contains 'JUNCTION BOX'? ", "JUNCTION BOX" in all_text)
# Where do those notes sit? Before/after the 6000-char prompt cap?
for kw in ("ADHESIVE CABLE","EARTH STRAP","JUNCTION BOX","MAINS CABLE","GU10"):
    idx = all_text.find(kw)
    print("  '%s' first at char %s %s" % (kw, idx, "(BEYOND 6000 cap!)" if idx>6000 else "(within cap)" if idx>=0 else "(NOT FOUND)"))

print("\n=== run scan on the REAL all_text ===")
import note_scan as ns
def sb(c,desc,q): return {"part_number":c,"description":desc,"quantity":q,"page_roles":["bought_in"]}
out = ns.scan_notes_for_bought_in(all_text, existing_pns={"ELECTRICS","FIXING5","FIXING236","FIXING125"},
    seen_codes={"ELECTRICS","FIXING5","FIXING236","FIXING125"}, existing_descriptions=set(), stub_builder=sb)
print("returned %d items" % len(out))
for s in out: print("  ", s["part_number"])

