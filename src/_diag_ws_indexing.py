r"""READ-ONLY. Confirm the index-base bug: is `ws` passed to _manual_bom_lines a raw xlrd
sheet (0-indexed cell_value) or an adapter with 1-indexed .cell(r,c).value? And how is the
manual workbook opened + how is _manual_bom_lines called (what row/col bounds)? This decides
whether the fix is 'use cell_value with 0-index' or 'the adapter is fine, bug is elsewhere'."""
import os, re
p = r"C:\ClaudeVision\src\estimate_full_parity_report.py"
src = open(p, encoding="utf-8", errors="replace").read()
L = src.splitlines()

# 1) how is the workbook opened (xlrd.open_workbook / openpyxl / adapter)?
print("="*72); print("1 — workbook open + sheet access"); print("="*72)
for i,ln in enumerate(L):
    if re.search(r"open_workbook|load_workbook|xlrd|sheet_by|\.cell\(|class .*Sheet|def cell|WorkbookAdapter|_XlrdSheet|CellShim|\.value", ln):
        if re.search(r"open_workbook|load_workbook|sheet_by|class .*(Sheet|Adapter|Shim)|def cell|xlrd\.", ln):
            print(f"  {i+1}: {ln.strip()[:112]}")

# 2) is there an adapter/shim class wrapping xlrd to give .cell(r,c).value ?
print("\n"+"="*72); print("2 — any adapter/shim class definition"); print("="*72)
m = re.search(r"class\s+(\w*(?:Sheet|Adapter|Shim|Wrap)\w*)", src)
if m:
    cls = m.group(1); print("  found class:", cls)
    ci = src.index(m.group(0)); 
    block = src[ci:ci+900]
    for ln in block.splitlines()[:30]:
        print("   ", ln.rstrip()[:108])
else:
    print("  NO adapter class found -> ws is likely a RAW xlrd sheet (0-indexed).")
    print("  => parser's ws.cell(row,col) with 1-index is the bug OR xlrd sheet has no .cell method.")

# 3) how is _manual_bom_lines CALLED (bounds, and what `ws` is)
print("\n"+"="*72); print("3 — _manual_bom_lines call site(s)"); print("="*72)
for i,ln in enumerate(L):
    if "_manual_bom_lines(" in ln and "def " not in ln:
        for j in range(max(0,i-6), min(len(L), i+2)):
            print(f"  {j+1}: {L[j].strip()[:112]}")
        print("   ----")

# 4) does xlrd sheet even HAVE .cell(r,c).value? (yes — xlrd Cell has .value, and sheet.cell(r,c) exists, 0-indexed)
print("\n"+"="*72); print("4 — _norm_line_code (how codes are normalised for matching)"); print("="*72)
mm = re.search(r"def _norm_line_code.*?(?=\ndef )", src, re.S)
if mm:
    for ln in mm.group(0).splitlines()[:22]:
        print("   ", ln.rstrip()[:108])
