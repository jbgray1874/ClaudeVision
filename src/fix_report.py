"""fix_report.py — run once from C:\\ClaudeVision\\src to repair job_analysis_report.py"""
import re, shutil, pathlib

f = pathlib.Path("job_analysis_report.py")
if not f.exists():
    print("ERROR: job_analysis_report.py not found — run from C:\\ClaudeVision\\src")
    raise SystemExit(1)

shutil.copy(f, f.with_suffix(".py.bak"))
src = f.read_text(encoding="utf-8")

# Remove every broken variant that previous patch attempts may have introduced
bad_patterns = [
    r'"parts": parts,`n\s+"parts": parts,',
    r'"parts": parts,\\n\s+"fab_parts"',
]
for pat in bad_patterns:
    src = re.sub(pat, '"fab_parts"', src)

# Now do the clean single insertion
old = '"fab_parts": fab_parts,'
new = '"parts": parts,\n        "fab_parts": fab_parts,'
if old not in src:
    print("ERROR: anchor not found — file may need to be re-downloaded from Claude")
    raise SystemExit(1)

src = src.replace(old, new, 1)
f.write_text(src, encoding="utf-8")

# Verify it parses
import ast
try:
    ast.parse(src)
    print("job_analysis_report.py: fixed and syntax OK")
except SyntaxError as e:
    print(f"SyntaxError at line {e.lineno}: {e.msg}")
    print("Restoring backup...")
    shutil.copy(f.with_suffix(".py.bak"), f)
