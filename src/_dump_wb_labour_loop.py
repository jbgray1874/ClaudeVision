"""READ-ONLY. Dumps wb_populate.py's labour-row loop (~488-530) so we can see the exact
variables in scope (op, wb_op, pe, desc, and any material/thickness/geometry accessors) and
the exact text of the desc-write line, to build a correct applier.

Run from C:\\ClaudeVision\\src :
  C:\\ClaudeVision\\.venv\\Scripts\\python.exe _dump_wb_labour_loop.py
"""
from pathlib import Path
lines = Path(r"C:\ClaudeVision\src\wb_populate.py").read_text(encoding="utf-8").splitlines()
start, end = 486, 530
print(f"=== wb_populate.py lines {start}..{end} ===")
for i in range(start-1, min(end, len(lines))):
    print(f"{i+1:4}  {lines[i]}")

# Also show what 'desc' is set to just before the write (search upward from 523)
print("\n=== where is 'desc' assigned in the labour loop? ===")
for i in range(440, 525):
    if i < len(lines) and ("desc =" in lines[i] or "desc=" in lines[i]):
        print(f"{i+1:4}  {lines[i].strip()}")

# Show what material/thickness/geometry fields the part 'pe' exposes (as used elsewhere in file)
print("\n=== material/thickness/geometry accessors used in wb_populate.py ===")
import re
for i, l in enumerate(lines):
    if re.search(r'normalized_material|normalized_thickness|normalized_geometry|material_estimate|estimated_bend|estimated_hole|thickness_mm', l):
        print(f"{i+1:4}  {l.strip()[:100]}")
