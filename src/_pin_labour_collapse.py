r"""READ-ONLY. estimate_labour_costs math is CORRECT (rate x run_hours, no bad /qty). So the bug is
the INPUTS: either rate is tiny, or run_times_min_per_unit is tiny (and differs from the
unit_times_min I read before). PIN IT with real JSON numbers for laser on 12120:
  - What rate was APPLIED to laser_cutting? (rate_sources / hourly_rate_gbp)
  - What run_min was COSTED (run_times_min_per_unit) vs what I displayed (unit_times_min)?
  - The resulting costs_gbp[op] — show rate x (run_min/60) and confirm it equals the £ on sheet.
  - Do this for EACH op so we see whether it's rate-too-small or time-too-small.
Read the numbers; stop guessing."""
import sys, os, json, glob
SRC=r"C:\ClaudeVision\src"; sys.path.insert(0, SRC)
hits=glob.glob(r"C:\ClaudeVision\output\json\*12120*.json")
jsons=[h for h in hits if 'report' not in h.lower() and 'quote' not in h.lower()]
JP=max(jsons, key=os.path.getmtime)
S=json.load(open(JP,encoding="utf-8"))
es=S.get("estimate_summary",{}) or {}

# The labour cost lives per-part in process_estimate/labour, OR aggregated. Find it.
print("="*70); print("per-part: rate applied, run_min costed, unit_min displayed, £"); print("="*70)
tot_cost=0.0; tot_runmin=0.0; tot_unitmin=0.0
for p in es.get("part_estimates") or []:
    pn=p.get("part_number")
    proc=p.get("process_estimate",{}) or {}
    lab=proc.get("labour") or proc.get("labour_costs") or {}
    costs=lab.get("costs_gbp") or {}
    rate_src=lab.get("rate_sources") or {}
    run_times=proc.get("run_times_min_per_unit") or {}
    unit_times=proc.get("unit_times_min") or {}
    if not costs: continue
    for op in costs:
        rate=(rate_src.get(op) or {}).get("hourly_rate_gbp")
        rmin=run_times.get(op)
        umin=unit_times.get(op)
        c=costs.get(op)
        tot_cost+=float(c or 0); tot_runmin+=float(rmin or 0); tot_unitmin+=float(umin or 0)
        # recompute rate*run/60
        recomputed = (float(rate)* (float(rmin or 0)/60.0)) if rate else None
        print(f"  {pn:<16}{op:<16} rate={rate} run_min={rmin} unit_min={umin} £={c} "
              f"[rate*run/60={recomputed:.3f}]" if recomputed is not None else
              f"  {pn:<16}{op:<16} rate={rate} run_min={rmin} unit_min={umin} £={c}")

print("\n"+"="*70); print("TOTALS"); print("="*70)
print(f"  total £ = {tot_cost:.2f}   total run_min = {tot_runmin:.1f}   total unit_min = {tot_unitmin:.1f}")
print(f"  -> if run_min << unit_min, the COSTED time is smaller than the DISPLAYED time (bug is time)")
print(f"  -> if rate is ~7-15 not 40-68, the RATE lookup is wrong (bug is rate)")

# also check: is there a separate aggregated labour block that the SHEET actually reads?
print("\n"+"="*70); print("aggregate labour block (what wep/sheet reads)"); print("="*70)
for k in ("labour_costs","labour","aggregated_labour","document_labour"):
    v=es.get(k)
    if v: print(f"  estimate_summary['{k}']: {json.dumps(v)[:300]}")
wep=es.get("workbook_equivalent_pricing",{}) or {}
print(f"  WEP: labour £{wep.get('m103_labour_subtotal_gbp')} hours {wep.get('labour_hours_total')}")

# CRITICAL: what are the run_times vs unit_times at document level?
print("\n"+"="*70); print("run_times_min_per_unit vs unit_times_min (are they different?)"); print("="*70)
for p in (es.get("part_estimates") or [])[:1]:
    proc=p.get("process_estimate",{}) or {}
    print(f"  sample part {p.get('part_number')}:")
    print(f"    run_times_min_per_unit: {proc.get('run_times_min_per_unit')}")
    print(f"    unit_times_min:         {proc.get('unit_times_min')}")
    print(f"    setup_times_min:        {proc.get('setup_times_min')}")
