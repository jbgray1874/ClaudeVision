r"""READ-ONLY. Material moved £133.45->£131.67 run-to-run; labour identical. So non-determinism is
in GEOMETRY/AREA, not operations. Find WHICH part's material/area is unstable and whether an LLM
feeds it. (Fixes the null-material crash from the last probe.)
Dumps per-part: material, blank_area_m2, cut_length, unit_material_cost, price_source, and the
geometry_source (DXF vs inferred vs vision) — the ones sourced by LLM/vision are the drift suspects.
No edits."""
import json, os, re

JP=r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
S=json.load(open(JP,encoding="utf-8"))
es=S.get("estimate_summary",{})
parts=es.get("part_estimates") or []

print("="*84)
print(f"{'part':<14}{'material':<11}{'area_m2':>9}{'cut_mm':>9}{'mat£':>8}  {'price_src':<14}{'geom_src'}")
print("="*84)
for p in parts:
    pn=str(p.get('part_number') or '?')
    mat=str(p.get('normalized_material') or '—')
    me=p.get('material_estimate',{}) or {}
    area=me.get('blank_area_m2')
    matcost=me.get('unit_material_cost_gbp')
    psrc=str(me.get('price_source') or '—')[:13]
    ng=p.get('normalized_geometry',{}) or {}
    cut=ng.get('cut_length_mm') or (p.get('process_estimate',{}) or {}).get('cut_length_mm')
    # geometry source: DXF-backed, inferred, or vision?
    gsrc=str(ng.get('stock_form') or '') 
    prov=p.get('part_provenance')
    geomrel=ng.get('geometry_confidence')
    def f(x,w,d=3):
        try: return f"{float(x):>{w}.{d}f}"
        except: return f"{'—':>{w}}"
    print(f"{pn:<14}{mat:<11}{f(area,9,4)}{f(cut,9,1)}{f(matcost,8,2)}  {psrc:<14}conf={geomrel}")

# Which geometry source policy is in play — DXF or inferred/vision?
print("\n"+"="*66); print("geometry_source_policy (DXF vs inferred vs vision)"); print("="*66)
gsp=S.get("geometry_source_policy")
if isinstance(gsp,dict):
    for k,v in gsp.items():
        if not isinstance(v,(dict,list)): print(f"  {k} = {v}")
gsum=S.get("geometry_summary",{}) or {}
for k in ("source","primary_source","dxf_parts","inferred_parts","vision_parts","method"):
    if k in gsum: print(f"  geometry_summary.{k} = {gsum[k]}")

# Does an LLM feed geometry/area? check the modules that produce blank_area/cut_length
print("\n"+"="*66); print("does an LLM feed area/geometry? (the drift source)"); print("="*66)
SRC=r"C:\ClaudeVision\src"
pat=re.compile(r"(temperature|seed|messages\.create|chat\.completions|grok|xai|\.invoke\()", re.I)
for fn in ("geometry_inference.py","vision_extractor.py","dxf_reader.py","json_normaliser.py","file_scan.py"):
    p=os.path.join(SRC,fn)
    if not os.path.exists(p): 
        print(f"  {fn:<24} (not found)"); continue
    txt=open(p,encoding="utf-8",errors="replace").read()
    has_llm=bool(re.search(r"(messages\.create|chat\.completions|grok|xai|\.invoke\()",txt,re.I))
    temp0=bool(re.search(r"temperature\s*=\s*0",txt))
    seed=bool(re.search(r"seed\s*=",txt))
    produces_area=("blank_area" in txt or "cut_length" in txt)
    print(f"  {fn:<24} llm={has_llm}  temp0={temp0}  seed={seed}  produces_area={produces_area}")

# dxf_augmentation — are parts getting DXF geometry or falling back?
print("\n"+"="*66); print("dxf_augmentation (are parts DXF-backed or inferred?)"); print("="*66)
dxa=S.get("dxf_augmentation")
if isinstance(dxa,dict):
    for k,v in dxa.items():
        if not isinstance(v,(dict,list)): print(f"  {k} = {v}")
    if isinstance(dxa.get("summary"),dict):
        for k,v in dxa["summary"].items():
            if not isinstance(v,(dict,list)): print(f"  summary.{k} = {v}")
