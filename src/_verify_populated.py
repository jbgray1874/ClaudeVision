"""
Read-only. Read the POPULATED xlsx directly and print exactly which parts are in
the steel block vs BOM block, so we compare the FILE against what the console said.
Settles whether the file matches the clean-run classification or is stale.
Run: C:\ClaudeVision\.venv\Scripts\python.exe _verify_populated.py "C:\ClaudeVision\output\estimates\1282 - Milwaukee Wall Bay_20260702_172911.xlsx"
"""
import sys
try:
    import openpyxl
except ImportError:
    print("need openpyxl"); sys.exit(1)

P = sys.argv[1] if len(sys.argv) > 1 else r"C:\ClaudeVision\output\estimates\1282 - Milwaukee Wall Bay_20260702_172911.xlsx"
wb = openpyxl.load_workbook(P, data_only=False)
ws = wb["Estimate"]

def cell(r, c): 
    v = ws.cell(row=r, column=c).value
    return "" if v is None else str(v)

print("FILE:", P)
print("\n=== BOM block (rows 11-25), col C=desc, H=code ===")
for r in range(11, 26):
    desc, code = cell(r, 3), cell(r, 8)
    if desc or code:
        print(f"  row {r}: {desc[:40]:<40} [{code}]")

print("\n=== STEEL block (rows 38-48), col C=desc, F=len, G=wid, H=gauge ===")
for r in range(38, 49):
    desc = cell(r, 3)
    if desc:
        print(f"  row {r}: {desc[:40]:<40} L={cell(r,6)} W={cell(r,7)} G={cell(r,8)}")

print("\n=== Other Sheet block (rows 51-58), col C=desc ===")
for r in range(51, 59):
    desc = cell(r, 3)
    if desc:
        print(f"  row {r}: {desc[:40]:<40} L={cell(r,5)} W={cell(r,6)}")

print("\nCompare: does STEEL block contain 1448-01/1455-C-101/1453-GA-C?")
print("If YES -> this file was written by OLD code (pre-fix), timestamp notwithstanding.")
print("If NO  -> the file is clean and your earlier paste was from a different file.")
