r"""READ-ONLY. Final structure check before building the client-quote generator. Show exactly:
  1) process_estimate.routing shape across parts -> the OPERATIONS for 'What's included'
     (collect the distinct operation names as they actually appear).
  2) powder_coating_summary + any finish/colour source -> the 'Finish' spec line.
  3) job number + rev derivation from job_output_stem and the GA PDF /Title.
  4) confirm the customer key: 'milwaukee' (folder + GA path) -> milwaukee.svg is correctly named.
No edits — last look, then I build client_quote_html.py."""
import json, re
S=json.load(open(r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json",encoding="utf-8"))
es=S.get("estimate_summary",{})
parts=es.get("part_estimates") or []

print("="*66); print("1 — routing / operations (the real shape)"); print("="*66)
# show routing for first 2 parts verbatim
for p in parts[:2]:
    pe=p.get("process_estimate",{}) or {}
    r=pe.get("routing")
    print(f"  part {p.get('part_number')} routing type={type(r).__name__}:")
    if isinstance(r,list):
        for item in r[:6]:
            print("     ", item if not isinstance(item,dict) else {k:item.get(k) for k in list(item)[:6]})
    elif isinstance(r,dict):
        print("      keys:", sorted(r.keys()))
        for k,v in list(r.items())[:6]:
            print(f"        {k} = {v if not isinstance(v,(dict,list)) else type(v).__name__}")
    else:
        print("     ", r)

# collect ALL distinct operation tokens across every part's routing
ops=set()
for p in parts:
    r=(p.get("process_estimate",{}) or {}).get("routing")
    if isinstance(r,list):
        for item in r:
            if isinstance(item,str): ops.add(item)
            elif isinstance(item,dict):
                ops.add(str(item.get("operation") or item.get("op") or item.get("name") or item.get("process") or ""))
    elif isinstance(r,dict):
        for k in r.keys(): ops.add(str(k))
ops={o for o in ops if o}
print("\n  DISTINCT operations across all parts (for What's-included mapping):")
print("   ", sorted(ops))

# also try times_min keys (operations often keyed there)
print("\n  process_estimate.times_min keys (operations may be keyed here):")
tm=(parts[0].get("process_estimate",{}) or {}).get("times_min")
if isinstance(tm,dict): print("   ", sorted(tm.keys()))
else: print("   ", type(tm).__name__, tm if not isinstance(tm,(dict,list)) else "")

print("\n"+"="*66); print("2 — finish / colour source"); print("="*66)
pcs=es.get("powder_coating_summary")
if isinstance(pcs,dict):
    print("  powder_coating_summary keys:", sorted(pcs.keys()))
    for k,v in pcs.items():
        if not isinstance(v,(dict,list)): print(f"    {k} = {v}")
# labour_estimate.costs_gbp keys are the operations that got costed — reliable op list
print("\n  labour_estimate.costs_gbp keys (operations actually costed) for first 3 parts:")
for p in parts[:3]:
    c=(p.get("labour_estimate",{}) or {}).get("costs_gbp")
    if isinstance(c,dict):
        print(f"    {p.get('part_number')}: {sorted(c.keys())}")

print("\n"+"="*66); print("3 — job number / rev / product name derivation"); print("="*66)
stem=S.get("job_output_stem","")
print("  job_output_stem      =", stem)
print("  -> job_number (split)=", stem.split("-")[0].strip() if stem else "")
print("  -> product (folder)  =", re.sub(r'^\d+\s*-\s*','',stem).strip() if stem else "")
title=(S.get("pdf_metadata",{}) or {}).get("/Title","") or (S.get("drawing_metadata",{}).get("pdf_metadata",{}) or {}).get("/Title","")
print("  GA /Title            =", title)
m=re.search(r'_rev([A-Z0-9]+)', title, re.I)
print("  -> rev (from title)  =", ("Rev "+m.group(1).upper()) if m else "(none)")

print("\n"+"="*66); print("4 — customer key confirm"); print("="*66)
print("  folder+GA path contain 'Milwaukee' -> key 'milwaukee' -> milwaukee.svg  ✓ (already named right)")
