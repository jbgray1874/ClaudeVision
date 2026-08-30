"""READ-ONLY. Get (a) the exact Sell Price cell + worksheet name from wb_populate CELL_MAP,
and (b) the verbatim _mat_source_explanation() + how a part is identified as bought-in,
so both edits target the real code.
Run: C:\ClaudeVision\.venv\Scripts\python.exe _cellmap_probe.py"""
from pathlib import Path
SRC = Path(r"C:\ClaudeVision\src")

print("=" * 72); print("1. CELL_MAP — sheet name + sell price / totals cells"); print("=" * 72)
wl = (SRC / "wb_populate.py").read_text(encoding="utf-8", errors="replace").splitlines()
# print CELL_MAP from its start until 'labour' or ~120 lines, focusing on names/totals
start = next((i for i,l in enumerate(wl) if "CELL_MAP = {" in l), 40)
for i in range(start, min(start+130, len(wl))):
    u = wl[i].lower()
    if any(t in u for t in ("sheet", "sell", "total", "unit cost", "name", '"row"', "'row'",
                            '"col"', "'col'", "price", "margin", "}", "estimate")):
        print(f"  {i+1:4}: {wl[i].rstrip()[:120]}")

print("\n" + "=" * 72); print("2. _mat_source_explanation() verbatim + bought-in detection"); print("=" * 72)
jl = (SRC / "job_decision_report.py").read_text(encoding="utf-8", errors="replace").splitlines()
s = next((i for i,l in enumerate(jl) if "_mat_source_explanation" in l and "def " in l), 113)
for i in range(s, min(s+40, len(jl))):
    print(f"  {i+1:4}: {jl[i]}")
print("\n  --- how is a part flagged bought_in in this file? ---")
for i,l in enumerate(jl,1):
    if "bought_in" in l.lower() or "page_roles" in l.lower() or 'BI-' in l:
        print(f"  {i:4}: {l.strip()[:110]}")
