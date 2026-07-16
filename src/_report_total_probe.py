"""READ-ONLY. Two things needed to make the Decision Report total show the WB's
authoritative Sell Price via a live cross-sheet formula:
  1. The exact WB sheet name + Sell Price cell (from wb_populate.py CELL_MAP).
  2. The real job_decision_report.py total-rendering code (so we edit verbatim).

Run: C:\ClaudeVision\.venv\Scripts\python.exe _report_total_probe.py
"""
import re
from pathlib import Path

SRC = Path(r"C:\ClaudeVision\src")

# 1. Find the WB template sheet name + Sell Price cell in wb_populate.py
print("=" * 72)
print("1. WB Sell Price cell + sheet name (from wb_populate.py)")
print("=" * 72)
wbp = SRC / "wb_populate.py"
if wbp.exists():
    text = wbp.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    # Find any line mentioning sell price / the sheet name / CELL_MAP total cells
    for i, ln in enumerate(lines, 1):
        u = ln.lower()
        if any(t in u for t in ("sell price", "sell_price", "sellprice", "total unit cost",
                                "unit cost price", "cell_map", "sheet_name", "ws_name",
                                "worksheet", "estimate sheet", '"totals"', "'totals'")):
            print(f"  {i:4}: {ln.strip()[:120]}")
else:
    print("  wb_populate.py NOT FOUND — checking other files for the template sheet name")
    for f in SRC.glob("*.py"):
        t = f.read_text(encoding="utf-8", errors="replace")
        if "Sell Price" in t or "sell_price" in t.lower():
            print(f"  '{f.name}' mentions sell price")

# 2. Dump job_decision_report.py total-rendering region (lines ~245-270 + the TOTAL ESTIMATE row ~355-365)
print("\n" + "=" * 72)
print("2. job_decision_report.py total-rendering code")
print("=" * 72)
jdr = SRC / "job_decision_report.py"
if jdr.exists():
    jl = jdr.read_text(encoding="utf-8", errors="replace").splitlines()
    print("  --- header total (around line 245-270) ---")
    for i in range(244, min(272, len(jl))):
        print(f"  {i+1:4}: {jl[i]}")
    print("\n  --- TOTAL ESTIMATE row (search) ---")
    for i, ln in enumerate(jl, 1):
        if "TOTAL ESTIMATE" in ln or ("total" in ln.lower() and "_c(" in ln):
            for j in range(max(0,i-2), min(i+2, len(jl))):
                print(f"  {j+1:4}: {jl[j]}")
            print("   ...")
else:
    print("  job_decision_report.py NOT FOUND")

# 3. Also check the bought-in material RENDERING in the report (for the Option B display fix)
print("\n" + "=" * 72)
print("3. Where the report renders material / material-source for a part (Option B target)")
print("=" * 72)
if jdr.exists():
    for i, ln in enumerate(jl, 1):
        u = ln.lower()
        if any(t in u for t in ("material source", "mat_source", "suffix", "mdf/timber",
                                "→ mild steel", "material —", "mat.", "ai inference")):
            print(f"  {i:4}: {ln.strip()[:120]}")
