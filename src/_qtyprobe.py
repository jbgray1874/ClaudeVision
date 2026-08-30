import json, glob, os
f = max(glob.glob(r"C:\ClaudeVision\output\json\*Milwaukee*.json"), key=os.path.getmtime)
d = json.load(open(f, encoding="utf-8"))
print("FILE:", os.path.basename(f))
parts = d.get("manufacturing_writeup", {}).get("parts") or []
keys = set()
for p in parts:
    keys |= set(p.keys())
qty_keys = sorted(k for k in keys if "qt" in k.lower() or "quant" in k.lower() or "count" in k.lower())
print("qty-ish keys present on parts:", qty_keys)
print("--- x2 parts ---")
for p in parts:
    pn = p.get("part_number")
    if pn in ("1448-01","1448-02","3886-01","3886-02","3886-03","1448-GA","3886-GA"):
        print(" ", pn, {k: p.get(k) for k in qty_keys})
