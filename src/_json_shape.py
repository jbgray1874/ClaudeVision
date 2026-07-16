# -*- coding: utf-8 -*-
r"""Show the JSON output structure so we can find where bought-in parts/prices live.
Read-only.
  cd C:\ClaudeVision\src
  C:\ClaudeVision\.venv\Scripts\python.exe _json_shape.py
"""
import json, os, glob

candidates = glob.glob(r"C:\ClaudeVision\output\json\*1282*.json")
path = max(candidates, key=os.path.getmtime)
print(f"Reading: {path}\n")
data = json.load(open(path, encoding="utf-8"))

def show(d, prefix="", depth=0):
    if depth > 3:
        return
    if isinstance(d, dict):
        for k, v in d.items():
            if isinstance(v, list):
                print(f"{prefix}{k}: list[{len(v)}]")
                if v and isinstance(v[0], dict):
                    print(f"{prefix}  [0] keys: {list(v[0].keys())[:12]}")
            elif isinstance(v, dict):
                print(f"{prefix}{k}: dict({len(v)} keys)")
                show(v, prefix + "  ", depth + 1)
            else:
                sv = str(v)[:40]
                print(f"{prefix}{k}: {sv}")

print("=== TOP-LEVEL STRUCTURE ===")
show(data)

# Try to find any list whose items mention LOOM or FIXING
print("\n=== HUNTING for bought-in items anywhere ===")
def hunt(d, path="root"):
    if isinstance(d, dict):
        for k, v in d.items():
            hunt(v, f"{path}.{k}")
    elif isinstance(d, list):
        for i, it in enumerate(d):
            if isinstance(it, dict):
                blob = json.dumps(it).upper()
                if "LOOM" in blob or "FIXING5" in blob or "FOAM TAPE" in blob:
                    desc = it.get("description") or it.get("part_number") or "?"
                    # find any price-like key
                    prices = {k: v for k, v in it.items() if "cost" in k.lower() or "price" in k.lower() or "estimate" in k.lower()}
                    print(f"  {path}[{i}]: '{desc}'  keys={list(it.keys())[:10]}")
                    print(f"      prices: {prices}")
            else:
                hunt(it, f"{path}[{i}]")
hunt(data)
