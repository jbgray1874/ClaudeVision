r"""READ-ONLY. Pinned: dual-path rows (FIXING qty 4, FIXINGTBC qty 2) live in
document_analysis.bom_rows, but the SHEET is populated from part_estimates which still carry
BI-SELFCLINCHNUT qty 1 placeholders. synthesize_folder_job_bom_rows (bay_rollup:569) rebuilds from
part_estimates AFTER the dual-path override, so placeholders win. To fix at the right point, show:
  1) synthesize_folder_job_bom_rows body — does it read document_analysis.bom_rows (dual-path) or
     only part_estimates?
  2) How the sheet's BOM section is actually populated (which structure feeds wb_populate's BOM) —
     part_estimates? bay_bom_rows? bom_rows?
  3) The _reconcile_bought_in (estimator:3637) — is THIS where dual-path should merge into
     part_estimates, and does it currently see the dual-path rows?
No edits — find the right intervention point so dual-path identities/qtys reach the sheet."""
import os, re
SRC=r"C:\ClaudeVision\src"

print("="*66); print("1 — synthesize_folder_job_bom_rows body (reads dual-path or only parts?)"); print("="*66)
p=os.path.join(SRC,"bay_rollup.py"); L=open(p,encoding="utf-8",errors="replace").read().splitlines()
for i in range(568, min(len(L),640)):
    print(f"  {i+1}: {L[i].rstrip()[:98]}")
    if i>568 and re.match(r"def ", L[i]): break

print("\n"+"="*66); print("2 — what feeds the sheet's BOM (wb_populate BOM source)"); print("="*66)
p=os.path.join(SRC,"wb_populate.py")
if os.path.exists(p):
    L=open(p,encoding="utf-8",errors="replace").read().splitlines()
    for i,ln in enumerate(L):
        if re.search(r"(bom_rows|bay_bom_rows|part_estimates|bought_in|BI-|bill_of_material|for .* in .*bom)", ln, re.I):
            print(f"  wb_populate.py:{i+1}: {ln.strip()[:92]}")
else:
    # maybe xlsx_output
    for fn in ("xlsx_output.py","document_builder.py"):
        p=os.path.join(SRC,fn)
        if not os.path.exists(p): continue
        L=open(p,encoding="utf-8",errors="replace").read().splitlines()
        for i,ln in enumerate(L):
            if re.search(r"(bom_rows|bay_bom_rows|bought_in.*row|for .* in .*bom)", ln, re.I):
                print(f"  {fn}:{i+1}: {ln.strip()[:92]}")

print("\n"+"="*66); print("3 — _reconcile_bought_in (does it see dual-path rows?)"); print("="*66)
p=os.path.join(SRC,"estimator.py"); L=open(p,encoding="utf-8",errors="replace").read().splitlines()
for i in range(3636, min(len(L),3700)):
    print(f"  {i+1}: {L[i].rstrip()[:98]}")
    if i>3637 and re.match(r"def ", L[i]): break
