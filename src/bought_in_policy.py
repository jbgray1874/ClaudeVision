"""
bought_in_policy.py — one answer to "do we MAKE this part, or do we BUY it?"

That question was being answered in four places with four different rules
(estimation_report, job_decision_report, the estimator's dedup pass, and the estimator's
own bought_in_candidate logic), which is how one record came to be a catalogue line on the
BOM and a fabricated part carrying weld, powder and glue labour on the route at once.

The rule, and why:

  CATALOGUE IDENTITY DECIDES. A part matching a bought-in code family, carrying a
  bought-in page role, or priced as a catalogue line IS bought in. A drawing existing for
  it changes nothing — we routinely draw bought-in components so they can be located on an
  assembly, and treating "has a drawing" as evidence of fabrication is what let fabrication
  labour attach to purchased items.

  CONFLICTS ARE FLAGGED, NOT RESOLVED SILENTLY. Where a part is bought-in by identity and
  ALSO carries genuine fabrication evidence — its own flat pattern, a modelled cut list —
  the two sources disagree about what the part is. That deserves an estimator's attention
  and is recorded on the part. It is not grounds for the engine to overrule the catalogue
  on its own: the failure mode of guessing wrong here is fabrication labour booked against
  something we simply buy.

Deliberately identity-only — no cost, no route, no timing — so it is safe to call at any
stage, including BEFORE process costing. That is the point: the cost of getting this wrong
is labour on a purchased item, and by costing time it is already too late to ask cheaply.
"""
from __future__ import annotations

from typing import Any, Dict, List

__all__ = [
    "is_bought_in",
    "bought_in_reason",
    "has_fabrication_evidence",
    "bought_in_conflict",
    "strip_fabrication_ops",
    "FABRICATION_OPS",
    "FABRICATED_FAMILIES",
]

# THE FAMILY IS AN ANSWER TO THIS QUESTION, AND IT WAS BEING THROWN AWAY.
#
# Every BOM row the extract returns is classified metal / acrylic / timber / wire / tube /
# bought_in. Five of those six are things we cut and form here; only one is a purchase. That
# classification was read from the drawing and then consumed by nothing at all.
#
# On M&S 2085 the two tubes arrived with no material — the GA states MILD STEEL once, at
# assembly level — and an unidentified part falls through to BOUGHT_IN by default. Being
# bought-in, every fabrication operation was stripped, so the saw and the weld never
# happened, and the outer tube was priced at GBP 86.04 by a market estimate. GBP 2.00 of
# labour on a welded three-part bracket.
#
# A stated family beats a defaulted material, which is all "BOUGHT_IN with nothing else on
# the record" ever was. It does NOT beat catalogue identity — a BI- code, a bought-in page
# role, an explicit flag — because that is the module's founding rule and the failure mode of
# getting it wrong is fabrication labour booked against something we simply buy.
FABRICATED_FAMILIES = frozenset({"metal", "acrylic", "timber", "wire", "tube"})

# Code families that are bought-in by construction. BI- is SDI's own prefix; the rest are
# commercial lines that are never fabricated.
_BOUGHT_IN_PREFIXES = ("BI-", "FIXING", "VINYL", "PACKAGING", "DELIVERY", "POWDER",
                       "THUM", "STD PART")

# Sources that only ever produce bought-in records.
_BOUGHT_IN_SOURCE_TOKENS = ("recogniser", "bought_in", "note_scan", "catalogue")

# Fabrication operations a purchased component can never incur. Handling/assembly is NOT
# here: we do handle and fit bought-in parts, and that bench time is real work.
FABRICATION_OPS = frozenset({
    "laser_cutting", "laser", "punch", "punching", "guillotine", "saw", "tube_cut",
    "folding", "fold", "linebend", "line_bending", "rolling", "roll", "tubebend",
    "tube_bending", "welding", "spot_welding", "spotweld", "resistance_welding",
    "dress_welds", "dressing", "cnc_routing", "cnc", "cnc_machining", "cnc_joinery",
    "pin_router", "edge_banding", "wire_forming", "robomac", "hole_machining",
    "drilling", "deburring", "deburr", "linishing", "glue", "gluing", "glueing",
    "bonding", "powder_coating", "wet_spray", "diamond_polish", "diamond_polishing",
})


def _upper(v: Any) -> str:
    return str(v or "").strip().upper()


def bought_in_reason(part: Dict[str, Any]) -> str:
    """WHICH rule decided, in words, or "" for a part we make.

    is_bought_in returns a bare boolean, and when a part turned out to be classified wrongly
    there was no way to tell which of seven rules had fired without reading the record by
    hand. This returns the answer and the reason together so a wrong classification is
    diagnosable from the run itself."""
    if not isinstance(part, dict):
        return ""
    # Catalogue identity first — these are the strong signals and they are not overridable.
    if part.get("is_bought_in") or part.get("_bought_in_from_text_scan"):
        return "flagged bought-in on the record"
    if "bought_in" in [str(r).lower() for r in (part.get("page_roles") or [])]:
        return "the drawing page is a bought-in page"
    src = str(part.get("source") or "").lower()
    for tok in _BOUGHT_IN_SOURCE_TOKENS:
        if tok in src:
            return f"read from a bought-in-only source ({tok})"
    if _upper(part.get("part_number")).startswith(_BOUGHT_IN_PREFIXES):
        return "the part number is a bought-in code family"

    fam = str(part.get("material_family") or "").strip().lower()
    if fam == "bought_in":
        return "the drawing classifies it as a purchased component"
    if _upper(part.get("normalized_material")) == "BOUGHT_IN" or _upper(part.get("material")) == "BOUGHT_IN":
        # The weakest signal there is: "we could not identify the material". A family read
        # from the drawing is a positive statement and outranks that absence.
        if fam in FABRICATED_FAMILIES:
            return ""
        return "no material was identified, so it defaulted to bought-in"
    return ""


def is_bought_in(part: Dict[str, Any]) -> bool:
    """True when the part is purchased rather than made.

    Union of every rule the codebase previously applied separately, so adopting this
    predicate cannot make any consumer classify FEWER parts as bought-in than before — with
    one deliberate exception, documented at FABRICATED_FAMILIES: a part the drawing puts in a
    fabricated family is not bought-in merely because its material went unidentified."""
    return bool(bought_in_reason(part))


def has_fabrication_evidence(part: Dict[str, Any]) -> bool:
    """POSITIVE evidence that SDI makes this part: measured flat geometry of its own.

    Deliberately narrow. A drawing, a material or a thickness is not evidence — bought-in
    components have all three. Only geometry we could actually cut from counts."""
    if not isinstance(part, dict):
        return False
    # An explicit "nothing was measured" outranks every positive marker below. flat_pattern
    # _detected is also set from drawing EXTENTS as a fallback (drawing_job_merge), which is
    # not measured geometry, and being checked first it let a matched-but-unreadable DXF
    # count as evidence — the exact case this predicate was narrowed to exclude.
    #
    # "No blank was measured" is NOT "nothing was measured". A DXF whose cut layer yields a
    # measured cut path but no closed outline has told us something real: a profile is being
    # cut. Only the blank claim is absent, and only the blank claim gates the allowance. The
    # two used to share dxf_measured_outline, so withdrawing the blank claim would otherwise
    # take the part's fabrication evidence with it and make something we cut look purchased.
    if (part.get("dxf_measured_outline") is False
            and not part.get("dxf_measured_cut_length")
            and not part.get("native_flat_pattern")):
        return False
    if part.get("flat_pattern_detected") or part.get("native_flat_pattern"):
        return True
    # dxf_augmented is set ONLY where an outline was actually measured. dxf_source_file is
    # deliberately NOT accepted: it records that a file MATCHED, which since the reader
    # learned to distinguish the two can be true with nothing measured at all (a flat
    # exported as an unreadable block, say). Counting it would make "a DXF exists" into
    # fabrication evidence again — the very thing this predicate is narrow to avoid — and
    # would raise a make/buy conflict on a purchased part that merely has a drawing.
    if part.get("dxf_augmented") or part.get("dxf_measured_outline"):
        return True
    _gs = str(part.get("geometry_source") or "").lower()
    return "dxf" in _gs and _gs != "dxf_matched_no_geometry"


def bought_in_conflict(part: Dict[str, Any]) -> bool:
    """Bought-in by identity, yet carrying its own measured geometry — the two sources
    disagree about what this part is. Flagged for an estimator, never auto-resolved."""
    return is_bought_in(part) and has_fabrication_evidence(part)


def strip_fabrication_ops(part: Dict[str, Any]) -> List[str]:
    """Remove fabrication operations from a bought-in part, in place.

    Returns what was removed so the caller can flag it. Does nothing to a part that is not
    bought-in, and never touches handling/assembly — fitting a purchased component is real
    bench time and must keep being charged."""
    if not is_bought_in(part):
        return []
    removed: List[str] = []
    for field in ("textual_operations", "inferred_operations"):
        vals = part.get(field)
        if not isinstance(vals, list):
            continue
        kept: List[Any] = []
        for op in vals:
            if str(op).lower() in FABRICATION_OPS:
                if str(op) not in removed:
                    removed.append(str(op))
            else:
                kept.append(op)
        part[field] = kept
    return removed
