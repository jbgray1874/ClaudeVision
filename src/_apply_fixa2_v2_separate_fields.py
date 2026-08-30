# -*- coding: utf-8 -*-
"""FIX A2 v2: the first Fix A2 concatenated region_text.bom + notes + general and ran
extract_bom_rows on the JOINED string. PROVEN problem (via _probe_bom_field_content.py):
region_text.bom holds MANGLED text ('Y T O T O R P R O 3 5.3 FRONT F REAR...') while
region_text.notes holds the CLEAN BOM ('ITEM DWG NO. DESCRIPTION QTY 1 12532-02-03M FRONT
PANEL 1 ...'). Joining them puts the mangled prefix first and breaks QTY_TABLE_ROW_PATTERN's
anchoring, so extract_bom_rows finds nothing.

v2 FIX: run extract_bom_rows on EACH region_text field SEPARATELY (notes, bom, general),
so the clean 'notes' field is parsed on its own and yields the rows. Proven: extract_bom_rows
on the clean notes string yields 12532-02-03M->FRONT PANEL, 12532-03-03M->SHELF BODY
(_probe_bom_desc_map.py). Pooled BOM still wins; per-page fills only gaps.

This applier REPLACES the whole v1 Fix A2 block (found by its distinctive comment) with v2.
It locates from the 'Fix A2 (SDI Intelligence)' comment through the end of the try/except.
Exact-string match-or-refuse on the v1 block; if the live text differs, it refuses and asks
to see the block.

Run from C:\ClaudeVision\src :
  C:\ClaudeVision\.venv\Scripts\python.exe _apply_fixa2_v2_separate_fields.py

AFTER: re-run Recipe Card — 12532-02-03M -> FRONT PANEL, 12532-03-03M -> SHELF BODY.
Then 1282 regression (must hold).
"""
from pathlib import Path
import re

TARGET = Path(r"C:\ClaudeVision\src\document_builder.py")
src = TARGET.read_text(encoding="utf-8")

# Locate the v1 Fix A2 block: from its comment line to the closing 'except Exception:\n        pass'
# that precedes the final assignment loop. We match generously on the known markers.
start_marker = "    # Fix A2 (SDI Intelligence):"
# the block ends right before the existing assignment loop 'for p in parts:' that follows it
# (the same loop that was already there for Fix A). We replace only the injected A2 try/except.
if start_marker not in src:
    print("REFUSED: 'Fix A2 (SDI Intelligence):' marker not found. Live file differs.")
    print("Paste lines ~1461-1500 of document_builder.py so I can re-key the replacement.")
    raise SystemExit(1)

# Find the block: from start_marker up to and including the first '    except Exception:\n        pass\n'
si = src.index(start_marker)
# find the end: the first occurrence of the A2 try/except tail after si
tail = "    except Exception:\n        pass\n"
ti = src.find(tail, si)
if ti == -1:
    print("REFUSED: could not find the A2 try/except tail ('    except Exception:\\n        pass').")
    print("Paste the current Fix A2 block so I can re-key.")
    raise SystemExit(1)
block_end = ti + len(tail)
v1_block = src[si:block_end]

print("=== Located v1 Fix A2 block (will be replaced) ===")
print(v1_block[:400], "..." if len(v1_block) > 400 else "")
print("=== end located block ===\n")

V2_BLOCK = '''    # Fix A2 (SDI Intelligence) v2: the pooled document_analysis.bom_rows is built from the
    # anchor GA and can MISS parts whose description lives only in a sub-assembly BOM on a
    # detail page (12532-02-03M FRONT PANEL page 4, 12532-03-03M SHELF BODY page 17). Those
    # descriptions sit in region_text.NOTES (clean), while region_text.bom holds mangled OCR
    # text. v1 concatenated the fields and the mangled prefix broke QTY_TABLE_ROW_PATTERN, so
    # nothing parsed. v2 runs extract_bom_rows on EACH field SEPARATELY (notes first — it is the
    # clean one), so the clean rows are recovered. Pooled keys win (added first); per-page fills
    # only gaps, so jobs with a complete pooled BOM (1282/1298) are unchanged.
    try:
        from extractor_patterns import extract_bom_rows as _extract_bom_rows_perpage
        for _pg in summary.get("pages", []) or []:
            _rt = _pg.get("region_text") or {}
            for _fld in ("notes", "bom", "general"):
                _txt = str(_rt.get(_fld) or "").strip()
                if not _txt:
                    continue
                try:
                    _rows = _extract_bom_rows_perpage(_txt)
                except Exception:
                    continue
                for _row in _rows or []:
                    _pn = str(_row.get("part_number") or "").strip().upper()
                    _dsc = str(_row.get("description") or "").strip()
                    if _pn and _dsc and _pn not in _bom_desc and _is_good_description(_dsc):
                        _bom_desc[_pn] = _dsc
    except Exception:
        pass
'''

new_src = src[:si] + V2_BLOCK + src[block_end:]
TARGET.write_text(new_src, encoding="utf-8")
print("APPLIED: Fix A2 v2 (per-field separate parsing) replaces v1.")
print("Fingerprint:")
print('  Select-String -Path C:\\ClaudeVision\\src\\document_builder.py -Pattern "Fix A2 \\(SDI Intelligence\\) v2"')
