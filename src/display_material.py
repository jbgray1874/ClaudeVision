"""What a line is made of, as a document may state it — one fact, one place.

James Gray, 18 September 2026:

    "`display_material` is still worthwhile next, to stop bought-in items such as tape
     inheriting the assembly's steel material on any output."

THE TITLE BLOCK DESCRIBES THE DRAWING, NOT EVERY ROW ON IT. A drawing sheet states one
material and the engine stamps it onto the parts it found there, which is right for the
fabricated leaves — they ARE that material — and wrong for every bought-in on the same parts
table. The magnetic tape came out as ACRYLIC on 0355255 and MILD STEEL on 401912-02, beside a
description that says EPDM in the first case and TAPE in the second, because the row inherited
the sheet's reading and nothing recorded that it had.

AND IT IS THE SAME SHAPE AS THE OTHER TWO. `fold_count` was three facts read as one; the
£3.88 was one fact re-derived by five renderers. Here it is one figure with the wrong OWNER:
a reading that belongs to the sheet, printed as though it belonged to the row. So it is
answered once and every consumer asks, rather than each surface learning its own exceptions —
`costed_facts._material_label` already knew about commercial lines, subcontract services and
roll goods, and the four other surfaces that print a material knew about none of them.

── WHEN A BOUGHT-IN'S MATERIAL MAY BE PRINTED ──────────────────────────────────────────────

Only when it came from a source that is ABOUT THAT PART. The engine records `material_source`
per field and has for months; it was being used for confidence and provenance and never for
this. A bought-in whose material was read from its own parts-table row, confirmed by an
estimator, or taken from its own model, is stating something about itself. One carrying the
sheet's title block is carrying the assembly's material, and printing it is the whole defect.

WHAT IT SAYS INSTEAD IS "— (bought-in)", not a guess. A bought-in is BOUGHT: what it is made
of does not price it, and the description the drawing office typed is still on the line for
anyone who wants to know. Inventing a material for it from its description would be a fourth
opinion about a question nobody needs answered.

THIS CHANGES NOTHING FOR A FABRICATED PART. A leaf's title block IS its own drawing's title
block, which is exactly the right source for what it is made of. The rule is narrow on purpose:
it fires on the lines where the reading demonstrably belongs to somebody else.
"""
from typing import Any, Dict, Mapping, Optional

# What a renderer prints, and where the reading came from.
OWN = "own"                  # the part's own evidence
KIND = "kind"                # the line is not made of anything (commercial, service)
ROLL = "roll"                # priced by length off a roll; the roll is in the description
INHERITED = "inherited"      # a reading that belongs to the sheet, withheld
NOTHING = "none"

# Sources that describe the DRAWING SHEET or the engine's own reasoning rather than the row.
# A bought-in carrying one of these is carrying somebody else's material.
#
# `title_block` heads the list and is the whole reason this module exists. `bom_tree` is here
# too and it is the near miss: it means "the bill of materials said so", which for a material
# is the parent assembly's structure and not a statement about the bought part.
SHEET_LEVEL_SOURCES = frozenset({
    "title_block", "pdf_overall_dims", "dxf_filename", "bom_tree",
    "compiler_default", "inference", "geometry_inference", "unknown", "",
})

_KIND_LABEL = {
    "commercial": "— (commercial line)",
    "service": "— (subcontract service)",
}


def _mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _clean(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _source_of(part: Mapping[str, Any]) -> str:
    """`material_source`, reduced to its key.

    Stamped as `override_rule:SOMENAME` in one case, so the prefix before the colon is what
    is compared — a rule an estimator wrote IS about the part.
    """
    raw = _clean(part.get("material_source")).lower()
    return raw.split(":", 1)[0] if raw else ""


def is_roll_goods(part: Mapping[str, Any]) -> bool:
    """Priced by the length used, off a roll. The roll's own identity is in the description."""
    me = _mapping(part.get("material_estimate"))
    return (_clean(me.get("stock_form")).lower() == "roll"
            or _clean(me.get("cost_method")).lower().startswith("roll_goods"))


def display_material(part: Mapping[str, Any], kind: Any = "") -> Dict[str, Any]:
    """{text, basis, source, inherited, why} — what this line's Material column may say.

    `kind` is the costed record's line kind where the caller has it (`costed_facts._line_kind`
    answers it). Callers that do not are served correctly for everything but the distinction
    between a bought-in and a leaf, which they get from the part's own roles.
    """
    if not isinstance(part, Mapping):
        return {"text": "Unknown", "basis": NOTHING, "source": "", "inherited": False,
                "why": "no part"}

    kind = _clean(kind).lower() or _kind_from_part(part)
    if kind in _KIND_LABEL:
        return {"text": _KIND_LABEL[kind], "basis": KIND, "source": _source_of(part),
                "inherited": False,
                "why": "this line is a charge, not a thing that is made of something"}

    if is_roll_goods(part):
        return {"text": "Roll goods (priced by length)", "basis": ROLL,
                "source": _source_of(part), "inherited": False,
                "why": ("priced by the length used; what the roll is stays in the "
                        "description, where the drawing office put it")}

    stated = _clean(part.get("normalized_material") or part.get("material"))
    source = _source_of(part)

    if kind == "bought_in":
        if not stated or stated.upper() == "BOUGHT_IN":
            return {"text": "— (bought-in)", "basis": NOTHING, "source": source,
                    "inherited": False, "why": "nothing states what this is made of"}
        if not material_is_the_parts_own(part):
            # THE DEFECT, NAMED RATHER THAN PRINTED. The reading is kept on the record so a
            # reader can see what was inherited and from where; it is not the Material column.
            return {"text": "— (bought-in)", "basis": INHERITED, "source": source,
                    "inherited": True,
                    "why": (f"the only material on this line is {stated}, read from "
                            f"{source or 'no recorded source'} — which describes the drawing "
                            f"sheet, not a part bought in on it")}
        return {"text": stated, "basis": OWN, "source": source, "inherited": False,
                "why": f"stated for this part by {source}"}

    if not stated:
        return {"text": "Unknown", "basis": NOTHING, "source": source, "inherited": False,
                "why": "nothing states what this is made of"}
    return {"text": stated, "basis": OWN, "source": source, "inherited": False, "why": ""}


def material_is_the_parts_own(part: Mapping[str, Any]) -> bool:
    """Whether the material on this line was stated ABOUT THIS PART.

    TWO SIGNALS, AND BOTH WERE ALREADY IN THE RECORD.

    `material_source` says which reader produced it, and the engine has stamped it per field
    for months — it was being used for confidence and provenance and never for this.

    `page_roles` says which kinds of page this part appears on, and
    `estimate_explained._material_stated` was already using it for exactly this question, on
    exactly one column, with its own private rule: *"a line whose only page role is bought_in
    has no detail drawing, so the sheet it appears on states the assembly's material and not
    its own. Where a bought-in DOES have a detail drawing the material on it is genuinely the
    part's."* That is right, and it belongs here rather than in one renderer, which is the
    whole argument of this module.

    A DETAIL PAGE SETTLES IT EITHER WAY. Where a bought-in has its own drawing, that drawing's
    title block IS its own — so the source test does not apply and the material is printed.
    """
    roles = [_clean(r).lower() for r in (part.get("page_roles") or [])]
    if "detail" in roles:
        return True
    return _source_of(part) not in SHEET_LEVEL_SOURCES


def _kind_from_part(part: Mapping[str, Any]) -> str:
    """A caller's best answer where the costed record's kind was not passed in.

    Deliberately narrow: it recognises the two placeholder kinds by the marks the mints leave
    and a bought-in by its roles, and calls everything else a leaf — which is what the old
    per-surface code did for every line, so nothing gets worse where this cannot tell.
    """
    pn = _clean(part.get("part_number")).upper()
    method = _clean(_mapping(part.get("material_estimate")).get("cost_method")
                    or part.get("cost_source") or part.get("source")).lower()
    if part.get("_plating_placeholder") or "plating" in method or pn.endswith("-PLATE"):
        return "service"
    if (part.get("_commercial_placeholder")
            or _clean(part.get("source")) == "commercial_placeholder"
            or pn in ("PACKAGING", "DELIVERY")):
        return "commercial"
    if _clean(part.get("canonical_kind")):
        return _clean(part.get("canonical_kind")).lower()
    roles = [_clean(r).lower() for r in (part.get("page_roles") or [])]
    if "bought_in" in roles or _clean(part.get("normalized_material")).upper() == "BOUGHT_IN":
        return "bought_in"
    return "leaf"


def material_text(part: Mapping[str, Any], kind: Any = "") -> str:
    """The string alone, for a renderer that wants one."""
    return display_material(part, kind)["text"]


def describes_the_product(part: Mapping[str, Any], kind: Any = "") -> Optional[str]:
    """The material where it says something about WHAT THE CUSTOMER IS BUYING, else None.

    The quotation's Material line is built by collecting the distinct materials across the
    job's parts. A bought-in carrying the sheet's reading adds nothing there — at best it
    repeats what a fabricated part already said, and at worst it puts a second material on a
    customer's quotation for a product made of one.
    """
    fact = display_material(part, kind)
    return fact["text"] if fact["basis"] == OWN else None
