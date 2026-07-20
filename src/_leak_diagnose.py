r"""
_leak_diagnose.py — READ-ONLY. Find the path by which shapely's net blank_area_mm2 reached
the POWDER number when it went live (total dropped £8.62; powder area 5.361 -> 1.639 m2, a
value matching NEITHER gross bbox (5.45) NOR net (4.34) — so a DERIVED dimension was involved).

General field-flow trace, no part numbers. Three questions:
  A) Does anything DERIVE blank_length_mm / blank_width_mm FROM blank_area_mm2?
     (e.g. width = area / length, or sqrt(area) — that would change L/W when net area changed,
      and powder reads L x W.)
  B) Does merge_dxf_into_scan_json / geometry_inference OVERWRITE L/W using area?
  C) What exactly feeds the powder loop's _sl/_sw at runtime — material_estimate or
     normalized_geometry — and does that record get its L/W from the flat-pattern (area-bearing)
     path or the bbox path?
"""
import os, re
root = r"C:\ClaudeVision\src"

def scan(fn, pat, label, ctx=1):
    p = os.path.join(root, fn)
    if not os.path.exists(p): return
    L = open(p, encoding="utf-8", errors="replace").read().splitlines()
    hits=[]
    for i, ln in enumerate(L):
        if re.search(pat, ln):
            hits.append(i)
    if hits:
        print(f"\n  [{fn}] {label}")
        shown=set()
        for i in hits:
            for j in range(max(0,i-ctx), min(len(L),i+ctx+1)):
                if j not in shown:
                    mark=">>" if j==i else "  "
                    print(f"   {mark}{j+1}: {L[j].rstrip()[:140]}")
                    shown.add(j)
            print("     -")

print("="*72)
print("A) Any dimension DERIVED from area?  (width=area/length, sqrt(area), area/_l ...)")
print("="*72)
for fn in sorted(os.listdir(root)):
    if not fn.endswith(".py") or fn.startswith("_") or fn.endswith((".backup.py",".bak")): continue
    scan(fn, r"(blank_)?(length|width|_l|_w)\w*\s*=\s*[^=].*(area|sqrt)", "derives L/W from area?", ctx=1)

print("\n"+"="*72)
print("B) geometry_inference.py — full look at how it sets blank_length/width")
print("="*72)
p=os.path.join(root,"geometry_inference.py")
if os.path.exists(p):
    L=open(p,encoding="utf-8",errors="replace").read().splitlines()
    for i,ln in enumerate(L):
        if re.search(r"blank_(length|width|area)|=\s*.*area|sqrt|width|length|aspect|ratio",ln,re.I):
            print(f"   {i+1}: {ln.rstrip()[:140]}")

print("\n"+"="*72)
print("C) merge_dxf_into_scan_json — does it write L/W AND area into normalized_geometry?")
print("="*72)
scan("dxf_reader.py.py", r"blank_(length|width|area)_mm2?|normalized_geometry|geo\.update|geo\[", "flat-pattern -> part record writes", ctx=0)

print("\n"+"="*72)
print("D) Anything reading blank_area_mm2 to compute a LENGTH/WIDTH/coverage downstream?")
print("="*72)
for fn in sorted(os.listdir(root)):
    if not fn.endswith(".py") or fn.startswith("_") or fn.endswith((".backup.py",".bak")): continue
    scan(fn, r"blank_area_mm2", "reads blank_area_mm2", ctx=1)
