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
    "process_statements",
    "states_only_a_process",
    "names_one_face",
    "own_or_mirror_finish",
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


# ── A FINISH FIELD THAT STATES A PROCESS ─────────────────────────────────────────────────
# 12173-03-202 / 203, 06-01M / 03M and the mesh 04-04M print "FINISH: WELDED". That says how
# the part is MADE, not what it is coated with, and the vocabulary is config's
# (FINISH_FIELD_PROCESS_STATEMENTS: token -> the operations that discharge it). Two readers
# share it: weld_symbols (the sheet states the weld) and the finish census in invariants
# (a statement is fabrication, not an unknown coat).
_PROCESS_STATEMENTS_DEFAULT = {
    "SPOT WELDED": ("spot_welding", "spotweld", "spot_weld", "resistance_welding"),
    "WELDED": ("welding", "weld", "spot_welding", "spotweld", "spot_weld",
               "resistance_welding"),
}


def _process_statement_vocab() -> Mapping[str, Any]:
    try:
        import config as _cfg
        vocab = getattr(_cfg, "FINISH_FIELD_PROCESS_STATEMENTS", None)
    except Exception:                                                # noqa: BLE001
        vocab = None
    return vocab if isinstance(vocab, Mapping) and vocab else _PROCESS_STATEMENTS_DEFAULT


def process_statements(finish_text: Any) -> tuple:
    """({token: {ops that discharge it}}, the finish text with every statement taken out).

    LONGEST TOKEN FIRST, WHOLE WORDS, EACH MATCH CONSUMED. "SPOT WELDED" is one statement; a
    shorter token matching inside it would leave "SPOT" behind to be read as an unknown
    finish. WELDMENT and WELD ASSEMBLY are not WELDED (whole words), so a description that
    names a weldment is not a statement."""
    vocab = _process_statement_vocab()
    upper = str(finish_text or "").upper()
    hits: dict = {}
    for token in sorted(vocab, key=lambda t: len(str(t)), reverse=True):
        pat = r"\b" + re.escape(str(token).upper()).replace(r"\ ", r"\s+") + r"\b"
        if re.search(pat, upper):
            hits[str(token).upper()] = {str(o).strip().lower() for o in (vocab[token] or ())}
            upper = re.sub(pat, " ", upper)
    rest = re.sub(r"\s+", " ", upper).strip(" -,/&:;+.")
    return hits, rest


def names_one_face(text: Any) -> bool:
    """True when a finish note names ONE face ("PAINTED TOP FACE", "TOP FACE ONLY").

    12173-03-02J is sprayed on its top face only; costed both faces, the spray time doubles.
    The pattern is config's (SINGLE_FACE_FINISH_PATTERN). A plural ("PAINTED FACES/AREA")
    names no single face."""
    try:
        import config as _cfg
        pat = getattr(_cfg, "SINGLE_FACE_FINISH_PATTERN", "") or ""
    except Exception:                                                # noqa: BLE001
        pat = ""
    if not pat:
        return False
    return bool(re.search(pat, str(text or "").upper()))


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


def states_only_a_process(finish_text: Any) -> bool:
    """True when the finish field holds a process statement and nothing that names a coat.

    A FIELD THAT ONLY STATES A PROCESS STATES NO COAT. "FINISH: WELDED" says the part leaves
    its own sheet welded; read as an unread finish, the document's powder stamp and the
    route's coat gate had nothing to weigh, so 12173's hook members (06-01M / 03M) and the
    pocket mesh (04-04M) were coated beside the weldments that hold them. For the COAT gates
    such a field reads as bare — the parent that is coated says so on its own sheet.
    finish_families itself is unchanged: the plating census still reads a WELDED member of a
    plated weldment as stating no finish of its own, which is what it always did."""
    upper = str(finish_text or "").upper()
    if not upper.strip() or finish_families(upper):
        return False
    _stated, _rest = process_statements(upper)
    # Only the statement and words that qualify nothing (a sheen, "FINISH:") remain.
    return bool(_stated) and not re.search(r"[A-Z]{3,}", re.sub(
        r"\b(?:FINISH|FINISHED|AS|ONLY|MATT|MATTE|GLOSS|SATIN)\b", " ", _rest))


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
    if not named and states_only_a_process(finish):
        named = {"bare"}
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
    if named == {"bare"} and states_only_a_process(finish):
        return (f"the part's own sheet states {finish!r} — how it is made, and no coat; a "
                f"coat on the assembly it goes into is that assembly's, not this part's")
    return (f"the drawing states {finish!r}, which is "
            f"{', '.join(sorted(named))}, not {op.replace('_', ' ')}")


def mirror_base_number(record: Mapping[str, Any]) -> str:
    """The part this record is the other hand of, or "" — the code's own marker (-H, MIR,
    Mirror<code>), else the sheet's note (mirror_of), else the mirror pass's stamp."""
    if not isinstance(record, Mapping):
        return ""
    try:
        from part_code_conventions import mirror_base
        base = mirror_base(str(record.get("part_number") or ""))
    except Exception:                                                # noqa: BLE001
        base = ""
    return (base or str(record.get("mirror_of") or "").strip()
            or str(((record.get("normalized_geometry") or {}) if isinstance(
                record.get("normalized_geometry"), Mapping) else {}).get("mirrored_from")
                   or "").strip())


def own_or_mirror_finish(record: Mapping[str, Any], lookup: Any) -> str:
    """The finish this part's own sheet states, or — for a mirrored hand that states none —
    the finish its base's sheet states.

    A HAND IS ITS BASE, OPPOSITE. 12173-04-02M-H and 07-1-02M-H have no sheet of their own;
    their bases (04-02M, 07-1-02M) state RAW. Read on their own records they stated nothing,
    so the document's powder stamp coated them while their bases were correctly bare — one
    pair of identical flats, one coated and one not. A hand takes no finish its base's sheet
    does not state, and loses none it does. `lookup(part_number)` returns a record or None."""
    own = stated_finish(record)
    if own:
        return own
    base_pn = mirror_base_number(record)
    if not base_pn or not callable(lookup):
        return ""
    try:
        base = lookup(base_pn)
    except Exception:                                                # noqa: BLE001
        base = None
    if not isinstance(base, Mapping) or base is record:
        return ""
    return stated_finish(base)

