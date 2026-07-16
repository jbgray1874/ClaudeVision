"""
layout_zones.py  —  spatial layout helpers for SDI drawing page analysis.

Drop-in replacement that keeps the original API (zone_boxes, words_in_box,
words_to_text, segment_bom_rows, bom_rows_to_text) fully intact, and adds
a new cell-model title block extractor (extract_title_block_fields) that
correctly reads both legacy 2011/2013 SDI drawings and modern SolidWorks
exports without needing to change the PDF library.

WHY THE ORIGINAL words_to_text FAILS ON TITLE BLOCKS
─────────────────────────────────────────────────────
SDI title blocks are a grid: labels sit on one row, their values on the row
directly below, in aligned columns.  Joining all words by (top, x0) produces
a flat string like "DESCRIPTION CLIENT PROJECT TITLE DWG NO REVISION
MILWAUKEE 500mm… TTI MILWAUKEE 500mm… 1282-GA 7" — the label row and value
row are interleaved with no separator, so a simple regex picks the wrong
token for each field (Rev → '1282' instead of '7', Client → blank, etc.).

The cell-model extractor treats the title block as a table:
  1. Find a line that contains at least two known label tokens.
  2. For each label, note its x-range (label_x0 … next_label_x0).
  3. Look on the NEXT row down in that same x-range — those words are the value.

This works regardless of where on the page the title block sits, at what
scale, or how many columns it has — so it handles both 2011-era and 2025-era
drawings without any job-specific rules.

EXPORTS (public API — unchanged from original)
───────────────────────────────────────────────
  zone_boxes(page_width, page_height)   → Dict[str, box]
  words_in_box(words, box)              → List[word]
  words_to_text(words)                  → str       (unchanged — used for BOM/notes)
  segment_bom_rows(words, y_tolerance)  → List[List[word]]
  bom_rows_to_text(rows)                → str

NEW
───
  extract_title_block_fields(page, zone_top_pct=0.80) → Dict[str, str]
      Call this instead of words_to_text on title_block_words.
      Returns field names as keys: drawing_number, revision, client,
      client_ref, project_title, description, material, finish, colour,
      weight, drawn_by, modified_by, date.
"""
from __future__ import annotations
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple
import re

from extractor_patterns import normalize_text


# ─────────────────────────────────────────────── original API (unchanged) ───

def zone_boxes(
    page_width: float,
    page_height: float,
) -> Dict[str, Tuple[float, float, float, float]]:
    """Return spatial zone boxes for the four drawing regions.
    Coordinates: (x0, top, x1, bottom) in PDF points."""
    return {
        "title_block": (page_width * 0.58, page_height * 0.72, page_width, page_height),
        "bom":         (0.0,              page_height * 0.55, page_width * 0.55, page_height),
        "notes":       (page_width * 0.55, 0.0,               page_width,        page_height * 0.5),
        "revision":    (page_width * 0.72, page_height * 0.55, page_width,        page_height * 0.8),
    }


def words_in_box(
    words: List[Dict[str, Any]],
    box:   Tuple[float, float, float, float],
) -> List[Dict[str, Any]]:
    """Return words whose bounding box overlaps *box* = (x0, top, x1, bottom)."""
    x0, top, x1, bottom = box
    selected: List[Dict[str, Any]] = []
    for word in words:
        wx0 = float(word.get("x0",     0.0))
        wx1 = float(word.get("x1",     0.0))
        wt  = float(word.get("top",    0.0))
        wb  = float(word.get("bottom", 0.0))
        if wx1 >= x0 and wx0 <= x1 and wb >= top and wt <= bottom:
            selected.append(word)
    return selected


def words_to_text(words: List[Dict[str, Any]]) -> str:
    """Join words spatially (top, x0) into a normalised string.
    Used for BOM, notes, and revision zones — NOT recommended for title
    blocks (use extract_title_block_fields instead)."""
    ordered = sorted(
        words,
        key=lambda item: (round(float(item.get("top", 0.0)), 1), float(item.get("x0", 0.0))),
    )
    return normalize_text(" ".join(str(item.get("text", "")) for item in ordered))


def segment_bom_rows(
    words:       List[Dict[str, Any]],
    y_tolerance: float = 5.0,
) -> List[List[Dict[str, Any]]]:
    """Group words into BOM rows by y-proximity, each row sorted left-to-right."""
    if not words:
        return []
    sorted_words = sorted(words, key=lambda w: float(w.get("top", 0.0)))
    rows: List[List[Dict[str, Any]]] = []
    current_row: List[Dict[str, Any]] = [sorted_words[0]]
    current_top = float(sorted_words[0].get("top", 0.0))
    for word in sorted_words[1:]:
        word_top = float(word.get("top", 0.0))
        if abs(word_top - current_top) <= y_tolerance:
            current_row.append(word)
        else:
            rows.append(sorted(current_row, key=lambda w: float(w.get("x0", 0.0))))
            current_row = [word]
            current_top = word_top
    if current_row:
        rows.append(sorted(current_row, key=lambda w: float(w.get("x0", 0.0))))
    return rows


def bom_rows_to_text(rows: List[List[Dict[str, Any]]]) -> str:
    lines = [words_to_text(row) for row in rows if row]
    return "\n".join(line for line in lines if line)


# ──────────────────────────────────────────── cell-model title block reader ───

# Known label tokens, longest-first so "CLIENT REF" matches before "CLIENT"
_LABEL_FIELDS: Dict[str, str] = {
    "DWG NO":       "drawing_number",
    "DWG NO.":      "drawing_number",
    "REVISION":     "revision",
    "CLIENT REF":   "client_ref",
    "CLIENT":       "client",
    "PROJECT TITLE":"project_title",
    "DESCRIPTION":  "description",
    "MATERIAL":     "material",
    "SURFACE FINISH":"finish",
    "COLOUR":       "colour",
    "WEIGHT":       "weight",
    "DRAWN BY":     "drawn_by",
    "MODIFIED BY":  "modified_by",
    "DATE":         "date",
    "SCALE":        "scale",
    "SHEET SIZE":   "sheet_size",
    "SHEET":        "sheet",
}
_SORTED_LABELS = sorted(_LABEL_FIELDS.keys(), key=len, reverse=True)

# Tokens that look like noise / continuation text — never a real value
_NOISE_RE = re.compile(
    r"^(DO\s+NOT\s+SCALE|IF\s+IN\s+DOUBT|UNLESS\s+OTHERWISE|"
    r"ALL\s+DIMENSIONS|LINEAR\s+TOL|ANGULAR\s+TOL|THIS\s+DRAWING|"
    r"SCALE\s*[-–]\s*IF|CLIENT\s+REF|SHEET\s+SIZE|SHEET\b)$",
    re.I,
)

def _is_noise_word(text: str) -> bool:
    """Single-character fragments and legal-disclaimer letters."""
    t = text.strip()
    if not t:
        return True
    # Single lowercase letter — character fragment from exploded disclaimer
    if len(t) == 1 and t.islower():
        return True
    return False


def extract_title_block_fields(
    page,
    zone_top_pct: float = 0.80,
) -> Dict[str, str]:
    """
    Extract title block fields from a pdfplumber Page using the cell model.

    SDI drawings place labels on one row and values on the row directly below,
    in aligned columns. This function finds each label, then looks for values
    below it, bounded by the next label's x-position on the right.

    Parameters
    ----------
    page : pdfplumber Page object
    zone_top_pct : float
        Fraction of page height above which to ignore words (default 0.80 —
        bottom 20% of page).  Raise to 0.85 if revision-table noise appears.

    Returns
    -------
    Dict[str, str]  field names → values.  Missing fields are absent.
    """
    try:
        pw = float(page.width)
        ph = float(page.height)
        words = page.extract_words(x_tolerance=3, y_tolerance=3) or []
    except Exception:
        return {}

    # Filter noise and restrict to title block area
    clean = [
        w for w in words
        if not _is_noise_word(w.get("text", ""))
        and float(w.get("top", 0.0)) >= ph * zone_top_pct
    ]

    # Group into y-bands (6pt row tolerance)
    bands: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for w in clean:
        y_key = round(float(w["top"]) / 6) * 6
        bands[y_key].append(w)

    y_keys = sorted(bands.keys())
    rows: List[List[Dict[str, Any]]] = [
        sorted(bands[y], key=lambda w: float(w["x0"])) for y in y_keys
    ]

    result: Dict[str, str] = {}

    for row_idx, row_words in enumerate(rows):
        # ---- Scan for labels on this row ----
        found: List[Tuple[str, float, float, int]] = []  # (label, x0, x1_label, end_idx)
        i = 0
        while i < len(row_words):
            for label in _SORTED_LABELS:
                tokens = label.split()
                end = i + len(tokens)
                if end > len(row_words):
                    continue
                candidate = " ".join(
                    row_words[i + j]["text"].upper().rstrip(":.") for j in range(len(tokens))
                )
                if candidate == label:
                    x0_lbl  = float(row_words[i]["x0"])
                    x1_lbl  = float(row_words[end - 1]["x1"])
                    found.append((label, x0_lbl, x1_lbl, end))
                    i = end
                    break
            else:
                i += 1

        if len(found) < 2:
            # Not a label row (fewer than 2 labels = not the title block header)
            continue

        # ---- For each label, find its value in the row(s) below ----
        for lbl_idx, (label, lbl_x0, lbl_x1, _) in enumerate(found):
            field = _LABEL_FIELDS[label]
            if field in result:
                continue

            # Right boundary = next label's x0 (or page edge)
            right_bound = found[lbl_idx + 1][1] if lbl_idx + 1 < len(found) else pw + 10

            # Look in the next 1–3 rows for value words in the label's column
            for value_row in rows[row_idx + 1: row_idx + 4]:
                val_words = [
                    w for w in value_row
                    if float(w["x0"]) >= lbl_x0 - 8
                    and float(w["x1"]) <= right_bound + 5
                ]
                if not val_words:
                    continue
                val = " ".join(w["text"] for w in val_words).strip(" :.-")
                # Reject if it looks like another label row or noise
                if not val:
                    continue
                if _NOISE_RE.match(val):
                    continue
                # Reject if the value *is itself* a label (means next row is another label row)
                if any(val.upper().rstrip(":.") == lbl for lbl in _SORTED_LABELS):
                    continue
                result[field] = val
                break

    return result
