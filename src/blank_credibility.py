r"""A blank that cannot contain its own cut path is not a small part. It is a wrong number.

Job 12392's back panel was recorded as a 16 x 3.7 mm blank carrying a 6,679 mm cut path —
six and a half metres of cutting inside a rectangle the size of a staple. It priced at
GBP 0.01. The sheet claimed 5,865 of them out of one 2500 x 1250, and the material total
for a steel panel job came to a few pounds.

Each number is perfectly plausible alone. Only the pair is impossible, and nothing was
comparing them, so the engine priced from the wrong one of the two and said nothing.

WHY THIS IS A MODULE. The invariant that reports it and the estimator that prices from it
must agree about what "impossible" means. A checker that blocks a job the pricer has
already costed at a hundredth of its value is not a check — it is a second opinion nobody
acted on, arriving after the money was written down.

THE DIRECTION OF SAFETY. This says a blank is impossible, never that it is right. A blank
that passes has not been verified; it has merely not been caught. Every caller must go on
treating an unverified dimension as unverified.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

# The closest two cut lines can credibly run in sheet metal, in millimetres. A laser kerf
# is nearer 0.2mm, so this is generous by a factor of five on purpose: the test exists to
# catch a blank that is impossible, not one that is merely dense.
MIN_CREDIBLE_CUT_SPACING_MM = 1.0

# And then only complain at several times over. A long narrow strip is nearly all
# perimeter — 2500 x 2 has 5,004mm of outline in 5,000mm2 of room — so a bare "over one"
# would fire on geometry that is unusual rather than impossible. The cases this exists for
# clear the bar a hundredfold, so the margin costs nothing and buys the test the right to
# stop a price.
CUT_PATH_ABSURDITY_MARGIN = 3.0


def _num(value: Any) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out > 0 else None


def cut_path_a_blank_could_hold_mm(length_mm: Any, width_mm: Any) -> Optional[float]:
    """The most cutting that fits in a blank before the lines are closer than a kerf.

    Area divided by the minimum credible spacing: a rectangle of L x W has room for
    roughly area/spacing millimetres of line before the cuts merge into each other.
    """
    length, width = _num(length_mm), _num(width_mm)
    if not length or not width:
        return None
    return (length * width) / MIN_CREDIBLE_CUT_SPACING_MM


def assess(length_mm: Any, width_mm: Any, cut_path_mm: Any) -> Dict[str, Any]:
    """Can this blank and this cut path both be true?

    Returns {'credible', 'evaluated', 'ratio', 'implied_spacing_mm', 'reason'}.

    `evaluated` is False when either number is missing — which is NOT a pass. A part with
    no cut path has not been shown to be consistent; it has not been asked.
    """
    length, width, cut = _num(length_mm), _num(width_mm), _num(cut_path_mm)
    if not length or not width or not cut:
        return {"credible": True, "evaluated": False, "ratio": None,
                "implied_spacing_mm": None,
                "reason": "no cut path or no blank recorded — nothing to compare"}

    room = cut_path_a_blank_could_hold_mm(length, width) or 0.0
    ratio = (cut / room) if room else float("inf")
    spacing = (length * width) / cut
    credible = ratio <= CUT_PATH_ABSURDITY_MARGIN
    if credible:
        return {"credible": True, "evaluated": True, "ratio": round(ratio, 2),
                "implied_spacing_mm": round(spacing, 4),
                "reason": "the cut path fits inside the blank"}
    return {
        "credible": False, "evaluated": True, "ratio": round(ratio, 1),
        "implied_spacing_mm": round(spacing, 4),
        "reason": (f"a {length:g} x {width:g} mm blank cannot hold a {cut:,.0f} mm cut path "
                   f"({ratio:.1f}x more than it could contain, implying cuts "
                   f"{spacing:.4f} mm apart)"),
    }


def is_credible(length_mm: Any, width_mm: Any, cut_path_mm: Any) -> bool:
    return bool(assess(length_mm, width_mm, cut_path_mm)["credible"])


def better_blank_from(candidates: Tuple[Tuple[str, Any, Any], ...],
                      cut_path_mm: Any) -> Optional[Dict[str, Any]]:
    """The first candidate blank that could hold this cut path, with where it came from.

    Candidates are (source_name, length, width), offered in the order the caller trusts
    them. Used when a recorded blank has been shown impossible: a modelled bounding box
    understates a developed length and is a poor blank, but it is a defensible FLOOR, and
    a defensible floor beats a number already proven wrong by two orders of magnitude.

    Returns None when nothing offered survives — in which case the part has no blank we
    can stand behind, and saying so is the only honest answer left.
    """
    for name, length, width in candidates or ():
        if is_credible(length, width, cut_path_mm) and _num(length) and _num(width):
            verdict = assess(length, width, cut_path_mm)
            if verdict["evaluated"]:
                return {"source": name, "blank_length_mm": _num(length),
                        "blank_width_mm": _num(width), "assessment": verdict}
    return None
