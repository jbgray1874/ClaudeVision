# -*- coding: utf-8 -*-
"""FIX: make Sheet-Steel overflow LOUD on the sheet instead of silently dropping parts.

Context (PROVEN): the steel block is 11 fixed rows (38-48) wired 1:1 into hidden laser/CNC rate
calculators (Q=LOOKUP Estimate!$Y$38:$Y$46, AD49=SUM(AD38:AD48), M59=SUM(...M38:M48...)) with
per-row merged cells (C38:D38 ...). Inserting rows breaks all of this — a prior widen was reverted
for 'failed MergedCell'. So we CANNOT widen; we make overflow VISIBLE.

Current behaviour (wb_populate.py steel loop): on overflow it logs a console-only flag and `break`s,
so extra steel parts are SILENTLY absent from the xlsx the estimator opens. This fix: before
breaking, overwrite the LAST steel row's description cell with a loud marker naming the count and
the dropped part numbers, so the estimator sees the BOM is incomplete. No rows inserted, no formulas
or merges touched — writes into an existing block cell only.

SAFE: exact-string match-or-refuse on the overflow break block. Regression: jobs with <=11 steel
parts never hit this path (1282 has 10) — unchanged.

BEFORE APPLYING, confirm anchor:
  Select-String -Path C:\ClaudeVision\src\wb_populate.py -Pattern "Steel overflow:" -Context 3,2

Run from C:\ClaudeVision\src :
  C:\ClaudeVision\.venv\Scripts\python.exe _apply_loud_steel_overflow.py

AFTER: re-run Recipe Card (14 steel parts). The last steel row (48) should show a loud
'+N STEEL PARTS NOT SHOWN: <pns>' marker; console flag still prints. 1282 unaffected.
"""
from pathlib import Path

TARGET = Path(r"C:\ClaudeVision\src\wb_populate.py")

ANCHOR = '''    row = s["first_row"]
    for pe in steel_parts:
        if row > s["last_row"]:
            _flag(f"Steel overflow: {len(steel_parts)} steel parts but only "
                  f"{s['last_row']-s['first_row']+1} rows — extras DROPPED. Widen block.", flags)
            break'''

REPLACEMENT = '''    row = s["first_row"]
    for _si, pe in enumerate(steel_parts):
        if row > s["last_row"]:
            # Cannot widen: the steel rows are wired 1:1 into hidden laser/CNC rate calculators
            # with row-locked absolute refs + per-row merged cells (a prior widen was reverted for
            # 'failed MergedCell'). So make the overflow LOUD ON THE SHEET instead of silently
            # dropping parts: overwrite the last steel row's description with a marker naming the
            # count and the dropped part numbers, so the estimator sees the BOM is incomplete.
            _dropped_pns = [str(x.get("part_number") or x.get("description") or "?")
                            for x in steel_parts[_si:]]
            _n = len(_dropped_pns)
            ws.cell(row=s["last_row"], column=s["col_desc"],
                    value=f"\u26a0 +{_n} STEEL PART(S) NOT SHOWN (block full): "
                          f"{', '.join(_dropped_pns)} \u2014 see Decision Report")
            _flag(f"Steel overflow: {len(steel_parts)} steel parts but only "
                  f"{s['last_row']-s['first_row']+1} rows — {_n} shown on sheet as LOUD marker "
                  f"in last row (not silently dropped): {', '.join(_dropped_pns)}", flags)
            break'''

src = TARGET.read_text(encoding="utf-8")
if ANCHOR not in src:
    print("REFUSED: anchor not found exactly. Paste the steel loop (wb_populate.py ~line 400) so I can re-key.")
    raise SystemExit(1)
if src.count(ANCHOR) != 1:
    print(f"REFUSED: anchor found {src.count(ANCHOR)} times (need 1).")
    raise SystemExit(1)
src = src.replace(ANCHOR, REPLACEMENT)
TARGET.write_text(src, encoding="utf-8")
print("APPLIED: steel overflow now writes a LOUD on-sheet marker naming dropped parts (no silent drop).")
print("Fingerprint:")
print('  Select-String -Path C:\\ClaudeVision\\src\\wb_populate.py -Pattern "STEEL PART.S. NOT SHOWN"')
