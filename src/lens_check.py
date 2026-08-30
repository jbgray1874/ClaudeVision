import json
from pathlib import Path
data = json.loads(Path(r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json").read_text(encoding="utf-8"))
def walk(o, p="root"):
    if isinstance(o, dict):
        yield p, o
        for k, v in o.items(): yield from walk(v, p + "." + str(k))
    elif isinstance(o, list):
        for i, v in enumerate(o): yield from walk(v, p + "[" + str(i) + "]")
c = [(sum(1 for x in d.values() if x not in (None, "", [], {})), p, d)
     for p, d in walk(data) if isinstance(d, dict) and str(d.get("part_number") or "") == "1455-C-005"]
c.sort(key=lambda t: t[0], reverse=True)
print(f"{len(c)} record(s) for 1455-C-005:\n")
for n, p, d in c[:3]:
    print(f"--- {n} fields @ {p} ---")
    for k in ("materials", "normalized_material", "normalized_thickness_mm",
              "thicknesses", "material_inherited_from", "dxf_augmented",
              "flat_pattern_detected", "textual_operations"):
        print(f"    {k:24}: {d.get(k)}")
    me = d.get("material_estimate") or {}
    print(f"    material_estimate.material : {me.get('material')}")
    print(f"    material_estimate.method   : {me.get('cost_method')}")
    print()
