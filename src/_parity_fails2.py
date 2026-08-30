# -*- coding: utf-8 -*-
r"""Show the 4 money_fail lines with the CORRECT column names, plus the
totals-level comparison. Read-only.
  cd C:\ClaudeVision\src
  C:\ClaudeVision\.venv\Scripts\python.exe _parity_fails2.py
"""
import json, csv

C = r"C:\ClaudeVision\output\csv\estimate_full_parity_flat.csv"
J = r"C:\ClaudeVision\output\csv\estimate_full_parity_bundle.json"

print("=== ALL non-OK lines (the 4 fails) with real fields ===\n")
with open(C, encoding="utf-8") as fh:
    rows = list(csv.DictReader(fh))

for r in rows:
    st = str(r.get("status","")).lower()
    if st not in ("match", "ok", "money_match", ""):  # show fails/warnings
        print(f"STATUS={r.get('status')}  CATEGORY={r.get('category')}  SECTION={r.get('section')}")
        print(f"  label        : {r.get('label') or r.get('display_label')}")
        print(f"  operation    : {r.get('canonical_operation') or r.get('operation_code')}")
        print(f"  JSON cost    : {r.get('json_labour_cost_gbp') or r.get('json_numeric')}")
        print(f"  workbook cost: {r.get('workbook_line_cost_gbp') or r.get('workbook_cached_numeric')}")
        print(f"  JSON hours   : {r.get('json_hours_decimal')}   workbook hours: {r.get('workbook_hours_decimal')}")
        print(f"  cost var %   : {r.get('cost_pct_variance')}    hours var %: {r.get('hours_pct_variance')}")
        print(f"  detail       : {str(r.get('detail',''))[:80]}")
        print()

print("=== TOTALS comparison (the headline parity) ===")
b = json.load(open(J, encoding="utf-8"))
# look for a totals / headline section
def hunt(d, path=""):
    if isinstance(d, dict):
        for k, v in d.items():
            kl = k.lower()
            if ("total" in kl or "headline" in kl or "subtotal" in kl or "grand" in kl) and isinstance(v,(int,float)):
                print(f"   {path}{k} = {v}")
            hunt(v, path+k+".")
    elif isinstance(d, list):
        pass  # skip the long per-part lists
# only top 2 levels to avoid the noise
for k, v in b.items():
    if isinstance(v, dict):
        for k2, v2 in v.items():
            if "total" in k2.lower() and isinstance(v2,(int,float)):
                print(f"   {k}.{k2} = {v2}")
    elif isinstance(v,(int,float)) and "total" in k.lower():
        print(f"   {k} = {v}")
