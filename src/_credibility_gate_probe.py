"""READ-ONLY. Finds where the credibility gate computes 'credible X%' and the
'DXF on Y% of N fabricated parts' ratio, and answers the key question:

  Are bought-ins / electricals / packaging (which CORRECTLY never have a DXF)
  sitting in the denominator of the DXF-coverage ratio? If so, they structurally
  drag the ratio below the quotable threshold and no legitimate fix can cross it
  -> that's a DENOMINATOR BUG, not a policy knob.

It (a) greps the source for the gate logic, (b) dumps the gate function(s) verbatim
to a file, and (c) reconstructs the ratio from 1282's JSON the way the message implies
(14 fabricated parts, 71% DXF) to see which parts are counted.

Run: C:\ClaudeVision\.venv\Scripts\python.exe _credibility_gate_probe.py
Then: notepad C:\ClaudeVision\src\credibility_gate_dump.txt
"""
import json, io, re
from pathlib import Path

OUT = io.open(r"C:\ClaudeVision\src\credibility_gate_dump.txt", "w", encoding="utf-8")
def w(*a):
    line = " ".join(str(x) for x in a)
    print(line); OUT.write(line + "\n")

SRC = Path(r"C:\ClaudeVision\src")

w("=" * 78)
w("A. Where does the gate live? grep for the message + ratio terms")
w("=" * 78)
TERMS = re.compile(
    r"INSUFFICIENT DATA|credible|DO NOT QUOTE|fabricated part|DXF on|coverage|"
    r"headline suppressed|reportable|credibility|not_reportable|dxf_coverage",
    re.I,
)
gate_files = []
for fp in sorted(SRC.glob("*.py")):
    try:
        lines = fp.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        continue
    hits = [(i + 1, l) for i, l in enumerate(lines) if TERMS.search(l)]
    if hits:
        gate_files.append(fp.name)
        w(f"\n  --- {fp.name}: {len(hits)} line(s) ---")
        for ln, l in hits[:30]:
            w(f"    {ln:5}: {l.strip()[:120]}")

w("\n" + "=" * 78)
w("B. What counts as a 'fabricated part'? grep the denominator logic")
w("=" * 78)
DENOM = re.compile(
    r"fabricated|is_bought_in|bought_in|page_role|has_dxf|dxf_augmented|"
    r"geometry_source|len\(|denominator|ratio|/ *len|sum\(1|count", re.I,
)
for name in gate_files:
    fp = SRC / name
    lines = fp.read_text(encoding="utf-8", errors="replace").splitlines()
    # show only lines near a 'credible'/'fabricated'/'coverage' anchor to keep it focused
    anchors = [i for i, l in enumerate(lines)
               if re.search(r"credible|fabricated|coverage|dxf.*ratio|reportable", l, re.I)]
    seen = set()
    if anchors:
        w(f"\n  --- {name}: denominator context around gate anchors ---")
    for a in anchors:
        for i in range(max(0, a - 4), min(len(lines), a + 8)):
            if i in seen:
                continue
            seen.add(i)
            if DENOM.search(lines[i]) or re.search(r"credible|fabricated|coverage|reportable", lines[i], re.I):
                w(f"    {i+1:5}: {lines[i].strip()[:120]}")

w("\n" + "=" * 78)
w("C. Reconstruct 1282's ratio from JSON — which parts are in the denominator?")
w("=" * 78)
P = r"C:\ClaudeVision\output\json\1282 - Milwaukee Wall Bay.json"
data = json.load(io.open(P, encoding="utf-8"))
parts = (data.get("manufacturing_writeup") or {}).get("parts") or data.get("parts") or []

def is_boughtin(p):
    pn = str(p.get("part_number","")).upper()
    roles = [str(r).lower() for r in (p.get("page_roles") or [])]
    return (pn.startswith(("BI-","FIXING","VINYL","PACKAGING","DELIVERY"))
            or "bought_in" in roles
            or str(p.get("normalized_material","")).upper() == "BOUGHT_IN")

def has_dxf(p):
    return bool(p.get("dxf_augmented")) or "dxf" in str(p.get("geometry_source","")).lower()

fab, fab_with_dxf, boughtins = [], [], []
for p in parts:
    pn = p.get("part_number")
    if is_boughtin(p):
        boughtins.append(pn); continue
    fab.append(pn)
    if has_dxf(p):
        fab_with_dxf.append(pn)

w(f"  Total part records:        {len(parts)}")
w(f"  Bought-in (NO DXF by nature): {len(boughtins)}  {boughtins}")
w(f"  Fabricated parts:          {len(fab)}  ->  {fab}")
w(f"  Fabricated WITH dxf:       {len(fab_with_dxf)}  ->  {fab_with_dxf}")
if fab:
    w(f"  DXF coverage of fabricated = {len(fab_with_dxf)}/{len(fab)} = {100*len(fab_with_dxf)/len(fab):.0f}%")
w("")
w("  The console said '14 fabricated parts, 71% DXF'. If THIS count matches 14 and 71%,")
w("  the gate already excludes bought-ins -> denominator is correct, gate is POLICY.")
w("  If the gate's 14 instead includes bought-ins (i.e. counts differently), that's the BUG.")
w("  Compare the numbers above to the console line to decide bug-vs-policy.")

w("\n" + "=" * 78)
w("D. Full dump of gate function(s) to credibility_gate_dump.txt")
w("=" * 78)
for name in gate_files:
    fp = SRC / name
    src = fp.read_text(encoding="utf-8", errors="replace")
    # dump any function that mentions credible/fabricated/coverage/reportable
    funcs = re.findall(r"(def [^\n]*\n(?:(?:    .*|\t.*|\s*\n))+)", src)
    picked = [f for f in funcs if re.search(r"credible|fabricated|coverage|reportable|dxf.*ratio|INSUFFICIENT", f, re.I)]
    if picked:
        OUT.write(f"\n########## {name} — gate function(s) ##########\n")
        for f in picked:
            OUT.write(f + "\n" + ("-"*60) + "\n")
        w(f"  dumped {len(picked)} function(s) from {name}")

OUT.close()
print("\n[done] gate code dumped to C:\\ClaudeVision\\src\\credibility_gate_dump.txt")
