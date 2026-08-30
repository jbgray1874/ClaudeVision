# -*- coding: utf-8 -*-
"""READ-ONLY. We're making steel (and other-block) overflow LOUD on the sheet instead of silently
dropping parts. Read the live wb_populate.py overflow sites (steel ~400, BOM ~360, other ~423,
labour ~514) to see exactly how the loop stops at last_row and how _flag works, so the on-sheet
marker is written correctly (right cell, right sheet, doesn't collide with the next block header).

Run from C:\\ClaudeVision\\src :
  C:\\ClaudeVision\\.venv\\Scripts\\python.exe _probe_overflow_site.py
"""
from pathlib import Path
p = Path(r"C:\ClaudeVision\src\wb_populate.py")
lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()

def show(a, b, tag):
    print(f"\n=== {tag}: lines {a}-{b} ===")
    for i in range(a-1, min(b, len(lines))):
        print(f"  {i+1}: {lines[i]}")

# steel overflow region
show(395, 420, "STEEL write loop + overflow")
# how _flag is defined
print("\n=== _flag definition ===")
for i, l in enumerate(lines):
    if "def _flag" in l:
        show(i+1, i+12, "_flag def"); break
# how a cell is written (helper) — find the write helper used in the steel loop
print("\n=== cell-write helper (how values land in the sheet) ===")
for i, l in enumerate(lines):
    if ("def _set" in l or "def _write" in l or "def _put" in l or ".value =" in l) and i < 360:
        print(f"  {i+1}: {l.strip()[:100]}")
