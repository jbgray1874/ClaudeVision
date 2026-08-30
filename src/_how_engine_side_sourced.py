r"""READ-ONLY. The parity engine-side numbers come from the JSON's stale WEP block, but should
come from OUR populated .xlsx's Excel-computed cells (£189.01). Find:
  1) How build_full_parity_report sources the ENGINE side — the _parity_money_specs, and whether
     json_numeric always reads from the JSON path (WEP) regardless of read_via_excel.
  2) What read_via_excel actually recalculates — is it Tim's workbook or ours? (it takes ONE
     workbook_path). Does the money comparison read engine from JSON and manual from workbook?
  3) The exact structure: does it compare JSON-engine vs workbook-manual, meaning to fix we must
     either (a) point the JSON engine fields at real values, or (b) add our populated .xlsx as a
     second workbook to read the engine side from.
Show the money-spec + comparison build. No edits — need the precise data flow to fix correctly."""
import re
p=r"C:\ClaudeVision\src\estimate_full_parity_report.py"
src=open(p,encoding="utf-8",errors="replace").read()
L=src.splitlines()

# the money specs: json_path (engine) + cell (manual workbook)
print("="*70); print("1 — _parity_money_specs (engine json_path vs manual cell)"); print("="*70)
m=re.search(r"_parity_money_specs\s*=.*?\]", src, re.S)
if m:
    for ln in m.group(0).splitlines()[:40]:
        print("  ", ln.rstrip()[:100])

# how money_cell_comparisons sets json_numeric vs workbook_cached_numeric
print("\n"+"="*70); print("2 — where json_numeric (engine) + workbook_cached_numeric (manual) are set"); print("="*70)
for i,ln in enumerate(L):
    if re.search(r"json_numeric|workbook_cached_numeric|_read_money_cells|_resolve_json_path|summary_path", ln):
        print(f"  {i+1}: {ln.strip()[:98]}")

# what read_via_excel changes — which workbook does it recalc
print("\n"+"="*70); print("3 — read_via_excel: which workbook is recalculated?"); print("="*70)
for i in range(1125, min(len(L),1180)):
    if L[i].strip():
        print(f"  {i+1}: {L[i].rstrip()[:98]}")
