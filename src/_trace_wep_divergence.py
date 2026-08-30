r"""READ-ONLY. Trace WHY workbook_equivalent_pricing = £214.11 but the spreadsheet = £189.01.
Show:
  1) _build_workbook_equivalent_pricing source (estimator.py ~2927) — its actual arithmetic
     (m59, m103, m105 formulas, overhead, rebate).
  2) main.py 520-555 — the re-build step: what _new_mat / _new_lab / _bought_in_total /
     _assembly_cost it feeds in, and how _m105_rec is used.
  3) From the fresh JSON: the actual values that go IN (part material total, labour total,
     bought_in, assembly) so we can hand-compute both paths and see the split.
No edits — pure diagnosis so the fix targets the real cause."""
import re, json

# 1) the WEP builder arithmetic
p=r"C:\ClaudeVision\src\estimator.py"
src=open(p,encoding="utf-8",errors="replace").read()
m=re.search(r"def _build_workbook_equivalent_pricing\b.*?(?=\n    def |\ndef )", src, re.S)
print("="*70); print("1 — _build_workbook_equivalent_pricing arithmetic (estimator.py)"); print("="*70)
if m:
    for ln in m.group(0).splitlines()[:60]:
        print("  ", ln.rstrip()[:104])

# 2) main.py re-build step
print("\n"+"="*70); print("2 — main.py re-build step (520-556)"); print("="*70)
mp=open(r"C:\ClaudeVision\src\main.py",encoding="utf-8",errors="replace").read().splitlines()
for i in range(505, min(len(mp),560)):
    if mp[i].strip():
        print(f"  {i+1}: {mp[i].rstrip()[:100]}")

# 3) the actual input values from the fresh JSON
print("\n"+"="*70); print("3 — actual input values (fresh JSON) to hand-compute both paths"); print("="*70)
S=json.load(open(r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json",encoding="utf-8"))
es=S.get("estimate_summary",{})
wep=es.get("workbook_equivalent_pricing",{})
cb=S.get("cost_breakdown",{})
print("  workbook_equivalent_pricing block (the £214 path):")
for k,v in wep.items(): print(f"    {k} = {v}")
print("\n  cost_breakdown (may feed spreadsheet):")
print("    material.total =", cb.get("material",{}).get("total"))
print("    labour.total   =", cb.get("labour",{}).get("total"))
print("  document_total_estimated_cost_gbp =", es.get("document_total_estimated_cost_gbp") or S.get("document_total_estimated_cost_gbp"))
# sum part material + labour directly
parts=es.get("part_estimates") or []
pm=sum(float(p.get("material_cost_gbp") or 0) for p in parts)
pl=sum(float(p.get("labour_cost_gbp") or 0) for p in parts)
print(f"\n  sum(part material_cost_gbp) = {pm:.2f}")
print(f"  sum(part labour_cost_gbp)   = {pl:.2f}")
print(f"  part count = {len(parts)}")
# bought-in + assembly if present
print("\n  bought_in / assembly hints:")
for k in ("bought_in_total_gbp","bought_in_materials_total_gbp","assembly_labour_gbp","assembly_pack_labour_gbp"):
    for box,lbl in [(es,"es"),(S,"root"),(cb,"cb")]:
        if isinstance(box,dict) and k in box: print(f"    {lbl}.{k} = {box[k]}")
print("\n  overhead/rebate:")
for k in ("overhead_absorption_factor","m107_rebate_fraction","m109_sell_margin_fraction"):
    if k in wep: print(f"    {k} = {wep[k]}")
