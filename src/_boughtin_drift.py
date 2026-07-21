r"""READ-ONLY. BIG finding: Python per-part material £108.15 vs Excel m59 £131.67 = £23 gap. The
Excel total rolls in BOUGHT-IN materials (BI-LED* £10-26 each) that the per-part material_estimate
sum excludes. So the drift is likely in the BOUGHT-IN total, not fabricated material — which fits
'material moves, labour stable' AND the known dup-SKU-two-prices catalogue issue.

Check:
  1) Sum the bought-in line costs from the JSON (the BI-* parts) — is £108.15 + bought-in ≈ £131.67?
  2) How is each bought-in part PRICED — from job_bought_in_materials.json (fixed) or the catalogue
     (which has the dup-price non-determinism)? Show the source per BI part.
  3) The BoughtInCatalogue dup-price path: does it pick from an unordered source (SQL without full
     ORDER BY, or a dict) so the winning price varies run-to-run?
No edits — is the bought-in total the drifting piece?"""
import json, os, re

JP=r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
S=json.load(open(JP,encoding="utf-8"))
es=S.get("estimate_summary",{}); parts=es.get("part_estimates") or []

print("="*66); print("1 — fabricated vs bought-in material split"); print("="*66)
fab=0.0; bi=0.0; bi_rows=[]
for p in parts:
    pn=str(p.get("part_number") or "")
    me=p.get("material_estimate",{}) or {}
    ext=me.get("extended_material_cost_gbp")
    v=ext if isinstance(ext,(int,float)) else 0
    mat=str(p.get("normalized_material") or "")
    is_bi = pn.upper().startswith("BI-") or mat=="BOUGHT_IN" or (me.get("stock_form")=="bought_in")
    # bought-in cost may be in a different field
    bi_cost = (me.get("unit_material_cost_gbp") or 0)*(p.get("quantity") or 0) if is_bi else 0
    if is_bi:
        bi += (v if v else bi_cost)
        bi_rows.append((pn, mat, me.get("unit_material_cost_gbp"), ext, str(me.get("price_source"))[:40]))
    else:
        fab += v
print(f"  fabricated material sum  = £{round(fab,2)}")
print(f"  bought-in material sum   = £{round(bi,2)}")
print(f"  fab + bought-in          = £{round(fab+bi,2)}")
print(f"  (Excel m59 target        = £131.67)")

print("\n"+"="*66); print("2 — how each BOUGHT-IN part is priced (source)"); print("="*66)
for pn,mat,unit,ext,src in bi_rows:
    print(f"    {pn:<20} unit=£{unit} ext=£{ext}  src={src}")
# also dump any bought-in materials json the run uses
bij=r"C:\ClaudeVision\src\job_bought_in_materials.json"
if os.path.exists(bij):
    try:
        d=json.load(open(bij,encoding="utf-8"))
        print(f"\n  job_bought_in_materials.json present: {len(d) if isinstance(d,(list,dict)) else '?'} entries")
    except: pass

print("\n"+"="*66); print("3 — catalogue price selection: unordered winner?"); print("="*66)
# the SQL/lookup that picks bought-in price — is there a full deterministic ORDER BY?
for fn in ("pricing_service.py","bought_in_pricing.py"):
    p=os.path.join(r"C:\ClaudeVision\src",fn); L=open(p,encoding="utf-8",errors="replace").read().splitlines()
    for i,ln in enumerate(L):
        if re.search(r"(ORDER BY|SELECT .* price|WHERE .*sku|GROUP BY|DISTINCT|LIMIT 1|TOP 1|fetchone|fetchall)", ln, re.I):
            print(f"  {fn}:{i+1}: {ln.strip()[:96]}")
        # dict-based price pick where two prices for same key -> last wins non-deterministically
        if re.search(r"(prices?\[|by_sku|by_code|catalog\[|book\[).*=", ln) and "price" in ln.lower():
            print(f"  {fn}:{i+1}: {ln.strip()[:96]}")

# 4) the known 84-row dup-price view issue: which view/source, does it dedupe deterministically?
print("\n"+"="*66); print("4 — BoughtInCatalogue dup-price handling (rag_fallback vs web_indicative)"); print("="*66)
for fn in ("pricing_service.py","bought_in_pricing.py"):
    p=os.path.join(r"C:\ClaudeVision\src",fn); txt=open(p,encoding="utf-8",errors="replace").read()
    for i,ln in enumerate(txt.splitlines()):
        if re.search(r"(rag_fallback|web_indicative|dedup|duplicate|BoughtInCatalogue|confidence.*0\.6|GROUP BY.*sku)", ln, re.I):
            print(f"  {fn}:{i+1}: {ln.strip()[:96]}")
