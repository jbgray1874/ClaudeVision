# Read the EXACT fields the powder loop reads: material_estimate.blank_length_mm/_width_mm
# and normalized_geometry.blank_length_mm/_width_mm, per part-estimate. Compare to the
# workbook Sheet Steel L/W. This shows whether the shapely patch shrank these dims.
import json, glob, os
d = r"C:\ClaudeVision\output\json"
f = max(glob.glob(os.path.join(d, "*.json")), key=os.path.getmtime)
print("reading:", os.path.basename(f), "\n")
J = json.load(open(f, encoding="utf-8"))

# find the part_estimates list the powder loop iterates (_all_pes_pw)
def walk(o, path=""):
    if isinstance(o, dict):
        yield path, o
        for k,v in o.items(): yield from walk(v, f"{path}.{k}")
    elif isinstance(o, list):
        for i,v in enumerate(o): yield from walk(v, f"{path}[{i}]")

# collect part-estimate-like records: have material_estimate or normalized_geometry + part_number
recs = {}
for path, node in walk(J):
    if isinstance(node, dict) and node.get("part_number") and \
       ("material_estimate" in node or "normalized_geometry" in node):
        pn = str(node["part_number"])
        me = node.get("material_estimate") or {}
        ng = node.get("normalized_geometry") or {}
        rec = recs.setdefault(pn, {})
        # the loop's exact read: me first, then ng
        if "me_L" not in rec:
            rec["me_L"] = me.get("blank_length_mm"); rec["me_W"] = me.get("blank_width_mm")
            rec["ng_L"] = ng.get("blank_length_mm"); rec["ng_W"] = ng.get("blank_width_mm")
            rec["me_area"] = me.get("blank_area_mm2"); rec["ng_area"] = ng.get("blank_area_mm2")
            rec["stock"] = me.get("stock_form"); rec["qty"] = node.get("quantity")

print(f"{'part':<13}{'me_L':<9}{'me_W':<9}{'ng_L':<9}{'ng_W':<9}{'eff_L':<9}{'eff_W':<9}{'stock':<7}{'qty'}")
print("-"*90)
tot=0.0
for pn in sorted(recs):
    r = recs[pn]
    eff_L = r["me_L"] or r["ng_L"]      # exactly what line 511 computes
    eff_W = r["me_W"] or r["ng_W"]
    print(f"{pn[:12]:<13}{str(r['me_L']):<9}{str(r['me_W']):<9}{str(r['ng_L']):<9}{str(r['ng_W']):<9}"
          f"{str(eff_L):<9}{str(eff_W):<9}{str(r['stock'])[:6]:<7}{r['qty']}")
    try:
        if eff_L and eff_W and str(r['stock']).lower() in ("sheet","plate",""," ","none",""):
            tot += (float(eff_L)/1000)*(float(eff_W)/1000)*2.0*float(r['qty'] or 1)
    except: pass
print(f"\nReconstructed powder area from eff L/W (sheet only): ~{tot:.4f} m2  (run reported 1.639)")
