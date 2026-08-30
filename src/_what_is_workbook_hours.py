r"""READ-ONLY. The bundle's workbook_line_cost_gbp is 0.0 for every op; workbook_hours_decimal
holds numbers (powder 13.6163) whose meaning is unclear. Find what 13.6163 actually IS by
reading Tim's sheets directly. Powder rows on the Estimate sheet were: P/C lines with small
hours (0.32, 0.79, 0.24...) and Rate/Hr 424/638. Sum the powder hours and powder costs from
the Estimate sheet's Labour block and see which matches 13.6163 (hours) or the £ (cost).
Also peek at 'Labour' and 'Route Import' sheets. No edits."""
import xlrd
MANUAL=r"K:\Estimating\Completed\Manual Estimates\2026\TTI\1282- MILWAUKEE RED 50cm PEG\1282-MILWAUKEE 50CM PEG WALL BAY(ISS 7)-.xls"
bk=xlrd.open_workbook(MANUAL)
print("sheets:", bk.sheet_names(), "\n")

# Estimate sheet: find the Labour block, sum P/C (powder) hours and value columns
sh=bk.sheet_by_name("Estimate")
def cv(r,c):
    try: return sh.cell_value(r,c)
    except: return None
# header row of labour block: 'Operation ... Rate Per Hour ... Total Hours ... Labour Cost ... Total Value'
labhdr=None
for r in range(sh.nrows):
    row=" ".join(str(cv(r,c)) for c in range(sh.ncols)).lower()
    if "operation" in row and ("total hours" in row or "labour cost" in row or "rate per hour" in row):
        labhdr=r; print(f"labour header row {r}: {[cv(r,c) for c in range(sh.ncols) if cv(r,c) not in (None,'')]}"); break

# scan labour rows, collect P/C (powder) rows: which columns hold hours vs value
print("\nPowder (P/C) labour rows on Estimate sheet:")
pc_hours_sum=0.0; pc_value_sum=0.0; pc_totalhrs_sum=0.0
if labhdr:
    for r in range(labhdr+1, min(sh.nrows, labhdr+80)):
        cells=[cv(r,c) for c in range(sh.ncols)]
        rowtxt=" ".join(str(x) for x in cells if x not in (None,""))
        # P/C rows have 'P/C' in the dept column
        if any(str(x).strip()=="P/C" for x in cells) or "p.coat" in rowtxt.lower() or "p/c" in rowtxt.lower():
            nums=[(c,cv(r,c)) for c in range(sh.ncols) if isinstance(cv(r,c),(int,float)) and cv(r,c)!=0]
            print(f"  r{r}: {rowtxt[:60]}  nums={nums}")

# Also dump Labour + Route Import sheets briefly to see if per-op cost lives there
for nm in ("Labour","Route Import"):
    if nm in bk.sheet_names():
        s2=bk.sheet_by_name(nm)
        print(f"\n--- '{nm}' sheet {s2.nrows}x{s2.ncols} (first 12 rows) ---")
        for r in range(min(s2.nrows,12)):
            row=[s2.cell_value(r,c) for c in range(min(s2.ncols,12))]
            row=[x for x in row if x not in (None,"")]
            if row: print(f"  r{r}: {row}")
