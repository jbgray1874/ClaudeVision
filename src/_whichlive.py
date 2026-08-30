import os, re
root = r"C:\ClaudeVision\src"
# which module does the pipeline actually import for the DXF reader + estimator?
for caller in ("main.py","file_scan.py","drawing_job_merge.py","load_drawings.py"):
    p = os.path.join(root, caller)
    if not os.path.exists(p):
        continue
    L = open(p, encoding="utf-8", errors="replace").read().splitlines()
    for i, ln in enumerate(L):
        if re.search(r"import\s+(dxf_reader|estimator|pricing_service|wb_populate|xlsx_output)\b|from\s+(dxf_reader|estimator|pricing_service|wb_populate|xlsx_output)\b", ln):
            print(f"{caller}:{i+1}: {ln.strip()}")
