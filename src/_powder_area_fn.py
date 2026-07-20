r"""
READ-ONLY. Read the _powder_coated_area_m2 function in estimator.py — the SECOND powder
path (distinct from wb_populate's L x W loop). This is the prime leak suspect: if it reads
blank_area_mm2 (shapely net area) internally, then deploying shapely net-area changes powder
here. Skips the permission-denied load_drawings_rewrite.py.
"""
import os, re
p = r"C:\ClaudeVision\src\estimator.py"
L = open(p, encoding="utf-8", errors="replace").read().splitlines()

# find the function def and print its whole body
start = next((i for i,l in enumerate(L) if re.search(r"def _powder_coated_area_m2", l)), None)
if start is None:
    print("_powder_coated_area_m2 NOT FOUND in estimator.py")
else:
    i = start+1; end=len(L)
    while i < len(L):
        if re.match(r"def \w", L[i]) and not L[i].startswith(" "):
            end=i; break
        i+=1
    print(f"=== _powder_coated_area_m2  (lines {start+1}-{end}) ===")
    for j in range(start, min(end, start+80)):
        print(f"{j+1}: {L[j].rstrip()[:150]}")

# also: does it read blank_area_mm2 anywhere in that body?
print("\n=== does the powder-area fn reference blank_area_mm2 / area (net) ? ===")
if start is not None:
    for j in range(start, end):
        if re.search(r"blank_area_mm2|\.area|net_area|area_mm2", L[j]):
            print(f"  {j+1}: {L[j].strip()[:140]}")
