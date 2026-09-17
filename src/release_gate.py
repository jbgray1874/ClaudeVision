"""A required line with no price stops the estimate. It never quietly totals as zero.

James Gray, 18 September 2026, on the 7332-01 six-off book:

    "we should have a price for everything.. why would a price be 0 when we have so many
     layers including llm"

    "the estimate must be blocked as incomplete, not totalled with a zero... It must never
     show a normal-looking £108.89 unit price that quietly excludes four required costs."

    "an LLM indicative price may contribute to the estimate total. It must be a genuine
     fourth pricing rung, with independent research or a reproducible calculation; source
     links/details, date, unit and quantity basis; a clear 'LLM indicative - review
     required' label... If that evidence cannot be produced, the line makes the estimate
     incomplete and blocks release. It never becomes £0."

WHY A GATE RATHER THAN A PRICE.

Withdrawing the typed commodity prices (D-095) was right and, on its own, made the problem
WORSE: the felt pad went from a wrong price to no price, and no price reaches the sheet as
a blank that the total simply steps over. A zero is the one answer that is never true. The
pad costs something; the plating costs something; the freight costs something. An estimate
that adds up as though they cost nothing is not incomplete-looking, it is WRONG-looking,
and it looks exactly like a finished one.

So the rule is about what the engine is willing to PUBLISH, not about what it can price.

    A ZERO IS ONLY EVER VALID when the line is free-issued, not required, or deliberately
    excluded by an estimator decision. Those three are decisions somebody made. Everything
    else is an unanswered question, and an unanswered question blocks.

THE FOUR RUNGS, AND WHAT COUNTS AS AN ANSWER.

    1  the current SDI Live / UDEF rate
    2  a supplier catalogue or API
    3  an identified current quote for this job
    4  an LLM-supported indicative price - independently researched or reproducibly
       calculated, dated, carrying its source and its unit and quantity basis

Rungs 1 to 3 are answers because somebody outside this engine stands behind them. Rung 4 is
an answer ONLY with its evidence, and that is the whole difference between it and the
config literals just deleted: a figure typed into a source file and a figure labelled
INDICATIVE both look the same on a sheet, and neither can be checked. A researched price
that names its source, its date and what it is per CAN be checked, which is what makes it
admissible. `evidence_gaps` below is deliberately specific about which of those is missing,
because "no evidence" is not something an estimator can act on.

WHAT THIS MODULE DOES NOT DO. It does not price anything and it does not decide the rungs'
order; the pricing path does that. It reads the finished estimate and answers one question:
is this releasable. Kept separate so the answer cannot be quietly weakened by a change made
for some other reason inside the pricing chain.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

__all__ = [
    "LLM_INDICATIVE_LABEL",
    "evidence_gaps",
    "is_evidenced_indicative",
    "line_is_answered",
    "assess_release",
]

# The words that must appear against a rung-4 price wherever it is shown - workbook, report
# and quote alike. One spelling, so a reader who has seen it once recognises it anywhere.
LLM_INDICATIVE_LABEL = "LLM indicative - review required"

# A price is money; these are the four things that make a researched figure checkable.
_EVIDENCE_FIELDS = (
    ("source", "where the figure came from - a link, a supplier, a named calculation"),
    ("as_of", "the date it was true, because a market price without a date is folklore"),
    ("unit_basis", "what the figure is PER - each, per metre, per kg, per order"),
    ("quantity_basis", "the quantity it was found at, since break pricing moves with it"),
)

# Reasons a line may legitimately carry nothing. Each is a DECISION somebody made, which is
# what separates it from a gap.
_LEGITIMATE_ZERO = ("free_issue", "not_required", "estimator_excluded", "customer_supplied")


def _clean(value: Any) -> str:
    return str(value or "").strip()


def evidence_gaps(price_record: Any) -> List[str]:
    """Which of the four evidence fields a researched price is missing, in words.

    Returns [] when the record carries all four. Named individually because "not evidenced"
    tells an estimator nothing they can act on, while "no date, and no unit basis" does.
    """
    if not isinstance(price_record, dict):
        return [why for _f, why in _EVIDENCE_FIELDS]
    return [why for field, why in _EVIDENCE_FIELDS if not _clean(price_record.get(field))]


def is_evidenced_indicative(price_record: Any) -> bool:
    """A rung-4 price that may contribute to the total.

    The evidence is the admission ticket. Without it the figure is indistinguishable from
    the literals withdrawn under D-095 - and those were labelled INDICATIVE too.
    """
    if not isinstance(price_record, dict):
        return False
    try:
        amount = float(price_record.get("price_gbp"))
    except (TypeError, ValueError):
        return False
    if amount <= 0:
        return False
    return not evidence_gaps(price_record)


def line_is_answered(line: Any) -> bool:
    """Does this line have a price, or a decision that it needs none?

    A line is answered when it carries money above zero, OR when somebody has ruled that it
    costs nothing - free-issued, not required, excluded by the estimator, supplied by the
    customer. A blank with no ruling behind it is not an answer; it is the question nobody
    got to, and it is exactly what this whole module exists to stop being totalled.
    """
    if not isinstance(line, dict):
        return False
    if _clean(line.get("zero_reason")).lower() in _LEGITIMATE_ZERO:
        return True
    if not line.get("required", True):
        return True
    try:
        amount = float(line.get("price_gbp"))
    except (TypeError, ValueError):
        return False
    if amount <= 0:
        return False
    # A rung-4 figure only counts with its evidence. Rungs 1 to 3 have somebody outside this
    # engine standing behind them and need none.
    if _clean(line.get("rung")).lower() in ("llm", "llm_indicative", "market", "web_ai",
                                            "web_ai_fallback", "llm_market_estimate"):
        return is_evidenced_indicative(
            dict(line.get("evidence") or {}, price_gbp=amount))
    return True


def assess_release(lines: Any, *, job: Any = "") -> Dict[str, Any]:
    """Is this estimate releasable, and if not, exactly which lines stop it.

    `lines` is any iterable of dicts carrying at least a description and a price; the
    keys this reads are documented on `line_is_answered`. The verdict is deliberately
    blunt - releasable or not - because "mostly priced" is the state that produced a
    normal-looking total with four costs missing from it.
    """
    blocking: List[Dict[str, Any]] = []
    answered = 0
    for line in list(lines or []):
        if not isinstance(line, dict):
            continue
        if line_is_answered(line):
            answered += 1
            continue
        _gaps = (evidence_gaps(line.get("evidence"))
                 if _clean(line.get("rung")).lower().startswith("llm") else [])
        blocking.append({
            "code": _clean(line.get("code")) or _clean(line.get("part_number")) or "-",
            "description": _clean(line.get("description"))[:160],
            "owner": _clean(line.get("owner")) or "not named",
            "why": (f"a researched price was offered without {', '.join(_gaps)}"
                    if _gaps else "no price from any rung, and no ruling that it needs none"),
        })

    releasable = not blocking
    return {
        "schema": "estimate_release_gate.v1",
        "job": _clean(job),
        "releasable": releasable,
        "lines_answered": answered,
        "lines_blocking": len(blocking),
        "blocking": blocking,
        "headline": (
            "RELEASABLE - every required line is priced or ruled"
            if releasable else
            f"NOT RELEASABLE - {len(blocking)} required line(s) carry no price. This "
            f"estimate is INCOMPLETE: its total excludes real costs and must not be read "
            f"as a unit price or sent to a customer."
        ),
        # The reader's instruction, not a description of the state. An incomplete estimate
        # that says only "incomplete" gets released by somebody in a hurry.
        "what_to_do": (
            "" if releasable else
            "Price each line below from SDI Live, a supplier catalogue or a current quote, "
            "or record an evidenced indicative figure (source, date, unit basis, quantity "
            "basis). If a line genuinely costs nothing, say why - free issue, not required, "
            "excluded - and that is an answer. A blank is not."
        ),
    }
