r"""READ-ONLY. To fix the hybrid BOM properly I must reuse the existing merge mechanics, not invent
parallel ones. Show:
  1) The REST of _reconcile_bought_in (estimator ~3700-3800) — HOW it merges a matched pair: does it
     sum qty, keep higher-authority, update fields? And the _BOUGHT_IN_SOURCE_RANK authority order.
  2) _bought_in_token_set + _bought_in_same_item — the matching logic I'd reuse to match dual-path
     'FIXING'/self-clinch to part_estimate 'BI-SELFCLINCHNUT'.
  3) Where dual-path rows could be turned INTO part_estimates (or merged into them) — the point
     between the dual-path override (file_scan 1219) and wb_populate reading part_estimates (344).
No edits — understand the merge mechanics before writing the reconciliation."""
import os, re
SRC=r"C:\ClaudeVision\src"
p=os.path.join(SRC,"estimator.py"); L=open(p,encoding="utf-8",errors="replace").read().splitlines()

print("="*66); print("1 — _reconcile_bought_in MERGE half (3700-3800)"); print("="*66)
for i in range(3699, min(len(L),3800)):
    print(f"  {i+1}: {L[i].rstrip()[:98]}")

print("\n"+"="*66); print("2 — _BOUGHT_IN_SOURCE_RANK (authority order)"); print("="*66)
for i,ln in enumerate(L):
    if "_BOUGHT_IN_SOURCE_RANK" in ln and "=" in ln:
        for j in range(i, min(len(L),i+18)):
            print(f"  {j+1}: {L[j].rstrip()[:92]}")
            if "}" in L[j] and j>i: break
        break

print("\n"+"="*66); print("3 — _bought_in_token_set + _bought_in_same_item (matching logic)"); print("="*66)
for name in ("_bought_in_token_set","_bought_in_same_item"):
    for i,ln in enumerate(L):
        if f"def {name}" in ln:
            for j in range(i, min(len(L),i+26)):
                print(f"  {j+1}: {L[j].rstrip()[:96]}")
                if j>i and re.match(r"def ", L[j]): break
            print()
            break
