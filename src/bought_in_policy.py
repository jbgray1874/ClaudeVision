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
    "has_fabrication_evidence",
    "bought_in_conflict",
    "strip_fabrication_ops",
    "FABRICATION_OPS",
]

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


def is_bought_in(part: Dict[str, Any]) -> bool:
    """True when the part is purchased rather than made.

    Union of every rule the codebase previously applied separately, so adopting this
    predicate cannot make any consumer classify FEWER parts as bought-in than before."""
    if not isinstance(part, dict):
        return False
    if _upper(part.get("normalized_material")) == "BOUGHT_IN":
        return True
    if _upper(part.get("material")) == "BOUGHT_IN":
        return True
    if part.get("is_bought_in") or part.get("_bought_in_from_text_scan"):
        return True
    if "bought_in" in [str(r).lower() for r in (part.get("page_roles") or [])]:
        return True
    src = str(part.get("source") or "").lower()
    if any(tok in src for tok in _BOUGHT_IN_SOURCE_TOKENS):
        return True
    if _upper(part.get("part_number")).startswith(_BOUGHT_IN_PREFIXES):
        return True
    return False


def has_fabrication_evidence(part: Dict[str, Any]) -> bool:
    """POSITIVE evidence that SDI makes this part: measured flat geometry of its own.

    Deliberately narrow. A drawing, a material or a thickness is not evidence — bought-in
    components have all three. Only geometry we could actually cut from counts."""
    if not isinstance(part, dict):
        return False
    if part.get("flat_pattern_detected") or part.get("native_flat_pattern"):
        return True
    if part.get("dxf_augmented") or part.get("dxf_source_file"):
        return True
    return "dxf" in str(part.get("geometry_source") or "").lower()


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
