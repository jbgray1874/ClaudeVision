# -*- coding: utf-8 -*-
r"""Is the material gap a systematic RATE/SCRAP difference vs scattered part errors?
Shows engine's material rate + scrap assumptions, and Tim's biggest material lines.
Read-only. (Fixes the dict-sort crash.)
  cd C:\ClaudeVision\src
  C:\ClaudeVision\.venv\Scripts\python.exe _material_rate_check.py
"""
import json, os

J = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
data = json.load(open(J, encoding="utf-8"))

print("=== ENGINE material RATE + SCRAP assumptions ===")
def hunt(d, keys, path=""):
    out=[]
    if isinstance(d, dict):
        for k,v in d.items():
            if any(t in k.lower() for t in keys) and isinstance(v,(int,float,str)):
                out.append((path+k, v))
            out += hunt(v, keys, path+k+".")
    elif isinstance(d, list):
        for i,it in enumerate(d[:3]):
            out += hunt(it, keys, f"{path}[{i}].")
    return out
for k,v in hunt(data, ("per_tonne","scrap","cost_per_kg","gbp_per_kg","waste","nesting")):
    print(f"   {k} = {v}")

print("\n=== TIM's biggest material lines (sorted safely) ===")
PB = r"C:\ClaudeVision\output\csv\estimate_full_parity_bundle.json"
recon = {}
if os.path.exists(PB):
    recon = json.load(open(PB, encoding="utf-8")).get("bom_set_reconciliation", {}) or {}
manual_only = recon.get("manual_only", []) or []
rows=[]
for m in manual_only:
    c = m.get("manual_cost_gbp")
    if isinstance(c,(int,float)):
        lbl = m.get("description") or m.get("part_code") or m.get("code") or m.get("label") or "?"
        rows.append((c, str(lbl)[:48]))
rows.sort(key=lambda x: x[0], reverse=True)   # sort by cost only — no dict comparison
print(f"{'£cost':>10}  description")
for c, lbl in rows[:20]:
    print(f"{c:>10.2f}  {lbl}")
print(f"\nTim manual_only line count = {len(manual_only)}")
