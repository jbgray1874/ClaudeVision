import json, glob, os
# newest job JSON
d = r"C:\ClaudeVision\output\json"
f = max(glob.glob(os.path.join(d, "*.json")), key=os.path.getmtime)
print("reading:", os.path.basename(f), "\n")
J = json.load(open(f, encoding="utf-8"))

def walk(o):
    if isinstance(o, dict):
        yield o
        for v in o.values(): yield from walk(v)
    elif isinstance(o, list):
        for v in o: yield from walk(v)

seen = {}
for node in walk(J):
    am = node.get("area_method")
    if am:
        pn = node.get("part_number") or node.get("filename_stem") or "?"
        ba = node.get("blank_area_mm2") or node.get("area_mm2")
        bb = node.get("bbox_area_mm2")
        fill = node.get("bbox_fill_pct")
        seen[str(pn)] = (am, ba, bb, fill)

if not seen:
    print("NO area_method found in job JSON.")
    print("-> Either flat-pattern path didn't run on these parts, or the field isn't")
    print("   persisted into the saved JSON (it may live only in the transient dict).")
else:
    print(f"{'part':<16}{'area_method':<24}{'net area':<14}{'bbox area':<14}{'fill%'}")
    print("-"*74)
    for pn,(am,ba,bb,fill) in sorted(seen.items()):
        print(f"{pn[:15]:<16}{am:<24}{str(ba):<14}{str(bb):<14}{fill}")
    methods = [v[0] for v in seen.values()]
    n_shapely = sum(1 for m in methods if m=="shapely_polygonize")
    print(f"\nshapely_polygonize: {n_shapely}/{len(methods)}   bbox_fallback: {len(methods)-n_shapely}")
