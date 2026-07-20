r"""
READ-ONLY. Dump blank_length_mm / blank_width_mm for every steel part from the CURRENT
(shapely-reverted) job JSON. This is the BEFORE baseline. After re-applying shapely we dump
the same and diff — if L/W changes, that's how powder moved (both powder paths read L x W).
If L/W is identical, powder cannot move and the earlier drop came from elsewhere.

Reads the fields powder actually consumes: material_estimate.blank_length_mm / _width_mm,
falling back to normalized_geometry — exactly as wb_populate:511 and estimator:2215 do.
"""
import json, glob, os
d = r"C:\ClaudeVision\output\json"
f = max(glob.glob(os.path.join(d, "*.json")), key=os.path.getmtime)
print("BEFORE baseline from:", os.path.basename(f), "\n")
J = json.load(open(f, encoding="utf-8"))

def walk(o):
    if isinstance(o, dict):
        yield o
        for v in o.values(): yield from walk(v)
    elif isinstance(o, list):
        for v in o: yield from walk(v)

# collect the deepest record per part that actually has blank dims (skip thin dupes)
best = {}
for n in walk(J):
    if not isinstance(n, dict): continue
    pn = n.get("part_number")
    if not pn: continue
    me = n.get("material_estimate") or {}
    ng = n.get("normalized_geometry") or {}
    L = me.get("blank_length_mm") or ng.get("blank_length_mm")
    W = me.get("blank_width_mm") or ng.get("blank_width_mm")
    A = me.get("blank_area_mm2") or ng.get("blank_area_mm2")
    if L or W or A:
        # keep the record with the most complete dims
        prev = best.get(str(pn))
        score = (1 if L else 0)+(1 if W else 0)+(1 if A else 0)
        if not prev or score > prev[0]:
            best[str(pn)] = (score, L, W, A)

print(f"{'part':<14}{'blank_L':<12}{'blank_W':<12}{'blank_area_mm2':<16}{'L*W':<12}")
print("-"*66)
tot_lw = 0.0
for pn in sorted(best):
    _, L, W, A = best[pn]
    lw = ""
    try:
        if L and W:
            lwv = float(L)*float(W)
            lw = f"{lwv:,.0f}"
    except: pass
    print(f"{pn[:13]:<14}{str(L):<12}{str(W):<12}{str(A):<16}{lw:<12}")
print("\nSave these numbers. Re-run this AFTER re-applying shapely; any change in blank_L/blank_W")
print("is the powder-move mechanism. blank_area_mm2 SHOULD change (that's the fix); L/W must NOT.")
