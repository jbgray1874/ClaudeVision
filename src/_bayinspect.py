import json
d = json.load(open(r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.PRECACHE.json", encoding="utf-8"))
be = d.get("bay_estimate", {})
print("bay lines:")
for ln in be.get("lines", []):
    if ln.get("kind") == "catalogue" or ln.get("costed"):
        print(f"  code={ln.get('code')!r:18} kind={ln.get('kind'):12} costed={ln.get('costed')} "
              f"uc={ln.get('unit_cost_gbp')} src={ln.get('cost_source')!r}")
