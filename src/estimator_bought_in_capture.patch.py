"""
PATCH — estimator.py — drawing-sourced bought-in BOM capture
============================================================
Validated against the real 1282 BOM text (pages 1/10/11/20/21) on 15 Jun 2026.
Captures alphabetic-prefixed bought-in rows the SDI/GA parsers structurally
skip: ELECTRICS, FIXING5, FIXING 236, FIXING 125 — and nothing spurious from
the SDI/GA tables or the tube row.

WHY HERE (not Fix B): document_builder._is_reference_like_part() treats any
"FIXING*" code as reference-like, so Fix B's _is_valid_part_identifier() drops
them. The dedicated bought-in scanner is the correct home — it already produces
_bought_in_part_stub records that price as bought-in.

HOW TO APPLY
------------
1. Paste the CONSTANTS block immediately ABOVE the existing
   `def extract_bought_in_from_pages(` in estimator.py.
2. Paste the `_extract_bought_in_table_rows` helper just above it too.
3. Replace the body of `extract_bought_in_from_pages` with the version below
   (it adds the structured pass FIRST, then keeps the existing FIXING/MINIFIX/
   dowel regexes as belt-and-braces — all deduped by seen_codes).
4. Re-run 1282. Expect ELECTRICS, FIXING5, FIXING125, FIXING236 as bought_in;
   confirm £182.84 anchor holds (these are inert on the manufactured total).
"""

import re
from typing import Any, Dict, List, Optional


# ── CONSTANTS (paste above extract_bought_in_from_pages) ──────────────────────

# A BOM-table row whose part code is ALPHABETIC-prefixed (optionally followed by
# digits, with an optional single space — e.g. "FIXING 236"). The SDI/GA parsers
# only match digit-leading hyphenated codes, so these rows are otherwise lost.
#   group1 = item no   group2 = code   group3 = description   group4 = qty
_BOUGHT_IN_ROW_RE = re.compile(
    r"(?:^|\s)(\d{1,3})\s+"
    r"([A-Z][A-Z]+(?:\s?\d{1,4})?)"                # ELECTRICS / FIXING5 / FIXING 236
    r"\s+([A-Z0-9][A-Z0-9 /\-\.&():%x]{1,60}?)"     # description (non-greedy)
    r"\s+(\d{1,3})"                                  # qty
    r"(?=\s+\d|\s*$|\s+[A-Z*])",                     # boundary: next row / end / marker
    re.IGNORECASE,
)

# Codes that are table headers, margin labels, materials or drawing furniture —
# never a real bought-in part. Exact-match on the captured CODE only.
_BOUGHT_IN_STOP_EXACT = {
    "ITEM", "NO", "QTY", "DWG", "PART", "PARTNO", "REV", "SCALE", "DETAIL",
    "SECTION", "VIEW", "TYP", "GA", "SA", "NOTES", "NOM", "MAX", "MIN", "REF",
    "AND", "THE", "FOR", "WITH", "NOT", "SEE", "ALL", "EXT", "INT", "CRS",
    "THRU", "RAW", "HIPS", "MILD", "STEEL", "CR4", "DESCRIPTION", "LENGTH",
    "BLACK", "COUNTRY", "DEPENDENT", "EARTH", "STRAP", "DETAIL", "PITCH",
}
# Header-fragment prefixes (e.g. "ITEMDWG" from a header with no space).
_BOUGHT_IN_STOP_PREFIX = ("ITEM", "DESC", "QTY", "DWG", "PART", "NOTE")
# Description tokens that mark drawing/spec text rather than a real part line.
_BOUGHT_IN_JUNK_DESC = (
    "TOLERANCE", "COPYRIGHT", "DIMENSION", "PROTOTYPE", "SPECIFICATION",
    "CONFIDENTIAL", "PROPERTY OF", "DO NOT SCALE",
)


def _normalise_bought_in_code(code: str) -> str:
    """'FIXING 236' -> 'FIXING236' — match SDI's spaceless fixing convention."""
    return re.sub(r"\s+", "", str(code or "").upper())


# ── HELPER (paste above extract_bought_in_from_pages) ─────────────────────────

def _extract_bought_in_table_rows(
    pages: List[Dict[str, Any]],
    existing_pns: set,
    seen_codes: set,
) -> List[Dict[str, Any]]:
    """Per-page structured capture of alphabetic-prefixed bought-in BOM rows.

    Gated to BOM pages (text contains DESCRIPTION and QTY) and to the structural
    item-no/code/description/qty shape, then screened by stop-lists. Mirrors the
    pattern validated against the real 1282 tables. Returns _bought_in_part_stub
    records tagged source='drawing_bom_scan'.
    """
    captured: List[Dict[str, Any]] = []
    for page in pages:
        text = _page_text_for_bought_in_scan(page)  # existing helper
        if not text:
            continue
        upper = text.upper()
        # Only scan inside a BOM context — both column headers must be present.
        if "DESCRIPTION" not in upper or "QTY" not in upper:
            continue
        for m in _BOUGHT_IN_ROW_RE.finditer(text):
            _item, _code, _desc, _qty = m.groups()
            cu = _code.upper().strip()
            if cu in _BOUGHT_IN_STOP_EXACT:
                continue
            if any(cu.startswith(p) for p in _BOUGHT_IN_STOP_PREFIX):
                continue
            code_key = _normalise_bought_in_code(_code)
            if len(code_key) < 3:                       # single letters, "GA", noise
                continue
            if any(j in _desc.upper() for j in _BOUGHT_IN_JUNK_DESC):
                continue
            try:
                q = int(_qty)
            except (TypeError, ValueError):
                continue
            if not (1 <= q <= 250):
                continue
            if code_key in existing_pns or code_key in seen_codes:
                continue
            seen_codes.add(code_key)
            stub = _bought_in_part_stub(code_key, _desc.strip(), q)
            stub["source"] = "drawing_bom_scan"
            captured.append(stub)
    return captured


# ── REPLACEMENT for extract_bought_in_from_pages ──────────────────────────────

def extract_bought_in_from_pages(
    summary: Dict[str, Any],
    *,
    existing_part_records: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Scan assembly/BOM text for bought-in items that are not detail parts.

    Primary pass: structured BOM table-row capture (drawing-sourced), which
    recovers alphabetic-prefixed codes (ELECTRICS, FIXING 236, FIXING 125, ...)
    that the SDI/GA parsers skip. Secondary passes: the original narrow FIXING/
    MINIFIX/WOODEN DOWEL regexes, kept as belt-and-braces (deduped).
    """
    pages = summary.get("pages", [])
    if existing_part_records is not None:
        existing_parts = existing_part_records
    else:
        existing_parts = summary.get("manufacturing_writeup", {}).get("parts") or summary.get("parts") or []
    existing_pns = {str(p.get("part_number", "")).strip().upper() for p in existing_parts if p.get("part_number")}

    bought_in: List[Dict[str, Any]] = []
    seen_codes: set = set()

    # ── Primary: structured drawing BOM-table capture ─────────────────────────
    bought_in.extend(_extract_bought_in_table_rows(pages, existing_pns, seen_codes))

    # ── Secondary: original narrow text-scan passes (deduped) ─────────────────
    primary = " ".join(
        str(page.get("pdfplumber_text", "") or "") + " " + str(page.get("normalized_text", "") or "") for page in pages
    )
    secondary = " ".join(_page_text_for_bought_in_scan(p) for p in pages)
    all_text = (primary + " " + secondary).upper()

    _bom_line_re = re.compile(
        r"(FIXING\d+[A-Z]?|MINIFIX)\s+(\S[^\t]{2,58}?)\s+(\d{1,3})\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    for _m in _bom_line_re.finditer(all_text):
        _raw_code = _m.group(1).strip().upper().replace(" ", "")
        _raw_desc = _m.group(2).strip()[:80]
        _raw_qty = int(_m.group(3).strip())
        if _raw_code in existing_pns or _raw_code in seen_codes:
            continue
        if _raw_qty > 200:
            continue
        seen_codes.add(_raw_code)
        bought_in.append(_bought_in_part_stub(_raw_code, _raw_desc, _raw_qty))

    _dowel_re = re.compile(
        r"(\d+MM\s*X\s*\d+MM\s+WOODEN\s+DOWEL|\d+MM\s+WOODEN\s+DOWEL)\s+\S[^\t]{0,30}?\s+(\d{1,3})\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    for _m in _dowel_re.finditer(all_text):
        _raw_code = "WOODEN-DOWEL"
        if _raw_code in seen_codes:
            continue
        _raw_qty = int(_m.group(2).strip())
        if _raw_qty > 200:
            continue
        seen_codes.add(_raw_code)
        bought_in.append(_bought_in_part_stub(_raw_code, "Wooden Dowel", _raw_qty))

    if bought_in:
        print(f"[DEBUG] Bought-in items from BOM scan: {len(bought_in)} -> {[b['part_number'] for b in bought_in]}")

    return bought_in
