# -*- coding: utf-8 -*-
"""FIX: back-fill part descriptions from PER-PAGE BOM tables, not just the pooled BOM.

Root cause (proven via _probe_pooled_bom.py): the description fallback at document_builder.py
L1461-1470 builds _bom_desc ONLY from summary['document_analysis']['bom_rows'] (the pooled/anchor
BOM, 20 rows). Two parts' descriptions live only in SUB-ASSEMBLY BOMs on pages 4 and 17
(12532-02-03M FRONT PANEL, 12532-03-03M SHELF BODY), which pooling dropped — so those parts stay
description=None and render as "12532-03-03M None".

Proven data-in-hand: extract_bom_rows() over those pages' region_text.notes yields the correct
descriptions (via _probe_bom_desc_map.py). This fix ADDS a second source to the SAME _bom_desc:
per-page extract_bom_rows over each page's BOM text. Pooled entries take precedence (built first);
per-page fills only the gaps. No new extraction — reuses the existing, proven extract_bom_rows.

SAFE: exact-string match-or-refuse. Inserts immediately AFTER the existing pooled build loop
(L1466-1467) and BEFORE the assignment loop (L1468), so the pooled map is augmented, not replaced.
Regression-safe: for jobs where the pooled BOM already has every part (1282, 1298), the per-page
pass only re-confirms existing keys (pooled wins), changing nothing.

BEFORE APPLYING, confirm the anchor in live src:
  Select-String -Path C:\ClaudeVision\src\document_builder.py -Pattern "back-fill missing descriptions from BOM rows" -Context 0,10

Run from C:\ClaudeVision\src :
  C:\ClaudeVision\.venv\Scripts\python.exe _apply_perpage_bom_desc.py

AFTER: re-run 12532 Recipe Card — 12532-02-03M should show FRONT PANEL, 12532-03-03M SHELF BODY.
Then re-run 1282 (MUST hold — pooled BOM already complete there) and 1298 as regression.
"""
from pathlib import Path

TARGET = Path(r"C:\ClaudeVision\src\document_builder.py")

# Anchor: the existing pooled-BOM build loop + the assignment loop. Match exactly.
ANCHOR = '''    # Fix A: back-fill missing descriptions from BOM rows
    _bom_desc: Dict[str, str] = {}
    for row in (summary.get("document_analysis") or {}).get("bom_rows") or []:
        pn = str(row.get("part_number") or "").strip()
        dsc = str(row.get("description") or "").strip()
        if pn and dsc and _is_good_description(dsc):
            _bom_desc[pn.upper()] = dsc
    for p in parts:
        if not p.get("description"):
            p["description"] = _bom_desc.get(str(p.get("part_number") or "").upper())'''

REPLACEMENT = '''    # Fix A: back-fill missing descriptions from BOM rows
    _bom_desc: Dict[str, str] = {}
    for row in (summary.get("document_analysis") or {}).get("bom_rows") or []:
        pn = str(row.get("part_number") or "").strip()
        dsc = str(row.get("description") or "").strip()
        if pn and dsc and _is_good_description(dsc):
            _bom_desc[pn.upper()] = dsc
    # Fix A2 (SDI Intelligence): the pooled document_analysis.bom_rows is built from the anchor
    # GA and can MISS parts whose description lives only in a sub-assembly BOM on a detail page
    # (e.g. 12532-02-03M FRONT PANEL on page 4, 12532-03-03M SHELF BODY on page 17 — pooling
    # dropped both, leaving them description=None). Augment _bom_desc from every page's own BOM
    # text using the SAME extract_bom_rows parser (proven to yield these descriptions). Pooled
    # keys win (added first); per-page fills only gaps, so jobs with a complete pooled BOM
    # (1282/1298) are unchanged.
    try:
        from extractor_patterns import extract_bom_rows as _extract_bom_rows_perpage
        for _pg in summary.get("pages", []) or []:
            _rt = _pg.get("region_text") or {}
            _bom_text = " ".join(
                str(_rt.get(k) or "") for k in ("bom", "notes", "general")
            ).strip()
            if not _bom_text:
                continue
            try:
                _rows = _extract_bom_rows_perpage(_bom_text)
            except Exception:
                continue
            for _row in _rows or []:
                _pn = str(_row.get("part_number") or "").strip().upper()
                _dsc = str(_row.get("description") or "").strip()
                if _pn and _dsc and _pn not in _bom_desc and _is_good_description(_dsc):
                    _bom_desc[_pn] = _dsc
    except Exception:
        pass
    for p in parts:
        if not p.get("description"):
            p["description"] = _bom_desc.get(str(p.get("part_number") or "").upper())'''

src = TARGET.read_text(encoding="utf-8")
if ANCHOR not in src:
    print("REFUSED: anchor not found exactly. Live source differs from expectation.")
    print("Run the Select-String check in the docstring and paste the region so I can re-key.")
    raise SystemExit(1)
count = src.count(ANCHOR)
if count != 1:
    print(f"REFUSED: anchor found {count} times (need exactly 1).")
    raise SystemExit(1)
src = src.replace(ANCHOR, REPLACEMENT)
TARGET.write_text(src, encoding="utf-8")
print("APPLIED: per-page BOM description back-fill (Fix A2) inserted at document_builder.py.")
print("Fingerprint to confirm:")
print('  Select-String -Path C:\\ClaudeVision\\src\\document_builder.py -Pattern "Fix A2 \\(SDI Intelligence\\)"')
