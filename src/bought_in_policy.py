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

# The one module that knows how SDI's part numbers are spelled. Identity-only and
# dependency-free, like this one, so asking it here costs nothing and keeps the convention
# in a single place — a private regex in each reader is how one of them goes quietly stale.
import part_code_conventions

__all__ = [
    "is_bought_in",
    "bought_in_reason",
    "has_fabrication_evidence",
    "bought_in_conflict",
    "strip_fabrication_ops",
    "strip_leaf_operations",
    "is_assembly",
    "assembly_reason",
    "FABRICATION_OPS",
    "LEAF_ONLY_OPS",
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


# OPERATIONS THAT CAN ONLY HAPPEN TO ONE PIECE OF STOCK, so an assembly cannot incur them —
# they belong to the parts it is made from. A deliberate SUBSET of FABRICATION_OPS, and what
# is left out is the point:
#
#   JOINING stays. Welding, gluing and bonding are what an assembly IS. The route compiler
#   already has a weld-parent rule for exactly this, and stripping welds from a weldment
#   would take the job's real labour out of the estimate.
#   FINISHING stays. A welded frame is powder coated as one thing, after joining, and
#   assembly-level finish is a case this engine handles on purpose.
#
# What remains cuts, forms or dresses a single blank: you cannot laser an assembly, and you
# cannot edge-band one. On job 12392 the panel assembly 12392-02-201 collected cnc_routing,
# edge banding and laminating from an MDF title block on a different sheet of the same pack —
# three joinery operations on a thing that is two steel panels bolted together, each
# unverifiable because no part on the assembly could have incurred them.
#
# The vocabulary lives here beside FABRICATION_OPS on purpose: two lists of operation names
# maintained separately are two lists that disagree the first time one is edited.
LEAF_ONLY_OPS = frozenset({
    "laser_cutting", "laser", "punch", "punching", "guillotine", "saw", "tube_cut",
    "folding", "fold", "linebend", "line_bending", "rolling", "roll", "tubebend",
    "tube_bending", "cnc_routing", "cnc", "cnc_machining", "cnc_joinery", "pin_router",
    "edge_banding", "edgebanding", "laminating", "lamination", "veneering",
    "wire_forming", "robomac", "hole_machining", "drilling", "deburring", "deburr",
    "linishing",
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
    _roles = [str(r).strip().lower() for r in (part.get("page_roles") or [])]
    if "bought_in" in _roles:
        # A PAGE ROLE THAT CONTRADICTS ITSELF IS NOT AUTHORITY. 12392's mounting brackets
        # carry BOTH "detail" and "bought_in": one page reads as a detail sheet for a part we
        # cut, another as a bought-in listing. That is two readings of the same code
        # disagreeing, not a catalogue statement — and taken as decisive it stripped the
        # laser and the fold from two steel brackets the workbook then had to put back.
        #
        # Only a SECOND positive signal overturns it, so this cannot be reached by absence:
        # the part must both be drawn as a detail AND carry SDI's own material-suffix
        # convention, which is a code written by whoever drew it. Two statements that we make
        # the part, against one that reads it as bought. Every stronger rule — an explicit
        # flag, a bought-in-only source, a BI- code family — is checked before this and is
        # untouched.
        _detailed = any(r in {"detail", "fabricated", "flat_pattern"} for r in _roles)
        if not (_detailed and part_code_conventions.material_suffix(_upper(part.get("part_number")))):
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
        # SO IS THE PART NUMBER. "12392-04-01M" is not a name; it is SDI's own convention for
        # a part we cut in metal (-M steel, -A acrylic, -T MDF), and it is written by the
        # person who drew it. That is a statement about what the part IS, from the drawing,
        # in exactly the way a stated family is — so it stops the same default, and only that
        # default. Every catalogue rule above has already returned: a BI- code, a bought-in
        # page role, a bought-in-only source and an explicit flag all outrank this and are
        # untouched, which matters because the cost of getting THIS wrong is a purchased item
        # carrying laser and fold time.
        #
        # Two independent paths reached the same wrong answer on 12392 and this is the second
        # one. The first was json_normaliser never consulting the convention when the material
        # text was noise rather than blank; fixing it there means these brackets arrive as
        # MILD_STEEL and never reach this branch. But a part can be stamped BOUGHT_IN by other
        # routes, and a rule that holds in one module and not the other is not one rule.
        if part_code_conventions.material_suffix(_upper(part.get("part_number"))):
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


def assembly_reason(part: Dict[str, Any]) -> str:
    """WHY this record is a parent rather than a part we cut, in words, or "" for a leaf.

    THE SAME IDEA UNDER FOUR NAMES. estimator.py's own comment records the defect: "both
    suppressions here and in estimate_part keyed on is_assembly_parent, a different name for
    the same idea", and 12120-01-103 was correctly identified as a sub-assembly from the GA
    tree while still being given sheet material, a laser and a fold — because the field that
    said so was not the field that pass read. The canonical graph adds a fifth spelling,
    canonical_kind.

    A union, deliberately, exactly as is_bought_in is: adopting this predicate cannot make
    any consumer recognise FEWER assemblies than it did before. That is what makes it safe to
    introduce into a costing path — the failure direction is a parent charged as a leaf,
    which is material and fabrication booked twice, and a union can only reduce it.

    It does NOT decide anything about geometry. A part with its own measured flat is a
    fabricated leaf whatever a transcribed hierarchy says, and that arbitration stays where
    it is, in the caller that holds the measurement.
    """
    if not isinstance(part, dict):
        return ""
    if str(part.get("canonical_kind") or "").strip().lower() == "assembly":
        return "the canonical part graph compiled it as an assembly"
    if part.get("is_assembly_parent"):
        return "flagged an assembly parent on the record"
    if part.get("is_sub_assembly"):
        return "the drawing's hierarchy names it as a sub-assembly"
    if part.get("assembly_children"):
        return "it names children of its own"
    return ""


def is_assembly(part: Dict[str, Any]) -> bool:
    """True when the record is a parent: its material and leaf work belong to its children."""
    return bool(assembly_reason(part))


def strip_leaf_operations(part: Dict[str, Any]) -> List[str]:
    """Remove single-blank operations from an ASSEMBLY, in place. Returns what was removed.

    Deliberately mirrors strip_fabrication_ops, because it is the same shape of mistake in
    the other direction: there, a purchased part carrying work we never did; here, a parent
    carrying work that belongs to its children. Both put labour on a record that cannot have
    incurred it, and both were flagged for an estimator and then charged anyway.

    Does nothing unless the record is already classified as an assembly. That classification
    is the canonical graph's to make and this never second-guesses it — a part wrongly called
    an assembly is a different defect, and silently stripping its route would hide it.
    """
    if not (part.get("is_assembly_parent") or part.get("is_sub_assembly")
            or str(part.get("canonical_kind") or "").lower() == "assembly"):
        return []
    removed: List[str] = []
    for field in ("textual_operations", "inferred_operations"):
        vals = part.get(field)
        if not isinstance(vals, list):
            continue
        kept: List[Any] = []
        for op in vals:
            if str(op).strip().lower() in LEAF_ONLY_OPS:
                if str(op) not in removed:
                    removed.append(str(op))
            else:
                kept.append(op)
        part[field] = kept
    return removed


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
