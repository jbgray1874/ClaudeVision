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

from typing import Dict, Optional, Set

__all__ = [
    "IMPOSSIBLE_OPS_BY_STOCK_FORM",
    "IMPOSSIBLE_OPS_BY_MATERIAL",
    "is_impossible_operation",
    "impossibility_reason",
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
IMPOSSIBLE_OPS_BY_MATERIAL: Dict[str, Set[str]] = {
    "acrylic": {"punch", "punching"},
}


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
    for mat_key, impossible in IMPOSSIBLE_OPS_BY_MATERIAL.items():
        if mat_key in mat and key in impossible:
            return f"{key} is not physically possible on {mat_key}"
    return None


def is_impossible_operation(operation: str, stock_form: str = "",
                            material: str = "") -> bool:
    """True when this stock form / material cannot have this operation done to it."""
    return impossibility_reason(operation, stock_form, material) is not None
