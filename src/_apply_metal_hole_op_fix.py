"""Suppresses the spurious 'hole_machining' op for METAL (sheet-steel) parts.

WHY: On metal, holes are laser-cut (they fold into the laser profile) — there is NO
separate hole/drill op. This matches shop practice, Tim's sheets (which have no metal
hole op, only 'Drill (Acrylic)'), and job 1282 (all metal parts, no hole ops). But the
extractor currently emits 'hole_machining' whenever the drawing mentions HOLE/DRILL/PUNCH,
regardless of material — so 1298 (MILD STEEL Drill Holder) gets a bogus hole_machining line
that falls through to Guillotine (~£0.29). This scopes the emission to NON-metal parts only.

The function already computes `is_sheet_steel` in scope, so the fix is a one-line guard.

SAFE: exact-string match-or-refuse. If the live src differs from this pattern, it refuses
and prints what to check — it will NOT blind-edit.

BEFORE APPLYING, confirm live src matches:
  Select-String -Path C:\ClaudeVision\src\extractor_patterns.py -Pattern "operations.append\(.hole_machining.\)" -Context 2,0

Run from C:\ClaudeVision\src :
  C:\ClaudeVision\.venv\Scripts\python.exe _apply_metal_hole_op_fix.py

AFTER: re-run 1282 (expect BYTE-IDENTICAL — all metal, already no hole ops) and 1298
(expect the hole_machining/GUIL line GONE). Also check 1298 has no stray 'drilling' line;
if it does, 'drilling' is emitted elsewhere and needs the same guard (flag for follow-up).
"""
from pathlib import Path

TARGET = Path(r"C:\ClaudeVision\src\extractor_patterns.py")

# Match the exact 2-line emission. Keep whitespace as in the snapshot; if the live
# file differs (indent, comment), the applier refuses rather than guessing.
OLD = '''    if hole_cue:
        operations.append("hole_machining")'''

NEW = '''    # Metal holes are laser-cut (fold into the laser profile) — no separate op, matching
    # shop practice and Tim's sheets (metal has no hole op; only "Drill (Acrylic)" exists).
    # Only acrylic/plastic parts (not is_sheet_steel) get a genuine separate drilling op.
    if hole_cue and not is_sheet_steel:
        operations.append("hole_machining")'''

src = TARGET.read_text(encoding="utf-8")

if 'if hole_cue and not is_sheet_steel:' in src:
    print("ALREADY APPLIED — metal hole-op guard already present.")
    raise SystemExit(0)

if OLD not in src:
    print("NOT APPLIED — exact 'if hole_cue:' emission block not found in live src.")
    print("The live extractor_patterns.py differs from the snapshot. Dump it and check:")
    print(r'  Select-String -Path C:\ClaudeVision\src\extractor_patterns.py -Pattern "hole_cue" -Context 1,2')
    print("Paste that back and I will re-target the fix to the live code.")
    raise SystemExit(1)

if src.count(OLD) > 1:
    print(f"NOT APPLIED — {src.count(OLD)} matches, expected 1. Refusing to guess.")
    raise SystemExit(1)

# Confirm is_sheet_steel is defined before this point (safety: the guard needs it in scope)
if "is_sheet_steel" not in src.split(OLD)[0]:
    print("NOT APPLIED — 'is_sheet_steel' not found before the emission point.")
    print("The variable may be named differently in live src. Dump and check before editing.")
    raise SystemExit(1)

TARGET.write_text(src.replace(OLD, NEW), encoding="utf-8")
print("APPLIED — hole_machining now emitted only for NON-metal parts (acrylic/plastic).")
print("Fingerprint: Select-String extractor_patterns.py -Pattern 'hole_cue and not is_sheet_steel'")
print("Next: re-run 1282 (expect byte-identical) AND 1298 (expect hole_machining/GUIL line GONE).")
print("Also check: does fixed 1298 still show a 'drilling' line? If so, 'drilling' is emitted")
print("elsewhere and needs the same material guard — flag for follow-up.")
