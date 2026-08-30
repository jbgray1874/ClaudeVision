r"""
READ-ONLY. shapely made blank_area_mm2 valid -> parts flipped stock_form "sheet"->"stated_weight"
-> dropped from the powder loop's sheet-only filter (wb_populate:506). Two things to confirm:
 1) WHERE stock_form is set to 'stated_weight' (the weight path enabled by valid area).
 2) The exact powder inclusion test at wb_populate:505-509, so the fix keys on
    'coated steel with a blank' not 'stock_form == sheet'.
Also flag the phantom FIXING125/VINYL76 in the powder sum (blank stock_form, non-steel).
"""
import os, re
root = r"C:\ClaudeVision\src"

print("="*70)
print("1) WHERE is stock_form set to 'stated_weight'?  (weight path)")
print("="*70)
for fn in sorted(os.listdir(root)):
    if not fn.endswith(".py") or fn.startswith("_"): continue
    if fn.endswith((".backup.py",".bak")) or fn in ("estimator1.py","estimator_old.py"): continue
    p=os.path.join(root,fn)
    try: L=open(p,encoding="utf-8",errors="replace").read().splitlines()
    except: continue
    for i,ln in enumerate(L):
        if re.search(r'stock_form.*=.*stated_weight|["\']stated_weight["\']|stock_form.*=.*["\']sheet["\']', ln):
            lo,hi=max(0,i-2),min(len(L),i+3)
            print(f"  --{fn}--")
            for j in range(lo,hi):
                print(f"    {j+1}: {L[j].rstrip()[:130]}")
            print()

print("="*70)
print("2) The powder inclusion test (wb_populate ~505-517) verbatim")
print("="*70)
p=os.path.join(root,"wb_populate.py")
L=open(p,encoding="utf-8",errors="replace").read().splitlines()
for j in range(500,520):
    if j<len(L): print(f"  {j+1}: {L[j].rstrip()[:130]}")

print("\n"+"="*70)
print("3) Does the powder loop guard on finish=powder or material=steel at all?")
print("="*70)
for j in range(494,548):
    if j<len(L) and re.search(r'finish|powder.*coat|MILD|STEEL|material|surface', L[j], re.I):
        print(f"  {j+1}: {L[j].rstrip()[:130]}")
