"""
SDI AI Estimating Platform — Operation Code Normalisation
==========================================================
Maps between three representations of the same operation:
  1. AI operation names   (e.g. "laser_cutting", "folding")
  2. SDI workbook codes   (e.g. "LASM", "FOLD", "P/C")
  3. Historical free-text (e.g. "Laser (Metal)", "P.Coat", "Weld (CO2)")

Used by:
  - estimate_full_parity_report.py — labour route matching
  - pricing_service.py             — historical RAG labour lookup
  - estimate_parity_pretty_report.py — display labels
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set


# ── 1. AI operation name → SDI workbook code(s) ──────────────────────────────
# Order matters: first code is the primary workbook code.
# SDI_CODE_TO_AI uses first claimant per code (later duplicate codes are ignored).

AI_TO_SDI: Dict[str, List[str]] = {
    "laser_cutting":    ["LASM", "LASP", "LASA"],
    "folding":          ["FOLD", "L/BEND", "TBEN"],
    "welding":          ["WELD", "SPOT"],
    "dress_welds":      ["DRES", "DRESS"],
    "spot_welding":     ["SPOT"],
    "powder_coating":   ["P/C", "PC", "PCOA"],
    "wet_spray":        ["SPRY"],
    "cnc":              ["CNCJ"],
    "bench_work":       ["BENC"],
    "packing_manual":   ["PACM"],
    "packing_machine":  ["PACP"],
    "handling":         ["MANM", "HAND", "MAN M", "MANA"],
    "drilling":         ["DRIL", "PDRIL"],
    "countersinking":   ["COUN"],
    "tapping":          ["TAP"],
    "grinding":         ["GRIN"],
    "diamond_polish":   ["DPOL", "D/POL"],
    "glue":             ["GLUE"],
    "hole_machining":   ["DRIL", "TAP", "COUN", "PUNCH", "PUNC"],
    "assembly":         ["PACM", "BENC", "MANM"],
    "robomac":          ["ROBO", "ROBOMAC"],
    "pin_router":       ["PINR", "PIN R"],
    "linebend":         ["LINE", "LINB"],
    "guillotine":       ["GUILL"],
    "roll":             ["ROLL"],
    "tube_bend":        ["TBEN"],
    "wire_forming":     ["ROBO", "ROBOMAC", "WFOR"],
    "deburring":        ["DRES", "DEBUR", "DEBU"],
    "resistance_welding": ["SPOT", "WELD"],
}

# ── 2. Historical free-text → normalised AI operation name ──────────────────

_FREE_TEXT_MAP: Dict[str, str] = {
    "laser (metal)":        "laser_cutting",
    "laser (acrylic)":      "laser_cutting",
    "laser":                "laser_cutting",
    "lasm":                 "laser_cutting",
    "lasp":                 "laser_cutting",
    "lasa":                 "laser_cutting",
    "plaser":               "laser_cutting",
    "fold":                 "folding",
    "folding":              "folding",
    "l/bend":               "folding",
    "linebend":             "folding",
    "line":                 "folding",
    "tben":                 "folding",
    "tubebend":             "folding",
    "fold joggle":          "folding",
    "weld (co2)":           "welding",
    "weld":                 "welding",
    "weld header assembly": "welding",
    "tac weld":             "welding",
    "tack weld":            "welding",
    "spotweld":             "welding",
    "spot weld":            "welding",
    "spot":                 "spot_welding",
    "robomac":              "robomac",
    "robo":                 "robomac",
    "robot welder":         "welding",
    "weld foot assembly":   "welding",
    "dress welds":          "dress_welds",
    "dress":                "dress_welds",
    "dres":                 "dress_welds",
    "p.coat":               "powder_coating",
    "p/c":                  "powder_coating",
    "powder":               "powder_coating",
    "powder coat":          "powder_coating",
    "p-coat":               "powder_coating",
    "pcoa":                 "powder_coating",
    "tool holder rsb - p-coat": "powder_coating",
    "wet spray":            "wet_spray",
    "spry":                 "wet_spray",
    "cnc":                  "cnc",
    "cncj":                 "cnc",
    "cnc joinery":          "cnc",
    "cnc shelf":            "cnc",
    "cnc base":             "cnc",
    "punch":                "hole_machining",
    "punc":                 "hole_machining",
    "punch bottom":         "hole_machining",
    "drill":                "drilling",
    "pdrill":               "drilling",
    "pin router":           "pin_router",
    "pinr":                 "pin_router",
    "pin r":                "pin_router",
    "guillotine":           "guillotine",
    "guill":                "guillotine",
    "p.coat circ saw shelf":     "powder_coating",
    "p.coat drill holder":       "powder_coating",
    "manual labour (metal)":     "handling",
    "manual labour (acrylic)":   "handling",
    "manm":                      "handling",
    "man m":                     "handling",
    "mana":                      "handling",
    "man p":                     "handling",
    "manual handling":           "handling",
    "pacm":                 "packing_manual",
    "pacp":                 "packing_machine",
    "pacj":                 "packing_manual",
    "pack":                 "packing_manual",
    "assemble/pack (metal)":"packing_manual",
    "assemble/pack (acrylic)":"packing_manual",
    "assemble & pack":      "packing_manual",
    "assemble / pack unit": "packing_manual",
    "bulk pack":            "packing_manual",
    "collate/bulk pack":    "packing_manual",
    "assemble/bulk pack":   "packing_manual",
    "box/pallet":           "packing_manual",
    "box/palletise":        "packing_manual",
    "benc":                 "bench_work",
    "bench work joinery":   "bench_work",
    "machines joinery":     "bench_work",
    "glue":                 "glue",
    "diamond polish":       "diamond_polish",
    "d/pol":                "diamond_polish",
    "dpol":                 "diamond_polish",
    "roll":                 "roll",
    "form tube":            "roll",
    "robomac form hook":    "robomac",
    "saw":                  "guillotine",
    "apply vinyl":          "handling",
    "vinyl application":    "handling",
    "peel both sides":      "handling",
    "apply mag tape":       "handling",
    "wire forming":         "wire_forming",
    "wire form":            "wire_forming",
    "wire bending":         "wire_forming",
    "wire bender":          "wire_forming",
    "robomac form":         "wire_forming",
    "wire former":          "wire_forming",
    "coil form":            "wire_forming",
    "deburr":               "deburring",
    "deburring":            "deburring",
    "debur":                "deburring",
    "sharps removed":       "deburring",
    "sharps to be removed": "deburring",
    "remove sharps":        "deburring",
    "resistance weld":      "resistance_welding",
    "resistance welding":   "resistance_welding",
    "contact points":       "resistance_welding",
}

SDI_CODE_TO_AI: Dict[str, str] = {}
for _ai_op, _codes in AI_TO_SDI.items():
    for _code in _codes:
        if _code not in SDI_CODE_TO_AI:
            SDI_CODE_TO_AI[_code.upper()] = _ai_op

AI_DISPLAY_LABELS: Dict[str, str] = {
    "laser_cutting":    "Laser Cutting",
    "folding":          "Folding / Bending",
    "welding":          "Welding",
    "dress_welds":      "Dress Welds",
    "spot_welding":     "Spot Welding",
    "powder_coating":   "Powder Coating",
    "wet_spray":        "Wet Spray",
    "cnc":              "CNC Machining",
    "bench_work":       "Bench Work",
    "packing_manual":   "Manual Packing",
    "packing_machine":  "Machine Packing",
    "handling":         "Handling",
    "drilling":         "Drilling",
    "countersinking":   "Countersinking",
    "tapping":          "Tapping / Thread",
    "grinding":         "Grinding",
    "diamond_polish":   "Diamond Polish",
    "glue":             "Glueing / Bonding",
    "hole_machining":   "Hole Machining",
    "assembly":         "Assembly",
    "robomac":          "Robomac / Wire Former",
    "pin_router":       "Pin Router",
    "linebend":         "Linebend",
    "guillotine":       "Guillotine / Saw",
    "roll":             "Roll / Form",
    "tube_bend":        "Tube Bending",
    "wire_forming":     "Wire Forming",
    "deburring":        "Deburring / Sharp Removal",
    "resistance_welding": "Resistance Welding",
}


def normalise_operation_code(code: str) -> Optional[str]:
    """
    Convert any SDI workbook code or free-text operation description
    to a canonical AI operation name.

    Returns None if the code is noise (header rows, summary rows, etc.)
    """
    if not code:
        return None
    clean = code.strip().upper()

    _NOISE: Set[str] = {
        "PART DESCRIPTION", "LABOUR", "OPERATION", "TOTAL MATERIAL COST",
        "GAUGE", "DEPARTMENT", "TOTAL LABOUR COST (INCLUDING  DOWNTIME)",
        "TOTAL HOURS", "PART CODE", "QTY PER UNIT", "SHEET STEEL",
        "TOTAL LABOUR HOURS BY DEPT.", "BASE", "LABOUR COST",
        "DESCRIPTION", "RATE", "HOURS", "SETUP", "TOTAL",
    }
    if clean in _NOISE:
        return None
    if clean.startswith("TOTAL"):
        return None

    ai_op = SDI_CODE_TO_AI.get(clean)
    if ai_op:
        return ai_op

    lower = code.strip().lower()
    ai_op = _FREE_TEXT_MAP.get(lower)
    if ai_op:
        return ai_op

    for prefix, op in [
        ("laser",   "laser_cutting"),
        ("fold",    "folding"),
        ("weld",    "welding"),
        ("dress",   "dress_welds"),
        ("p.coat",  "powder_coating"),
        ("p/c",     "powder_coating"),
        ("powder",  "powder_coating"),
        ("punch",   "hole_machining"),
        ("drill",   "drilling"),
        ("glue",    "glue"),
        ("pack",    "packing_manual"),
        ("assemble","packing_manual"),
        ("collate", "packing_manual"),
        ("bulk pac","packing_manual"),
        ("box/",    "packing_manual"),
        ("robomac", "robomac"),
        ("roll",    "roll"),
        ("spotweld","welding"),
        ("spot weld","welding"),
        ("tac weld","welding"),
        ("apply vin","handling"),
        ("wire form","wire_forming"),
        ("wire bend","wire_forming"),
        ("wire former","wire_forming"),
        ("deburr",  "deburring"),
        ("sharp",   "deburring"),
        ("remove sharp","deburring"),
        ("resistance weld","resistance_welding"),
        ("vinyl",   "handling"),
        ("move",    "handling"),
        ("saw",     "guillotine"),
        ("guillot", "guillotine"),
        ("cnc",     "cnc"),
        ("linebend","folding"),
    ]:
        if lower.startswith(prefix):
            return op

    return None


def ai_op_to_primary_sdi_code(ai_op: str) -> Optional[str]:
    """Return the primary SDI workbook code for an AI operation name."""
    codes = AI_TO_SDI.get(ai_op, [])
    return codes[0] if codes else None


def ai_ops_match_sdi_code(ai_ops: List[str], sdi_code: str) -> bool:
    """True if any AI operation in the list maps to the given SDI code."""
    upper = sdi_code.strip().upper()
    target_ai = SDI_CODE_TO_AI.get(upper)
    if not target_ai:
        target_ai = normalise_operation_code(sdi_code)
    if not target_ai:
        return False
    return target_ai in ai_ops


def display_label(ai_op: str) -> str:
    return AI_DISPLAY_LABELS.get(ai_op, ai_op.replace("_", " ").title())


def get_all_sdi_codes_for_ai_op(ai_op: str) -> List[str]:
    return list(AI_TO_SDI.get(ai_op, []))
