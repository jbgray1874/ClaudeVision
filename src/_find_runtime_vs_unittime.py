r"""READ-ONLY. PINNED: costing uses run_times_min_per_unit (laser 0.5 min) but unit_times_min shows
3.5 min — 7x gap, and costing the small one gives the £7.34/hr effective rate. Find which field is
RIGHT by seeing how each is DERIVED:
  1) Where is run_times_min_per_unit computed? (the costed field)
  2) Where is unit_times_min computed? (the displayed field)
  3) What's the relationship — is run = unit - setup? is run throughput-derived and unit
     geometry-derived? Which reflects the REAL operation time Tim would book?
  4) The sheet's 'Total Hours' (e.g. Fold 5.10) — which field does IT come from? (If it shows
     unit_times but costs run_times, that's the display/cost mismatch.)
Read the derivation; identify which field is the artefact."""
import os, re
SRC=r"C:\ClaudeVision\src"
p=os.path.join(SRC,"estimator.py"); L=open(p,encoding="utf-8",errors="replace").read().splitlines()

print("="*66); print("1 — where run_times_min_per_unit is SET (the costed field)"); print("="*66)
for i,ln in enumerate(L):
    if "run_times_min_per_unit" in ln and ("=" in ln or "[" in ln or "setdefault" in ln):
        # show context
        for j in range(max(0,i-3), min(len(L),i+4)):
            mark=">>" if j==i else "  "
            print(f"  {mark}{j+1}: {L[j].rstrip()[:96]}")
        print()

print("="*66); print("2 — where unit_times_min is SET (the displayed field)"); print("="*66)
for i,ln in enumerate(L):
    if "unit_times_min" in ln and ("=" in ln or "[" in ln or "setdefault" in ln):
        for j in range(max(0,i-3), min(len(L),i+4)):
            mark=">>" if j==i else "  "
            print(f"  {mark}{j+1}: {L[j].rstrip()[:96]}")
        print()

print("="*66); print("3 — estimate_process_times: how run vs unit relate"); print("="*66)
# find the function and show where both are built
start=None
for i,ln in enumerate(L):
    if "def estimate_process_times" in ln: start=i; break
if start:
    for i in range(start, min(len(L),start+140)):
        ln=L[i]
        if re.search(r"(run_time|unit_time|throughput|/\s*throughput|60\.0|setup|per_unit|parts_per|band)", ln, re.I):
            print(f"  {i+1}: {ln.rstrip()[:98]}")

print("\n"+"="*66); print("4 — which field the sheet 'Total Hours' reads"); print("="*66)
p2=os.path.join(SRC,"wb_populate.py")
if os.path.exists(p2):
    L2=open(p2,encoding="utf-8",errors="replace").read().splitlines()
    for i,ln in enumerate(L2):
        if re.search(r"(unit_times_min|run_times_min|Total Hours|total_hours|hours)", ln):
            print(f"  wb_populate.py:{i+1}: {ln.strip()[:92]}")
