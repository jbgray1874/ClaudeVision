# -*- coding: utf-8 -*-
"""Why did FIXING5 go from £0.01 (correct, system_cost) to £1.05 (wrong)? Show how each
bought-in part is priced now — which source, which path. Reads the NEW JSON.
  C:\\ClaudeVision\\.venv\\Scripts\\python.exe _fixing_trace.py"""
import json
PATH = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
with open(PATH, encoding="utf-8") as fh:
    d = json.load(fh)

# Bay estimate lines — the authoritative bought-in pricing
be = d.get("bay_estimate") or {}
print("=== bay_estimate catalogue lines ===")
for ln in be.get("lines", []):
    if ln.get("kind") == "catalogue":
        print("  %-12s uc=%-7s line=%-7s src=%-22s conf=%s" % (
            ln.get("code"), ln.get("unit_cost_gbp"), ln.get("line_cost_gbp"),
            ln.get("cost_source"), ln.get("cost_confidence")))

# part_estimates for the fixings — are they ALSO costed here (double path)?
print("\n=== part_estimates for bought-in codes (the £1.05 source?) ===")
pe = (d.get("estimate_summary") or {}).get("part_estimates") or []
for p in pe:
    pn = str(p.get("part_number") or p.get("description") or "")
    if any(k in pn.upper() for k in ("FIXING","ELECTRIC","LOOM")):
        ce = p.get("cost_breakdown") or {}
        print("  %-12s unit_total=%-7s" % (pn[:12], p.get("unit_total_cost_gbp")))
        me = p.get("material_estimate") or {}
        print("       material_estimate unit_cost=%s source=%s" % (
            me.get("unit_material_cost_gbp"), me.get("supplier_source") or me.get("source")))