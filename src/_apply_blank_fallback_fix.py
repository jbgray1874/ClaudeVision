# -*- coding: utf-8 -*-
"""FIX: the non-metal blank fallback grabs the two LARGEST numbers in the WHOLE document, producing
a garbage square blank (RISER 12532-03-04A got 2026x2026 vs its real 645x102).

Root cause (PROVEN by trace): document_builder.py ~968-986, inside the `if _is_non_metal_mat` block.
When a non-metal part has no blank_length/width, it does:
    _pt_dims = re.findall(3-4 digit numbers, " ".join(ALL pages text))
    _nums = sorted([50..3000], reverse=True)      # two LARGEST numbers, document-wide
    part["blank_length_mm"] = _nums[0]; part["blank_width_mm"] = _nums[1]
This is context-blind: it takes the biggest numbers ANYWHERE in the 25-page doc, not this part's
dimensions. The RISER has a real DXF (645x102) landing in overall_length_mm/overall_width_mm, but
this fallback overwrote blank_* with the doc-wide max (2026,2026) — a nonsense square. (The acrylic
COST was unaffected — estimate_material recomputes from good dims — but the DISPLAYED blank is wrong.)

FIX: before the document-wide number-grab, prefer THIS part's own overall_length_mm/overall_width_mm
(populated from its DXF/geometry). Only fall back to the doc-text scan when the part has NO overall
dims either. This is the deterministic fix — use the part's own measured geometry, not the loudest
numbers in the document.

SAFE: exact-string match-or-refuse. Parts that genuinely have no dims at all still use the old
scan (unchanged). Parts with real geometry (RISER, and any DXF non-metal) now use their own dims.

BEFORE APPLYING, confirm anchor:
  Select-String -Path C:\ClaudeVision\src\document_builder.py -Pattern "_pt_dims = re.findall" -Context 3,6

Run from C:\ClaudeVision\src :
  C:\ClaudeVision\.venv\Scripts\python.exe _apply_blank_fallback_fix.py

AFTER: re-run Recipe Card — RISER blank should be ~645x102 (or ~651x108 from DXF flat), NOT
2026x2026. Acrylic parts unaffected in COST; only the displayed blank dims corrected.
"""
from pathlib import Path

TARGET = Path(r"C:\ClaudeVision\src\document_builder.py")

ANCHOR = '''            _blank_l = _safe_float(part.get("blank_length_mm"))
            _blank_w = _safe_float(part.get("blank_width_mm"))
            if not _blank_l or not _blank_w:
                _pt_dims = re.findall('''

REPLACEMENT = '''            _blank_l = _safe_float(part.get("blank_length_mm"))
            _blank_w = _safe_float(part.get("blank_width_mm"))
            # DETERMINISTIC FIX: before scanning the whole document for the two LARGEST numbers
            # (context-blind — gave RISER a garbage 2026x2026 square), prefer THIS part's own
            # measured overall dims (from its DXF/geometry). Only fall through to the doc-text
            # scan when the part has no overall dims of its own either.
            if (not _blank_l or not _blank_w):
                _own_l = _safe_float(part.get("overall_length_mm"))
                _own_w = _safe_float(part.get("overall_width_mm"))
                if _own_l and _own_w:
                    part["blank_length_mm"] = _own_l
                    part["blank_width_mm"] = _own_w
                    _blank_l, _blank_w = _own_l, _own_w
            if not _blank_l or not _blank_w:
                _pt_dims = re.findall('''

src = TARGET.read_text(encoding="utf-8")
if ANCHOR not in src:
    print("REFUSED: anchor not found exactly. Paste document_builder.py ~968-972 so I can re-key.")
    raise SystemExit(1)
if src.count(ANCHOR) != 1:
    print(f"REFUSED: anchor found {src.count(ANCHOR)} times (need 1).")
    raise SystemExit(1)
src = src.replace(ANCHOR, REPLACEMENT)
TARGET.write_text(src, encoding="utf-8")
print("APPLIED: non-metal blank fallback now prefers the part's own overall dims before doc-wide scan.")
print("Fingerprint:")
print('  Select-String -Path C:\\ClaudeVision\\src\\document_builder.py -Pattern "prefer THIS part.s own measured overall dims"')
