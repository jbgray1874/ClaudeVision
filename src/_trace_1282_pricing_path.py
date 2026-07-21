r"""READ-ONLY. JG asks the RIGHT question: which of the 4 TOP-1 queries actually priced 1282's
parts, and did the fix change the spreadsheet? Don't assume bought-in — TRACE it.
  1) For each 1282 part, what pricing SOURCE/PATH did it use (UDEF / bought_in_parts / catalog_url /
     config_default / geometry-based)? Read the price_source + provenance on each part.
  2) Which parts have a source that goes through a TOP-1 DB query (could tie) vs which are computed
     locally (geometry x rate — deterministic, unaffected)?
  3) The honest answer: could the fix have moved 1282's number at all, and via which table?
No edits — trace the actual price provenance."""
import json
JP=r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
S=json.load(open(JP,encoding="utf-8"))
es=S.get("estimate_summary",{}); parts=es.get("part_estimates") or []

print("="*78)
print(f"{'part':<18}{'material':<11}{'ext£':>8}  price_source / provenance")
print("="*78)
udef=bi_db=cat=cfg=geom=other=0
for p in parts:
    pn=str(p.get("part_number") or "")
    me=p.get("material_estimate",{}) or {}
    mat=str(p.get("normalized_material") or "")
    ext=me.get("extended_material_cost_gbp")
    ps=me.get("price_source")
    method=me.get("cost_method")
    supplier=me.get("supplier")
    # normalise the source description
    src_txt=""
    if isinstance(ps,dict):
        src_txt=str(ps.get("supplier_source") or ps.get("source") or ps)[:44]
    elif ps:
        src_txt=str(ps)[:44]
    else:
        src_txt=f"method={method} supplier={supplier}"
    # classify
    low=(src_txt+" "+str(method)+" "+str(supplier)).lower()
    if "udef" in low: udef+=1; tag="UDEF"
    elif "bought_in" in low or "bought-in" in low or (mat=="BOUGHT_IN" and ("catalog" in low or "db" in low)): bi_db+=1; tag="BOUGHT_IN_DB"
    elif "catalog" in low or "web_indicative" in low or "supplier_catalog" in low: cat+=1; tag="CATALOG_URL"
    elif "config" in low or "default" in low: cfg+=1; tag="CONFIG_DEFAULT"
    elif "geometry" in low or "flat" in low or "area" in low or "sheet" in low or "system" in low: geom+=1; tag="GEOMETRY"
    else: other+=1; tag="OTHER"
    print(f"{pn:<18}{mat:<11}{('£'+str(ext)) if ext is not None else '—':>8}  [{tag}] {src_txt}")

print("\n"+"="*66); print("SOURCE TALLY — which path priced 1282's parts"); print("="*66)
print(f"  UDEF (TOP-1, table 171)          : {udef}")
print(f"  bought_in_parts (TOP-1, 561)     : {bi_db}")
print(f"  supplier_catalog_url (TOP-1, 598): {cat}")
print(f"  config_default (no DB query)     : {cfg}")
print(f"  geometry x rate (local, determ.) : {geom}")
print(f"  other/unclassified               : {other}")
print("\n  -> Only parts on a TOP-1 DB path (UDEF / bought_in / catalog) could have been")
print("     affected by the tiebreaker fix. Config-default + geometry parts are unchanged.")

# 4) Are the bought-in prices actually coming from the DB, or from job_bought_in_materials.json?
print("\n"+"="*66); print("bought-in price origin: DB query vs job_bought_in_materials.json?"); print("="*66)
import os
bij=r"C:\ClaudeVision\src\job_bought_in_materials.json"
if os.path.exists(bij):
    try:
        d=json.load(open(bij,encoding="utf-8"))
        n = len(d) if isinstance(d,(list,dict)) else 0
        print(f"  job_bought_in_materials.json EXISTS ({n} entries).")
        print("  If 1282's BI prices come from THIS file (fixed), the DB tiebreaker fix does NOT")
        print("  affect them — they'd be deterministic already, and the drift is elsewhere.")
        # show a couple keys if dict
        if isinstance(d,dict):
            for k in list(d)[:5]: print(f"    key: {k}")
        elif isinstance(d,list):
            for it in d[:3]: print(f"    item: {str(it)[:70]}")
    except Exception as e:
        print("  (couldn't read:", e, ")")
else:
    print("  job_bought_in_materials.json NOT present -> BI prices come from DB (fix applies).")
