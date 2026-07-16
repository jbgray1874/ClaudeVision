"""READ-ONLY. Grab the exact code regions for the two edits:
  A) job_decision_report.py: the header (imports/args of add_decision_report_sheet),
     _mat_source_explanation start, the total computation (line ~251), and the
     TOTAL ESTIMATE write (~360-365) — so both edits target verbatim code.
  B) confirm how add_decision_report_sheet is CALLED (does it get the wb path / can it
     re-open the populated WB to scan for the 'Sell Price' label?).
Run: C:\ClaudeVision\.venv\Scripts\python.exe _final_edit_probe.py"""
from pathlib import Path
SRC = Path(r"C:\ClaudeVision\src")

jl = (SRC / "job_decision_report.py").read_text(encoding="utf-8", errors="replace").splitlines()

print("=== A1: file top / imports (lines 1-30) ===")
for i in range(0, min(30, len(jl))): print(f"{i+1:4}: {jl[i]}")

print("\n=== A2: add_decision_report_sheet signature + first lines (213-235) ===")
for i in range(212, min(236, len(jl))): print(f"{i+1:4}: {jl[i]}")

print("\n=== A3: _mat_source_explanation (114-145) ===")
for i in range(113, min(145, len(jl))): print(f"{i+1:4}: {jl[i]}")

print("\n=== A4: total computation + TOTAL ESTIMATE write (249-266, 358-366) ===")
for i in range(248, min(267, len(jl))): print(f"{i+1:4}: {jl[i]}")
print("  ...")
for i in range(357, min(367, len(jl))): print(f"{i+1:4}: {jl[i]}")

print("\n=== B: how add_decision_report_sheet is called (in main.py / xlsx_output.py) ===")
for f in ("main.py","xlsx_output.py"):
    p = SRC / f
    if p.exists():
        for i,l in enumerate(p.read_text(encoding="utf-8",errors="replace").splitlines(),1):
            if "add_decision_report_sheet" in l or "decision_report" in l.lower():
                print(f"  [{f}:{i}] {l.strip()[:110]}")

print("\n=== B2: does job_decision_report import openpyxl / have the wb object? ===")
for i,l in enumerate(jl,1):
    if "import" in l and ("openpyxl" in l or "load_workbook" in l): print(f"  {i}: {l.strip()}")
# the function gets 'wb' — confirm it's the live workbook object
print("  (add_decision_report_sheet receives 'wb' — the live openpyxl workbook, so it can read other sheets in-memory)")
