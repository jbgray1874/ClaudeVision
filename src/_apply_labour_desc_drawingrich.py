# -*- coding: utf-8 -*-
"""Richer, DRAWING-DERIVED labour-row descriptions. Each row shows the engine's own
extracted data (material, thickness, and op-relevant geometry like bend/hole counts) so the
sheet visibly demonstrates drawing-reading work, NOT a copy of Tim's shorthand.

BEFORE: every labour row Part Description = "DRILL HOLDER".
AFTER (examples, all from the drawing):
  Laser (Metal) - Drill Holder, 1.2mm MILD STEEL
  Fold - Drill Holder, 1.2mm MILD STEEL (4 bends)
  Assemble/pack - Drill Holder, 1.2mm MILD STEEL
(the separator rendered on the sheet is a real em-dash)

Every element is drawing-derived and already on the part estimate:
  - operation  -> inferred from geometry (cut paths -> laser, bend lines -> fold)
  - part name  -> read from title block / BOM (pe['description'])
  - thickness  -> pe['normalized_thickness_mm'] / material_estimate.thickness_mm
  - material   -> pe['normalized_material']
  - bend count -> normalized_geometry.estimated_bend_line_count (fold only)
  - hole count -> normalized_geometry.estimated_hole_count (drill/punch only)
Nothing from Tim, nothing invented. Cost columns UNCHANGED (cosmetic).

SAFE: exact-string match-or-refuse. Replaces only the labour-desc write line (live line 655).

Run from C:\\ClaudeVision\\src :
  C:\\ClaudeVision\\.venv\\Scripts\\python.exe _apply_labour_desc_drawingrich.py
Then re-run 1298 + 1282 (costs/totals UNCHANGED; descriptions richer & drawing-derived).
"""
from pathlib import Path

EMDASH = "\u2014"  # real em-dash, built at runtime (no escape in source lines below)

TARGET = Path(r"C:\ClaudeVision\src\xlsx_output.py")

OLD = '            _set(ws, ROW, 2, desc,           fill=bg, size=9)'

NEW = '''            # DRAWING-DERIVED row description: operation + part + material/thickness the
            # engine extracted, plus op-relevant geometry (bend/hole counts). Shows the
            # engine's own drawing-reading. All fields already on the part estimate.
            _op_verb = {
                "laser_cutting": "Laser (Metal)", "folding": "Fold", "welding": "Weld (CO2)",
                "spot_welding": "Spotweld", "resistance_welding": "Spotweld",
                "dress_welds": "Dress Welds", "powder_coating": "P.Coat",
                "wet_spray": "Wet Spray", "diamond_polish": "Diamond Polish",
                "cnc_routing": "CNC", "cnc": "CNC", "assembly": "Assemble/pack",
                "handling": "Assemble/pack", "packing": "Assemble/pack",
                "hole_machining": "Drill", "tapping": "Tap", "guillotine": "Guillotine",
                "punch": "Punch", "roll": "Roll", "linebend": "Linebend",
                "tube_bending": "Tubebend", "saw": "Saw", "deburring": "Deburr",
            }.get(str(op).lower(), _op_name(op))
            _me   = pe.get("material_estimate") or {}
            _ng   = pe.get("normalized_geometry") or {}
            _matx = str(pe.get("normalized_material") or "").replace("_", " ").strip()
            _thk  = _safe(pe.get("normalized_thickness_mm") or _me.get("thickness_mm"))
            _spec = []
            if _thk:
                _spec.append(("%g" % _thk) + "mm")
            if _matx:
                _spec.append(_matx)
            _detail = ""
            _ol = str(op).lower()
            if _ol == "folding":
                _bn = int(_safe(_ng.get("estimated_bend_line_count")))
                if _bn:
                    _detail = " (%d bend%s)" % (_bn, "" if _bn == 1 else "s")
            elif _ol in ("hole_machining", "drilling", "punch"):
                _hn = int(_safe(_ng.get("estimated_hole_count")))
                if _hn:
                    _detail = " (%d hole%s)" % (_hn, "" if _hn == 1 else "s")
            _base = str(desc).strip().title() if desc else ""
            _row_desc = str(_op_verb)
            if _base:
                _row_desc += " " + "\\u2014" + " " + _base
            if _spec:
                _row_desc += ", " + " ".join(_spec)
            _row_desc += _detail
            _set(ws, ROW, 2, _row_desc,      fill=bg, size=9)'''

src = TARGET.read_text(encoding="utf-8")

if "DRAWING-DERIVED row description" in src:
    print("ALREADY APPLIED - drawing-rich labour descriptions already present.")
    raise SystemExit(0)

if OLD not in src:
    print("NOT APPLIED - the labour-desc write line was not found verbatim.")
    print(r'  Select-String -Path C:\ClaudeVision\src\xlsx_output.py -Pattern "ROW, 2, desc" -Context 1,1')
    raise SystemExit(1)

if src.count(OLD) > 1:
    print("NOT APPLIED - line appears %d times, expected 1. Refusing to guess." % src.count(OLD))
    raise SystemExit(1)

# The injected code contains the token \\u2014 as a Python escape inside the target file,
# which the TARGET interprets at its runtime into a real em-dash. Write it literally.
new_code = NEW.replace('"\\\\u2014"', '"\\u2014"')
src2 = src.replace(OLD, new_code)
TARGET.write_text(src2, encoding="utf-8")
print("APPLIED - labour rows now drawing-derived, e.g.:")
print("  Laser (Metal) - Drill Holder, 1.2mm MILD STEEL")
print("  Fold - Drill Holder, 1.2mm MILD STEEL (4 bends)")
print("  (separator on the sheet is a real em-dash)")
print("Fingerprint: Select-String xlsx_output.py -Pattern 'DRAWING-DERIVED row description'")
print("Cosmetic only - costs/totals UNCHANGED. Re-run 1298 + 1282 to see them.")
