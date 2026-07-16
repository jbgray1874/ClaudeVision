#!/usr/bin/env python3
"""
patch_materials.py
Run from C:\\ClaudeVision\\src:
    python patch_materials.py

Adds PETG / HIPS / polystyrene awareness to the material classifier.
Backs up both files before touching them (.py.bak).
"""
import pathlib, shutil, sys

src = pathlib.Path(__file__).parent

# ── Patch 1: drawing_job_merge.py — add tokens to _DXF_MATERIAL_TOKENS ───
f1 = src / "drawing_job_merge.py"
if not f1.exists():
    sys.exit(f"ERROR: {f1} not found.\nRun this script from C:\\ClaudeVision\\src")

text1 = f1.read_text(encoding="utf-8-sig").replace("\r\n", "\n")

ANCHOR1 = '    (r"POLYCARB|\\bPC\\b", "POLYCARBONATE"),'
INSERT1 = (
    "    # PETG / HIPS / polystyrene — sheet plastics, same cutting workflow as acrylic\n"
    '    (r"\\bPETG\\b|\\bP\\.?E\\.?T\\.?G\\.?\\b", "ACRYLIC"),\n'
    '    (r"\\bHIPS\\b|HIGH\\s*IMPACT\\s*POLY|HI\\s*POLY", "ACRYLIC"),\n'
    '    (r"POLYSTYRENE|STYRENE", "ACRYLIC"),\n'
)

if ANCHOR1 not in text1:
    print("drawing_job_merge.py: already patched or anchor line changed — skipping.")
else:
    shutil.copy(f1, f1.with_suffix(".py.bak"))
    f1.write_text(text1.replace(ANCHOR1, INSERT1 + ANCHOR1, 1), encoding="utf-8")
    print("drawing_job_merge.py: PATCHED  (backup: drawing_job_merge.py.bak)")

# ── Patch 2: json_normaliser.py — expand _is_acrylic raw-material check ──
f2 = src / "json_normaliser.py"
if not f2.exists():
    sys.exit(f"ERROR: {f2} not found.")

text2 = f2.read_text(encoding="utf-8-sig").replace("\r\n", "\n")

ANCHOR2 = (
    '        any(k in _raw_mat_upper for k in ("ACRYLIC", "PERSPEX", "PMMA", "POLYCARBONATE"))'
)
NEW2 = (
    "        any(k in _raw_mat_upper for k in (\n"
    '            "ACRYLIC", "PERSPEX", "PMMA", "POLYCARBONATE",\n'
    '            "PETG", "HIPS", "POLYSTYRENE", "STYRENE",\n'
    "        ))"
)

ANCHOR2B = '        or any(k in _desc_upper for k in ("LENS", "ACRYLIC", "PERSPEX"))'
NEW2B    = '        or any(k in _desc_upper for k in ("LENS", "ACRYLIC", "PERSPEX", "PETG", "HIPS"))'

patched2 = False
if ANCHOR2 not in text2:
    print("json_normaliser.py: _raw_mat_upper anchor not found — already patched or changed.")
else:
    text2 = text2.replace(ANCHOR2, NEW2, 1)
    patched2 = True

if ANCHOR2B not in text2:
    print("json_normaliser.py: _desc_upper anchor not found — already patched or changed.")
else:
    text2 = text2.replace(ANCHOR2B, NEW2B, 1)
    patched2 = True

if patched2:
    shutil.copy(f2, f2.with_suffix(".py.bak"))
    f2.write_text(text2, encoding="utf-8")
    print("json_normaliser.py:   PATCHED  (backup: json_normaliser.py.bak)")

print("\nAll done. Now run:")
print('  python main.py --search-root "K:\\Estimating\\Completed\\AI Estimating\\Live Enquiry\\FOTM Belly Basket" --folder-as-job')
