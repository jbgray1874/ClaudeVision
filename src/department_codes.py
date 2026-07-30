"""
department_codes.py — the shop's closed vocabulary, in one place.

THE RATE TABLE IS THE ONLY VOCABULARY THAT PAYS.

The estimating workbook resolves a labour line against its own rate table (H173:K204). A
string that does not resolve produces a blank department, a zero rate and a zero cost — and
a zero-cost labour line is indistinguishable, on the sheet, from work that was never
identified at all. That is the worst failure mode this engine has: it is silent, it always
reduces the price, and nothing about the output says it happened.

The engine had TWO vocabularies and neither of them was the rate table:

  wb_populate.OP_NAME_MAP     engine op -> a workbook TITLE  ("Laser (Metal)", "Tube")
  config.SDI_OPERATION_CODES  engine op -> a CODE            (LASM, FOLD, ...)

Diffed against the real table, 18 of its 32 codes were absent from SDI_OPERATION_CODES —
including TUBE, SAW, TBEN, EDGE, ROLL, PUNC, LASA, GUIL, LINE, ROBO, DRES — and 5 codes the
engine believed in are not in the table at all: COUN, GRIN, HAND, PC, TAP. Every operation
routed to one of those five has been costing nothing, quietly. `deburring` is one of them.

So: one table, taken from the rate table itself, and a check that fails loudly rather than
a lookup that returns zero.

TITLES ARE MARKED. `title_confirmed=False` means the code is real (it is in the rate table)
but the exact title string the workbook matches on has NOT been read back from the template
— the template lives on the share, not in this repo. Those are safe to emit as codes and
must be confirmed before they are trusted as titles.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

__all__ = [
    "DEPARTMENT_CODES", "OPERATION_ALIASES", "code_for", "title_for",
    "unresolved_operations", "CODE_TITLES",
]

# The closed vocabulary, exactly as the workbook's rate table carries it.
DEPARTMENT_CODES = frozenset({
    "PACP", "PACM", "BENC", "CNC", "CNCJ", "DPOL", "DRES", "DRIL",
    "EDGE", "FOLD", "GLUE", "GUIL", "LASA", "LASM", "LINE", "MC J",
    "MANA", "MANM", "OVEN", "P/C", "PACJ", "PINR", "PUNC", "ROBO",
    "ROLL", "SALV", "SAW", "SPOT", "TUBE", "TBEN", "WELD", "SPRY",
})

# code -> (workbook title, title_confirmed). Confirmed titles are ones this engine has
# already put on a sheet and seen come back with a non-zero rate.
CODE_TITLES: Dict[str, Tuple[str, bool]] = {
    "LASM": ("Laser (Metal)", True),
    "P/C":  ("P.Coat", True),
    "PACM": ("Assemble/pack (Metal)", True),
    "FOLD": ("Fold", True),
    "WELD": ("Weld (CO2)", True),
    "SPOT": ("Spotweld", False),
    "DRES": ("Dress Welds", False),
    "SAW":  ("Saw", False),
    "TUBE": ("Tube", False),
    "TBEN": ("Tubebend", False),
    "LINE": ("Linebend", False),
    "ROLL": ("Roll", False),
    "PUNC": ("Punch", False),
    "GUIL": ("Guillotine", False),
    "LASA": ("Laser (Acrylic)", False),
    "CNCJ": ("CNC / Joinery machining", False),
    "CNC":  ("CNC", False),
    "MC J": ("MC J", False),
    "PINR": ("Pin Router", False),
    "EDGE": ("Edge Banding", False),
    "GLUE": ("Gluing / Bonding", False),
    "SPRY": ("Spray / Wet Paint", False),
    "DPOL": ("Diamond Polish", False),
    "ROBO": ("Robomac", False),
    "DRIL": ("Drilling / Tapping", False),
    "BENC": ("Bench work / fitting", False),
    "MANM": ("Manual labour (Metal)", False),
    "MANA": ("Manual labour (Acrylic)", False),
    "PACP": ("Packaging - Carton", False),
    "PACJ": ("Packaging - Joinery", False),
    "OVEN": ("Oven", False),
    "SALV": ("Salvage / Rework", False),
}

# Everything the engine, the extract prompts, or a model writing English might emit, mapped
# onto a code the rate table carries. Keys are lower-cased and space/underscore-insensitive
# (see _norm), so "tube_cut", "tube cut" and "TUBE CUT" are one entry.
#
# The five that were missing entirely — tube_cut, tube_bending, hole_machining, tapping,
# edge_banding — are here, and so is every free-text form a model actually produces. There
# is no TAP, GRIN, COUN or HAND row in the rate table, so tapping goes to DRIL (the shop
# drills and taps on the same bench), deburring to BENC, and handling to PACM.
OPERATION_ALIASES: Dict[str, str] = {}


def _norm(s: Any) -> str:
    return " ".join(str(s or "").strip().lower().replace("_", " ").split())


def _alias(code: str, *names: str) -> None:
    for n in names:
        OPERATION_ALIASES[_norm(n)] = code


_alias("LASM", "laser_cutting", "laser", "laser cut", "laser cutting", "laser (metal)",
       "laser metal", "profile cut", "profiling")
_alias("LASA", "laser acrylic", "laser (acrylic)", "acrylic laser")
_alias("PUNC", "punch", "punching")
_alias("GUIL", "guillotine", "shear", "shearing")
_alias("SAW",  "saw", "sawing", "saw tube", "cut to length", "cut off", "docking")
_alias("TUBE", "tube_cut", "tube cut", "tube cutting", "tube", "tube prep", "notching",
       "cut tube", "cut outer tube", "cut inner tube")
_alias("TBEN", "tube_bending", "tube bend", "tubebend", "tube bender")
_alias("FOLD", "folding", "fold", "press brake", "form", "forming", "bend", "bending")
_alias("LINE", "linebend", "line bend", "line bending")
_alias("ROLL", "roll", "rolling", "roll form")
_alias("WELD", "welding", "weld", "mig weld", "tig weld", "co2 weld", "mig", "tig",
       "weld (co2)", "welding (mig/tig)", "fabricate", "fabrication")
_alias("SPOT", "spotweld", "spot weld", "spot_weld", "resistance welding")
_alias("DRES", "dress_welds", "dress welds", "dress", "dressing", "linish", "linishing",
       "linisher")
_alias("BENC", "deburring", "deburr", "bench_work", "bench work", "fettling", "finishing")
_alias("DRIL", "hole_machining", "hole machining", "drilling", "drill", "tapping", "tap",
       "countersink", "countersinking")
_alias("CNCJ", "cnc_routing", "cnc routing", "cnc_joinery", "cnc joinery", "routing",
       "cnc / joinery machining")
_alias("CNC",  "cnc", "cnc machining")
_alias("PINR", "pin_router", "pin router")
_alias("EDGE", "edge_banding", "edge banding", "edgeband")
_alias("GLUE", "glue", "gluing", "glueing", "bonding", "solvent bond")
_alias("P/C",  "powder_coating", "powder coating", "powder coat", "powder", "p.coat",
       "p/c", "pc", "powdercoat")
_alias("SPRY", "wet_spray", "wet spray", "spray", "spray paint", "wet paint")
_alias("DPOL", "diamond_polish", "diamond polish", "diamond polishing", "polish")
_alias("ROBO", "robomac", "wire_forming", "wire forming", "wire form")
_alias("OVEN", "oven", "curing", "cure", "bake")
_alias("PACM", "handling", "assembly", "assemble", "assemble/pack (metal)", "pack",
       "packing", "packaging", "assemble & pack", "final assembly", "fit", "fitting")
_alias("PACP", "carton", "cartoning", "packaging - carton")
_alias("PACJ", "packaging - joinery")
_alias("MANM", "manual labour (metal)", "manual labour", "manual handling")
_alias("MANA", "manual labour (acrylic)")
# ACRYLIC ASSEMBLY — the one title this engine emits that the code list does not settle.
# OP_NAME_MAP_ACRYLIC has been writing "Assemble/pack (Acrylic)" for a long time, but the
# rate table's packing codes are PACP, PACM and PACJ and none of them says "acrylic". PACM
# ("Packaging - Manual / Assembly") is the generic manual-assembly row and definitely
# exists, so it is used: costing acrylic assembly at the manual-assembly rate is a small,
# visible error, and costing it at zero is an invisible one. CONFIRM against H173:K204
# whether acrylic assembly belongs to PACP or PACJ instead.
_alias("PACM", "assemble/pack (acrylic)", "assemble/pack acrylic")
_alias("SALV", "salvage", "rework")

# A code is always its own alias, so a model told to answer in codes is understood.
for _c in DEPARTMENT_CODES:
    OPERATION_ALIASES.setdefault(_norm(_c), _c)


def code_for(operation: Any) -> Optional[str]:
    """The rate-table code for an operation, or None if nothing recognises it.

    None is the whole point: it is the difference between "we could not price this" and a
    zero that reads like "this work does not exist"."""
    n = _norm(operation)
    if not n:
        return None
    hit = OPERATION_ALIASES.get(n)
    if hit:
        return hit
    # A model asked for a code and given a department title will sometimes answer with the
    # title. Match that too rather than dropping the line.
    for code, (title, _ok) in CODE_TITLES.items():
        if _norm(title) == n:
            return code
    return None


def title_for(operation: Any) -> Optional[str]:
    """The workbook title to write for an operation, or None if it does not resolve."""
    code = code_for(operation)
    if not code:
        return None
    entry = CODE_TITLES.get(code)
    return entry[0] if entry else None


def unresolved_operations(operations: Any) -> list:
    """Which of these operations the rate table cannot pay for. Report, never swallow."""
    return [str(o) for o in (operations or []) if o and not code_for(o)]
