# -*- coding: utf-8 -*-
r"""Trace the EXACT SQL + parameters _get_udef_anchor sends for the loom.
We've ruled out exact-code and description-LIKE by direct query, yet the function
returns ELECTRICS001/£539. This wraps the fetch to print what's actually executed.
Read-only.
  cd C:\ClaudeVision\src
  C:\ClaudeVision\.venv\Scripts\python.exe _udef_trace.py
"""
import sys, os
sys.path.insert(0, os.getcwd()); sys.path.insert(0, r"C:\ClaudeVision\src")
from pricing_service import PricingService

ps = PricingService()

# Wrap the fetch method to capture every SQL + params it runs
_orig = ps._fetch_one_with_retry
def _traced(sql, params=None, *a, **k):
    print("---- SQL ----")
    print(sql)
    print("---- PARAMS ----")
    print(params)
    res = _orig(sql, params, *a, **k)
    print("---- RESULT ----")
    print(res)
    print()
    return res
ps._fetch_one_with_retry = _traced

print("### Calling _get_udef_anchor for the loom ###\n")
loom = {"part_number": "ELECTRICS", "description": "50cm LOOM LIGHTING ELECTRICS"}
res = ps._get_udef_anchor(loom)
print("### FINAL UDEF RESULT ###")
print(f"  price = {res.get('unit_price_gbp') if res else None}")
print(f"  provenance = {res.get('provenance') if res else None}")
