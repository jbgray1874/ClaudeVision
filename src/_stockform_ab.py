r"""
READ-ONLY diagnostic. Dumps stock_form + powder-sum membership for every part from the
CURRENT json. Run it TWICE:
  (1) NOW (shapely applied)  -> save output as "AFTER"
  (2) after reverting shapely (.bak_shapely) and re-running 1282 -> "BEFORE"
Compare the stock_form column between the two. This DEFINITIVELY answers whether shapely
flipped stock_form (sheet->stated_weight), which is the powder-drop mechanism, or whether
stock_form was already stated_weight (meaning the drop came from elsewhere).

No theory — just the before/after fact.
"""
import json, glob, os
d = r"C:\ClaudeVision\output\json"
f = max(glob.glob(os.path.join(d, "*.json")), key=os.path.getmtime)
J = json.load(open(f, encoding="utf-8"))
pes = ((J.get("estimate_summary") or {}).get("part_estimates") or J.get("parts") or [])

def _s(v,d=0.0):
    try: return float(v)
    except: return d

print("STOCK_FORM SNAPSHOT — label this run BEFORE or AFTER shapely")
print(f"{'part':<14}{'stock_form':<16}{'material':<14}{'area_mm2':<12}{'L×W':<14}")
print("-"*70)
for p in pes:
    me=p.get("material_estimate") or {}
    ng=p.get("normalized_geometry") or {}
    pn=str(p.get("part_number") or "")
    sf=str(me.get("stock_form") or "")
    mat=str(p.get("normalized_material") or me.get("material") or "")[:13]
    A = me.get("blank_area_mm2") or ng.get("blank_area_mm2")
    L=_s(me.get("blank_length_mm") or ng.get("blank_length_mm"))
    W=_s(me.get("blank_width_mm") or ng.get("blank_width_mm"))
    if L>0 or sf:
        print(f"{pn[:13]:<14}{sf[:15]:<16}{mat:<14}{str(A):<12}{f'{L:.0f}×{W:.0f}':<14}")
print("\nKEY: compare the stock_form column BEFORE vs AFTER. If it changes sheet->stated_weight,")
print("shapely (via valid area) drove the reclassification. If identical, the powder drop is")
print("NOT stock_form and I must look elsewhere. blank_area_mm2 None(before)/number(after) is expected.")
