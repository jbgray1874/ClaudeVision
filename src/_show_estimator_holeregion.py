"""READ-ONLY. Shows the live estimator's op-handling region so we can see the ACTUAL
order of: (1) ops = _part_ops(part), (2) our _metal_hole_ops strip, (3) the hole_machining
costing `if "hole_machining" in ops`. If the strip is AFTER the costing, it runs too late —
that's the bug. Prints line numbers so we can place a corrected strip BEFORE the costing.

Run from C:\ClaudeVision\src :
  C:\ClaudeVision\.venv\Scripts\python.exe _show_estimator_holeregion.py
"""
from pathlib import Path
src = Path(r"C:\ClaudeVision\src\estimator.py").read_text(encoding="utf-8").splitlines()

def find_all(needle):
    return [(i+1, l) for i, l in enumerate(src) if needle in l]

print("=== KEY LANDMARKS (live line numbers) ===\n")
for label, needle in [
    ("ops = _part_ops(part)",        "ops = _part_ops(part)"),
    ("_has_cut_op anchor",           "_has_cut_op = any"),
    ("OUR STRIP (_metal_hole_ops)",  "_metal_hole_ops = "),
    ("hole_machining COSTING",       'if "hole_machining" in ops'),
]:
    hits = find_all(needle)
    if hits:
        for ln, txt in hits:
            print(f"  L{ln:5}  [{label}]  {txt.strip()[:70]}")
    else:
        print(f"  -----  [{label}]  NOT FOUND")

# Decide ordering
def first_line(needle):
    for i, l in enumerate(src):
        if needle in l:
            return i+1
    return None

strip_ln = first_line("_metal_hole_ops = ")
cost_ln  = first_line('if "hole_machining" in ops')
print("\n=== VERDICT ===")
if strip_ln and cost_ln:
    if strip_ln < cost_ln:
        print(f"  Strip (L{strip_ln}) is BEFORE costing (L{cost_ln}) — ordering is correct.")
        print("  If hole_machining STILL costs, the strip's material condition isn't matching")
        print("  this part (check _mat_u). Print _mat_u for 1298-01 next.")
    else:
        print(f"  Strip (L{strip_ln}) is AFTER costing (L{cost_ln}) — STRIP RUNS TOO LATE.")
        print("  The op is costed before we remove it. Fix: move the strip to just after")
        print("  `ops = _part_ops(part)` / the _has_cut_op anchor, BEFORE the costing.")
else:
    print("  Could not locate both markers — dump the region manually.")

# Show the actual strip block for confirmation
if strip_ln:
    print(f"\n=== strip block as it appears live (L{strip_ln-1}..{strip_ln+10}) ===")
    for ln in range(max(1,strip_ln-2), min(len(src), strip_ln+10)):
        print(f"  {ln+1:5}  {src[ln]}")
