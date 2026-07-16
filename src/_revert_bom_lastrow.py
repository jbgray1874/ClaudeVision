"""Reverts the BOM block last_row in wb_populate.py from 31 back to 25.

The template has been restored to its original layout: BOM ends ~row 25,
'Wire' heading at row 26, Wire data entry from row 28. wb_populate must stop
writing BOM at row 25 so it does NOT write into the Wire section (rows 26+).

This should stop the 'MergedCell read-only' crash: the engine no longer touches
rows 26-31 (which belong to the Wire block / its merges).

Exact string replace: matches and applies, or refuses.

Run from C:\ClaudeVision\src :
  C:\ClaudeVision\.venv\Scripts\python.exe _revert_bom_lastrow.py
Then re-run 1282: expect '[wb_populate] Populated template saved' (NO 'failed MergedCell').
Note: BOM back to 15 slots -> 1282's packaging/delivery will overflow again, but the
sheet will be CORRECT (not the malformed fallback). Proper widen is a next-session task.
"""
from pathlib import Path

TARGET = Path(r"C:\ClaudeVision\src\wb_populate.py")

OLD = '"first_row": 11, "last_row": 31,'
NEW = '"first_row": 11, "last_row": 25,'  # reverted: template BOM back to 15 rows (11-25)

src = TARGET.read_text(encoding="utf-8")

if '"first_row": 11, "last_row": 25,' in src:
    print("ALREADY REVERTED — BOM last_row already 25.")
    raise SystemExit(0)

if OLD not in src:
    print("NOT APPLIED — expected '\"first_row\": 11, \"last_row\": 31,' not found.")
    print("Check current value:")
    print(r'  Select-String -Path C:\ClaudeVision\src\wb_populate.py -Pattern "first_row.*11"')
    raise SystemExit(1)

if src.count(OLD) > 1:
    print(f"NOT APPLIED — {src.count(OLD)} matches, expected 1. Refusing to guess.")
    raise SystemExit(1)

TARGET.write_text(src.replace(OLD, NEW), encoding="utf-8")
print("REVERTED — BOM block last_row 31 -> 25 (back to 15 slots, matches restored template).")
print("Fingerprint: Select-String wb_populate.py -Pattern '\"first_row\": 11, \"last_row\": 25'")
print("Next: re-run 1282 — expect 'Populated template saved' (NO 'failed MergedCell').")
