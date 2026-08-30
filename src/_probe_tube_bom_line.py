# -*- coding: utf-8 -*-
"""READ-ONLY. Re-key the tube identity fix precisely. wb_populate.py ~368-372 builds the tube BOM
line's description+code from catalogue_description/catalogue_part_code (the FOREIGN 11406 identity),
falling back to the part's own only if absent. We want the OPPOSITE precedence: prefer THIS part's
own number+description, use catalogue for PRICE only. Dump the exact lines so the applier matches.

Run from C:\\ClaudeVision\\src :
  C:\\ClaudeVision\\.venv\\Scripts\\python.exe _probe_tube_bom_line.py
"""
from pathlib import Path
p = Path(r"C:\ClaudeVision\src\wb_populate.py")
lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
print("=== wb_populate.py lines 355-395 (BOM/tube line build) ===")
for i in range(354, min(395, len(lines))):
    print(f"  {i+1}: {lines[i]}")
