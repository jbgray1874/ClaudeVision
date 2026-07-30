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
    "unresolved_operations", "CODE_TITLES", "LEGACY_TITLES",
]

# TITLES THIS ENGINE USED TO WRITE, and the code they really belong to.
#
# The titles were corrected against the workbook's own rate table, but every job JSON
# already saved on disk carries the OLD string. A consumer that only knows the current
# spelling reads those rows as an unknown operation, so a finished job re-opened tomorrow
# silently loses its finish or its route.
#
# Deliberately an explicit list of RENAMES, not the alias table: the aliases include engine
# operation words ("assembly", "handling", "fold"), and treating those as department titles
# re-expands every synonym — which is the exact defect costed_facts exists to prevent.
LEGACY_TITLES: Dict[str, str] = {
    "Spray / Wet Paint": "SPRY",
    "CNC / Joinery machining": "CNCJ",
    "Gluing / Bonding": "GLUE",
    "Drilling / Tapping": "DRIL",
    "Pin Router": "PINR",
    "Salvage / Rework": "SALV",
    "Bench work / fitting": "BENC",
    # GRIN was never a real department. Rows carrying it were deburring, which now costs at
    # manual labour (metal) rather than at a joinery bench.
    "Grinding / Deburr": "MANM",
}

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
    "PACP": ("Assemble/pack (Acrylic)", True),
    "PACM": ("Assemble/pack (Metal)", True),
    "BENC": ("Bench Work Joinery", True),
    "CNC":  ("CNC", True),
    "CNCJ": ("CNC Joinery", True),
    "DPOL": ("Diamond Polish", True),
    "DRES": ("Dress Welds", True),
    # The title literally says Acrylic; the shop uses this row for metal drilling and
    # tapping too. Confirmed by the estimators, so the string stands as the table has it.
    "DRIL": ("Drill (Acrylic)", True),
    "EDGE": ("Edge Banding", True),
    "FOLD": ("Fold", True),
    "GLUE": ("Glue", True),
    "GUIL": ("Guillotine", True),
    "LASA": ("Laser (Acrylic)", True),
    "LASM": ("Laser (Metal)", True),
    "LINE": ("Linebend", True),
    "MC J": ("Machines Joinery", True),
    "MANA": ("Manual labour (Acrylic)", True),
    "MANM": ("Manual labour (Metal)", True),
    "OVEN": ("Oven", True),
    "P/C":  ("P.Coat", True),
    "PACJ": ("Packing Joinery", True),
    "PINR": ("Pin router", True),
    "PUNC": ("Punch", True),
    "ROBO": ("Robomac", True),
    "ROLL": ("Roll", True),
    # A Salvagnini panel bender, not "salvage/rework" -- which is what this was guessed as,
    # and would have sent reworked parts to a forming machine.
    "SALV": ("Salvagnini", True),
    "SAW":  ("Saw", True),
    "SPOT": ("Spotweld", True),
    "TUBE": ("Tube", True),
    "TBEN": ("Tubebend", True),
    "WELD": ("Weld (CO2)", True),
    "SPRY": ("Wet Spray", True),
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
_alias("BENC", "bench_work", "bench work", "bench work joinery")
# DEBURRING IS METAL WORK AND BENC IS A JOINERY BENCH.
# BENC's real title is "Bench Work Joinery". Deburring and fettling a steel part at the
# joinery bench rate is the wrong rate, so they go to MANM, Manual labour (Metal). Raised
# with the estimators; a wrong-but-visible department beats a right-sounding zero.
_alias("MANM", "deburring", "deburr", "fettling", "finishing")
_alias("DRIL", "hole_machining", "hole machining", "drilling", "drill", "tapping", "tap",
       "countersink", "countersinking")
_alias("CNCJ", "cnc_routing", "cnc routing", "cnc_joinery", "cnc joinery", "routing",
       "cnc / joinery machining")
_alias("MC J", "machines joinery", "mcj")
_alias("CNC",  "cnc", "cnc machining")
_alias("PINR", "pin_router", "pin router")
_alias("EDGE", "edge_banding", "edge banding", "edgeband")
_alias("GLUE", "glue", "gluing", "glueing", "bonding", "solvent bond", "gluing / bonding")
_alias("P/C",  "powder_coating", "powder coating", "powder coat", "powder", "p.coat",
       "p/c", "pc", "powdercoat")
_alias("SPRY", "wet_spray", "wet spray", "spray", "spray paint", "wet paint",
       "spray / wet paint")
_alias("DPOL", "diamond_polish", "diamond polish", "diamond polishing", "polish")
_alias("ROBO", "robomac", "wire_forming", "wire forming", "wire form")
_alias("OVEN", "oven", "curing", "cure", "bake")
_alias("PACM", "handling", "assembly", "assemble", "assemble/pack (metal)", "pack",
       "packing", "packaging", "assemble & pack", "final assembly", "fit", "fitting")
_alias("PACP", "assemble/pack (acrylic)", "assemble/pack acrylic", "assemble acrylic",
       "carton", "cartoning")
_alias("PACJ", "packing joinery", "packaging - joinery")
_alias("MANM", "manual labour (metal)", "manual labour", "manual handling")
_alias("MANA", "manual labour (acrylic)")
_alias("SALV", "salvagnini", "panel bender", "panel bending")

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
