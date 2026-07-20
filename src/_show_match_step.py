r"""READ-ONLY. Show the exact code to patch for the GENERAL token fix: _norm_line_code and the
reconciliation match step (where manual codes are set-compared to AI codes). Need exact current
strings for a clean exact-replace patch. The fix adds leading-token extraction so FIXING125-...
matches FIXING125 for ANY job. No edits here."""
import re
p=r"C:\ClaudeVision\src\estimate_full_parity_report.py"
src=open(p,encoding="utf-8",errors="replace").read()
L=src.splitlines()

def show(fn):
    m=re.search(rf"def {fn}\b.*?(?=\ndef )", src, re.S)
    if m:
        print(f"---- {fn} ----")
        for ln in m.group(0).splitlines()[:40]:
            print("  ", ln.rstrip()[:114])
        print()

show("_norm_line_code")
show("_ai_bom_lines")

# the reconciliation match step — where manual_by_code / ai_by_code sets intersect
print("---- reconciliation match step (set intersect) ----")
for i,ln in enumerate(L):
    if re.search(r"manual_by_code|ai_by_code|manual_codes|ai_codes|matched\.append|manual_only\.append|ai_only\.append|&\s*ai_codes|-\s*ai_codes|code in seen", ln):
        print(f"  {i+1}: {ln.rstrip()[:114]}")
