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

# A FINISH FAMILY IS NOT A KEYWORD MATCH ON THE OPERATION NAME.
#
# The first version of this rule asked whether the finish text contained the operation's
# own name — "does 'LACQUERED' contain 'spray'?" — and ruled wet_spray out when it did not.
# Lacquer IS applied through the wet-spray department, so that undercosted the exact timber
# route this gate exists to protect. A finish phrase and a department name are different
# vocabularies and cannot be compared by substring.
#
# So the drawing's words are resolved to a FAMILY, and an operation is contradicted only
# when the finish names a family that is recognised and is not this operation's. A phrase
# that resolves to nothing decides nothing — an unrecognised finish is not a contradiction,
# it is an unread one, and removing work on that basis is how a gate becomes a delete.
FINISH_FAMILIES = {
    "powder": ("POWDER",),
    # Lacquer, paint and varnish all go through the spray booth.
    "wet_spray": ("LACQUER", "PAINT", "WET SPRAY", "SPRAY", "ENAMEL", "VARNISH"),
    "polish": ("DIAMOND POLISH", "FLAME POLISH", "POLISH"),
    "anodise": ("ANODIS",),
    "plate": ("PLATED", "PLATING", "ZINC", "NICKEL", "CHROME", "GALVAN"),
    # An explicit statement that the part is NOT finished. The legacy gate treated these
    # the same way, and it is the reading that keeps powder off a bare bracket.
    "bare": ("RAW", "SELF COLOUR", "SELF-COLOUR", "MILL FINISH", "SCRAPED",
             "UNFINISHED", "NO FINISH", "NONE"),
}

# Operations whose whole purpose is to apply or produce a surface, and the family each one
# belongs to. Only these can be contradicted by a stated finish; a fold is not a finish
# claim.
_OPERATION_FAMILY = {
    "powder_coating": "powder",
    "wet_spray": "wet_spray",
    "diamond_polish": "polish",
    "diamond_polishing": "polish",
    "anodising": "anodise",
    "plating": "plate",
}


def finish_families(finish_text: str) -> set:
    """The finish families the drawing's words name, or an empty set when none are
    recognised. Empty means unread, never "no finish" — "RAW" is how a drawing says that,
    and it has its own family.

    THE TOKENS ARE STEMS, AND THE BOUNDARY BELONGS ONLY AT THE START.

    Plain substring matching read "AS DRAWING REV C" as a BARE finish, because "d-RAW-ing"
    contains RAW — which would have ruled powder coating off any part whose finish field
    points at the drawing. The same lesson as the bought-in exclusion matcher: a token
    inside a longer word is not that token.

    Anchoring BOTH ends then broke the opposite way: drawings write LACQUERED, PAINTED,
    ANODISED, POLISHED, and \\bLACQUER\\b matches none of them. So the boundary is required
    before the stem and free after it — "LACQUERED" matches, "DRAWING" does not, and
    "UNPAINTED" does not either, which is the conservative direction."""
    upper = str(finish_text or "").upper()
    return {
        family for family, tokens in FINISH_FAMILIES.items()
        if any(re.search(r"\b" + re.escape(token).replace(r"\ ", r"\s+"), upper)
               for token in tokens)
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
    family = _OPERATION_FAMILY.get(op)
    if family is None:
        return None
    finish = str(finish_text or "").strip().upper()
    if not finish or _is_pointer(finish):
        # Nothing stated, or stated somewhere else. Absence is not evidence.
        return None

    named = finish_families(finish)
    if not named:
        # The drawing says SOMETHING and we do not recognise it. That is an unread finish,
        # not a contradiction, and work must not be removed on the strength of it.
        return None
    if family in named:
        return None

    # A recognised finish that is not this operation's. Named both ways round so the
    # decision explains itself: what the drawing said, and what it therefore is not.
    if family == "polish" and "powder" in named:
        return (f"the drawing states {finish!r} — a diamond-polished edge does not survive "
                f"a powder finish")
    return (f"the drawing states {finish!r}, which is "
            f"{', '.join(sorted(named))}, not {op.replace('_', ' ')}")
