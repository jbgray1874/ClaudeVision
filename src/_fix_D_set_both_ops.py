"""Fixes Fix D so it updates BOTH part['operations'] AND part['textual_operations'].

ROOT CAUSE (confirmed): Fix D (mirroring Fix C) only set part['textual_operations'] and
called _interpret_part. But the displayed/costed op list is part['operations'] — a
SEPARATE field. _interpret_part does NOT write part['operations'] (it writes feature_rollup,
manufacturing_interpretation, etc.). So hole_machining is stripped from textual_operations
but SURVIVES in operations -> still shows the GUIL line on 1298.

FIX: mirror the WIRE-PART branch (line ~914-916), which correctly sets BOTH fields and does
NOT call _interpret_part:
    part["textual_operations"] = list(_ops)
    part["operations"] = sorted(_ops)

This applier finds our Fix D block by its distinctive strings and rewrites the mutation to
set both fields (and drop the _interpret_part call, which does nothing useful here and only
recomputes downstream metadata from the now-correct ops).

SAFE: exact-string match-or-refuse.

BEFORE APPLYING, dump the live Fix D block so we confirm the exact text to match:
  Select-String -Path C:\ClaudeVision\src\document_builder.py -Pattern "Fix D: METAL parts" -Context 0,14

Run from C:\ClaudeVision\src :
  C:\ClaudeVision\.venv\Scripts\python.exe _fix_D_set_both_ops.py
Then re-run 1298: Operations should be laser_cutting/folding/handling (NO hole_machining,
NO drilling), warning gone, GUIL line gone, total ~£3.08. Re-run 1282: expect unchanged.
"""
from pathlib import Path

TARGET = Path(r"C:\ClaudeVision\src\document_builder.py")

# The mutation tail our Fix D applier wrote (from _apply_metal_holeop_strip_docbuilder.py):
OLD = '''            _kept_m = [op for op in (part.get("textual_operations") or []) if op not in _metal_hole_ops]
            if _kept_m != part.get("textual_operations", []):
                part["textual_operations"] = _kept_m
                _interpret_part(part)'''

NEW = '''            _kept_m = [op for op in (part.get("textual_operations") or []) if op not in _metal_hole_ops]
            _kept_ops = [op for op in (part.get("operations") or []) if op not in _metal_hole_ops]
            if _kept_m != (part.get("textual_operations") or []) or _kept_ops != (part.get("operations") or []):
                # Set BOTH fields (mirror the wire-part branch). part["operations"] is what
                # the sheet/costing reads; textual_operations alone is insufficient. Do NOT
                # call _interpret_part — it does not rewrite part["operations"].
                part["textual_operations"] = _kept_m
                part["operations"] = sorted(_kept_ops)'''

src = TARGET.read_text(encoding="utf-8")

if 'part["operations"] = sorted(_kept_ops)' in src:
    print("ALREADY APPLIED — Fix D already sets both fields.")
    raise SystemExit(0)

if OLD not in src:
    print("NOT APPLIED — the Fix D mutation tail was not found verbatim.")
    print("Dump the live Fix D block and paste back so I can re-target:")
    print(r'  Select-String -Path C:\ClaudeVision\src\document_builder.py -Pattern "_metal_hole_ops" -Context 0,6')
    raise SystemExit(1)

if src.count(OLD) > 1:
    print(f"NOT APPLIED — {src.count(OLD)} matches, expected 1. Refusing to guess.")
    raise SystemExit(1)

TARGET.write_text(src.replace(OLD, NEW), encoding="utf-8")
print("APPLIED — Fix D now strips hole_machining/drilling from BOTH operations and")
print("textual_operations (mirrors the wire-part branch). No _interpret_part call.")
print("Fingerprint: Select-String document_builder.py -Pattern 'part\\[.operations.\\] = sorted\\(_kept_ops\\)'")
print("Next: re-run 1298 (expect NO hole_machining/drilling, GUIL line gone, total ~£3.08)")
print("AND 1282 (expect unchanged ~£204).")
