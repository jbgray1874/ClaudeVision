r"""READ-ONLY. wb_populate computes the CORRECT £189.01 (material £133.45, labour £42.33) but
WEP is fed stale £108.63/£75.35. Find the Python values wb_populate writes into the template
for material + labour subtotals (before Excel computes), because THOSE are what WEP should be
fed. Show wb_populate's material/labour aggregation + any total it computes/returns. Also check
if wb_populate returns or stashes these totals anywhere the WEP rebuild could read. No edits."""
import re
p=r"C:\ClaudeVision\src\wb_populate.py"
src=open(p,encoding="utf-8",errors="replace").read()
L=src.splitlines()

# material + labour subtotal aggregation in wb_populate
print("="*70); print("wb_populate material/labour subtotal computation"); print("="*70)
for i,ln in enumerate(L):
    if re.search(r"material.*subtotal|labour.*subtotal|total_material|total_labour|_mat_total|_lab_total|sum.*material|sum.*labour|material_sum|labour_sum|running.*mat|running.*lab", ln, re.I):
        for j in range(max(0,i-1),min(len(L),i+2)):
            mark=">>" if j==i else "  "
            print(f"{mark}{j+1}: {L[j].rstrip()[:100]}")
        print("   --")

# what does populate_workbook return?
print("\n"+"="*70); print("populate_workbook return + any totals it exposes"); print("="*70)
m=re.search(r"def populate_workbook\b", src)
if m:
    # find return statements in the function
    for i,ln in enumerate(L):
        if re.search(r"^\s*return\b", ln) and i>L.index(next(x for x in L if "def populate_workbook" in x)):
            print(f"  {i+1}: {ln.strip()[:100]}")
            if L.index(next(x for x in L if "def populate_workbook" in x))+400 < i: break

# does it write a subtotal cell we can read? (cell refs like M63, M113)
print("\n"+"="*70); print("cells wb_populate writes for subtotals (M63/M113/M115 etc.)"); print("="*70)
for i,ln in enumerate(L):
    if re.search(r"M63|M113|M115|M59|M103|M105|material_subtotal|labour_subtotal|['\"]?unit_cost", ln):
        print(f"  {i+1}: {ln.strip()[:100]}")
