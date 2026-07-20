import os, re
root = r"C:\ClaudeVision\src"
needles = ("textual_operations", "angles_deg", "DOWN", "fold", "bend_count", "folding", "operation_normaliser")
for fn in ("operation_normaliser.py","geometry_inference.py","estimator.py","file_scan.py","extractor_patterns.py","json_normaliser.py"):
    p = os.path.join(root, fn)
    if not os.path.exists(p): continue
    L = open(p, encoding="utf-8", errors="replace").read().splitlines()
    hits = [(i+1, ln.strip()) for i, ln in enumerate(L)
            if any(n.lower() in ln.lower() for n in ("textual_operation","angles_deg","fold","bend_count_dxf","bend_count","DOWN "))]
    if hits:
        print(f"\n==== {fn} ====")
        for ln_no, ln in hits[:20]:
            print(f"  {ln_no}: {ln[:120]}")
