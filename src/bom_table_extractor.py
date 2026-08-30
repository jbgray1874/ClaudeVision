"""
bom_table_extractor.py  —  read the GA BOM from table STRUCTURE, not scrambled text.

The legacy path runs regexes over pdfplumber's text flow, which scrambles ruled
CAD tables and forces per-job string repairs (see preprocess_bom_text's hardcoded
1453/1455/3886 fixes). That approach silently drops rows pdfplumber splits — e.g.
the 1455-C-GA header line on 1282.

pdfplumber's ruling-line table extraction recovers every cell in the right column,
including the split rows. This module reads the BOM table by its grid and applies
only generic part-code cleanup (whitespace around hyphens, trailing hyphens) — no
job-specific rules — so it generalises across the calibration set.

    extract_bom_table_rows(page)      -> rows from a pdfplumber Page
    bom_rows_from_tables(tables)      -> rows from raw extract_tables() output (testable)
"""
from __future__ import annotations
from typing import Any, Dict, List
import re


def _clean(cell: Any) -> str:
    return re.sub(r"\s+", " ", str(cell or "")).strip()

def _normalize_bom_code(code: str) -> str:
    """Generic repair of split/spaced part codes — NO job-specific rules.
    '1453-GA- C' -> '1453-GA-C' ; '1455-C- GA' -> '1455-C-GA' ;
    '1450 - GA' -> '1450-GA' ; '3886-GA-' -> '3886-GA'."""
    c = _clean(code).upper()
    c = re.sub(r"\s*-\s*", "-", c)   # collapse spaces around hyphens
    c = re.sub(r"-{2,}", "-", c)     # de-dupe hyphens
    c = c.strip("-")                  # drop leading/trailing hyphens
    c = re.sub(r"\s+", "", c)        # any residual internal space in a code
    return c

def _is_item_no(s: str) -> bool:
    return s.isdigit() and 1 <= int(s) <= 99

def _is_qty(s: str) -> bool:
    return s.isdigit() and 1 <= int(s) <= 250

def _has_words(s: str) -> bool:
    # a real description / spec carries at least one alphabetic run (rejects grid-label noise like '2 3 4 5')
    return bool(re.search(r"[A-Za-z]{2,}", s))

def _classify_part_ref(raw: str):
    """Decide whether a BOM part cell is a drawing reference to follow, or a
    bought-in commodity to price by description. Returns (kind, code_or_spec).

    A drawing reference is a single part-number TOKEN: digit-led, alnum+hyphens,
    no embedded words/spaces (after joining hyphen-adjacent spaces). Everything
    else — '50mm PP Wheel - 8mm Bore 50-PL', 'M6 (8mm) ... SSH-M6-8-35-A2',
    'Clinch Nut' — is a commodity spec we keep verbatim for pricing."""
    s = _clean(raw)
    joined = re.sub(r"\s*-\s*", "-", s).strip("-")     # join hyphen spacing only
    if " " not in joined and re.match(r"^\d{3,}(?:-[A-Z0-9]+)+$", joined, re.I):
        return "drawing_ref", _normalize_bom_code(s)
    return "bought_in", s


def bom_rows_from_tables(tables: List[List[List[Any]]]) -> List[Dict[str, Any]]:
    """Pull clean BOM rows from raw pdfplumber extract_tables() output.
    A BOM data row, once empty cells are dropped, is [item, code, desc..., qty]
    with item and qty small integers — that shape alone isolates it from the
    revision table, title block and dimension callouts."""
    out: List[Dict[str, Any]] = []
    seen = set()
    for tbl in tables or []:
        for raw in tbl:
            cells = [_clean(c) for c in raw if c and str(c).strip()]
            if len(cells) < 4:
                continue
            item, qty = cells[0], cells[-1]
            if not (_is_item_no(item) and _is_qty(qty)):
                continue
            part_ref = cells[1]
            desc = " ".join(cells[2:-1]).strip()
            # a genuine BOM row has a real description (rejects dimension/grid-label rows)
            if not _has_words(desc) and not _has_words(part_ref):
                continue
            kind, code_or_spec = _classify_part_ref(part_ref)
            key = (item, _clean(part_ref), qty)
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "item_number": item,
                "part_number": code_or_spec if kind == "drawing_ref" else "",
                "part_ref": _clean(part_ref),     # raw cell, always kept
                "description": desc,
                "quantity": int(qty),
                "kind": kind,                      # 'drawing_ref' (follow) | 'bought_in' (price)
                "source": "bom_table",
            })
    return out


def extract_bom_table_rows(page) -> List[Dict[str, Any]]:
    """Rows from a live pdfplumber Page. Safe on pages with no BOM table."""
    try:
        tables = page.extract_tables() or []
    except Exception:
        return []
    return bom_rows_from_tables(tables)
