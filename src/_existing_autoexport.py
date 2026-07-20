r"""READ-ONLY. main.py:666 says 'Auto-generate clean BOM/Routes/Summary xlsx on every scan'.
There's ALREADY an auto-export on every scan. Show that block so the client quote + parity
report slot into the SAME flow, not a parallel one. Show:
  1) main.py lines 660-712 (the auto-export + populate + save region)
  2) what function does the BOM/Routes/Summary export + where it writes (archive? estimates?)
  3) confirm today's estimates dir is empty / where today's runs would land
No edits."""
import os, re, glob
mp=r"C:\ClaudeVision\src\main.py"
L=open(mp,encoding="utf-8",errors="replace").read().splitlines()

print("="*66); print("1 — main.py 655-712 (auto-export + populate + save)"); print("="*66)
for i in range(654, min(len(L),712)):
    print(f"  {i+1}: {L[i].rstrip()[:104]}")

# 2) the BOM/Routes/Summary exporter function
print("\n"+"="*66); print("2 — BOM/Routes/Summary exporter (function + write path)"); print("="*66)
src=open(mp,encoding="utf-8",errors="replace").read()
# what's called near line 666
for i in range(660, min(len(L),680)):
    if re.search(r"generate|export|write|build|\(summary", L[i]):
        print(f"  main.py:{i+1}: {L[i].strip()[:100]}")
# find the imported name
for i,ln in enumerate(L[:60]):
    if re.search(r"import.*bom|import.*route|import.*summary|clean.*bom|BOM.*Route", ln, re.I):
        print(f"  import main.py:{i+1}: {ln.strip()[:100]}")

# 3) estimates dir contents (today?) + archive convention
print("\n"+"="*66); print("3 — output dirs: estimates (today?) + where versioned CSVs go"); print("="*66)
for d in [r"C:\ClaudeVision\output\estimates", r"C:\ClaudeVision\output\csv", r"C:\ClaudeVision\output\archive\csv"]:
    if os.path.isdir(d):
        files=sorted(glob.glob(os.path.join(d,"*")), key=os.path.getmtime, reverse=True)[:5]
        print(f"  {d}  ({len(glob.glob(os.path.join(d,'*')))} files, newest 5):")
        for f in files:
            import datetime
            mt=datetime.datetime.fromtimestamp(os.path.getmtime(f)).strftime("%Y-%m-%d %H:%M")
            print(f"      {mt}  {os.path.basename(f)[:70]}")
