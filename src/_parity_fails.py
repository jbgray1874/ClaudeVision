# -*- coding: utf-8 -*-
r"""Show the money_fail lines + totals from the parity bundle, so we see exactly
where the engine differs from Tim. Read-only.
  cd C:\ClaudeVision\src
  C:\ClaudeVision\.venv\Scripts\python.exe _parity_fails.py
"""
import json, csv, os

J = r"C:\ClaudeVision\output\csv\estimate_full_parity_bundle.json"
C = r"C:\ClaudeVision\output\csv\estimate_full_parity_flat.csv"

print("=== TOTALS (engine vs Tim) ===")
try:
    b = json.load(open(J, encoding="utf-8"))
    # hunt for total-level numbers
    def find(d, keys, path=""):
        out = []
        if isinstance(d, dict):
            for k, v in d.items():
                if any(t in k.lower() for t in keys) and isinstance(v, (int, float)):
                    out.append((path + k, v))
                out += find(v, keys, path + k + ".")
        elif isinstance(d, list):
            for i, it in enumerate(d):
                out += find(it, keys, f"{path}[{i}].")
        return out
    for k, v in find(b, ("total", "manual", "ai_value", "money")):
        print(f"   {k} = {v}")
except Exception as e:
    print("   (could not read bundle:", e, ")")

print("\n=== MONEY_FAIL / mismatch lines from flat CSV ===")
try:
    with open(C, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if rows:
        print("   columns:", list(rows[0].keys()))
        print()
    for r in rows:
        status = " ".join(str(v).lower() for v in r.values())
        if "fail" in status or "mismatch" in status:
            # print the most useful fields
            label = r.get("part_number") or r.get("metric_name") or r.get("line") or r.get("description") or "?"
            man = r.get("manual_value") or r.get("manual") or ""
            ai = r.get("ai_value") or r.get("ai") or ""
            var = r.get("abs_variance") or r.get("pct_variance") or ""
            st = r.get("status") or ""
            print(f"   FAIL: {label}  manual={man}  ai={ai}  var={var}  [{st}]")
            print(f"         notes: {str(r.get('notes',''))[:70]}")
except Exception as e:
    print("   (could not read CSV:", e, ")")
