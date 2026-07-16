# -*- coding: utf-8 -*-
"""FIX #6 part 2/2: wb_populate writes the acrylic/board SHEET PRICE into the WB 'Other Sheet'
block 'Cost per sheet' cell (col L=12), which is currently never written -> Cost Per Part = £0.

Two edits:
 (A) add "col_cost_per_sheet": 12 to the other_sheet block column map.
 (B) in the Other Sheet writer loop, after writing sheet L/W, write the sheet price into col L,
     sourced from the material result's sheet_price_gbp (added by part 1/2). Fallback: reconstruct
     from cost_per_part_gbp × parts_per_sheet ÷ (1+scrap) if sheet_price_gbp absent (older results).
     If neither available, leave blank + flag (honest £0, not a silent guess).

The WB formula M=(L/J)*(1+K)*D then computes the correct per-part acrylic cost (£46.20/60×1.04×2≈£1.60
ext for the RISER). SAFE: only fills a currently-blank input cell for board parts; steel/labour blocks
untouched; parts with no sheet price fall back to blank+flag (same as today, but now flagged).

BEFORE: Select-String -Path C:\ClaudeVision\src\wb_populate.py -Pattern "col_sheet_l" -Context 1,2
Run from C:\ClaudeVision\src :
  C:\ClaudeVision\.venv\Scripts\python.exe _apply_othersheet_cost_write.py
"""
from pathlib import Path
TARGET = Path(r"C:\ClaudeVision\src\wb_populate.py")
src = TARGET.read_text(encoding="utf-8")

# ---- Edit A: add col_cost_per_sheet to the block map ----
ANCHOR_A = '''        "col_desc": 3, "col_qty": 4, "col_length": 5, "col_width": 6, "col_thick": 7,
        "col_sheet_l": 8, "col_sheet_w": 9,
    },'''
REPLACEMENT_A = '''        "col_desc": 3, "col_qty": 4, "col_length": 5, "col_width": 6, "col_thick": 7,
        "col_sheet_l": 8, "col_sheet_w": 9, "col_cost_per_sheet": 12,
    },'''

# ---- Edit B: write the sheet price into col L in the writer loop ----
ANCHOR_B = '''        ws.cell(row=row, column=o["col_sheet_l"], value=_safe(sh[0]) if len(sh) > 0 else 2440)
        ws.cell(row=row, column=o["col_sheet_w"], value=_safe(sh[1]) if len(sh) > 1 else 1220)
        row += 1'''
REPLACEMENT_B = '''        ws.cell(row=row, column=o["col_sheet_l"], value=_safe(sh[0]) if len(sh) > 0 else 2440)
        ws.cell(row=row, column=o["col_sheet_w"], value=_safe(sh[1]) if len(sh) > 1 else 1220)
        # Cost per sheet (col L): the WB formula M=(L/J)*(1+K)*D needs this input, else Cost Per
        # Part = 0. Prefer the material result's raw pre-scrap sheet price; fall back to
        # reconstructing it from the per-part cost × parts-per-sheet ÷ (1+scrap). Board parts with
        # neither are left blank + flagged (honest £0, not a silent guess).
        _sheet_price = _safe(me.get("sheet_price_gbp"))
        if not _sheet_price:
            _cpp = _safe(me.get("cost_per_part_gbp") or me.get("unit_material_cost_gbp"))
            _pps = _safe(me.get("parts_per_sheet"))
            _scrap_frac = _safe(me.get("scrap_pct")) or 0.04
            if _cpp and _pps:
                _sheet_price = round(float(_cpp) * float(_pps) / (1.0 + float(_scrap_frac)), 2)
        if _sheet_price:
            ws.cell(row=row, column=o["col_cost_per_sheet"], value=_sheet_price)
        else:
            _flag(f"Other-sheet {pe.get('part_number')} has no sheet price — Cost Per Part will be 0.", flags)
        row += 1'''

for name, a, r in (("A", ANCHOR_A, REPLACEMENT_A), ("B", ANCHOR_B, REPLACEMENT_B)):
    if a not in src:
        print(f"REFUSED edit {name}: anchor not found. Paste the relevant wb_populate.py section so I can re-key.")
        raise SystemExit(1)
    if src.count(a) != 1:
        print(f"REFUSED edit {name}: anchor found {src.count(a)} times (need 1).")
        raise SystemExit(1)
    src = src.replace(a, r)

TARGET.write_text(src, encoding="utf-8")
print("APPLIED part 2/2: wb_populate writes sheet price into Other Sheet col L (Cost per sheet).")
print("Fingerprint: Select-String -Path C:\\ClaudeVision\\src\\wb_populate.py -Pattern \"col_cost_per_sheet\"")
