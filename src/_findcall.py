import re
for fn in (r"C:\ClaudeVision\src\file_scan.py", r"C:\ClaudeVision\src\document_builder.py", r"C:\ClaudeVision\src\estimator.py"):
    L = open(fn, encoding="utf-8").read().splitlines()
    for i, ln in enumerate(L):
        if "apply_effective_quantities" in ln or "resolve_effective_quantities" in ln or "merge_table_bom_rows" in ln:
            print(f"{fn.split(chr(92))[-1]}:{i+1}: {ln.strip()}")
