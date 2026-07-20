r"""READ-ONLY DIAGNOSIS. The manual-.xls BOM parser in estimate_full_parity_report.py is
misreading Tim's 1282 sheet: bom_set_reconciliation shows code='0.0', description='100.0',
matched_count=0. Find WHY.

Two halves:
  1) Read Tim's ACTUAL .xls with xlrd — dump the rows around the BOM block so we see the real
     column layout (which column holds the part code, which holds description, which holds cost).
  2) Show the parser's _manual_bom_lines column-scan logic so we see what columns/heuristics it
     uses — and where its assumption diverges from the real sheet.
No edits. Diagnosis only.
"""
import os, re

MANUAL = r"K:\Estimating\Completed\Manual Estimates\2026\TTI\1282- MILWAUKEE RED 50cm PEG\1282-MILWAUKEE 50CM PEG WALL BAY(ISS 7)-.xls"

# ---- 1) real sheet layout via xlrd ----
print("="*74); print("PART 1 — Tim's ACTUAL .xls layout (xlrd)"); print("="*74)
try:
    import xlrd
    bk = xlrd.open_workbook(MANUAL)
    print("sheets:", bk.sheet_names())
    sh = bk.sheet_by_index(0)
    # try the 'Estimate' sheet if present
    for nm in bk.sheet_names():
        if "estimate" in nm.lower():
            sh = bk.sheet_by_name(nm); print("using sheet:", nm); break
    print(f"dims: {sh.nrows} rows x {sh.ncols} cols\n")
    # find the BOM header row ('Part code' / 'Bill of Materials') and dump ~30 rows after
    header_row = None
    for r in range(min(sh.nrows, 60)):
        rowvals = [str(sh.cell_value(r, c)) for c in range(min(sh.ncols, 14))]
        joined = " ".join(rowvals).lower()
        if "part code" in joined or "bill of material" in joined or ("supplier" in joined and "price" in joined):
            header_row = r
            print(f">>> BOM HEADER at row {r}: {[v for v in rowvals if v.strip()]}")
    start = (header_row or 6)
    print(f"\n--- rows {start}..{start+28} (col index : value) ---")
    for r in range(start, min(sh.nrows, start+28)):
        cells = []
        for c in range(min(sh.ncols, 14)):
            v = sh.cell_value(r, c)
            if v not in ("", None):
                cells.append(f"[{c}]={repr(v)[:26]}")
        if cells:
            print(f"  r{r}: " + "  ".join(cells))
except Exception as e:
    print("xlrd read failed:", repr(e))

# ---- 2) parser logic ----
print("\n"+"="*74); print("PART 2 — parser _manual_bom_lines column-scan logic"); print("="*74)
p = r"C:\ClaudeVision\src\estimate_full_parity_report.py"
L = open(p, encoding="utf-8", errors="replace").read().splitlines()
# find the function and print it
start=end=None
for i,ln in enumerate(L):
    if re.search(r"def _manual_bom_lines", ln):
        start=i
    elif start is not None and re.match(r"^def ", ln) and i>start:
        end=i; break
if start is not None:
    end = end or min(len(L), start+90)
    for j in range(start, min(end, start+95)):
        print(f"  {j+1}: {L[j].rstrip()[:118]}")
else:
    print("  _manual_bom_lines not found — searching for code/description column heuristics")
    for i,ln in enumerate(L):
        if re.search(r"part.?code|code_col|desc_col|cost_col|column|cell_value|is_code|looks_like", ln, re.I):
            print(f"  {i+1}: {ln.strip()[:112]}")
