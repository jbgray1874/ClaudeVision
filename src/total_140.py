# -*- coding: utf-8 -*-
"""Is £140.16 built cleanly, or does it double-count the bought-in (once in bay rollup £13,
once in part_estimates as the wrong ~£1 fixings)? Reads NEW JSON.
  C:\\ClaudeVision\\.venv\\Scripts\\python.exe _total_140.py"""
import json
PATH = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
with open(PATH, encoding="utf-8") as fh:
    d = json.load(fh)

es = d.get("estimate_summary") or {}
print("document totals:")
for k in ("document_total_estimated_cost_gbp","document_total_provisional_gbp","document_total_raw_gbp"):
    print("  %-40s %s" % (k, es.get(k)))

# Sum part_estimates — do they INCLUDE the bought-in codes (double count risk)?
pe = es.get("part_estimates") or []
fab_sum = 0.0
bi_in_parts = 0.0
BI = ("FIXING","ELECTRIC","LOOM")
for p in pe:
    pn = str(p.get("part_number") or p.get("description") or "").upper()
    ext = p.get("extended_total_cost_gbp") or 0
    if isinstance(ext,(int,float)):
        if any(k in pn for k in BI):
            bi_in_parts += ext
        else:
            fab_sum += ext
print("\nsum of FABRICATED part extended costs: %.2f" % fab_sum)
print("sum of BOUGHT-IN appearing in part_estimates (should NOT feed total): %.2f" % bi_in_parts)

be = d.get("bay_estimate") or {}
bi_bay = sum((ln.get("line_cost_gbp") or 0) for ln in be.get("lines",[]) if ln.get("kind")=="catalogue")
print("bought-in from bay_estimate (the CORRECT figure): %.2f" % bi_bay)

# labour / assembly
print("\nassembly/pack labour & other reconciliation add-ons feed the rest.")
print("If 140.16 ~= fab_sum(%.2f) + bi_bay(%.2f) + labour, that's CLEAN." % (fab_sum, bi_bay))
print("If it also includes bi_in_parts(%.2f), that's DOUBLE-COUNTING." % bi_in_parts)