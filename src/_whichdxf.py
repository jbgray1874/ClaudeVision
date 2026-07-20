L = open(r"C:\ClaudeVision\src\drawing_job_merge.py", encoding="utf-8").read().splitlines()
import re
for i, ln in enumerate(L):
    if re.search(r"extract_flat_pattern|extract_dxf_geometry|analyse_dxf|merge_dxf_into_scan|_exact_perimeter|blank_area|from dxf_reader|import dxf_reader", ln):
        print(f"{i+1}: {ln.strip()}")
