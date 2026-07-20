r"""
READ-ONLY. Post-both-fixes (powder-include-stated_weight + shapely). Reconstruct the powder
sum and show EXACTLY which parts are in it now, to confirm:
  - powder is now 6.575 (stable, shapely can't move it)
  - the 5.361->6.575 increase is real coated steel (footbases etc.) previously dropped
  - FIXING125/VINYL76 phantom still present (the residual known bug)
"""
import json, glob, os
d = r"C:\ClaudeVision\output\json"
f = max(glob.glob(os.path.join(d, "*.json")), key=os.path.getmtime)
print("current JSON:", os.path.basename(f), "\n")
J = json.load(open(f, encoding="utf-8"))
pes = ((J.get("estimate_summary") or {}).get("part_estimates") or J.get("parts") or [])

def _s(v,dd=0.0):
    try: return float(v)
    except: return dd

ACR = {"ACRYLIC","HIGH IMPACT ACRYLIC","PERSPEX","PMMA","POLYCARBONATE"}
# NEW filter: sheet/plate/stated_weight/"" (the patched inclusion)
OK_FORMS = ("sheet","plate","stated_weight","")

print(f"{'part':<13}{'stock_form':<15}{'material':<13}{'finish?':<9}{'L×W':<13}{'in?':<5}{'m2'}")
print("-"*76)
total=0.0
for p in pes:
    me=p.get("material_estimate") or {}
    ng=p.get("normalized_geometry") or {}
    pn=str(p.get("part_number") or "")
    sf=str(me.get("stock_form") or "").lower()
    mat=str(p.get("normalized_material") or me.get("material") or "").upper()
    fin=str((p.get("manufacturing_features") or {}).get("finish_required") or p.get("surface_finishes") or "")[:8]
    L=_s(me.get("blank_length_mm") or ng.get("blank_length_mm"))
    W=_s(me.get("blank_width_mm") or ng.get("blank_width_mm"))
    q=_s(p.get("quantity"),1) or 1
    is_acr=any(a in mat.replace("_"," ") for a in ACR)
    ok=(sf in OK_FORMS) and not is_acr and L>0 and W>0
    contrib=(L/1000.0)*(W/1000.0)*2.0*q if ok else 0.0
    if ok: total+=contrib
    if L>0 or sf:
        flag=""
        if ok and ("VINYL" in pn or "FIXING" in pn): flag=" <-PHANTOM(non-steel)"
        print(f"{pn[:12]:<13}{sf[:14]:<15}{mat[:12]:<13}{fin:<9}{f'{L:.0f}×{W:.0f}':<13}{'YES' if ok else 'no':<5}{contrib:.4f}{flag}")
print("-"*76)
print(f"RECONSTRUCTED powder area = {total:.4f} m2  (run showed 6.5750)")
print(f"  baseline was 5.3610; delta +{total-5.361:.3f} m2")
print("  Parts NEWLY included (stated_weight steel) are real coated parts previously dropped.")
print("  Any <-PHANTOM lines are the residual non-steel bug (FIXING/VINYL mislabelled MILD_STEEL).")
