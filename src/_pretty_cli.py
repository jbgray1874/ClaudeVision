r"""READ-ONLY. Show the exact CLI / argparse for estimate_parity_pretty_report.py so the
HTML parity report command is correct first time — arg names, defaults, output path, and
whether it needs a pre-built parity bundle JSON or reads summary+workbook directly."""
import os, re
p = r"C:\ClaudeVision\src\estimate_parity_pretty_report.py"
L = open(p, encoding="utf-8", errors="replace").read().splitlines()
print(f"{os.path.basename(p)}  ({len(L)} lines)\n")

# argparse block + main + any 'input bundle' expectation
print("=== argparse / main / inputs ===")
for i, ln in enumerate(L):
    if re.search(r"add_argument|def main|__main__|ArgumentParser|out.*html|\.html|bundle|summary.?json|workbook|required=True", ln, re.I):
        print(f"  {i+1}: {ln.strip()[:130]}")

# does it call estimate_full_parity_report to build the bundle, or read a pre-made one?
print("\n=== does it depend on a pre-built bundle vs build it itself? ===")
for i, ln in enumerate(L):
    if re.search(r"import estimate_full_parity|from estimate_full_parity|full_parity|reconcile|_manual_bom|load.*bundle|json\.load", ln):
        print(f"  {i+1}: {ln.strip()[:130]}")

# top docstring usage
print("\n=== top usage/docstring ===")
for ln in L[:30]:
    if re.search(r"usage|python |--|\.py", ln, re.I):
        print(f"  {ln.strip()[:130]}")
