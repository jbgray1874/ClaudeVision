"""
stock_form_rules.py — what a given stock form physically cannot have done to it.

One table, two readers. These rules were written inside wb_populate's legacy labour loop,
and the canonical route cutover replaced that loop wholesale: `for pe in ([] if
_canonical_cutover else labour_parts)`. Every gate in it — including this one — stopped
running the moment the cutover was enabled, and nothing failed, because a gate that is
never asked reports nothing. A solid 8mm round bar came back out of the canonical path
carrying a Laser (Metal) row, which is the exact defect the wire entry below was written
for.

So the rules live here, where the route COMPILER can apply them as decisions and the
workbook renderer can keep applying them to any legacy job. Duplicating them in the
compiler would have left two tables to update and one of them silently stale — the same
shape as the defect.

WHAT THIS IS NOT. This is not a route opinion competing with the drawing. A laser cannot
profile a solid round bar whoever says it should, so a claim to the contrary is not
outranked, it is impossible. Nor is it a remap: an operation the shop performs on different
equipment for this stock form (a tube is sawn, not lasered; acrylic is line-bent, not
press-braked) belongs in wb_populate's operation maps, which redirect the work. Deleting
work the shop really does is the expensive half of this distinction — 2085's tubes lost
their cut entirely to an over-broad entry here and were costed as if they arrived at
length.
"""
from __future__ import annotations

import re
from typing import Dict, Optional, Set

__all__ = [
    "IMPOSSIBLE_OPS_BY_STOCK_FORM",
    "IMPOSSIBLE_OPS_BY_MATERIAL",
    "is_impossible_operation",
    "impossibility_reason",
    "non_metal_reason",
]

IMPOSSIBLE_OPS_BY_STOCK_FORM: Dict[str, Set[str]] = {
    # A TUBE HAS NO FLAT BLANK, SO IT IS NOT PUNCHED.
    #
    # Cutting is NOT here. A tube is still cut to length — it is sawn rather than
    # profile-lasered — and that redirection lives in wb_populate's _TUBE_OP_REMAP. When
    # laser/guillotine sat in this table instead, 2085's two tubes came off the sheet with
    # no cutting operation of any kind and the cut was free.
    #
    # Putting a hole through a tube wall is not cutting it to length, and hole work has its
    # own operation, so punch stays impossible.
    "tube": {"punch", "punching"},
    # A SOLID ROUND BAR HAS NO FLAT BLANK EITHER, AND UNLIKE A TUBE IT HAS NO WALL.
    # It cannot be lasered, folded, punched, line-bent, guillotined or diamond-polished.
    # It is cut (Robomac / Saw) and welded. 1310-02 STUD (8mm dia x 65) carried Laser £4.91
    # from a misread that treated its DIAMETER as an 8mm sheet THICKNESS.
    "wire": {
        "laser", "laser_cutting", "laser_metal",
        "fold", "folding",
        "punch", "punching",
        "linebend", "line_bend",
        "guillotine",
        "diamond_polish",
    },
}

# Acrylic is laser- or CNC-cut, never punched — a punch press shatters it.
#
# AND NOTHING NON-METAL GOES THROUGH THE POWDER OVEN. Powder coating cures at 180-200 C:
# melamine faced chipboard delaminates, MDF swells and off-gasses, acrylic softens and
# distorts. This is not a preference, it is what the oven does.
#
# It matters because a GA states ONE finish for a whole product and the compiler propagates
# it. 12422-24 is a 28mm MFC panel with three powder-coated steel brackets on it, and
# nothing else stopped the panel taking a P.Coat event off the assembly's finish note.
# Board finishes are laminate, foil, veneer, lacquer and paint — all of which are applied
# cold and none of which are this operation.
_NON_METAL_COATING_OPS = {"powder_coating", "powder_coat", "powder", "p_coat", "pcoat"}
IMPOSSIBLE_OPS_BY_MATERIAL: Dict[str, Set[str]] = {
    # NON-COATING impossibilities only. The oven rule is NOT enumerated here — see
    # non_metal_reason below. This table listed eleven materials by name and PETG was not
    # one of them, so 11650's PETG side panels were held to be powder-coatable and booked
    # coated area on a sheet whose own finish resolver had just concluded that nothing in
    # the job is coated. Enumerating the members of a physical class is how the twelfth
    # member gets billed for an oven it would melt in.
    "acrylic": {"punch", "punching"},
}

# ── WHAT IS NOT METAL ───────────────────────────────────────────────────────────────
# The rule is about the CLASS, so the code has to name the class. Powder cures at
# 180-200 C: every thermoplastic softens or melts, every board delaminates or off-gasses.
# There is no plastic for which this is untrue, which is why the answer must not depend on
# whether somebody remembered to add a trade name.
#
# TWO LISTS, BECAUSE TWO KINDS OF NAME MATCH DIFFERENTLY. The long names are unambiguous
# anywhere they appear; the abbreviations are two to four letters and matching those as
# substrings is how "ABSORBER" becomes plastic and, worse, how a metal picks up a plastic
# rule. wb_populate learned this the expensive way: "LED" is a non-metal keyword there, and
# COLD ROLLED STEEL and ANNEALED STAINLESS both contain it.
_NON_METAL_NAMES = (
    "ACRYLIC", "PERSPEX", "POLYCARBONATE", "POLYPROPYLENE", "POLYSTYRENE",
    "POLYETHYLENE", "POLYTHENE", "POLYESTER", "STYRENE", "VINYL", "NYLON",
    "ACETAL", "DELRIN", "PLASTIC", "FOAMEX", "FOAMED PVC", "CORREX",
    "MELAMINE", "CHIPBOARD", "PLYWOOD", "TIMBER", "HARDBOARD", "PLASTICS",
    "WOOD", "OAK", "BEECH", "BIRCH", "PINE", "SPRUCE", "MDF",
)
_NON_METAL_CODES = frozenset({
    "PETG", "PET", "PC", "PP", "PE", "PS", "PVC", "ABS", "HIPS", "PMMA",
    "HDPE", "LDPE", "UHMW", "MFC", "MDF", "HPL", "PU",
})
# A METAL SAYS SO, AND IT WINS. "PLASTIC COATED STEEL" is steel with a plastic finish on
# it, and it goes through the booth like any other steel. Checked first so no coating
# vocabulary can reclassify a metal — the failure that would cost real money here.
_METAL_NAMES = (
    "STEEL", "STAINLESS", "ALUMINI", "ALUMINU", "GALV", "ZINTEC", "BRASS",
    "COPPER", "BRONZE", "IRON", "CR4", "MILD", "TITANIUM", "ZINC",
)
_TOKEN_SPLIT = re.compile(r"[^A-Z0-9]+")


def non_metal_reason(material: str = "") -> Optional[str]:
    """The name that makes this material non-metal, or None.

    Public because two other modules were each keeping a private four-plastic set and
    answering this question differently — which is how one job's powder OPERATION was
    correctly refused while its powder MATERIAL was billed anyway.
    """
    mat = str(material or "").upper().replace("_", " ")
    if not mat.strip():
        return None
    if any(m in mat for m in _METAL_NAMES):
        return None
    for name in _NON_METAL_NAMES:
        if name in mat:
            return name
    for token in _TOKEN_SPLIT.split(mat):
        if token in _NON_METAL_CODES:
            return token
    return None


def impossibility_reason(operation: str, stock_form: str = "",
                         material: str = "") -> Optional[str]:
    """Why this operation cannot happen here, or None when it can.

    Returns the sentence rather than a bare bool so the decision that rules the operation
    out can carry its own reason. A route line removed with no stated cause is
    indistinguishable from one that was never read, and an estimator cannot tell whether
    the engine decided or simply lost it."""
    key = str(operation or "").strip().lower()
    if not key:
        return None
    sf = str(stock_form or "").strip().lower()
    if key in IMPOSSIBLE_OPS_BY_STOCK_FORM.get(sf, frozenset()):
        return (f"{key} is not physically possible on stock form {sf!r} — "
                f"the part has no flat blank to work")
    mat = str(material or "").strip().lower()
    if key in _NON_METAL_COATING_OPS:
        # ASKED AS A CLASS, NOT AS A LIST OF NAMES.
        found = non_metal_reason(material)
        if found:
            return (f"{key} cures at 180-200 C and {found.lower()} cannot go through the "
                    f"oven — board and plastic are finished cold (laminate, foil, veneer, "
                    f"lacquer, paint). A finish stated once for a whole product does "
                    f"not make its non-metal parts powder-coatable.")
    for mat_key, impossible in IMPOSSIBLE_OPS_BY_MATERIAL.items():
        if mat_key in mat and key in impossible:
            return f"{key} is not physically possible on {mat_key}"
    return None


def is_impossible_operation(operation: str, stock_form: str = "",
                            material: str = "") -> bool:
    """True when this stock form / material cannot have this operation done to it."""
    return impossibility_reason(operation, stock_form, material) is not None
