r"""
READ-ONLY. Powder loop (wb_populate:505-515) reads L x W (gross) and only sums parts with
stock_form in (sheet/plate/""). L/W is unchanged, yet powder fell 5.361->1.639. So parts
must have DROPPED from the sum via stock_form change. Dump every part's stock_form + L/W +
whether it qualifies for the powder sum, and RECONSTRUCT _sheet_powder_area_m2 to see which
parts contribute now vs what would give 5.361.
"""
import json, glob, os
d = r"C:\ClaudeVision\output\json"
f = max(glob.glob(os.path.join(d, "*.json")), key=os.path.getmtime)
print("post-shapely JSON:", os.path.basename(f), "\n")
J = json.load(open(f, encoding="utf-8"))

def _safe(v, dflt=0.0):
    try: return float(v)
    except: return dflt

pes = ((J.get("estimate_summary") or {}).get("part_estimates") or J.get("parts") or [])
print(f"part_estimates count: {len(pes)}\n")

print(f"{'part':<14}{'stock_form':<16}{'L':<10}{'W':<10}{'qty':<5}{'in_sum?':<8}{'m2_contrib'}")
print("-"*74)
total = 0.0
ACR = {"ACRYLIC","HIGH IMPACT ACRYLIC","PERSPEX","PMMA","POLYCARBONATE"}
for p in pes:
    me = p.get("material_estimate") or {}
    ng = p.get("normalized_geometry") or {}
    pn = str(p.get("part_number") or "")
    sf = str(me.get("stock_form") or "").lower()
    mat = str(p.get("normalized_material") or me.get("material") or "").upper()
    L = _safe(me.get("blank_length_mm") or ng.get("blank_length_mm"))
    W = _safe(me.get("blank_width_mm") or ng.get("blank_width_mm"))
    q = _safe(p.get("quantity"), 1) or 1
    is_acr = any(a in mat for a in ACR)
    qualifies = (sf in ("sheet","plate","")) and not is_acr and L>0 and W>0
    contrib = (L/1000.0)*(W/1000.0)*2.0*q if qualifies else 0.0
    if qualifies: total += contrib
    if L>0 or sf:
        print(f"{pn[:13]:<14}{sf[:15]:<16}{L:<10.1f}{W:<10.1f}{q:<5.0f}{'YES' if qualifies else 'no':<8}{contrib:.4f}")
print("-"*74)
print(f"RECONSTRUCTED _sheet_powder_area_m2 = {total:.4f} m2")
print(f"  (current run shows 1.6390; baseline was 5.3610)")
print(f"  If this ~1.639, the drop is parts leaving via stock_form/acrylic/L-W=0.")
print(f"  Look for parts with stock_form NOT sheet/plate/'' that have real L/W -> those dropped.")
