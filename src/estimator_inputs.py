"""
estimator_inputs.py — what a person still has to supply before this sheet is a price.

THE PROBLEM THIS SOLVES. On 2085 the Estimate tab showed a Unit Cost of £6.33 and a Sell
Price of £6.33, and both looked finished. They were not: neither tube contributed any
material, the powder rate is a known-wrong assumption, packaging and delivery were zero
placeholders, and the margin was 0%. Every one of those was stated somewhere — in a console
flag that scrolls past, in a `£-` that reads like a real zero — and none of it was on the
sheet where the estimator works.

A blank that looks like a zero is worse than an error. An error stops someone; a plausible
number does not.

So this module answers one question per line: what would a person have to type here, and
what do they need to know to type it? The answer is derived from the record — the section
profile, the length we did or did not read, the rate we could not find — never from a part
number or a job. A new job with the same gap gets the same sentence.

WHAT IS NOT HERE. This does not decide prices, block the sheet, or change a total. The
workbook's own arithmetic is untouched; a provisional sheet still calculates, because an
estimator needs the working even when it is incomplete. What changes is that the sheet says
so, in the places a person actually looks.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

__all__ = [
    "MATERIAL_UNPRICED",
    "PLACEHOLDER_UNPRICED",
    "ASSUMPTION_UNCONFIRMED",
    "MARGIN_UNSET",
    "DUPLICATE_ARTICLE",
    "section_summary",
    "material_input_note",
    "input_note_for_line",
    "canonical_pricing_status",
    "indicative_price_to_withhold",
    "indicative_price_note",
    "banner_text",
]

MATERIAL_UNPRICED = "material_unpriced"
PLACEHOLDER_UNPRICED = "placeholder_unpriced"
ASSUMPTION_UNCONFIRMED = "assumption_unconfirmed"
MARGIN_UNSET = "margin_unset"

# The things a price column can mean. "Blank" is most of them, and telling them apart is the
# whole difference between a checklist somebody works and one they stop reading.
PRICED = "priced"
COSTED_IN_MATERIAL_BLOCK = "costed_in_material_block"
NOT_APPLICABLE = "not_applicable"
UNPRICED = "unpriced"
# The drawing named one article on two BOM lines. The money sits on the other line, so this
# one is blank on purpose and there is nothing here for anybody to price. Asking for a rate
# would be asking for the double-count back -- exactly the failure canonical_pricing_status
# was written for, arriving through a different door.
DUPLICATE_ARTICLE = "duplicate_article"


def _num(value: Any) -> Optional[float]:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float("inf") else None


def _fmt(value: Any) -> str:
    f = _num(value)
    if f is None:
        return ""
    return f"{f:g}"


def section_summary(part: Mapping[str, Any]) -> str:
    """The section as far as we read it — "12.7 x 1.2 CHS", "40 x 20 x 2 RHS", or "".

    Named so the estimator can price it without opening the drawing again. Missing pieces
    are simply absent rather than defaulted: a wall thickness we did not read must not
    appear as a number someone could rate against.
    """
    if not isinstance(part, Mapping):
        return ""
    ss = part.get("section_stock")
    ss = ss if isinstance(ss, Mapping) else {}
    if not ss:
        return ""
    a, b, t = _fmt(ss.get("a")), _fmt(ss.get("b")), _fmt(ss.get("t"))
    form = str(ss.get("profile_form") or "").upper().strip()
    dims = " x ".join(d for d in (a, b, t) if d)
    return " ".join(p for p in (dims, form) if p).strip()


def section_length_mm(part: Mapping[str, Any]) -> Optional[float]:
    """The cut length, from wherever it was actually read. None when it was not."""
    if not isinstance(part, Mapping):
        return None
    me = part.get("material_estimate")
    me = me if isinstance(me, Mapping) else {}
    stock = me.get("stock_estimate")
    stock = stock if isinstance(stock, Mapping) else {}
    ss = part.get("section_stock")
    ss = ss if isinstance(ss, Mapping) else {}
    for candidate in (stock.get("section_length_mm"), ss.get("length_mm"),
                      part.get("overall_length_mm")):
        value = _num(candidate)
        if value and value > 0:
            return value
    return None


def material_input_note(part: Mapping[str, Any]) -> str:
    """The sentence appended to an unpriced line's description.

    Says three things, in the order an estimator needs them: that the material is unpriced,
    what the stock is as far as we read it, and which specific figure is missing. "Confirm
    the section rate" is actionable; "£-" is not.
    """
    section = section_summary(part)
    length = section_length_mm(part)
    if section or length:
        known = section or "section stock"
        if length:
            return (f"MATERIAL UNPRICED: {known}, cut length {length:g}mm — "
                    f"confirm the length and enter a section rate (£/kg or £/m)")
        return (f"MATERIAL UNPRICED: {known}, cut length NOT READ — "
                f"enter the cut length and a section rate (£/kg or £/m)")
    return "MATERIAL UNPRICED: enter a unit rate for this item"


def input_note_for_line(part: Mapping[str, Any]) -> Dict[str, str]:
    """{kind, note} for a BOM line the sheet wrote with no price.

    A placeholder and an unpriced fabricated part are different jobs for the estimator —
    one is a commercial figure to decide, the other a rate to look up — and telling them
    apart is the difference between a checklist that gets worked and one that gets ignored.
    """
    if not isinstance(part, Mapping):
        return {"kind": MATERIAL_UNPRICED, "note": "MATERIAL UNPRICED"}
    description = str(part.get("description") or "")
    if part.get("_duplicate_of"):
        return {"kind": DUPLICATE_ARTICLE,
                "note": (f"SAME ARTICLE AS {part['_duplicate_of']} — costed there, not here. "
                         f"Nothing to price on this line; check the quantity on "
                         f"{part['_duplicate_of']} covers both.")}
    if part.get("_price_explicitly_withheld") or "estimator to price" in description.lower():
        return {"kind": PLACEHOLDER_UNPRICED,
                "note": "NOT YET PRICED: enter the per-unit figure for this line"}
    return {"kind": MATERIAL_UNPRICED, "note": material_input_note(part)}


def canonical_pricing_status(part: Mapping[str, Any], price: Any) -> str:
    """What a BOM row's price column actually MEANS, once the canonical kind is known.

    A CHECKLIST IS ONLY WORKED IF EVERY LINE ON IT IS REAL. Job 11350 listed six outstanding
    inputs and two of them were "enter a unit rate" for 11350-01-01 and 11350-01-02 — parts
    the Sheet Steel block had already costed at £0.77 and £0.48, on the same sheet, from
    measured blanks. Those rows exist so an estimator can SEE the fabricated parts in the
    bill of materials; they are priced at zero precisely so the material total is not
    doubled. Asking someone to price them is asking for the double-count back.

    Two lines of noise in six is enough to make a person stop reading the list, and the ones
    that were real — packaging, delivery, the fixings — are exactly what gets lost.

    An ASSEMBLY has no material line of its own either: its material is its children's. It
    is not unpriced, it has nothing to price.

    Everything else with no positive figure IS a real outstanding input, and the narrowness
    matters as much as the rule: excuse one row too many and the list stops being a list.
    """
    if not isinstance(part, Mapping):
        return UNPRICED
    if part.get("_bom_cross_reference"):
        return COSTED_IN_MATERIAL_BLOCK
    if part.get("_duplicate_of"):
        return NOT_APPLICABLE
    if str(part.get("_canonical_kind") or "").strip().lower() == "assembly":
        return NOT_APPLICABLE
    numeric = _num(price)
    return PRICED if numeric is not None and numeric > 0 else UNPRICED


def indicative_price_to_withhold(part: Mapping[str, Any], is_indicative: bool,
                                 price_gbp: Any) -> Optional[float]:
    """The AI figure to KEEP OFF the price column, or None when the line prices normally.

    A guess that changes every run is not a price. Job 11350's right arm came back at
    £79.04 on one run and £86.04 on the next — 82% then 95% of the entire material total,
    on a part with a measured flat we could have costed as sheet steel. The invariant
    refused to call the job firm, but the Estimate tab still showed a total built on it,
    and nothing on that tab distinguishes the number from a catalogue rate.

    This matters MORE as search degrades: with a programmatic provider exhausted or
    unconfigured, the lookup falls straight through to the LLM, so every missing price
    becomes a figure like this rather than an obvious gap.

    The number is returned, not discarded — it belongs on the line as a hint, where it
    informs without being summed.

    WHAT ACTUALLY DISQUALIFIED IT WAS INSTABILITY, NOT UNCERTAINTY. Every sentence above
    turns on the figure CHANGING between runs, and that is now fixable: a generated price
    is asked once per specification and stored, so the same part returns the same number
    tomorrow and on somebody else's machine. Once it holds still, an estimator can weigh
    it exactly as they weigh any other indicative figure — and estimating would rather
    have a low-confidence number to correct than a blank to fill from nothing.

    So a REPRODUCIBLE estimate now prices the line, loudly tagged as indicative. Only one
    that cannot be reproduced is still kept off the total, because a total nobody can
    reproduce is not an estimate at all — two people reading the same job on the same day
    would disagree about what it says.
    """
    if not is_indicative:
        return None
    if isinstance(part, Mapping) and part.get("_price_explicitly_withheld"):
        return None          # already an estimator input; nothing to move
    if isinstance(part, Mapping) and part.get("_price_is_reproducible"):
        return None          # it holds still; price it, tagged as indicative
    value = _num(price_gbp)
    return value if value and value > 0 else None


def indicative_price_note(price_gbp: float) -> str:
    """The line's description once its AI figure has been moved out of the price column."""
    return (f"NOT PRICED — an AI market estimate suggested £{price_gbp:,.2f}, which changes "
            f"every run and is NOT a quote. Enter a catalogue or supplier rate.")


def banner_text(inputs: List[Mapping[str, Any]]) -> str:
    """The line that sits beside Unit Cost and Sell Price.

    Counts, because "PROVISIONAL" alone tells an estimator nothing about how much is
    missing, and a count is the thing that makes someone scroll to the list."""
    count = len([i for i in inputs if isinstance(i, Mapping)])
    if not count:
        return ""
    return (f"PROVISIONAL — {count} ESTIMATOR INPUT{'S' if count != 1 else ''} REQUIRED "
            f"(see OUTSTANDING ESTIMATOR INPUTS below)")
