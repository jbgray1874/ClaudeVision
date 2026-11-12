"""Audit estimate books: does "Total Labour Hours By Dept." cover every labour row? (D-325)

The template's hidden Labour sheet read only the first 40 labour rows (the rest pointed below
the block). Books with more than 40 labour rows understate department hours; money is unaffected.
Reads Excel's cached values, so audit books Excel has saved.

usage: python tools\diagnose\audit_labour_hours.py <folder or .xlsx> ..."""
import sys, re, glob, os, openpyxl

def audit(path):
    try:
        wf = openpyxl.load_workbook(path, data_only=False, read_only=False)
        wv = openpyxl.load_workbook(path, data_only=True, read_only=False)
    except Exception as e:
        return f"{os.path.basename(path)}: unreadable ({e.__class__.__name__})"
    if "Estimate" not in wf.sheetnames or "Labour" not in wf.sheetnames:
        return None
    E, Ev, L = wf["Estimate"], wv["Estimate"], wf["Labour"]
    col = {str(c.value).strip().lower(): c.row for c in E["C"] if isinstance(c.value, str)}
    op = next((r for r in range(1, E.max_row + 1) if str(E.cell(r, 3).value or "").strip().lower() == "operation"), None)
    tot = next((r for r in range(op or 1, E.max_row + 1) if str(E.cell(r, 3).value or "").strip().lower().startswith("total labour cost")), None) if op else None
    if not (op and tot):
        return f"{os.path.basename(path)}: labour block not found"
    fr, lr = op + 1, tot - 1
    read = set()
    for r in range(1, 201):
        m = re.match(r"^=\s*'?Estimate'?!\$?G\$?(\d+)", str(L.cell(r, 1).value or ""))
        if m: read.add(int(m.group(1)))
    gap = [r for r in range(fr, lr + 1) if r not in read]      # the sheet's own references
    ops = [r for r in range(fr, lr + 1) if E.cell(r, 3).value not in (None, "")]
    raw = {r: Ev.cell(r, 10).value for r in ops}
    hours = {r: float(v) for r, v in raw.items() if isinstance(v, (int, float)) and v}
    calculated = any(isinstance(v, (int, float)) for v in raw.values())
    missed = {r: h for r, h in hours.items() if r not in read}
    dept_label = next((r for r in range(tot, E.max_row + 1)
                       if str(E.cell(r, 3).value or "").strip().lower() == "total hours"), None)
    shown = Ev.cell(dept_label, 4).value if dept_label else None
    sheet = (f"Labour sheet misses rows {gap[0]}..{gap[-1]} ({len(gap)})" if gap
             else "Labour sheet covers the block")
    name = os.path.basename(path)
    if missed:
        return (f"UNDERSTATED {name}: {sheet}; {len(hours)} rows = {sum(hours.values()):.2f} h, "
                f"dept total shown {round(float(shown or 0), 2)}, missed {len(missed)} rows "
                f"({sum(missed.values()):.2f} h)")
    if ops and not calculated:
        return (f"NOT CALC    {name}: {sheet}; {len(ops)} labour rows but no calculated values "
                f"(never opened and saved in Excel) - cannot say; affected only if rows beyond "
                f"the sheet's reach are used: {[r for r in ops if r not in read][:3] or 'none are'}")
    tag = "GAP (unused)" if gap else "ok"
    return (f"{tag:11} {name}: {sheet}; {len(ops)} labour rows, "
            f"{sum(hours.values()):.2f} h, dept total shown {shown}")


paths = []
for a in sys.argv[1:]:
    paths += sorted(glob.glob(os.path.join(a, "**", "*.xlsx"), recursive=True)) if os.path.isdir(a) else [a]
for p in paths:
    if os.path.basename(p).startswith("~$"):
        continue
    out = audit(p)
    if out: print(out)
