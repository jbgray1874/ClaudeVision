r"""READ-ONLY. Wire the wep-readback into main.py right AFTER wb_populate saves the .xlsx, so
the JSON is stamped with real Excel-computed totals every run (failure-isolated). Show:
  1) main.py 700-712: the exact save block + xlsx_path variable + the canonical json path var,
     so I insert the readback call with the right variables.
  2) confirm the canonical JSON path the run writes (saved_output_paths.json) so readback targets it.
  3) the pct_variance sign bug in the report bundle: find where pct_variance is computed for
     money cells (labour showing +32.1% when it should be -24%) — quick note for a follow-up fix.
No edits."""
import re
p=r"C:\ClaudeVision\src\main.py"
L=open(p,encoding="utf-8",errors="replace").read().splitlines()

print("="*66); print("1 — save block + variables (695-715)"); print("="*66)
for i in range(694, min(len(L),716)):
    print(f"  {i+1}: {L[i].rstrip()[:100]}")

print("\n"+"="*66); print("2 — canonical json path the run uses (_canon / saved_output_paths)"); print("="*66)
for i,ln in enumerate(L):
    if re.search(r"_canon|saved_output_paths|scan_label|xlsx_path\s*=", ln):
        print(f"  {i+1}: {ln.strip()[:96]}")

# 3) pct_variance computation in the parity report (sign bug)
print("\n"+"="*66); print("3 — pct_variance computation (labour sign bug)"); print("="*66)
pp=r"C:\ClaudeVision\src\estimate_full_parity_report.py"
ps=open(pp,encoding="utf-8",errors="replace").read()
for i,ln in enumerate(ps.splitlines()):
    if re.search(r"pct_variance|_pct_diff|def _pct", ln):
        print(f"  efpr:{i+1}: {ln.strip()[:96]}")
