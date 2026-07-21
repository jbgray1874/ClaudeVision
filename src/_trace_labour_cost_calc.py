r"""READ-ONLY. CORRECTED diagnosis: times are REAL (64 min/unit, 1.07 hr) but labour is only £7.85
=> effective rate £7.34/hr vs Tim's £40-68/hr dept rates. The bug is in TIME x RATE, not the time
model. On the sheet: Fold 'Total Hours 5.10' but '£1.15' (5.10 x £40.47 should be £206). Trace:
  1) How is labour £ computed per op? Find estimate_labour_costs (estimator:2322) — the exact
     time x rate x qty math.
  2) In the JSON: for one op (fold), show the hours used, the rate applied, and the resulting £ —
     find where 5.10 hr collapses to £1.15.
  3) Is there a DIVISION by batch/qty (180) that shouldn't be there? Or is the rate wrong?
  4) The disconnect: 'Total Hours' displayed vs hours COSTED — are they the same field?
This finds the REAL bug (hours-to-cost link broken), not the time model I wrongly blamed."""
import sys, os, json, glob, re
SRC=r"C:\ClaudeVision\src"; sys.path.insert(0, SRC)

print("="*66); print("1 — estimate_labour_costs math (estimator 2322+)"); print("="*66)
p=os.path.join(SRC,"estimator.py"); L=open(p,encoding="utf-8",errors="replace").read().splitlines()
for i in range(2321, min(len(L),2420)):
    ln=L[i]
    if re.search(r"(rate|hour|qty|quantity|cost|/|\*|Total|labour|setup|time)", ln, re.I):
        print(f"  {i+1}: {ln.rstrip()[:100]}")

print("\n"+"="*66); print("2 — JSON: one op's hours -> rate -> £ (find the collapse)"); print("="*66)
hits=glob.glob(r"C:\ClaudeVision\output\json\*12120*.json")
jsons=[h for h in hits if 'report' not in h.lower() and 'quote' not in h.lower()]
JP=max(jsons, key=os.path.getmtime)
S=json.load(open(JP,encoding="utf-8"))
es=S.get("estimate_summary",{}) or {}
# find labour cost structure
lc=es.get("labour_costs") or es.get("labour") or {}
print(f"  labour_costs keys: {list(lc)[:12] if isinstance(lc,dict) else type(lc)}")
# dump the labour rows if present
lrows = lc.get("rows") if isinstance(lc,dict) else None
if not lrows if False else (lrows := (lc.get("operations") if isinstance(lc,dict) else None)) or lrows:
    pass
for key in ("rows","operations","lines","by_operation","operation_costs"):
    v=lc.get(key) if isinstance(lc,dict) else None
    if v:
        print(f"  labour_costs['{key}']: {len(v)} entries")
        for r in (v[:8] if isinstance(v,list) else list(v.items())[:8]):
            print(f"    {json.dumps(r)[:150]}")
        break

# also the wep labour + hours
wep=es.get("workbook_equivalent_pricing",{}) or {}
print(f"\n  WEP labour £{wep.get('m103_labour_subtotal_gbp')}  hours_total {wep.get('labour_hours_total')}")
print(f"  -> effective rate = {float(wep.get('m103_labour_subtotal_gbp',0))/max(float(wep.get('labour_hours_total',1)),0.001):.2f} £/hr (should be 40-68)")

print("\n"+"="*66); print("3 — search for a suspicious /qty or /180 in labour cost"); print("="*66)
for i in range(2321, min(len(L),2500)):
    ln=L[i]
    if re.search(r"(/\s*(job_quantity|quantity|qty|batch|order_qty|180)|per_unit|/ *_?qty)", ln):
        print(f"  estimator.py:{i+1}: {ln.strip()[:96]}")

print("\n"+"="*66); print("4 — how Total Hours vs Total Value are written to the sheet"); print("="*66)
p2=os.path.join(SRC,"wb_populate.py")
if os.path.exists(p2):
    L2=open(p2,encoding="utf-8",errors="replace").read().splitlines()
    for i,ln in enumerate(L2):
        if re.search(r"(total_hours|Total Hours|total_value|Total Value|labour_cost|rate_per_hour|hours\s*\*|\*\s*rate)", ln, re.I):
            print(f"  wb_populate.py:{i+1}: {ln.strip()[:96]}")
