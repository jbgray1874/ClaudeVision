"""
applied_finish.py — what a stated finish costs, or who has to say.

POWDER WAS THE ONLY FINISH THIS ENGINE COULD COST. That is right for steel and wrong for
everything else, and the gap was invisible because both halves looked correct on their own:
the non-metal rule correctly refuses to powder-coat a plastic, and the route correctly
contains no powder operation — so nothing was flagged and the finish was silently free.

11650-04's side panels state `1/2 INCH REEDED VINYL + UV OR CLEAR VINYL`. The engine read it,
printed it as an observation, and costed laser, manual labour and assembly. There was no vinyl
operation in the vocabulary, no rate for one, and no line on the sheet. The vinyl was free —
on a panel where it is most of what the customer is buying.

PAINT, VINYL, LAMINATE, PRINT AND FOIL GO ON WOOD, MDF, ACRYLIC AND PETG EVERY DAY. Ruling
powder out on a non-metal is correct; leaving nothing in its place is an under-charge that
grows with every non-metal job this shop takes.

THE THREE ANSWERS, IN ORDER, AND NEVER A FOURTH.

  A RATE WE HOLD          firm, reproducible, in the total. One line in config, keyed on the
                          finish code — so the next enquiry inherits it and no pack needs code.

  NO RATE                 an explicit line the estimator must fill, carrying the finish code
                          and the area it applies to. NOT zero. A finish costed at zero and a
                          finish nobody has priced look identical on a sheet, and only one of
                          them is an under-charge somebody can catch.

  NEVER AN INVENTED ONE   this module does not guess what a finish costs. A market indication
                          may sit beside the line as a hint and is never summed — the same
                          policy the material path already enforces.

ONE VOCABULARY, ONE OWNER. What counts as vinyl is decided here and nowhere else. A second
list of finish words beside this one is how a material vocabulary came to know HIPS and not
PETG, and that cost three commits of arbitration that could not fire.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

import config

SCHEMA = "applied_finish.v1"

# WHAT THE DRAWING SAYS -> WHAT IT IS. Ordered, because a sheet naming two finishes names the
# dearest one first in practice and because the specific must beat the general: "UV VARNISH"
# is not "VINYL" merely because the same sentence mentions both.
#
# These are FILM AND COATING PROCESSES APPLIED TO A FACE, charged by area. Processes charged
# some other way — polishing by edge length, powder by mass — are not here; powder keeps its
# own workbook formula and is not re-costed by this module.
_FINISH_PATTERNS: Tuple[Tuple[str, str], ...] = (
    (r"\bREEDED\b.*\bVINYL\b|\bVINYL\b.*\bREEDED\b", "VINYL_REEDED"),
    (r"\bVINYL\b|\bSELF\s*ADHESIVE\s*FILM\b|\bWRAP\b", "VINYL"),
    (r"\bUV\s*(?:HARD\s*)?COAT|\bUV\s*VARNISH\b|\bUV\s*LACQUER\b", "UV_COAT"),
    (r"\bLAMINAT", "LAMINATE"),
    (r"\bFOIL\s*BLOCK|\bHOT\s*FOIL\b|\bFOIL\b", "FOIL"),
    (r"\bSCREEN\s*PRINT|\bDIGITAL\s*PRINT|\bLITHO\b|\bPRINTED?\b", "PRINT"),
    (r"\bSPRAY\b|\bPAINT(?:ED)?\b|\bLACQUER\b|\b2\s*PACK\b", "PAINT"),
    (r"\bANODIS|\bANODIZ", "ANODISE"),
    (r"\bVENEER", "VENEER"),
)

# How many faces a finish goes on unless the drawing says otherwise. One, because a decorative
# film is applied to the face the customer sees; assuming two would double the money on every
# panel in the shop on nothing but an assumption.
_DEFAULT_FACES = 1


def finish_codes(text: Any) -> List[str]:
    """Every applied finish named in this text, most specific first, no duplicates.

    A LIST, BECAUSE DRAWINGS NAME MORE THAN ONE. `1/2 INCH REEDED VINYL + UV OR CLEAR VINYL`
    is a reeded vinyl AND a UV coat, and costing only the first would charge for half the work
    the sheet asks for.
    """
    s = str(text or "").upper()
    if not s.strip():
        return []
    out: List[str] = []
    for pat, code in _FINISH_PATTERNS:
        if re.search(pat, s) and code not in out:
            out.append(code)
    # A reeded vinyl IS a vinyl; naming both would charge the film twice.
    if "VINYL_REEDED" in out and "VINYL" in out:
        out.remove("VINYL")
    return out


def rate_for(code: str) -> Optional[Dict[str, Any]]:
    """The £/m² we hold for this finish, with where it came from — or None.

    ONE PLACE TO CLOSE THE GAP. When a rate arrives it is a line in config keyed on the code,
    and every job that states that finish is priced from it. No pack-specific code, ever: that
    is the difference between a system that gets quieter and one that needs an engineer per
    enquiry.
    """
    rates = getattr(config, "APPLIED_FINISH_RATES_GBP_PER_M2", {}) or {}
    try:
        rate = float(rates[code])
    except (KeyError, TypeError, ValueError):
        return None
    if rate <= 0:
        return None
    return {"rate_gbp_per_m2": rate, "source_class": "catalogue",
            "source_name": "config.APPLIED_FINISH_RATES_GBP_PER_M2", "reproducible": True}


def applied_finish_estimate(part: Dict[str, Any], blank_length_mm: Optional[float],
                            blank_width_mm: Optional[float],
                            quantity: int) -> Optional[Dict[str, Any]]:
    """A costed line per applied finish this part states, or an owned gap where we hold no rate.

    Returns None when the drawing states no applied finish — the ordinary case, and it must
    add nothing to a job that does not ask for it.
    """
    if not isinstance(part, dict):
        return None
    text = " ".join(str(x) for x in (
        part.get("normalized_finish"), part.get("surface_finish"),
        " ".join(str(v) for v in (part.get("surface_finishes") or [])),
    ) if x)
    codes = finish_codes(text)
    if not codes:
        return None
    try:
        area_m2 = (float(blank_length_mm) * float(blank_width_mm)) / 1_000_000.0
    except (TypeError, ValueError):
        area_m2 = 0.0
    try:
        qty = max(1, int(quantity))
    except (TypeError, ValueError):
        qty = 1

    lines: List[Dict[str, Any]] = []
    for code in codes:
        line: Dict[str, Any] = {
            "finish_code": code, "stated_as": text.strip()[:200],
            "faces": _DEFAULT_FACES, "area_m2_per_part": round(area_m2 * _DEFAULT_FACES, 6),
        }
        _rate = rate_for(code)
        if _rate and area_m2 > 0:
            unit = area_m2 * _DEFAULT_FACES * _rate["rate_gbp_per_m2"]
            line.update({
                "rate_gbp_per_m2": _rate["rate_gbp_per_m2"],
                "unit_finish_cost_gbp": round(unit, 4),
                "extended_finish_cost_gbp": round(unit * qty, 2),
                "price_source": _rate,
                "estimator_input_required": False,
            })
        else:
            # NOT ZERO, AND NOT SILENCE. The line exists, names the work, and says who has to
            # price it. A finish costed at nothing and a finish nobody has priced read the same
            # on a sheet, and only one of them is an under-charge anybody can catch.
            line.update({
                "rate_gbp_per_m2": None,
                "unit_finish_cost_gbp": None,
                "extended_finish_cost_gbp": None,
                "estimator_input_required": True,
                "reason": "no_rate_for_finish",
                "note": (f"{code.replace('_', ' ').title()} is stated on the drawing and this "
                         f"engine holds no rate for it. "
                         + (f"{area_m2 * _DEFAULT_FACES:.3f} m² per part, {qty} off — "
                            if area_m2 > 0 else "No blank size, so no area either — ")
                         + "price it, or add a £/m² to "
                           "config.APPLIED_FINISH_RATES_GBP_PER_M2 and every job stating this "
                           "finish is priced from it."),
            })
        lines.append(line)

    _priced = [ln for ln in lines if ln.get("extended_finish_cost_gbp") is not None]
    return {
        "schema": SCHEMA,
        "finishes": lines,
        "quantity": qty,
        # Only rates we hold reach a total. An indication may sit beside a line as a hint and
        # is never summed — the same policy the material path already enforces.
        "extended_finish_cost_gbp": round(sum(ln["extended_finish_cost_gbp"]
                                              for ln in _priced), 2) if _priced else 0.0,
        "unpriced_finishes": [ln["finish_code"] for ln in lines
                              if ln.get("estimator_input_required")],
    }
