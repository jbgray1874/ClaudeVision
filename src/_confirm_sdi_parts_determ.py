r"""READ-ONLY. 11 parts tagged '[OTHER] SDI Displays Ltd' carry most of 1282's material cost. Are
they DETERMINISTIC (geometry x fixed steel rate) or do they secretly hit a TOP-1 DB query that
could tie? Confirm the fabricated-steel pricing path so we know the fix covers the real drift and
these aren't a hidden second source. Show each such part's cost_method + price basis + whether a
rate came from a DB lookup or config. No edits."""
import json
JP=r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
S=json.load(open(JP,encoding="utf-8"))
es=S.get("estimate_summary",{}); parts=es.get("part_estimates") or []

print("="*80)
print(f"{'part':<14}{'cost_method':<34}{'price_source':<22}{'rate_src'}")
print("="*80)
for p in parts:
    me=p.get("material_estimate",{}) or {}
    sup=me.get("supplier")
    if str(sup)!="SDI Displays Ltd": 
        continue
    pn=str(p.get("part_number"))
    cm=str(me.get("cost_method") or "")[:33]
    ps=me.get("price_source")
    ps_t = (ps.get("supplier_source") if isinstance(ps,dict) else ps) or ""
    # any DB-ish rate source?
    stock=me.get("stock_estimate",{}) or {}
    rate_src=str(stock.get("rate_source") or me.get("rate_source") or me.get("price_basis") or "")[:30]
    print(f"{pn:<14}{cm:<34}{str(ps_t)[:21]:<22}{rate_src}")

print("\n"+"="*66); print("VERDICT"); print("="*66)
print("  If cost_method is 'sheet_area x rate' / 'flat_blank' / 'system_cost' and the rate comes")
print("  from CONFIG (steel £/tonne), these are DETERMINISTIC — geometry is stable, rate is fixed.")
print("  If any shows a DB-derived per-tonne or per-part rate via a TOP-1 query, that's a 2nd source.")

# what's the steel rate source? config or DB?
print("\n"+"="*66); print("steel rate origin (config vs DB)"); print("="*66)
ewi=es.get("estimate_workbook_inputs",{})
print("  sheet_steel_cost_per_tonne_gbp (from inputs) =", ewi.get("sheet_steel_cost_per_tonne_gbp"))
print("  -> if this single config number drives all SDI-fab parts, they're deterministic.")
