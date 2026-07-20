import json, glob, os
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
for n in walk(J):
    pn = n.get("part_number")
    if pn and ("blank_length_mm" in n or "blank_area_mm2" in n or "area_method" in n):
        key = str(pn)
        rec = seen.setdefault(key, {})
        for fld in ("blank_length_mm","blank_width_mm","blank_area_mm2","bbox_area_mm2","area_method","bbox_fill_pct"):
            if n.get(fld) is not None and fld not in rec:
                rec[fld] = n.get(fld)
print(f"{'part':<14}{'blank_L':<10}{'blank_W':<10}{'area_mm2':<12}{'bbox_mm2':<12}{'method':<22}{'fill'}")
print("-"*90)
for pn in sorted(seen):
    r = seen[pn]
    print(f"{pn[:13]:<14}{str(r.get('blank_length_mm','-')):<10}{str(r.get('blank_width_mm','-')):<10}"
          f"{str(r.get('blank_area_mm2','-')):<12}{str(r.get('bbox_area_mm2','-')):<12}"
          f"{str(r.get('area_method','-')):<22}{r.get('bbox_fill_pct','-')}")
