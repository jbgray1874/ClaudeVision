r"""READ-ONLY. Get the EXACT main()/argparse arg names for estimate_parity_pretty_report.py
so we can render the HTML from the bundle produced by estimate_full_parity_report.py.
Also confirm estimate_full_parity_report's default out paths (where the bundle lands)."""
import os, re
root = r"C:\ClaudeVision\src"

print("=== estimate_parity_pretty_report.py :: main() + argparse ===")
p = os.path.join(root, "estimate_parity_pretty_report.py")
L = open(p, encoding="utf-8", errors="replace").read().splitlines()
# find the __main__ / argparse near bottom
start = None
for i, ln in enumerate(L):
    if "__main__" in ln or (re.search(r"def main", ln)):
        start = i
        break
if start is not None:
    for j in range(max(0,start-2), min(len(L), start+40)):
        print(f"  {j+1}: {L[j].rstrip()[:130]}")

print("\n=== estimate_full_parity_report.py :: default out paths (bundle/csv) ===")
p2 = os.path.join(root, "estimate_full_parity_report.py")
L2 = open(p2, encoding="utf-8", errors="replace").read().splitlines()
for i, ln in enumerate(L2):
    if re.search(r"out-json|out-csv|out_json|out_csv|default=str\(config|ESTIMATE_FULL_PARITY|CSV_DIR", ln):
        print(f"  {i+1}: {ln.strip()[:130]}")

print("\n=== config CSV_DIR value ===")
pc = os.path.join(root, "config.py")
if os.path.exists(pc):
    for i, ln in enumerate(open(pc, encoding="utf-8", errors="replace").read().splitlines()):
        if re.search(r"CSV_DIR\s*=|OUTPUT_DIR\s*=|CSV_DIR", ln):
            print(f"  {i+1}: {ln.strip()[:130]}")
