# -*- coding: utf-8 -*-
"""Dump the REAL keys + cost/time data for 3886-01 from BOTH part_estimates and
manufacturing_writeup, so we stop guessing key names. Reads PRECACHE, no re-run.
  C:\\ClaudeVision\\.venv\\Scripts\\python.exe _tube_keys.py"""
import json
PATH = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.PRECACHE.json"
with open(PATH, encoding="utf-8") as fh:
    d = json.load(fh)

def find_3886(parts):
    for p in parts or []:
        if str(p.get("part_number") or "") == "3886-01":
            return p
    return None

# part_estimates is where the run-log "Unit estimate: 4.22" comes from
pe = find_3886((d.get("estimate_summary") or {}).get("part_estimates"))
print("=== 3886-01 in estimate_summary.part_estimates ===")
if pe:
    print("TOP-LEVEL KEYS:", list(pe.keys()))
    # print anything mentioning cost / labour / time / laser
    for k, v in pe.items():
        ks = k.lower()
        if any(t in ks for t in ("cost","labour","time","laser","operation","total","material")):
            sv = json.dumps(v) if isinstance(v,(dict,list)) else str(v)
            print(f"  {k}: {sv[:200]}")
else:
    print("  (not found in part_estimates)")

# Also search whole doc for a laser_cutting cost line attached to 3886-01 context
print("\n=== does 'laser' appear with a £ near 3886-01 anywhere? ===")
blob = json.dumps(d)
i = blob.find('"3886-01"')
while i != -1 and i < len(blob):
    window = blob[i:i+1500]
    if "laser" in window.lower():
        # show the laser mention
        j = window.lower().find("laser")
        print("  ...", window[max(0,j-40):j+80].replace("\n"," "))
    i = blob.find('"3886-01"', i+1)
    if i > 4_000_000: break