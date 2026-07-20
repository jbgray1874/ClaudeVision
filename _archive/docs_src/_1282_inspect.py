"""Digest the three 1282 component scan JSONs after a re-scan.

Run from C:\\ClaudeVision:  python output\\_1282_inspect.py
"""
import json, glob, os

pats = ["1449*Peg*.json", "1450*Base*.json", "1455*Header*.json"]
files = []
for p in pats:
    files += glob.glob(os.path.join("output", "json", p))

if not files:
    print("No 1282 JSONs found in output\\json - run the re-scan first.")

for f in sorted(set(files)):
    d = json.load(open(f, encoding="utf-8-sig"))
    a = d.get("dxf_augmentation") or {}
    es = d.get("estimate_summary") or {}
    print("=" * 64)
    print(os.path.basename(f))
    print(f"  matched={len(a.get('matched', []))}  "
          f"unmatched={len(a.get('unmatched_dxf', []))}  "
          f"ambiguous={len(a.get('ambiguous_dxf', []))}")

    for amb in a.get("ambiguous_dxf", []):
        print(f"  AMBIGUOUS {amb.get('part_number')} -> chose {os.path.basename(amb.get('chosen',''))}")
        for c in amb.get("candidates", []):
            print(f"       candidate: {os.path.basename(c)}")

    for m in a.get("matched", []):
        print(f"  matched: {m.get('part_number')} <- {os.path.basename(m.get('dxf',''))}"
              f"  | src={m.get('geometry_source')} rel={m.get('geometry_reliability')}")

    for u in a.get("unmatched_dxf", []):
        print(f"  unmatched: {os.path.basename(u.get('path',''))} (pn={u.get('part_number')}, {u.get('reason')})")

    print("  -- per-part geometry source --")
    for prt in (d.get("manufacturing_writeup") or {}).get("parts", []):
        gs = (prt.get("normalized_geometry") or {}).get("geometry_source") or prt.get("geometry_source")
        print(f"     {prt.get('part_number')} -> {gs}  (mat={prt.get('normalized_material')})")

    print(f"  document_total = {es.get('document_total_estimated_cost_gbp')}")
    for k, v in es.items():
        if any(t in k.lower() for t in ("suffic", "credible", "reportable")):
            print(f"  {k}: {json.dumps(v)[:240]}")
