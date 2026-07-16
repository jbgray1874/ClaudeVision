"""
description_normaliser.py
─────────────────────────
Cleans and normalises bought-in part descriptions extracted from PDF BOMs
before they are written to BoughtInCatalogue or used in estimates.

Fixes applied (in order):
  1. Typo corrections (common OCR and human errors)
  2. Remove embedded prices (£x.xx) from descriptions
  3. Remove drawing part-number prefixes (e.g. '11087-17-09M /')
  4. Standardise unit abbreviations (Mtr → m, MM → mm, etc.)
  5. Remove redundant SKU repetition within descriptions
  6. Trim whitespace and collapse multiple spaces

Usage:
  from description_normaliser import normalise_description
  clean = normalise_description(raw_sku, raw_description)
"""

import re
from typing import Optional


# ── Typo corrections ─────────────────────────────────────────────────────────
_TYPOS: list[tuple[str, str]] = [
    # Spelling
    (r"\bAlen\b",        "Allen"),
    (r"\bConector\b",    "Connector"),
    (r"\bConnecter\b",   "Connector"),
    (r"\bFlanged\b",     "Flange"),          # "Flanged Button" → "Flange Button"
    (r"\bSemi[\s-]Gloss\b", "Semi-Gloss"),
    (r"\bGloss\b(?!\s*Coat)", "Gloss"),      # normalise standalone "Gloss"
    (r"\bAluminium\b",   "Aluminium"),        # already correct — keep
    (r"\bAssembley\b",   "Assembly"),
    (r"\bMeterial\b",    "Material"),
    (r"\bDovos\b",       "Davos"),           # common OCR error
    (r"\bNatural\s+Devos\b", "Natural Davos"),
    (r"\bMinifix\s+S\s*100\b", "Minifix S100"),
    # Unit abbreviations
    (r"\bMtr\b",         "m"),               # 75Mtr → 75m
    (r"\bMM\b",          "mm"),              # MM → mm
    (r"\bCM\b",          "cm"),
    (r"\bDIA\b",         "dia"),
    (r"\bDia\b",         "dia"),
    (r"\bTHRU\b",        "through"),
    (r"\bCSK\b",         "c/sunk"),
    (r"\bBZP\b",         "BZP"),             # keep — trade standard
    (r"\bA/2\b",         "A2"),
    (r"\bA/4\b",         "A4"),
    # Formatting
    (r"\s*\+\s*",        " + "),             # spaces around +
    (r"\s*x\s*",         "x"),               # no spaces around x in dimensions
    (r"(\d)\s*[Xx]\s*(\d)", r"\1x\2"),       # 30 x 30 → 30x30
    (r"(\d)\s*mm\b",     r"\1mm"),           # 30 mm → 30mm
]

# ── Compiled patterns ─────────────────────────────────────────────────────────
_TYPO_RES = [(re.compile(p, re.IGNORECASE), r) for p, r in _TYPOS]

# Remove embedded prices: "(bolt £0.20 + housing £0.06)" → "(bolt + housing)"
_PRICE_RE = re.compile(r'£\s*\d+\.\d+\s*', re.IGNORECASE)

# Remove drawing PN prefix: "11087-17-09M /..." or "11087-17-05M - "
_DRG_PREFIX_RE = re.compile(
    r'^\d{4,5}-\d{2}-\d{2,3}[A-Z]?\s*[/\-]\s*', re.IGNORECASE
)

# Remove trailing junk: "(UKPOS:SHFP28)" where SKU is already the key
_SKU_IN_DESC_RE = re.compile(
    r'\(\s*(?:UKPOS|VKF|SKU|REF|ITEM)[:\s]?[\w\-\.]+\s*\)$', re.IGNORECASE
)

# Collapse multiple spaces
_MULTI_SPACE_RE = re.compile(r'\s{2,}')


def _remove_price(text: str) -> str:
    """Remove embedded prices like £0.20 from descriptions."""
    # Replace "bolt £0.20 + housing £0.06" → "bolt + housing"
    cleaned = _PRICE_RE.sub('', text)
    # Clean up orphaned operators: "( + )" → "()"  then "()" → ""
    cleaned = re.sub(r'\(\s*\+\s*\)', '', cleaned)
    cleaned = re.sub(r'\(\s*\)', '', cleaned)
    return cleaned.strip()


def _apply_typos(text: str) -> str:
    for pattern, replacement in _TYPO_RES:
        text = pattern.sub(replacement, text)
    return text


def _remove_drg_prefix(text: str) -> str:
    """Strip leading drawing part-number prefixes."""
    return _DRG_PREFIX_RE.sub('', text).strip()


def normalise_description(sku: Optional[str], description: Optional[str]) -> str:
    """
    Main entry point. Returns a clean, normalised description.

    Args:
        sku: The part SKU (used to remove redundant self-reference in description)
        description: Raw description from PDF extraction or catalogue

    Returns:
        Cleaned description string
    """
    if not description:
        return description or ""

    text = str(description).strip()

    # 1. Remove drawing PN prefix
    text = _remove_drg_prefix(text)

    # 2. Remove embedded prices
    text = _remove_price(text)

    # 3. Apply typo corrections and unit standardisation
    text = _apply_typos(text)

    # 4. Remove redundant SKU from end of description
    if sku:
        sku_clean = str(sku).strip().upper().replace('-', '').replace(' ', '')
        # e.g. remove "(UKPOS:SHFP28)" from end
        text = _SKU_IN_DESC_RE.sub('', text).strip()

    # 5. Collapse whitespace
    text = _MULTI_SPACE_RE.sub(' ', text).strip()

    # 6. Title-case the first letter only (preserve rest as-is for part specs)
    if text:
        text = text[0].upper() + text[1:]

    return text


# ── Standard BOM description templates ───────────────────────────────────────
# For known SKUs, override with canonical descriptions regardless of what
# the PDF extraction produced.
CANONICAL_DESCRIPTIONS: dict[str, str] = {
    "MINIFIX":        "Minifix S100 Connector Set (bolt + cam housing)",
    "WOODEN-DOWEL":   "8mm x 25mm Wooden Dowel (glue-in)",
    "MFC046":         "Egger H3131 ST12 Natural Davos Oak FSC MFC 2800x2070x19mm sheet",
    "PALLET1":        "SDI Standard Pallet + Shrink Wrap (per job)",
    "BOX-SM":         "Compleat Packaging Box Small",
    "RAL9007":        "RAL9007 Grey Aluminium Semi-Gloss Powder Coat (per job)",
    "UKPOS-SHFP28":   "Pusher and Guide Rail 28mm 10-14N (Wanzl UKPOS-SHFP28)",
    "VKF-DBR18":      "Scanner Profile 18mm x 280mm (VKF DBR18)",
    "VKF-DBR39":      "Scanner Profile 39mm x 280mm (VKF DBR39)",
    "FIXING1784":     "Edging Seal Strip 10m Roll (Rubusec)",
    "EDGING-ABS-125": "ABS Edging 33x2mm 75m Roll - Davos Oak H3131 ST12",
    "PACKAGING-STD":  "Standard Packaging per Unit (Compleat)",
    "SUNDRIES-STD":   "Sundries Standard (per unit)",
    "BOX-296x404x40": "Box 296mm(w) x 404mm(d) x 40mm(h)",
    "FIXING12":       "4mm Allen Key",
    "FIXING636":      "No.8 x 16mm Pan Head Wood Screw Pozi",
    "FIXING2104":     "M6 x 10mm Flange Button Head Screw Black",
    "FIXING1596":     "M6 x 75mm Flange Button Head Screw Black",
    "FIXING597":      "M8 x 25mm Levelling Glide (adjustable foot)",
    "FIXING2105":     "M6 x 12mm Threaded Insert Headed Hex Drive",
    "FIXING105":      "M8 x 16g Hank Bush (weld-in nut insert)",
    "FIXING1067":     "M4 x 20mm Countersunk Bolt BZP",
    "FIXING47":       "M4 Thin Sheet Nutsert",
    "TUBE0070":       "Tube 60x30x2mm 933mm (Top Frame Side)",
    "TUBE0071":       "Tube 30x30x2mm 745mm (LH Sloping Leg)",
    "TUBE0072":       "Tube 30x30x2mm 745mm (RH Sloping Leg)",
    "TUBE0073":       "Tube 60x30x2mm 147mm (Top Tube End)",
    "TUBE0074":       "Tube 20mm Dia x 2mm Wall 657mm (Lower Tie)",
}


def get_canonical_description(sku: str, fallback: Optional[str] = None) -> str:
    """
    Return canonical description for known SKUs, or normalise the fallback.
    This is the function to call in the estimator for any catalogue lookup.
    """
    sku_upper = str(sku or "").strip().upper()
    if sku_upper in CANONICAL_DESCRIPTIONS:
        return CANONICAL_DESCRIPTIONS[sku_upper]
    return normalise_description(sku, fallback) if fallback else (fallback or "")


# ── Self-test ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    tests = [
        ("FIXING12",     "4mm Alen Key"),
        ("MINIFIX",      "Minifix S100 Conector Set (bolt £0.20 + housing £0.06)"),
        ("TUBE0071",     "11087-17-08M /Tube Legs 30 x 30 x 2.0mm 745mm Legs"),
        ("MFC046",       "Egger Natural Devos Oak H3131 ST12 FSC MFC"),
        ("EDGING-ABS-125","ABS Edging to Suit Davos Oak H3131 ST12 33 x 2mm 75Mtr Roll"),
        ("WOODEN-DOWEL", "8mm Wooden Dowel (glue-in)"),
        ("RAL9007",      "Powder RAL 9007 Grey Aluminium 30% Gloss (per job charge)"),
        ("UKPOS-SHFP28", "Pusher and Guide Rail 28mm width 10-14N (UKPOS:SHFP28)"),
        ("PALLET1",      "SDI Standard Pallet + Wrap (per job)"),
        ("UNKNOWN",      "11087-17-09M /Tube Legs 30 x 30 x 2.0MM 745mm Legs"),
    ]
    print("DESCRIPTION NORMALISER — SELF TEST")
    print("="*60)
    for sku, raw in tests:
        result = get_canonical_description(sku, raw)
        changed = "  ✅ changed" if result != raw else "  — unchanged"
        print(f"\n  SKU:  {sku}")
        print(f"  In:   {raw}")
        print(f"  Out:  {result}{changed}")
