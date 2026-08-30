# -*- coding: utf-8 -*-
"""Per-part audit of the pooled 1282 job. Reads the existing PRECACHE JSON, no re-run.
Run on the laptop:  C:\\ClaudeVision\\.venv\\Scripts\\python.exe _parts_audit.py"""
import json

PATH = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.PRECACHE.json"
with open(PATH, encoding="utf-8") as fh:
    d = json.load(fh)

# The run-log "Part summaries" come from manufacturing_writeup.parts — each part holds
# geometry_source + geometry_rollup directly. Read those exact keys.
parts = (d.get("manufacturing_writeup") or {}).get("parts") or []
if not parts:
    parts = (d.get("estimate_summary") or {}).get("part_estimates") or []

print("%-13s %-18s %5s %9s %6s %6s  %s" % ("part","geom_src","rel","cut_mm","bends","holes","ops"))
print("-"*92)
for p in parts:
    pn  = str(p.get("part_number") or "?")[:12]
    src = str(p.get("geometry_source") or "?")[:17]
    g   = p.get("geometry_rollup") or {}
    conf = g.get("confidence") or {}
    rel = conf.get("geometry_reliability")
    rel = ("%.2f" % rel) if isinstance(rel,(int,float)) else "?"
    cut = g.get("estimated_cut_length_mm") or 0
    bends = g.get("estimated_bend_line_count") or 0
    holes = g.get("estimated_hole_count") or g.get("estimated_pierce_count") or 0
    ops = (p.get("textual_operations") or []) + (p.get("inferred_operations") or [])
    if not ops:
        ops = p.get("operations") or []
    ops_s = ",".join(str(o) for o in ops)[:38]
    print("%-13s %-18s %5s %9.0f %6s %6s  %s" % (pn, src, rel, float(cut), bends, holes, ops_s))

print("\nTotal parts:", len(parts))