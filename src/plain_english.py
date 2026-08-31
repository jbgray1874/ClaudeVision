"""Every code this engine prints, in words an estimator can act on.

WHAT JAMES SAID, reading the 10575-02 report end to end:

    "10575-01-013 — risk flag: customer_supplied_zero_cost. - what does this mean?"
    "high bend count; low extraction confidence (44%). - why is there low confidence? Did the
     LLM extract a high bend count and we are not confident of it's accuracy? What does a high
     bend count mean?"
    "this also. it's all a bit like shrouded in codes. it's difficult to understand"

He is not asking for shorter words. He is asking three questions the report never answered, and
they are the same three questions for every code on the page:

    WHAT IS IT           what did the engine actually observe
    WHY DOES IT MATTER   what it does to the number underneath
    WHO DOES WHAT NEXT   and is that person him, the drawing office, or nobody

A REPORT THAT PRINTS A CODE HAS DELEGATED ITS JOB TO THE READER. `customer_supplied_zero_cost`
is not shorthand an estimator is expected to know — it is an internal identifier that leaked
onto a page written for somebody else. The three words are even misleading on their own: read
literally they say a customer supplied something at zero cost, when what happened is that the
engine recognised a free-issue item and deliberately costed it at nothing.

TWO FACTS JOINED BY A SEMICOLON ARE READ AS ONE. "high bend count; low extraction confidence
(26%)" put two independent observations in one clause with no subject, and James read them as a
single claim — that the confidence figure was about the bend count. It is not: the percentage is
the mean confidence across every field read for that part. Nothing on the page said so, and
nothing could have told him otherwise.

THIS MODULE IS THE ONE VOCABULARY. The parity report had a glossary of its own
(`_RISK_PLAIN`), the job report had a second and shorter one inline, and the workbook tabs had
none — so the same flag was explained three ways or not at all depending on which document
somebody opened. Everything now speaks from here.
"""
from __future__ import annotations

import re
from typing import Dict, Optional, Tuple

__all__ = ["explain", "action", "label", "explain_full", "SOURCE_NOTES", "why_no_price"]


# code -> (short label for a table cell, what it means, what to do about it)
#
# The label is what replaces the code in a narrow column. The meaning is a sentence that would
# satisfy somebody who has never seen the code before. The action names a person.
_CODES: Dict[str, Tuple[str, str, str]] = {

    # ── how the part was recognised ──────────────────────────────────────────
    "customer_supplied_zero_cost": (
        "Free-issue — costed at nil",
        "The engine recognised this as an item the customer supplies, so it is carried on the "
        "estimate at zero. That is deliberate, not a missing price: the part is in the build "
        "and the money for it is not ours.",
        "Confirm with the customer that it really is free-issue on this order. If SDI is "
        "buying it, price it and overwrite the zero."),
    "assembly_only_part_record": (
        "No detail drawing",
        "This part appears in the bill of materials but the pack has no detail drawing for it. "
        "Its geometry and material are inferred from the assembly, not read from a drawing.",
        "Ask the drawing office for the detail, or confirm the assumed size and material."),
    "many_bends": (
        "3 or more bends",
        "The engine counted three or more bend lines on this part. It is a flag, not a fault: "
        "bends drive folding time, they are set-up-heavy on short runs, and past this count a "
        "part often needs more than one set-up on the press brake.",
        "Sanity-check the fold count and the folding time against the drawing — this is where "
        "a short-run job quietly loses money."),
    "large_flat": (
        "Large blank",
        "The flat pattern is 2 m or more in one direction, or 1 m or more in the other. It may "
        "not nest on a standard sheet and may not fit the machine bed.",
        "Check the sheet size and the nesting assumption before quoting."),
    "hanging_holes": (
        "Hanging holes",
        "The part has holes the engine reads as hanging points for the powder line. They affect "
        "how the part is jigged and coated.",
        "No action unless the finish is unusual — noted so the powder figure can be checked."),
    "weld_required": (
        "Welding on the drawing",
        "The drawing carries a welding or weld-dressing cue. Weld time and dress time are "
        "separate operations and both are easy to leave out.",
        "Check the route includes weld AND dress time at the right rate."),

    # ── what the engine could not find ───────────────────────────────────────
    "missing_material_spec": (
        "No material on the drawing",
        "No material was stated anywhere the engine could read for this part — not the title "
        "block, not the BOM line, not a note. Without a material there is no rate, so there is "
        "no material cost.",
        "Ask the drawing office to state the material, or type it in."),
    "missing_material_thickness": (
        "No thickness on the drawing",
        "Thickness could not be read. Material weight is thickness x area x density, so with no "
        "thickness the weight and therefore the material cost cannot be calculated.",
        "Ask the drawing office for the gauge, or enter it."),
    "missing_material_price": (
        "Material has no rate in SDILive",
        "The material WAS identified — the engine knows what the part is made of. There is no "
        "price row for it in SDILive, so it cannot be costed.",
        "Add the rate to SDILive, or price the material by hand for this job."),
    "section_or_wire_stock_pricing_review": (
        "Section or wire stock",
        "This reads as tube, angle, channel or wire, which is priced per metre or per kg/m "
        "rather than per square metre of sheet.",
        "Check the per-metre rate and the kg/m figure used."),
    "web_ai_indicative_material_price": (
        "Price from an internet search",
        "The material price came from an AI internet search, not from SDILive or a supplier "
        "quote. It is an indication of the market, not a price anybody has offered SDI.",
        "Verify against a supplier quote before this goes out."),
    "web_ai_indicative_system_cost": (
        "Price from an internet search",
        "The bought-in cost came from an AI internet search rather than the catalogue.",
        "Verify against Access Supply Chain (SDILive) or a supplier quote."),

    # ── confidence ───────────────────────────────────────────────────────────
    "low_part_confidence": (
        "Low confidence on the fields read",
        "The readers record a confidence for every field they take off a drawing — material, "
        "thickness, overall size, and so on. This figure is the AVERAGE across all of them for "
        "this part. It is not about any single value, and in particular it is not a judgement "
        "on any other flag printed beside it. A low average usually means a busy or "
        "low-contrast drawing rather than a wrong number.",
        "Spot-check this part's material, thickness and overall size against the drawing."),
    "low_geometry_reliability_with_powder": (
        "Low geometry confidence on a coated part",
        "Powder cost is charged on surface area, and surface area comes from geometry the "
        "engine is not confident about on this part.",
        "Check the coated area and the powder figure."),
    "geometry_with_powder_below": (
        "Low geometry confidence on a coated part",
        "Powder cost is charged on surface area, and surface area comes from geometry the "
        "engine is not confident about on this part.",
        "Check the coated area and the powder figure."),
}

# Prefix codes carrying a payload after a colon, e.g. missing_labour_rate:laser_cutting
_PREFIXED = {
    "missing_labour_rate": (
        "No labour rate for {p}",
        "The route needs {p} and there is no rate for it in SDILive, so that operation is "
        "costing nothing. The time is in the estimate; the money is not.",
        "Add the {p} rate in SDILive, or price that operation by hand."),
}


def _split(code: str) -> Tuple[str, str]:
    s = str(code or "").strip()
    if ":" in s:
        head, tail = s.split(":", 1)
        return head, tail.replace("_", " ").strip()
    return s, ""


def _lookup(code: str) -> Optional[Tuple[str, str, str]]:
    head, payload = _split(code)
    if head in _PREFIXED and payload:
        return tuple(t.format(p=payload) for t in _PREFIXED[head])  # type: ignore[return-value]
    exact = _CODES.get(str(code or "").strip()) or _CODES.get(head)
    return exact


def label(code: str) -> str:
    """The short form for a table cell. Falls back to the code with its underscores opened out,
    which is worse than an entry and much better than a raw identifier."""
    found = _lookup(code)
    if found:
        return found[0]
    head, payload = _split(code)
    return (head.replace("_", " ").strip() + (f" — {payload}" if payload else "")) or str(code)


def explain(code: str) -> str:
    """What it means. Never empty: an unglossed code says so, rather than saying nothing.

    THE DEFAULT MATTERS MORE THAN THE ENTRIES. A glossary that silently returns "" for a code
    nobody has written up prints a blank cell, and a blank cell reads as "nothing to report" —
    the opposite of the truth. Saying the engine has no plain-English entry for this flag is an
    honest answer and it also puts the gap where somebody will see it and fill it in.
    """
    found = _lookup(code)
    if found:
        return found[1]
    return (f"No plain-English entry has been written for the code {str(code).strip()!r}. It is "
            f"a flag the engine raised on this part; treat it as something to look at rather "
            f"than something resolved.")


def action(code: str) -> str:
    found = _lookup(code)
    return found[2] if found else "Check this against the drawing before the job goes out."


def explain_full(code: str) -> str:
    """Meaning and action in one sentence pair, for a single cell."""
    return f"{explain(code)} {action(code)}".strip()


# ── where a datum came from, in the same three questions ─────────────────────
#
# Section 9 prints a source name per field and a dash for anything unstamped. James: "it's all
# a bit like shrouded in codes." The names themselves are plain — "the drawing", "engine
# inference" — but a name with no gloss cannot answer "so can I rely on it".
SOURCE_NOTES: Dict[str, str] = {
    "the drawing": "Read off the drawing's own text — the title block, a dimension or a note, "
                   "exactly as typed. Nothing was interpreted.",
    "the bill of materials": "Read from the BOM table on the drawing.",
    "the drawing's overall dimensions": "Not measured. The engine took the part's overall size "
                                        "from the drawing and worked the blank back from it, "
                                        "which is right for a flat part and approximate for a "
                                        "folded one.",
    "engine inference": "Calculated by the engine from other values on the part rather than "
                        "read from anything. Provisional by construction.",
    "engine inference from geometry": "Calculated by the engine from the measured shape rather "
                                      "than read from the drawing.",
    "Grok (xAI)": "Read by the vision model from the rendered page. It can be right and it "
                  "cannot be held against the drawing: another run may read it differently.",
    "the DXF flat pattern": "Measured from the DXF the drawing office exported. This is the "
                            "strongest geometry the engine has.",
    "the SolidWorks model": "Taken from the model itself — the structure the shop builds from.",
    "the measured opposite hand": "Mirrored from the handed pair, which WAS measured. The blank "
                                  "is the same one.",
    "an estimator": "Somebody entered or confirmed this by hand. It outranks everything else.",
    "SDI's knowledge base": "A value SDI has previously confirmed for this part or material.",
    "an SDI override rule": "A pattern rule in the engine set this — not an observation of this "
                            "drawing.",
    "a note on the drawing": "Found in the drawing's own note text by a keyword recogniser — "
                             "WELD AND DRESS, TAP M4, FOLD. The drawing says it; a recogniser "
                             "rather than a person read it.",
    "an unrecorded source": "The value is being used and nothing stamped where it came from. "
                            "That is a gap in the engine's record-keeping, not evidence the "
                            "value is wrong — but it cannot be traced back to a drawing.",
    "not stamped": "No source was recorded for this field. Usually it means the field was never "
                   "needed for this part — a bought-in item has no thickness to read — but "
                   "where the number IS used, an unstamped value cannot be traced.",
}


def why_no_price(code: str, part_is_fabricated: bool = False) -> Tuple[str, str, bool]:
    """The blank-price reasons, which needed the most work of anything here.

    WHAT THE REPORT SAID, for 10575-01-001 — a folded mild-steel bracket SDI makes itself:

        no_price_source — no catalogue, price file or quote we can query holds this item

    James: "I don't understand why price would not exist." He is right to stop there, because
    for a fabricated part the sentence is not an explanation, it is a category error. Nobody
    sells 10575-01-001. It has no catalogue price and never will. Its cost is material plus
    labour, and if that came out blank the reason is upstream — no thickness, no blank, or no
    rate — and the catalogue was never the place to look.

    So the reason a fabricated line is blank is stated as what it is: the engine could not
    build a cost, not that a supplier could not be found.

    THE THIRD RETURN VALUE SAYS TO DROP THE RECORDED DETAIL. The pricing writer stamps its own
    sentence beside the category, and on a fabricated line that sentence is the misleading one —
    "no catalogue row, price file or quote was found for this item", printed under an
    explanation that has just said the catalogue was never the place to look. Correcting the
    heading and leaving the original underneath argues with itself in one cell.
    """
    c = str(code or "").strip()
    if c == "no_price_source" and part_is_fabricated:
        return ("Could not be costed from material and labour",
                "This is a part SDI makes, so it has no catalogue price and never will — its "
                "cost is material plus labour. One of those could not be worked out, which "
                "almost always means the thickness, the blank size or a labour rate is "
                "missing. The specific gap is listed against this part in section 5.",
                True)
    if c == "no_price_source":
        return ("Nothing we can query holds a price for it",
                "This is a bought-in item and no catalogue row, price file or quote was found "
                "for it. Either the part code does not match what SDILive holds, or nobody has "
                "priced it yet.",
                True)
    return (label(c), explain(c), False)
