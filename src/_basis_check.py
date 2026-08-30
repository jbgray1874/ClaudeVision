# -*- coding: utf-8 -*-
r"""Settle the per-bay vs per-order question. For each operation, compare:
  engine hours (per bay)  vs  engine hours x order_qty  vs  Tim's hours
to see which basis Tim's sheet is on. Read-only.
  cd C:\ClaudeVision\src
  C:\ClaudeVision\.venv\Scripts\python.exe _basis_check.py
"""
import json, csv

J_SUMMARY = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
C = r"C:\ClaudeVision\output\csv\estimate_full_parity_flat.csv"

# order quantity
data = json.load(open(J_SUMMARY, encoding="utf-8"))
def find_qty(d):
    if isinstance(d, dict):
        for k, v in d.items():
            if k in ("assumed_job_quantity","order_quantity") and isinstance(v,(int,float)):
                return v
            r = find_qty(v)
            if r: return r
    elif isinstance(d, list):
        for it in d:
            r = find_qty(it)
            if r: return r
    return None
qty = find_qty(data) or 180
print(f"Order quantity = {qty}\n")

# per-operation hours from the flat CSV
with open(C, encoding="utf-8") as fh:
    rows = list(csv.DictReader(fh))

print(f"{'operation':<18} {'eng/bay':>9} {'eng x qty':>11} {'Tim':>9}  {'best basis match'}")
print("-"*70)
for r in rows:
    if r.get("section") != "labour_route":
        continue
    op = r.get("operation_code") or r.get("canonical_operation") or ""
    try:
        eng = float(r.get("json_hours_decimal") or 0)
    except: eng = 0.0
    try:
        tim = float(r.get("workbook_hours_decimal") or 0)
    except: tim = 0.0
    if eng == 0 and tim == 0:
        continue
    eng_order = eng * qty
    # which basis is closer to Tim?
    if tim > 0:
        d_bay = abs(eng - tim) / tim
        d_order = abs(eng_order - tim) / tim
        basis = "PER-BAY match" if d_bay < d_order and d_bay < 0.5 else ("PER-ORDER-ish" if d_order < 1.0 else "NEITHER - real diff")
    else:
        basis = "Tim=0"
    print(f"{op:<18} {eng:>9.3f} {eng_order:>11.1f} {tim:>9.3f}  {basis}")

print("\nIf 'eng x qty' lands near Tim -> Tim is per-ORDER, engine per-BAY (unit mismatch, not error).")
print("If neither matches -> genuine rate/time difference to investigate.")
