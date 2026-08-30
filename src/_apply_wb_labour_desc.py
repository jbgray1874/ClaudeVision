# -*- coding: utf-8 -*-
"""DRAWING-DERIVED labour-row descriptions in wb_populate.py (the REAL template writer).

The sheet you see is written by wb_populate.py, NOT xlsx_output.py. Line 523 writes bare
`desc` ("DRILL HOLDER") to the labour Part Description column. This replaces that with a
richer description built from the engine's OWN extracted data:

  Laser (Metal) - Drill Holder, 1.2mm MILD STEEL
  Fold - Drill Holder, 1.2mm MILD STEEL (4 bends)
  Assemble/pack (Metal) - Drill Holder, 1.2mm MILD STEEL
(separator on the sheet is a real em-dash)

Every element is drawing-derived and already on `pe` in this loop:
  - wb_op (the mapped operation)     -> already computed at line 517
  - part name (desc)                 -> line 501, from title block
  - thickness                        -> pe['normalized_thickness_mm'] / me.thickness_mm
  - material                         -> pe['normalized_material']
  - bend/hole counts                 -> pe['normalized_geometry']
Nothing from Tim, nothing invented. WB formulas read col_operation (unchanged) + qty +
throughput for costing; col_desc is descriptive only, so COSTS/TOTALS are UNCHANGED.

SAFE: exact-string match-or-refuse on the line-523 write.

BEFORE APPLYING, confirm the target line in live src:
  Select-String -Path C:\\ClaudeVision\\src\\wb_populate.py -Pattern 'col_desc..,      value=desc' -Context 0,1

Run from C:\\ClaudeVision\\src :
  C:\\ClaudeVision\\.venv\\Scripts\\python.exe _apply_wb_labour_desc.py
Then re-run 1298 + 1282 (descriptions richer & drawing-derived; costs/totals UNCHANGED).
"""
from pathlib import Path

TARGET = Path(r"C:\ClaudeVision\src\wb_populate.py")

OLD = '            ws.cell(row=row, column=lb["col_desc"],      value=desc)'

NEW = '''            # DRAWING-DERIVED description (engine's own extracted data): operation +
            # part + material/thickness + op-relevant geometry. Shows drawing-reading work.
            # col_operation (used by WB for costing) is unchanged; this col is descriptive.
            _me2   = pe.get("material_estimate") or {}
            _ng2   = pe.get("normalized_geometry") or {}
            _matx2 = str(pe.get("normalized_material") or "").replace("_", " ").strip()
            _thk2  = _safe(pe.get("normalized_thickness_mm") or _me2.get("thickness_mm"), 0)
            _spec2 = []
            if _thk2:
                _spec2.append(("%g" % _thk2) + "mm")
            if _matx2:
                _spec2.append(_matx2)
            _detail2 = ""
            _ol2 = str(op).lower()
            if _ol2 == "folding":
                _bn2 = int(_safe((_ng2 or {}).get("estimated_bend_line_count"), 0))
                if _bn2:
                    _detail2 = " (%d bend%s)" % (_bn2, "" if _bn2 == 1 else "s")
            elif _ol2 in ("hole_machining", "drilling", "punch"):
                _hn2 = int(_safe((_ng2 or {}).get("estimated_hole_count"), 0))
                if _hn2:
                    _detail2 = " (%d hole%s)" % (_hn2, "" if _hn2 == 1 else "s")
            _base2 = str(desc).strip().title() if desc else ""
            _row_desc2 = str(wb_op)
            if _base2:
                _row_desc2 += " " + "\\u2014" + " " + _base2
            if _spec2:
                _row_desc2 += ", " + " ".join(_spec2)
            _row_desc2 += _detail2
            ws.cell(row=row, column=lb["col_desc"],      value=_row_desc2)'''

src = TARGET.read_text(encoding="utf-8")

if "DRAWING-DERIVED description (engine's own extracted data)" in src:
    print("ALREADY APPLIED - wb_populate drawing-rich labour descriptions already present.")
    raise SystemExit(0)

if OLD not in src:
    print("NOT APPLIED - the line-523 desc write was not found verbatim.")
    print(r'  Select-String -Path C:\ClaudeVision\src\wb_populate.py -Pattern "col_desc" -Context 0,1')
    raise SystemExit(1)

if src.count(OLD) > 1:
    print("NOT APPLIED - line appears %d times, expected 1. Refusing to guess." % src.count(OLD))
    raise SystemExit(1)

# The token \\u2014 in the injected code becomes a Python escape in the target file,
# which the target interprets into a real em-dash at its runtime.
new_code = NEW.replace('"\\\\u2014"', '"\\u2014"')
TARGET.write_text(src.replace(OLD, new_code), encoding="utf-8")
print("APPLIED - wb_populate labour rows now drawing-derived, e.g.:")
print("  Laser (Metal) - Drill Holder, 1.2mm MILD STEEL")
print("  Fold - Drill Holder, 1.2mm MILD STEEL (4 bends)")
print("  (separator on the sheet is a real em-dash)")
print("Fingerprint: Select-String wb_populate.py -Pattern 'DRAWING-DERIVED description'")
print("Cosmetic only - costs/totals UNCHANGED. Re-run 1298 + 1282.")
