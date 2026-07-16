# -*- coding: utf-8 -*-
"""Trace what sums to the £119.37 document total: is it built from the SOUND part_estimates
(£89.74) + labour, or from the BROKEN bay_estimate (£23.54)? Determines severity.
Reads PRECACHE, no re-run.  C:\\ClaudeVision\\.venv\\Scripts\\python.exe _total_trace.py"""
import json
PATH = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.PRECACHE.json"
with open(PATH, encoding="utf-8") as fh:
    d = json.load(fh)

# Hunt for every field that looks like a document/bay/material total anywhere in the summary
def scan(obj, path=""):
    hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = k.lower()
            if any(t in kl for t in ("total","subtotal","_gbp","cost")) and isinstance(v,(int,float)):
                if 1 < v < 100000:
                    hits.append((path + "." + k, v))
            hits += scan(v, path + "." + k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:5]):
            hits += scan(v, path + "[%d]" % i)
    return hits

print("=== all total/cost-like numeric fields (top level + reconciliation) ===")
# Just the top-level + key sections, not deep part internals
for sect in ("estimate_summary","bay_estimate","reconciliation","cost_breakdown","totals"):
    s = d.get(sect)
    if isinstance(s, dict):
        print("\n[%s]" % sect)
        for k, v in s.items():
            if isinstance(v,(int,float)) and any(t in k.lower() for t in ("total","cost","gbp","labour","material")):
                print("   %-40s %s" % (k, v))

# Top-level totals
print("\n[top-level]")
for k, v in d.items():
    if isinstance(v,(int,float)) and any(t in k.lower() for t in ("total","cost","gbp")):
        print("   %-40s %s" % (k, v))