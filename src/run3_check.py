# -*- coding: utf-8 -*-
"""What did ELECTRICS price at this run, and is the double-count fix active?
  C:\\ClaudeVision\\.venv\\Scripts\\python.exe _run3_check.py"""
import json
PATH = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
with open(PATH, encoding="utf-8") as fh:
    d = json.load(fh)
be = d.get("bay_estimate") or {}
print("=== bay_estimate catalogue lines (this run) ===")
for ln in be.get("lines", []):
    if ln.get("kind") == "catalogue":
        print("  %-12s uc=%-8s src=%-22s conf=%s" % (
            ln.get("code"), ln.get("unit_cost_gbp"), ln.get("cost_source"), ln.get("cost_confidence")))
es = d.get("estimate_summary") or {}
print("\ndoc total:", es.get("document_total_estimated_cost_gbp"))
# Is the double-count fix active? Check if bought-in part_estimates are EXCLUDED from total.
pe = es.get("part_estimates") or []
bi = [p for p in pe if p.get("page_roles")==["bought_in"]]
print("\nbought-in part_estimate records still present:", len(bi))
for p in bi:
    print("  %-14s ext=%s page_roles=%s" % (
        str(p.get("part_number") or p.get("description"))[:14],
        p.get("extended_total_cost_gbp"), p.get("page_roles")))