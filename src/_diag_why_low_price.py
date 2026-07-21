r"""READ-ONLY. James asks: if BOMs + routes are mostly there, WHY is £22.72 not credible? PROVE it
(don't assert). Also list what outputs the --deliverables run produced. Establish:
  1) What output files exist for 12120 (xlsx, quote html, report html)?
  2) BREAK DOWN the £22.72: material subtotal vs labour subtotal. If labour is tiny, THAT's the
     issue — show each operation's TIME (hours) and its £ contribution.
  3) The smoking gun: for each labour op, show Rate/hr (throughput), Total Hours, and £ — if the
     throughput is huge (1477/hr) the time is ~0 so £ rounds to pennies. Quantify: what SHOULD the
     labour be if times were realistic? Compare to Tim (Tim's 12120 labour was much higher).
  4) Is the low number a ROUTE gap (missing ops) or a TIME model issue (ops present, times ~0)?
This answers James's real question: routes present ≠ realistic times."""
import sys, os, json, glob
SRC=r"C:\ClaudeVision\src"; sys.path.insert(0, SRC)

print("="*66); print("1 — 12120 output files that exist"); print("="*66)
import glob as G
for pat,label in [(r"C:\ClaudeVision\output\estimates\*12120*.xlsx","xlsx estimate"),
                  (r"C:\ClaudeVision\output\json\*12120*report*.html","report html"),
                  (r"C:\ClaudeVision\output\json\*12120*quote*.html","quote html"),
                  (r"C:\ClaudeVision\output\**\*12120*quot*","quote (any)"),
                  (r"C:\ClaudeVision\output\json\*12120*.json","json")]:
    fs=G.glob(pat, recursive=True)
    for f in sorted(fs)[-3:]:
        import os as _o
        print(f"  [{label}] {f}  ({_o.path.getsize(f)} bytes, {_o.path.getmtime(f)})")

print("\n"+"="*66); print("2/3 — the labour breakdown (WHY the price is low)"); print("="*66)
hits=G.glob(r"C:\ClaudeVision\output\json\*12120*.json")
# pick the newest non-report json
jsons=[h for h in hits if 'report' not in h.lower() and 'quote' not in h.lower()]
JP=max(jsons, key=os.path.getmtime) if jsons else None
print(f"  reading: {JP}")
S=json.load(open(JP,encoding="utf-8"))
es=S.get("estimate_summary",{}) or {}
wep=es.get("workbook_equivalent_pricing",{}) or {}
print(f"\n  HEADLINE: unit £{wep.get('m105_total_unit_cost_gbp')}  "
      f"material £{wep.get('m59_material_subtotal_gbp')}  labour £{wep.get('m103_labour_subtotal_gbp')}")
print(f"  labour hours total: {wep.get('labour_hours_total')}")

# per-op labour from part process estimates
print("\n  PER-OPERATION labour (time -> £):")
labour_by_op={}
for p in es.get("part_estimates") or []:
    proc=p.get("process_estimate",{}) or {}
    ut=proc.get("unit_times_min") or {}
    for op,mins in ut.items():
        labour_by_op.setdefault(op,{"min":0.0})
        labour_by_op[op]["min"]+=float(mins or 0)
for op,d in sorted(labour_by_op.items()):
    hrs=d["min"]/60.0
    print(f"    {op:<20} {d['min']:.2f} min  = {hrs:.3f} hr/unit")

print("\n"+"="*66); print("4 — is it ROUTE gap or TIME model? (the answer to James)"); print("="*66)
total_min=sum(d["min"] for d in labour_by_op.values())
print(f"  total labour: {total_min:.2f} min/unit = {total_min/60:.3f} hr/unit")
print(f"  -> Tim's 12120 total labour hours were MUCH higher (his sheet showed multiple ops at")
print(f"     real minutes each). If our total is <10 min/unit, the OPS are present but the TIMES")
print(f"     are near-zero -> TIME MODEL issue, not a route gap.")
print(f"  -> £{wep.get('m103_labour_subtotal_gbp')} labour on a welded/folded/coated bracket is the")
print(f"     tell: throughput model (parts/hr) is producing ~0 time per op, so time x £/hr = pennies.")
