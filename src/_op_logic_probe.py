"""
READ-ONLY probe. Dumps the operation-derivation / correction logic from the REAL
estimator.py on this machine, so we can extend it correctly (the /mnt/project snapshot
is stale). Prints the relevant regions with line numbers. Edits nothing.

Run:
  C:\ClaudeVision\.venv\Scripts\python.exe _op_logic_probe.py
"""
import re
from pathlib import Path

SRC = Path(r"C:\ClaudeVision\src\estimator.py")
text = SRC.read_text(encoding="utf-8", errors="replace")
lines = text.splitlines()
n = len(lines)
print(f"estimator.py: {n} lines\n")

def show(lo, hi, title):
    lo = max(1, lo); hi = min(n, hi)
    print("=" * 78)
    print(f"  {title}   (lines {lo}-{hi})")
    print("=" * 78)
    for i in range(lo, hi + 1):
        print(f"{i:5} | {lines[i-1]}")
    print()

# 1. Find the key anchors by content, then show a window around each.
anchors = {
    "tube op-correction (laser/saw strip)": r"bought as a length and never lasered|inferred_operations.*laser_cutting|for o in .*laser_cutting.*saw",
    "laser->punch conversion": r'\+ \["punch"\]|"punch" not in part\[',
    "_part_ops helper": r"def _part_ops",
    "textual/inferred merge": r"textual_operations.*inferred_operations|inferred_operations.*textual_operations",
    "powder_coating gating": r'"powder_coating" not in _part_ops|powder_coating.*not in',
    "operations assembly into labour": r"costs_gbp|labour_estimate.*costs|batch_hours",
    "_resolve_labour_rate": r"def _resolve_labour_rate",
    "cutting ops set": r"_CUTTING_OPS\s*=",
    "fold / bend detection": r"fold|bend.?line|BENDLINE|inferred.*fold",
}

seen_ranges = []
for title, pat in anchors.items():
    rx = re.compile(pat, re.IGNORECASE)
    hits = [i for i, ln in enumerate(lines, 1) if rx.search(ln)]
    if not hits:
        print(f"[no match] {title}  (pattern: {pat})\n")
        continue
    # show a window around the FIRST hit for each anchor
    first = hits[0]
    show(first - 8, first + 22, f"{title}  [{len(hits)} hit(s), first @ {first}]")

# 2. Also list every line that mentions fold/bend so we see where fold ops come from
print("=" * 78)
print("  ALL lines mentioning fold / bend (where does 'folding' get added?)")
print("=" * 78)
for i, ln in enumerate(lines, 1):
    if re.search(r"fold|bend", ln, re.IGNORECASE):
        print(f"{i:5} | {ln.strip()[:110]}")
