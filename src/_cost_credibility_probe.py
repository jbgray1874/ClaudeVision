"""READ-ONLY. Confirms the REAL trigger of insufficient_data on 1282 and decomposes
the credible-vs-unreliable cost, so we know exactly what a bought-in exemption in
_part_cost_credibility would move — before writing the patch.

Answers:
  1. The live data_sufficiency block: which ratio is actually under threshold?
     (credible_cost_ratio < 0.50 is the suspected real trigger, NOT the 37% dxf ratio.)
  2. Decompose extended cost into: bought-in (structurally no DXF) vs fabricated-with-DXF
     vs fabricated-WITHOUT-DXF. The last bucket is the honest one — real parts we lack
     geometry for; exempting bought-ins does NOT (and should not) rescue those.
  3. Simulate: if bought-ins are exempted, what does credible_cost_ratio become? Does it
     cross 0.50, or do the 4 fabricated no-DXF parts hold it under?

Run from C:\ClaudeVision\src :
  C:\ClaudeVision\.venv\Scripts\python.exe _cost_credibility_probe.py
"""
import json, io

P = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
data = json.load(io.open(P, encoding="utf-8"))

# ---- 1. the actual data_sufficiency block, wherever it sits ----
def find_key(obj, key, depth=0):
    if depth > 6 or not isinstance(obj, (dict, list)):
        return None
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            r = find_key(v, key, depth+1)
            if r is not None:
                return r
    else:
        for v in obj:
            r = find_key(v, key, depth+1)
            if r is not None:
                return r
    return None

print("=" * 88)
print("1. LIVE data_sufficiency block (which ratio is actually under threshold?)")
print("=" * 88)
ds = find_key(data, "data_sufficiency") or find_key(data, "estimate_data_sufficiency")
if ds:
    for k, v in (ds.items() if isinstance(ds, dict) else []):
        if isinstance(v, (int, float, str, bool)):
            print(f"   {k:32} = {v}")
    # spotlight the two ratios vs their thresholds
    print("\n   --- the decisive comparison ---")
    for rk, thr in (("credible_cost_ratio", 0.50), ("dxf_part_ratio", 0.25),
                    ("credible_cost_ratio_pct", 50), ("dxf_coverage", 25)):
        if isinstance(ds, dict) and rk in ds:
            val = ds[rk]
            try:
                fv = float(val)
                norm = fv/100 if fv > 1.5 else fv
                thn = thr/100 if thr > 1.5 else thr
                flag = "<-- UNDER THRESHOLD (TRIGGERS)" if norm < thn else "ok"
                print(f"   {rk:28} = {val}   (threshold {thr})   {flag}")
            except Exception:
                print(f"   {rk:28} = {val}")
else:
    print("   data_sufficiency not found by name — dumping top-level keys to locate it:")
    print("   ", list(data.keys()))
    est = data.get("estimate_summary") or {}
    if isinstance(est, dict):
        print("   estimate_summary keys:", list(est.keys()))

# ---- 2 & 3. decompose extended cost by bucket ----
parts = (data.get("manufacturing_writeup") or {}).get("parts") or data.get("parts") or []
est = data.get("estimate_summary") or {}
est_parts = est.get("parts") or est.get("part_estimates") or []
# map est cost by part number
cost_by_pn = {}
for ep in est_parts:
    pn = str(ep.get("part_number") or "").upper()
    c = ep.get("extended_total_cost_gbp") or ep.get("extended_cost_gbp") or ep.get("extended_estimate") or 0
    try:
        cost_by_pn[pn] = float(c or 0)
    except Exception:
        cost_by_pn[pn] = 0.0

def is_boughtin(p):
    pn = str(p.get("part_number","")).upper()
    roles = [str(r).lower() for r in (p.get("page_roles") or [])]
    return (pn.startswith(("BI-","FIXING","VINYL","PACKAGING","DELIVERY"))
            or "bought_in" in roles)

def has_dxf(p):
    return bool(p.get("dxf_augmented")) or "dxf" in str(p.get("geometry_source","")).lower()

print("\n" + "=" * 88)
print("2. Cost decomposition (which bucket holds the credibility down?)")
print("=" * 88)
b_boughtin = b_fab_dxf = b_fab_nodxf = 0.0
nodxf_fab_parts = []
for p in parts:
    pn = str(p.get("part_number","")).upper()
    cost = cost_by_pn.get(pn, 0.0)
    if is_boughtin(p):
        b_boughtin += cost
    elif has_dxf(p):
        b_fab_dxf += cost
    else:
        b_fab_nodxf += cost
        nodxf_fab_parts.append((pn, cost))
total = b_boughtin + b_fab_dxf + b_fab_nodxf
print(f"   Bought-in (structurally no DXF):        £{b_boughtin:8.2f}")
print(f"   Fabricated WITH dxf (credible):         £{b_fab_dxf:8.2f}")
print(f"   Fabricated WITHOUT dxf (real gap):      £{b_fab_nodxf:8.2f}   <-- honest uncertainty")
print(f"     the no-DXF fabricated parts:          {nodxf_fab_parts}")
print(f"   TOTAL extended:                         £{total:8.2f}")

print("\n" + "=" * 88)
print("3. What would the bought-in exemption actually move?")
print("=" * 88)
if total > 0:
    # current credible = only fab_with_dxf ; unreliable = boughtin + fab_nodxf
    cur_credible = b_fab_dxf
    cur_ratio = cur_credible / total
    # after exempting bought-ins: their cost becomes credible too
    new_credible = b_fab_dxf + b_boughtin
    new_ratio = new_credible / total
    print(f"   CURRENT credible_cost_ratio  ~ {cur_ratio:.0%}   (only fab-with-dxf counts credible)")
    print(f"   AFTER bought-in exemption    ~ {new_ratio:.0%}   (bought-ins now credible)")
    print(f"   Threshold = 50%.")
    if new_ratio >= 0.50 and cur_ratio < 0.50:
        print(f"   -> exemption CROSSES 50%: fix would make 1282 quotable.")
    elif new_ratio < 0.50:
        held = b_fab_nodxf
        print(f"   -> exemption does NOT cross 50%: the £{held:.2f} of fabricated NO-DXF parts")
        print(f"      ({[pn for pn,_ in nodxf_fab_parts]}) hold it under. That's a REAL DXF gap,")
        print(f"      not a bug — the honest fix for those is getting their DXFs, or threshold policy.")
    else:
        print(f"   -> already >=50% before exemption; the trigger is elsewhere, re-examine.")
    print("\n   NOTE: this is an approximation of _part_cost_credibility's own bucketing;")
    print("   confirm against the real data_sufficiency numbers in section 1.")
