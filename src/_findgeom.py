import os, re
root = r"C:\ClaudeVision\src"
needles = ("cut_len", "cutting_distance", "Intenal", "internal_cut", "bounding perim",
           "blank_length_mm", "dxf_raw_geometry", "polygonize", "unary_union",
           "modelspace", "ezdxf", "LWPOLYLINE")
for fn in os.listdir(root):
    if not fn.endswith(".py"):
        continue
    p = os.path.join(root, fn)
    try:
        L = open(p, encoding="utf-8", errors="replace").read().splitlines()
    except Exception:
        continue
    hits = [(i+1, ln.strip()) for i, ln in enumerate(L)
            if any(n in ln for n in needles)]
    if hits:
        print(f"\n==== {fn}  ({len(hits)} hits) ====")
        for ln_no, ln in hits[:25]:
            print(f"  {ln_no}: {ln[:130]}")
