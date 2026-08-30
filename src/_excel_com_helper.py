r"""READ-ONLY. Path 2 fix: after wb_populate, open the .xlsx via Excel COM, read the real
computed totals (Material/Labour/Unit), write them into the JSON's workbook_equivalent_pricing.
Show the EXISTING _open_workbook_excel_com helper (line ~128-175) so I reuse it, and the cell
label-scan that finds 'Total Material Cost' etc., so the readback finds the right cells. Also
confirm which rows hold the totals in the populated .xlsx (M92 material, row 168 labour, row 170
unit — from earlier). No edits — gathering the proven pieces for the fix."""
import re
p=r"C:\ClaudeVision\src\estimate_full_parity_report.py"
src=open(p,encoding="utf-8",errors="replace").read()
L=src.splitlines()

print("="*70); print("_open_workbook_excel_com (reuse this)"); print("="*70)
m=re.search(r"def _open_workbook_excel_com\b.*?(?=\ndef )", src, re.S)
if m:
    for ln in m.group(0).splitlines()[:60]:
        print("  ", ln.rstrip()[:104])

print("\n"+"="*70); print("how it reads a cell value (the wrapper .cell / value access)"); print("="*70)
# find the wrapper class for excel com cells
m2=re.search(r"class _ExcelCom\w+.*?(?=\nclass |\ndef )", src, re.S)
if m2:
    for ln in m2.group(0).splitlines()[:40]:
        print("  ", ln.rstrip()[:100])

# the label scan that finds totals (mode full_sheet_label_scan) - _read_money_cells
print("\n"+"="*70); print("label-scan for section totals (how 'Total Material Cost' is found)"); print("="*70)
m3=re.search(r"def _read_money_cells\b.*?(?=\ndef )", src, re.S)
if m3:
    for ln in m3.group(0).splitlines()[:45]:
        print("  ", ln.rstrip()[:100])
