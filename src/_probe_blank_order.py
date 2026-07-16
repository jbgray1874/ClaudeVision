# -*- coding: utf-8 -*-
"""READ-ONLY. Verify the ORDER: does DXF augmentation (sets overall_length_mm) run BEFORE or AFTER
the document_builder non-metal blank fallback (document_builder.py ~968)? The fix (prefer part's own
overall dims) only works if overall_* is populated BEFORE the fallback runs. If DXF runs after, the
fallback sees empty overall_* and the guard won't help.

Traces the call order in main.py / drawing_job_merge.py: when is build_document_summary (or whatever
runs the ~968 block) called relative to augment_summary_with_dxf?

Run from C:\\ClaudeVision\\src :
  C:\\ClaudeVision\\.venv\\Scripts\\python.exe _probe_blank_order.py
"""
from pathlib import Path
import re

mb = Path(r"C:\ClaudeVision\src\main.py").read_text(encoding="utf-8", errors="ignore").splitlines()
print("=== main.py call order: document build vs dxf augment ===")
for i, ln in enumerate(mb, 1):
    if re.search(r"augment_summary_with_dxf|augment.*dxf|build_document|document_summary|_interpret_part|finalize.*part|normalise|estimate_bay|process_job", ln, re.I):
        print(f"  {i}: {ln.strip()[:110]}")

print("\n=== which function contains the ~968 non-metal blank block? ===")
db = Path(r"C:\ClaudeVision\src\document_builder.py").read_text(encoding="utf-8", errors="ignore").splitlines()
# find nearest def above 968
for i in range(967, 0, -1):
    if db[i].startswith("def "):
        print(f"  block at ~968 is inside: {db[i].strip()}  (line {i+1})")
        break

print("\n=== is that function called from drawing_job_merge (before/after augment)? ===")
djm = Path(r"C:\ClaudeVision\src\drawing_job_merge.py").read_text(encoding="utf-8", errors="ignore").splitlines()
for i, ln in enumerate(djm, 1):
    if re.search(r"_interpret_part|build_document|augment_summary_with_dxf|_rollup_geometry", ln):
        print(f"  djm {i}: {ln.strip()[:110]}")

print("\n=== does drawing_job_merge set overall_length_mm (line 188-189 we saw earlier)? ===")
for i, ln in enumerate(djm, 1):
    if "overall_length_mm" in ln or "overall_width_mm" in ln:
        print(f"  djm {i}: {ln.strip()[:110]}")

print("\nVERDICT: if augment_summary_with_dxf (which sets overall_* at djm 188-189) runs BEFORE the")
print("function containing the ~968 block, the fix works (overall_* present). If the ~968 block runs")
print("first (e.g. during initial document build, before DXF), overall_* is empty there and the fix")
print("needs to move later OR read from a different already-populated field.")
