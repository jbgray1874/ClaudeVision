# -*- coding: utf-8 -*-
"""Does each assembly bay-line capture its detail parts' real DXF costs, or fall back to a
provisional GA estimate? Compares the assembly bay-line cost vs the sum of its costed
children from part_estimates. Reads PRECACHE, no re-run.
  C:\\ClaudeVision\\.venv\\Scripts\\python.exe _rollup_audit.py"""
import json
PATH = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.PRECACHE.json"
with open(PATH, encoding="utf-8") as fh:
    d = json.load(fh)

# Per-part unit/extended costs from part_estimates (the real DXF-based fab costs)
pe = (d.get("estimate_summary") or {}).get("part_estimates") or []
cost = {}
for p in pe:
    pn = str(p.get("part_number") or "")
    cost[pn] = {
        "unit": p.get("unit_total_cost_gbp"),
        "ext":  p.get("extended_total_cost_gbp"),
        "qty":  p.get("quantity"),
    }

print("=== all part_estimates costs ===")
tot_ext = 0.0
for pn, c in cost.items():
    e = c["ext"] or 0
    tot_ext += e if isinstance(e,(int,float)) else 0
    print("  %-14s qty=%-3s unit=%-8s ext=%-8s" % (pn, c["qty"], c["unit"], c["ext"]))
print("  -> sum of all extended part costs: %.2f" % tot_ext)

# Bay lines and their costs
be = d.get("bay_estimate") or {}
print("\n=== bay_estimate lines vs what they should contain ===")
bay_tot = 0.0
for ln in be.get("lines", []):
    code = str(ln.get("code") or "")
    uc = ln.get("unit_cost_gbp"); lc = ln.get("line_cost_gbp")
    bay_tot += lc if isinstance(lc,(int,float)) else 0
    print("  %-14s kind=%-9s uc=%-7s line=%-7s src=%s" % (
        code, ln.get("kind"), uc, lc, ln.get("cost_source")))
print("  -> bay lines total: %.2f" % bay_tot)
print("\nbay_unit_total_gbp:", be.get("bay_unit_total_gbp"))
print("headline_suppressed:", be.get("headline_suppressed"))

# The document total for reference
print("\nestimate_summary doc total / reconciled:",
      (d.get("estimate_summary") or {}).get("document_total_gbp"),
      d.get("reconciled_document_total_gbp"))