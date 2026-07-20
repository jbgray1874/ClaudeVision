r"""
READ-ONLY. Powder moved 5.361->1.639 while L/W stayed identical. So powder is fed by
blank_area_mm2 (which shapely corrected), NOT by L x W. Find where wb_populate writes the
template's "Powder Qty Calculator" columns (m2 Per Part / Powder Qty Per Part) and confirm
it reads blank_area_mm2 / net area. That is the real leak point — and the fix (make powder
read gross L x W) goes exactly there.
"""
import os, re
p = r"C:\ClaudeVision\src\wb_populate.py"
if not os.path.exists(p):
    # maybe it's wb_populate.py.py or similar
    import glob
    cands = glob.glob(r"C:\ClaudeVision\src\wb_populate*.py")
    print("wb_populate candidates:", cands)
    p = cands[0] if cands else None
if p and os.path.exists(p):
    L = open(p, encoding="utf-8", errors="replace").read().splitlines()
    print(f"reading {os.path.basename(p)} ({len(L)} lines)\n")
    # find powder-area / m2-per-part / coated writes and what they read
    print("=== lines touching powder area / m2-per-part / blank_area_mm2 / coated ===")
    for i, ln in enumerate(L):
        if re.search(r"m2[_ ]?per[_ ]?part|powder.*area|area.*powder|blank_area_mm2|coated.*m2|m2.*coated|_powder_coated_area|Powder Qty|sheet_powder_area|_sme|_sng|blank_length_mm", ln, re.I):
            print(f"  {i+1}: {ln.rstrip()[:145]}")
    print("\n=== the powder-area accumulation loop (context around 'powder' writes) ===")
    # dump a window around the first strong powder-area hit
    idx = next((i for i,l in enumerate(L) if re.search(r"sheet_powder_area|_powder_coated_area_m2|m2 Per Part|powder_area_m2", l, re.I)), None)
    if idx is not None:
        for j in range(max(0,idx-4), min(len(L), idx+30)):
            print(f"  {j+1}: {L[j].rstrip()[:145]}")
