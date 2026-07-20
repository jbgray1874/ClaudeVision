r"""READ-ONLY. Find where the bundle builder maps Tim's labour columns to workbook_hours_decimal
and workbook_line_cost_gbp — it's putting Tim's Total Value (col 12, £13.62) into hours and
leaving cost at 0. Need the exact code that reads the labour-route rows and assigns those two
fields, so the column mapping can be corrected. No edits."""
import re
p=r"C:\ClaudeVision\src\estimate_full_parity_report.py"
src=open(p,encoding="utf-8",errors="replace").read()
L=src.splitlines()

# find assignments to workbook_hours_decimal / workbook_line_cost_gbp
print("="*66); print("assignments to workbook_hours_decimal / workbook_line_cost_gbp"); print("="*66)
for i,ln in enumerate(L):
    if re.search(r"workbook_hours_decimal|workbook_line_cost_gbp", ln):
        # show context
        for j in range(max(0,i-3), min(len(L),i+2)):
            mark=">>" if j==i else "  "
            print(f"{mark}{j+1}: {L[j].rstrip()[:110]}")
        print("   ----")

# find where labour route rows are read from the sheet (column indices for hours/value)
print("\n"+"="*66); print("labour-route sheet reading (column picks)"); print("="*66)
for i,ln in enumerate(L):
    if re.search(r"total.?hours|total.?value|labour.?cost|rate.?per.?hour|hours_col|value_col|cost_col|cell\(.*\d+\).*hour|route.*column|_labour_route", ln, re.I):
        print(f"  {i+1}: {ln.strip()[:110]}")

# the function that builds labour_route_comparisons
print("\n"+"="*66); print("labour_route_comparisons builder function"); print("="*66)
m=re.search(r"def (\w*labour_route\w*)\b", src)
if m:
    fn=m.group(1); print("function:", fn)
    mm=re.search(rf"def {fn}\b.*?(?=\ndef )", src, re.S)
    if mm:
        for ln in mm.group(0).splitlines()[:60]:
            print("  ", ln.rstrip()[:108])
