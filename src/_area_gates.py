r"""
READ-ONLY. Find every GATE that keys on blank_area_mm2 (presence/>0) and show what branch
it controls. The leak is: blank_area_mm2 is normally None; shapely POPULATES it; any gate
using 'blank_area_mm2 > 0' as a has-geometry proxy then FLIPS, reclassifying parts and
moving powder. We need these gates to be robust to net area being populated.

General trace, no part numbers. Skips permission-denied files.
"""
import os, re
root = r"C:\ClaudeVision\src"
SKIP = {"load_drawings_rewrite.py"}

for fn in sorted(os.listdir(root)):
    if not fn.endswith(".py") or fn.startswith("_"): continue
    if fn in SKIP or fn.endswith((".backup.py",".bak")): continue
    # only LIVE files (skip the dead duplicates we identified)
    if fn in ("estimator1.py","estimator_old.py","pricing_service1.py","pricing_service3.py","pricing_service4.py"): continue
    p = os.path.join(root, fn)
    try:
        L = open(p, encoding="utf-8", errors="replace").read().splitlines()
    except PermissionError:
        print(f"  (skip, permission denied: {fn})"); continue
    except Exception:
        continue
    hits = [i for i,l in enumerate(L) if "blank_area_mm2" in l]
    if not hits: continue
    print(f"\n==== {fn} ====")
    shown=set()
    for i in hits:
        # show the line + 2 above/below for branch context
        for j in range(max(0,i-2), min(len(L),i+3)):
            if j not in shown:
                mark = ">>" if j==i else "  "
                print(f"  {mark}{j+1}: {L[j].rstrip()[:135]}")
                shown.add(j)
        print("     -")
