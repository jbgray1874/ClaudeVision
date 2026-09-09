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
from typing import Any, Dict, List, Optional
import re


# ── ONE VOCABULARY FOR WHAT A COLUMN MEANS ─────────────────────────────────────────────
# Owned here — the lowest module in the reader stack — and imported by the words reader
# and the Camelot bench, so a synonym learned from one pack serves every reader and none
# of them can disagree about what a header word names. Includes the customer aliases the
# 0359342 probe proved (PART # / PART NO / MATERIAL / MASS / KG).
HDR_ITEM = {"ITEM", "ITEMNO", "ITEM NO", "NO", "POS", "POSITION", "PART ITEM"}
HDR_CODE = {"DWG", "DWG NO", "DWGNO", "PARTNO", "PART NO", "PART", "PART NUMBER",
            "PARTNUMBER", "DRAWING", "DRAWING NO", "REF", "PART REF"}
HDR_DESC = {"DESCRIPTION", "DESC", "TITLE", "NAME", "PART DESCRIPTION"}
HDR_QTY = {"QTY", "QTY.", "QUANTITY", "QUANT", "QTY REQD", "QTY REQ", "REQD",
           "NO OFF", "NOOFF", "OFF", "NO. OFF", "QTY OFF", "REQUIRED"}
HDR_MATERIAL = {"MATERIAL", "MATL", "MAT", "MATERIAL SPEC", "SPEC"}
# No bare "KG": as a lone word it appears in title blocks beside a printed weight, and
# a family this weak could anchor a phantom weight column onto an SDI header row. A
# header CELL printing "MASS (KG)" reaches "MASS KG" through bracket-stripping.
HDR_WEIGHT = {"WEIGHT", "WT", "MASS", "UNIT WEIGHT", "WEIGHT KG", "MASS KG"}

_HDR_FAMILIES = [("item", HDR_ITEM), ("code", HDR_CODE), ("desc", HDR_DESC),
                 ("qty", HDR_QTY), ("material", HDR_MATERIAL), ("weight", HDR_WEIGHT)]


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


def _header_column_map(raw_row: List[Any]) -> Optional[Dict[str, int]]:
    """{family: column index} when this raw table row is a printed BOM header, else None.

    Matched against the shared families on the CLEANED cell text (brackets and # are
    layout, not meaning: 'PART #' names the part column). Indices are into the RAW row —
    the un-dropped grid — because that is the only frame in which a data row's cells
    line up with the header's."""
    found: Dict[str, int] = {}
    for ci, cell in enumerate(raw_row or []):
        norm = re.sub(r"\s+", " ", re.sub(r"[()#]", " ",
                                          _clean(cell))).strip().upper().replace(".", "")
        if not norm:
            continue
        for fam, family in _HDR_FAMILIES:
            if fam not in found and norm in family:
                found[fam] = ci
                break
    if "item" in found and "qty" in found and ("code" in found or "desc" in found):
        return found
    return None


def _code_token(raw: str) -> str:
    """The part cell's code, preserved INDEPENDENTLY of classification.

    Review probe: letting the mapped path classify letter-led codes as drawing
    references meant a table's LAYOUT decided whether THUM620 is purchased — adding a
    MATERIAL column reclassified a thumbscrew. Classification stays with the ONE
    shared rule (_classify_part_ref) whatever the table looks like; the code itself is
    kept here as its own fact, so J13092 / JAE820 / MBY439 never become anonymous and
    the shared identity policy downstream — purchasing evidence, drawing references —
    resolves their role from evidence rather than from column count."""
    s = _clean(raw)
    joined = re.sub(r"\s*-\s*", "-", s).strip("-")
    if joined and " " not in joined and re.match(r"^[A-Z0-9][A-Z0-9-]*$", joined, re.I):
        return _normalize_bom_code(s)
    return ""


def _rows_from_header_mapped_table(tbl: List[List[Any]], colmap: Dict[str, int],
                                   header_row: List[Any],
                                   out: List[Dict[str, Any]], seen: set) -> None:
    """Parse one table by its OWN printed header. QTY comes from the QTY column —
    never from 'the last cell', which on 0359342 is a 12.00kg mass that failed the
    integer test and deleted all six tables AFTER a successful extract. No universal
    quantity cap here either: the column says what the number is."""
    def _cell(row: List[Any], fam: str) -> str:
        ci = colmap.get(fam)
        return _clean(row[ci]) if ci is not None and ci < len(row) else ""

    for raw in tbl:
        if raw is header_row:
            continue
        item, qty = _cell(raw, "item"), _cell(raw, "qty")
        if not (item.isdigit() and int(item) >= 1 and qty.isdigit() and int(qty) >= 1):
            continue
        part_ref = _cell(raw, "code")
        desc = _cell(raw, "desc")
        if not _has_words(desc) and not _has_words(part_ref):
            continue
        # THE SAME CLASSIFIER AS THE POSITIONAL PATH — a table's layout must never
        # decide whether a part is purchased. The code survives separately below.
        kind, code_or_spec = _classify_part_ref(part_ref)
        key = (item, _clean(part_ref), qty)
        if key in seen:
            continue
        seen.add(key)
        row_out = {
            "item_number": item,
            "part_number": code_or_spec if kind == "drawing_ref" else "",
            "part_ref": _clean(part_ref),
            "description": desc,
            "quantity": int(qty),
            "kind": kind,
            "source": "bom_table",
            "header_mapped": True,
        }
        _tok = _code_token(part_ref)
        if _tok:
            row_out["code_token"] = _tok
        # The row's own printed material and mass, through the same unit rules the
        # words and vision readers use (lazy import: the words reader imports this
        # module, so a top-level import here would be a cycle).
        try:
            from _bom_words_reader import _row_material_fields as _rmf
            row_out.update(_rmf(_cell(raw, "material"), _cell(raw, "weight")))
        except Exception:                                        # pragma: no cover
            _mat = _cell(raw, "material")
            if _mat:
                row_out["material_text"] = _mat
        out.append(row_out)


def bom_rows_from_tables(tables: List[List[List[Any]]]) -> List[Dict[str, Any]]:
    """Pull clean BOM rows from raw pdfplumber extract_tables() output.

    A RECOGNISED HEADER IS USED — WHOLESALE, WHATEVER THE COLUMN ORDER. The table
    prints its own column meanings; guessing positions past them is how 0359342's
    [item, desc, part, qty, rev, material, mass] rows were deleted (the mass read as a
    failed quantity) and how an [item, desc, part, qty] table put 'Plinth assembly' in
    the part column — the review probe of the first cut, which gated the mapper on
    extra columns and so ignored a perfectly valid header. The positional path below
    is the fallback for GENUINELY HEADERLESS tables — a grid whose header row the
    extractor did not capture — where the proven SDI shape assumption
    [item, code, desc..., qty] is all there is to go on."""
    out: List[Dict[str, Any]] = []
    seen = set()
    for tbl in tables or []:
        _mapped = False
        for _hdr_candidate in (tbl or [])[:6]:
            colmap = _header_column_map(_hdr_candidate)
            if not colmap:
                continue
            _rows_from_header_mapped_table(tbl, colmap, _hdr_candidate, out, seen)
            _mapped = True
            break        # one header per table
        if _mapped:
            continue
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
