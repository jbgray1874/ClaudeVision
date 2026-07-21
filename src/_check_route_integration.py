r"""READ-ONLY. Q: are ALL manufacturing route paths integrated for the improved DXF analysis?
Don't assume — check the deployed code + 12120's actual routes. Establish:
  1) What operations/routes does the engine derive, and from where (DXF geometry -> route)?
     Find the route/operation derivation in the live path (estimator / geometry / process).
  2) What ROUTE OPERATIONS actually appeared on 12120 (laser/fold/powder/weld/assemble/etc.)?
     And are there operations that SHOULD derive but don't (punch vs laser, spot vs CO2 weld,
     roll, tube-bend, CNC, dress, diamond-polish)?
  3) Which operations are DXF-geometry-driven vs config-default vs missing.
  4) The 'genuine gaps requiring new conventions' from the SolidWorks framework (punch vs laser,
     spot vs CO2 weld, coat grouping) — are those resolved or still gaps?
No edits — what routes ARE integrated vs still gaps."""
import os, re, json, glob
SRC=r"C:\ClaudeVision\src"

print("="*68); print("1 — where routes/operations are derived (live path)"); print("="*68)
for fn in ("estimator.py","geometry_inference.py","operation_normaliser.py","process_estimator.py","dxf_reader.py"):
    p=os.path.join(SRC,fn)
    if not os.path.exists(p): continue
    L=open(p,encoding="utf-8",errors="replace").read().splitlines()
    for i,ln in enumerate(L):
        if re.search(r"(def .*rout|def .*operation|routing\s*=|operations?\s*=\s*\[|_derive_route|process_estimate|def .*process)", ln, re.I) and "def " in ln:
            print(f"  {fn}:{i+1}: {ln.strip()[:92]}")

print("\n"+"="*68); print("2 — operation vocabulary the engine KNOWS (from operation_normaliser)"); print("="*68)
p=os.path.join(SRC,"operation_normaliser.py")
if os.path.exists(p):
    txt=open(p,encoding="utf-8",errors="replace").read()
    # find operation code constants / mappings
    ops=set(re.findall(r"['\"]([A-Z][A-Za-z ()/_-]{2,30})['\"]\s*:", txt))
    known=[o for o in ops if re.search(r"(laser|fold|punch|weld|roll|bend|coat|powder|cnc|dress|polish|assemble|pack|spot|tube)", o, re.I)]
    for o in sorted(set(known))[:30]:
        print(f"    {o}")

print("\n"+"="*68); print("3 — routes that actually fired on 12120"); print("="*68)
hits=glob.glob(r"C:\ClaudeVision\output\json\*12120*.json")
if hits:
    S=json.load(open(hits[0],encoding="utf-8"))
    parts=S.get("estimate_summary",{}).get("part_estimates") or []
    all_ops=set(); driver_by_op={}
    for pp in parts:
        proc=pp.get("process_estimate",{}) or {}
        routing=proc.get("routing") or []
        for r in routing:
            if isinstance(r,dict):
                op=r.get("operation"); drv=r.get("driver") or r.get("source")
                if op: all_ops.add(op); driver_by_op.setdefault(op,set()).add(str(drv))
        # also times_min keys
        for k in (proc.get("times_min") or {}):
            all_ops.add(k)
    print(f"  operations on 12120: {sorted(all_ops)}")
    print("  driver per op:")
    for op in sorted(driver_by_op):
        print(f"    {op}: {sorted(driver_by_op[op])}")

print("\n"+"="*68); print("4 — known gaps (punch/laser, spot/CO2 weld, roll, tube-bend, coat-group)"); print("="*68)
# does the code distinguish these, or default?
for fn in ("estimator.py","operation_normaliser.py","geometry_inference.py"):
    p=os.path.join(SRC,fn)
    if not os.path.exists(p): continue
    txt=open(p,encoding="utf-8",errors="replace").read()
    for concept,pat in [("punch-vs-laser",r"punch"),("spot-vs-CO2-weld",r"spot.?weld"),
                        ("roll",r"\broll(?:ing)?\b"),("tube-bend",r"tube.?bend"),
                        ("diamond-polish",r"diamond.?polish"),("dress",r"\bdress\b")]:
        n=len(re.findall(pat, txt, re.I))
        if n: print(f"  {fn}: {concept} referenced {n}x")
