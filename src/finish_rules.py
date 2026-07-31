"""
finish_rules.py — when the finish the drawing STATES contradicts a routed finish operation.

The second half of the gates that went dead at the canonical cutover. wb_populate's legacy
labour loop dropped powder from a part whose drawing finish is not powder, and dropped
diamond polish from a part that is powder coated; the cutover replaced that loop entirely,
so a lacquered timber panel came back out of the canonical path with a P.Coat row and a
powder-coated steel face came back with a Diamond Polish row.

WHY THE DRAWING'S ROUTING TEXT CANNOT BE TRUSTED FOR THIS. These packs carry a range-wide
specification legend — "POWDER COATED STEEL", "WELD SPECIFICATION" — that applies to the
customer's whole product family, not to this job. It is how powder and weld dressing came
to be described against timber panels the Estimate sheet charges only saw, glue, CNC and
spray for. The finish stated in the part's own title block is a different and much stronger
signal, and where it contradicts the legend it wins.

DELIBERATELY CONSERVATIVE. These rules fire only where the part's own finish is STATED and
UNAMBIGUOUS. A blank finish decides nothing — absence of a reading is not a reading. A
finish that POINTS somewhere else ("SEE ASSEMBLY") decides nothing here either: the object
that goes through the booth is often the assembly, not the part, and resolving that pointer
needs the assembly's pages. wb_populate's legacy loop still carries that richer resolution
for legacy jobs; what lives here is the subset that can be decided from the part alone,
which is what the route compiler has in hand.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Optional

__all__ = [
    "POWDER_POINTER_HINTS",
    "stated_finish",
    "finish_is_powder",
    "finish_contradiction",
]

# A finish that defers to another drawing states nothing about THIS part. Treating one as a
# non-powder finish would rule powder off every part in a pack that specifies it once, on
# the GA.
POWDER_POINTER_HINTS = (
    "SEE ASSEMBLY", "SEE GA", "AS ASSEMBLY", "PER ASSEMBLY", "REFER TO ASSEMBLY",
)

# Operations whose whole purpose is to apply or produce a surface. Only these can be
# contradicted by a stated finish; a fold is not a finish claim.
_FINISH_OPERATIONS = {
    "powder_coating": "powder",
    "wet_spray": "spray",
    "diamond_polish": "polish",
    "diamond_polishing": "polish",
    "anodising": "anodis",
    "plating": "plat",
}


def stated_finish(record: Mapping[str, Any]) -> str:
    """The finish this part's own drawing states, uppercased, or "" when it states none."""
    if not isinstance(record, Mapping):
        return ""
    value = record.get("normalized_finish")
    text = str(value or "").strip()
    if not text:
        parts = record.get("surface_finishes") or []
        if isinstance(parts, str):
            parts = [parts]
        text = " ".join(str(p) for p in parts if p).strip()
    return re.sub(r"\s+", " ", text).upper()


def finish_is_powder(finish_text: str) -> bool:
    return "POWDER" in str(finish_text or "").upper()


def _is_pointer(finish_text: str) -> bool:
    upper = str(finish_text or "").upper()
    return any(hint in upper for hint in POWDER_POINTER_HINTS)


def finish_contradiction(operation: str, finish_text: str) -> Optional[str]:
    """Why the stated finish rules this operation out, or None.

    Returns the sentence so the decision that rules the operation out carries its own
    reason — a finish line that simply vanishes from a route is indistinguishable from one
    that was never read."""
    op = str(operation or "").strip().lower()
    needle = _FINISH_OPERATIONS.get(op)
    if needle is None:
        return None
    finish = str(finish_text or "").strip().upper()
    if not finish or _is_pointer(finish):
        # Nothing stated, or stated somewhere else. Absence is not evidence.
        return None

    # DIAMOND POLISH ON A POWDER FINISH. Polishing an edge and then burying it under powder
    # is not a route, it is boilerplate that survived from the acrylic template. The powder
    # is the stated finish, so the polish is the line that goes.
    if op in ("diamond_polish", "diamond_polishing") and finish_is_powder(finish):
        return (f"the drawing states {finish!r} — a diamond-polished edge does not survive "
                f"a powder finish")

    if needle in finish.lower():
        return None
    return (f"the drawing states {finish!r}, which is not {op.replace('_', ' ')}")
