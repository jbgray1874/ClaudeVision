# -*- coding: utf-8 -*-
"""Does the region selector actually capture the notes from the REAL all_text, and does
Grok then return them? Reproduces live all_text, runs _select_note_regions, shows the
selected text, then calls Grok on it. No swallowing.
  C:\\ClaudeVision\\.venv\\Scripts\\python.exe C:\\ClaudeVision\\src\\_notescan_live2.py"""
import json, traceback
PATH = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
with open(PATH, encoding="utf-8") as fh:
    d = json.load(fh)
pages = d.get("pages", [])
def _pt(p):
    ch=[]
    rt=p.get("region_text") or {}
    if isinstance(rt,dict):
        for v in rt.values():
            if v: ch.append(str(v))
    for k in ("pdfplumber_text","normalized_text","pypdf_text","text","text_preview"):
        v=p.get(k)
        if v: ch.append(str(v))
    ps=p.get("pattern_summary") or {}
    if isinstance(ps,dict) and ps.get("raw_text"): ch.append(str(ps["raw_text"]))
    return " ".join(ch)
primary=" ".join(str(p.get("pdfplumber_text","") or "")+" "+str(p.get("normalized_text","") or "") for p in pages)
secondary=" ".join(_pt(p) for p in pages)
all_text=(primary+" "+secondary).upper()
print("all_text len:", len(all_text))

import note_scan as ns
sel = ns._select_note_regions(all_text)
print("selected len:", len(sel))
for kw in ("JUNCTION BOX","EARTH STRAP","ADHESIVE CABLE","MAINS CABLE","GU10"):
    print("  selected contains %-16s %s" % (kw, kw in sel))
print("\n--- selected text (first 1200 chars) ---")
print(sel[:1200])
print("\n=== call Grok on the prompt built from this ===")
try:
    prompt = ns._build_prompt(all_text)
    raw = ns._call_llm(prompt)
    print("Grok returned type:", type(raw).__name__, "len:", len(raw) if isinstance(raw,(list,str)) else "n/a")
    print("Grok raw (first 600):", repr(raw)[:600])
except Exception:
    traceback.print_exc()