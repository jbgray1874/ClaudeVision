# -*- coding: utf-8 -*-
"""READ-ONLY. Dump the exact Other Sheet writer block (wb_populate.py ~448-492) so we see which
field the 'Cost per sheet' cell is written from (or whether it's left blank / formula-only).
Run from C:\\ClaudeVision\\src :
  C:\\ClaudeVision\\.venv\\Scripts\\python.exe _probe_othersheet2.py
"""
from pathlib import Path
WB = Path(r"C:\ClaudeVision\src\wb_populate.py")
lines = WB.read_text(encoding="utf-8", errors="replace").splitlines()
print("=== wb_populate.py lines 440-500 (Other Sheet writer) ===")
for i in range(439, min(500, len(lines))):
    print(f"  {i+1}: {lines[i]}")
