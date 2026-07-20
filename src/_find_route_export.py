r"""READ-ONLY. Find how the '0355592_9376-03-GA ... Manufacturing Routes' per-part route export
was generated. It has columns: Part No | Description | Operation | Dept | Qty/Unit | Rate(£/hr)
| Time(min) | Setup(min) | Labour Cost(£) | Extended(£). Locate:
  1) which script produces a 'Manufacturing Routes' export with those exact headers
  2) where 9376-03 job outputs live (json/estimates/csv) and the 0355592 prefix meaning
  3) how it was invoked (is it a --flag, a standalone tool, part of the run?)
No edits."""
import os, re, glob

roots=[r"C:\ClaudeVision\src", r"C:\ClaudeVision\output"]

# 1) which code emits 'Manufacturing Routes' + those headers
print("="*66); print("1 — code emitting 'Manufacturing Routes' / that header set"); print("="*66)
needles=["Manufacturing Routes","Qty/Unit","Extended (£)","Rate (£/hr)","Time (min)","dress_welds","cnc_routing"]
for p in glob.glob(r"C:\ClaudeVision\src\*.py"):
    if os.path.getsize(p)>2_000_000: continue
    try: txt=open(p,encoding="utf-8",errors="replace").read()
    except: continue
    hits=[n for n in needles if n in txt]
    if len(hits)>=2:
        print(f"  {os.path.basename(p)}: matches {hits}")
        for i,ln in enumerate(txt.splitlines()):
            if re.search(r"Manufacturing Routes|Qty/Unit|Extended|Rate.*hr|def .*route.*export|def .*manufacturing_route|write.*route", ln):
                print(f"      {i+1}: {ln.strip()[:96]}")

# 2) where do 9376-03 / 0355592 outputs live?
print("\n"+"="*66); print("2 — 9376-03 / 0355592 output files"); print("="*66)
for base in [r"C:\ClaudeVision\output"]:
    for p in glob.glob(os.path.join(base,"**","*9376*"),recursive=True)[:30]:
        print("  ", p)
    for p in glob.glob(os.path.join(base,"**","*0355592*"),recursive=True)[:30]:
        print("  ", p)

# 3) any 'route' export flag/tool in main.py or standalone scripts
print("\n"+"="*66); print("3 — route-export invocation (flags / standalone)"); print("="*66)
mp=r"C:\ClaudeVision\src\main.py"
if os.path.exists(mp):
    for i,ln in enumerate(open(mp,encoding="utf-8",errors="replace").read().splitlines()):
        if re.search(r"route.*export|manufacturing.?route|export.?route|--.*route|routes", ln, re.I):
            print(f"  main.py:{i+1}: {ln.strip()[:96]}")
# standalone route scripts
for p in glob.glob(r"C:\ClaudeVision\src\*rout*.py")+glob.glob(r"C:\ClaudeVision\src\*route*"):
    print("  standalone?:", os.path.basename(p))
