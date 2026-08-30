r"""READ-ONLY. Find where to slot the --deliverables orchestration in main.py. It must run AFTER
the wep-readback (JSON has real totals) and use the same failure-isolated pattern. Show:
  1) The argparse setup (where to add the --deliverables flag).
  2) The readback block we added (bak_wepreadback) — the orchestration goes right after it.
  3) The variables in scope there: xlsx_path, canonical json path, scan_label, summary — so the
     hook can call the quote + parity generators with the right paths.
  4) How the manual workbook is located (for the parity 'only if manual exists' branch) — is there
     an existing manual-lookup, or do we build the UNC path from job/customer?
No edits — locate the hook point + variables."""
import re
p=r"C:\ClaudeVision\src\main.py"
L=open(p,encoding="utf-8",errors="replace").read().splitlines()

print("="*66); print("1 — argparse (where to add --deliverables flag)"); print("="*66)
for i,ln in enumerate(L):
    if re.search(r"add_argument|ArgumentParser|parse_args", ln):
        print(f"  {i+1}: {ln.strip()[:96]}")

print("\n"+"="*66); print("2 — the wep-readback block (orchestration goes AFTER this)"); print("="*66)
for i,ln in enumerate(L):
    if "wep-readback" in ln or "stamp_real_totals" in ln or "_wep_exc" in ln:
        lo=max(0,i-3); hi=min(len(L),i+4)
        for j in range(lo,hi):
            print(f"  {j+1}: {L[j].rstrip()[:96]}")
        print("  ---")

print("\n"+"="*66); print("3 — variables in scope near the readback (paths for generators)"); print("="*66)
for i,ln in enumerate(L):
    if re.search(r"(xlsx_path\s*=|saved_output_paths|scan_label\s*=|_canon)", ln):
        print(f"  {i+1}: {ln.strip()[:90]}")

print("\n"+"="*66); print("4 — existing manual-workbook lookup? (for parity branch)"); print("="*66)
hits=0
for i,ln in enumerate(L):
    if re.search(r"(Manual Estimate|manual_workbook|\.xls|shareddata|find_manual|workbook_path|UNC)", ln, re.I):
        print(f"  {i+1}: {ln.strip()[:96]}"); hits+=1
if not hits:
    print("  (no manual-lookup in main.py — parity branch builds the UNC path from job/customer)")
# also check if parity_report_html / estimate_full_parity are imported anywhere
print("\n  existing imports of the generators?")
for i,ln in enumerate(L):
    if re.search(r"(parity_report_html|client_quote_html|estimate_full_parity|generate_report_files|generate_quote_files)", ln):
        print(f"    {i+1}: {ln.strip()[:90]}")
