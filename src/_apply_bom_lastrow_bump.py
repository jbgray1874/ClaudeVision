"""Bumps the BOM block's last_row in wb_populate.py from 25 to 31 to match the
widened template (Blank Estimate Sheet WB 2026.xlsx now has BOM rows 11-31 = 21 slots).

The template rows were added by JG; the engine's hardcoded last_row must agree or it
still stops at 15 and overflows. Exact string replace: matches and applies, or refuses.

Run from C:\ClaudeVision\src :
  C:\ClaudeVision\.venv\Scripts\python.exe _apply_bom_lastrow_bump.py
Then re-run 1282: expect NO overflow, all 17 BOM rows (incl. packaging/delivery), total sane.
"""
from pathlib import Path

TARGET = Path(r"C:\ClaudeVision\src\wb_populate.py")

# The BOM block dict. We only change last_row 25 -> 31. Match on the distinctive
# first_row/last_row pairing so we don't hit some other "25" in the file.
OLD = '"first_row": 11, "last_row": 25,'
NEW = '"first_row": 11, "last_row": 31,'  # widened template: BOM rows 11-31 (21 slots)

src = TARGET.read_text(encoding="utf-8")

if '"last_row": 31,' in src and '"first_row": 11,' in src:
    print("ALREADY APPLIED — BOM last_row already 31.")
    raise SystemExit(0)

if OLD not in src:
    print("NOT APPLIED — expected text not found. The BOM block dict differs.")
    print("Paste back:")
    print(r'  Select-String -Path C:\ClaudeVision\src\wb_populate.py -Pattern "first_row" -Context 0,2')
    raise SystemExit(1)

if src.count(OLD) > 1:
    print(f"NOT APPLIED — {src.count(OLD)} matches, expected 1. Refusing to guess.")
    raise SystemExit(1)

TARGET.write_text(src.replace(OLD, NEW), encoding="utf-8")
print("APPLIED — BOM block last_row 25 -> 31 (21 slots, matches widened template).")
print("Fingerprint: Select-String wb_populate.py -Pattern '\"last_row\": 31'")
print("Next: re-run 1282 — expect no overflow, all 17 BOM rows, packaging+delivery present.")
