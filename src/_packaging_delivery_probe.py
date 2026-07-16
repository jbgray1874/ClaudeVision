"""READ-ONLY. Before adding PACKAGING + DELIVERY rows, check what already happens:
  1. Are PACKAGING / DELIVERY already rows in the SAVED 1298 WB? How many of each?
  2. Are they in the JSON (we know they are) — do they survive into the Excel?
  3. How does wb_populate handle them / where would we add unconditional rows?
  4. Regression view: does 1282's saved WB already have them (so we don't double up)?

This decides: already-done (confirm) vs dropped (wire in) vs conditional (make unconditional).
"""
import io, json, re
from pathlib import Path
import openpyxl

EST = Path(r"C:\ClaudeVision\output\estimates")
SRC = Path(r"C:\ClaudeVision\src")

def latest(glob):
    xs = sorted(EST.glob(glob))
    return xs[-1] if xs else None

def scan_wb(path, label):
    print("=" * 78)
    print(f"{label}: {path.name if path else '(none found)'}")
    print("=" * 78)
    if not path:
        return
    try:
        wb = openpyxl.load_workbook(path, data_only=False)
    except Exception as e:
        print(f"  could not open: {e}"); return
    pack, deliv = [], []
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                if cell.value is None: continue
                s = str(cell.value).upper()
                if "PACKAG" in s:
                    pack.append((ws.title, cell.coordinate, str(cell.value)[:60]))
                if "DELIVER" in s or "HAULAGE" in s:
                    deliv.append((ws.title, cell.coordinate, str(cell.value)[:60]))
    print(f"  PACKAGING rows found: {len(pack)}")
    for t,c,v in pack: print(f"     [{t}] {c}: {v}")
    print(f"  DELIVERY rows found:  {len(deliv)}")
    for t,c,v in deliv: print(f"     [{t}] {c}: {v}")
    if len(pack) == 0 and len(deliv) == 0:
        print("  -> NEITHER in the WB (in JSON but dropped on populate) -> fix = wire them in.")
    elif len(pack) == 1 and len(deliv) == 1:
        print("  -> Both present exactly once -> may already be done; confirm labels/position.")
    else:
        print("  -> Unexpected count -> investigate (duplicates or partial).")
    wb.close()

scan_wb(latest("1298DrillHolder_*.xlsx"), "SAVED 1298 WB")
print()
scan_wb(latest("1282 - Milwaukee Wall Bay_*.xlsx"), "SAVED 1282 WB (regression view)")

# JSON side — confirm they're in the part list
print("\n" + "=" * 78)
print("JSON part list — PACKAGING / DELIVERY present?")
print("=" * 78)
for jname in ("1298DrillHolder.json", "1282 - Milwaukee Wall Bay.json"):
    jp = Path(r"C:\ClaudeVision\output\json") / jname
    if not jp.exists(): continue
    d = json.load(io.open(jp, encoding="utf-8"))
    parts = (d.get("manufacturing_writeup") or {}).get("parts") or d.get("parts") or []
    names = [str(p.get("part_number") or "").upper() for p in parts]
    print(f"  {jname}: PACKAGING={'PACKAGING' in names}  DELIVERY={'DELIVERY' in names}")

# how does wb_populate handle them
print("\n" + "=" * 78)
print("wb_populate handling of PACKAGING / DELIVERY / bought_in rows")
print("=" * 78)
wp = SRC / "wb_populate.py"
if wp.exists():
    txt = wp.read_text(encoding="utf-8", errors="replace")
    for i, l in enumerate(txt.splitlines(), 1):
        if re.search(r"PACKAG|DELIVER|HAULAGE|bought_in|estimator to price|BOM|skip|exclude", l, re.I):
            print(f"  {i:5}: {l.strip()[:100]}")
