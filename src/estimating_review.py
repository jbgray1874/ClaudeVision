"""
estimating_review.py — the flags, sorted into what a person actually does with them.

TWENTY-ONE FLAGS IN ONE UNDIFFERENTIATED LIST IS A RESEARCH PROJECT, EVEN WHEN EVERY NUMBER IN
IT IS RIGHT. An estimator opening 11650-04 got BLOCKING and warning interleaved, a missing
catalogue rate reading the same as an invented BOM node, and a declared powder assumption
sitting between them. All true, all in the wrong order, and the honest response to that list is
to close it.

SEVERITY IS NOT THE SORT. Severity says how bad; it does not say WHOSE. A BLOCKING "this
material has no rate" is a decision waiting for a person and is perfectly ordinary work. A
WARNING "this part was invented downstream of the drawing read" is the engine confessing and is
nobody's work but ours. Ordering by severity puts those next to each other and asks the reader
to tell them apart.

SO IT SORTS BY WHAT TO DO. Three buckets, in the order a person works:

  CONFIRM OR OVERWRITE   a number is on the sheet and somebody has to stand behind it —
                         indicative prices, a short-run offcut, a gauge two sources disagree
                         about. This is estimating, and a good run produces MORE of it.

  MISSING OR BROKEN      the engine could not read something cleanly, or read it and cannot
                         defend where it came from. Ours, and the list that has to shrink —
                         but NOT a reason to leave work off the estimate. Everything that
                         could be priced has been; what this bucket says is which numbers to
                         check first, and every one of them is a cell an estimator can change.

  FOR INFORMATION        a number the engine chose, said so, and named the lever for. Not a
                         decision and not a defect — until somebody disagrees, at which point
                         the lever is right there.

NAMED FOR THE FUNCTION, NOT THE PERSON. "Estimating review" survives Tim being on holiday; a
tab called Tim goes stale the first day somebody else estimates, and reads as a personal
to-do rather than a step in the process.

ONE ACTION PER LINE. "What, why it matters, what to do" — because a flag an estimator has to
interpret is a flag they will skip on the fourth job.
"""
from __future__ import annotations

from typing import Any, Dict, List

import engine_discoveries

SCHEMA = "estimating_review.v1"

DRAWINGS = "Ask the drawing office"
PRICES = "Missing from SDILive"
CONFIRM = "Confirm or overwrite"
BROKEN = "Missing or broken inputs"
INFORMATION = "For information — assumptions the engine made"

# ONE MORE SPLIT, BECAUSE ONE BUCKET HELD THREE PEOPLE'S WORK. "Missing or broken inputs"
# carried a flat pattern nobody has drawn, a rate nobody has entered in SDILive, and a node
# the engine invented — filed together because none of them is estimating. They are fixed by
# the drawing office, by whoever maintains the price data, and by us, and an estimator reading
# one list cannot hand any of it on.
#
# NOTHING HERE IS A VERDICT. These are not reasons to doubt the total; they are the specific
# things that would make the next estimate better, each named with an owner. Everything that
# could be priced has been priced.
#
# The order is who is furthest from the sheet. A DXF has to be asked for and waited on, so it
# goes first and goes early enough to matter; a rate is a row somebody can add today; the
# confirms are the estimator's own and can be done with the job open. Ours is last because it
# is our morning's work and not theirs.
ORDER = (DRAWINGS, PRICES, CONFIRM, BROKEN, INFORMATION)

_BUCKET_FOR = {"drawing": DRAWINGS, "commerce": PRICES, "estimator": CONFIRM,
               "engine": BROKEN, "assumption": INFORMATION, "unverified": BROKEN}

# WHAT TO DO, in a sentence, for the codes that carry a standard action. Anything not listed
# falls back to the bucket's own instruction rather than inventing advice — a made-up action is
# worse than none, because it gets followed.
_ACTION = {
    "price_not_reproducible": "Replace with a catalogue or supplier rate, or accept it and "
                              "quote this as an estimate rather than a firm price.",
    "material_has_no_rate_in_this_engine": "Enter a rate for the material, or confirm the part "
                                           "is something we already price.",
    "stated_finish_not_costed": "Price the finish, or add a £/m² to "
                                "config.APPLIED_FINISH_RATES_GBP_PER_M2 so every job carries it.",
    "short_run_pays_for_sheet_it_does_not_use": "Charge the offcut, or decide it goes to stock.",
    "two_sources_disagree_about_the_gauge": "Confirm which gauge the part is made from.",
    "two_sources_disagree_about_the_material": "Confirm which material the part is made from.",
    "handed_pair_disagrees": "The two hands read differently and the evidence is even. "
                             "Confirm which is right.",
    "handed_pair_settled_on_cut_file": "The two hands read different materials; priced from the "
                                       "exported cut file the CNC uses, not the model. Confirm "
                                       "the material before quoting firm.",
    "cad_files_not_read": "If any are flat patterns, ask for a DXF; general arrangements add "
                          "nothing over the PDF.",
    "price_not_firm": "Expected on an estimate. Clear it only when quoting firm.",
    # PRICED ANYWAY, AND SAID SO. A broken join is a fault in the drawing pack's structure,
    # not a reason to leave the work off the estimate. The part is costed from what WAS read;
    # what the broken join puts in doubt is the QUANTITY it should carry, and that is a number
    # an estimator changes in one cell.
    "canonical_route_bom_node_disconnected":
        "The part is priced from what was read. Its link to a parent assembly is broken in "
        "the drawing pack, so the quantity may be wrong — confirm or change it.",
    "bom_node_disconnected":
        "The part is priced from what was read. Its link to a parent assembly is broken in "
        "the drawing pack, so the quantity may be wrong — confirm or change it.",
    "native_top_assembly_ambiguous":
        "Two assemblies could each be the top of this job and one was chosen by closest "
        "match. Confirm it, or change the quantities if the other is right.",
    "assembly_only_part_record":
        "Built from assembly pages with no detail drawing of its own. Priced from what was "
        "read — confirm the size and material, or ask for the detail.",
}

_BUCKET_ACTION = {
    DRAWINGS: "Ask the drawing office for it. The job is priced from what could be read "
              "meanwhile.",
    PRICES: "Add the rate to SDILive, or price the line by hand on the sheet.",
    CONFIRM: "Confirm the figure or overwrite it.",
    # NOT "STOP". Everything that could be priced HAS been, and an estimator can change any
    # of it. What this bucket says is which numbers rest on something the engine could not
    # read cleanly — so they are checked first, not so the job waits.
    BROKEN: "Priced from what could be read. Check this one before the others, and change "
            "anything you disagree with.",
    INFORMATION: "No action unless you disagree with the assumption.",
}


def _line(violation: Dict[str, Any]) -> Dict[str, Any]:
    code = str(violation.get("code") or "")
    bucket = _BUCKET_FOR.get(engine_discoveries.classify(code), BROKEN)
    return {
        "bucket": bucket,
        "code": code,
        "severity": violation.get("severity"),
        # WHAT AND WHY, IN THE ENGINE'S OWN WORDS. These messages were written to be read; a
        # summary of a summary loses the part an estimator needs.
        "what": str(violation.get("message") or "").strip(),
        "what_to_do": _ACTION.get(code) or _BUCKET_ACTION[bucket],
    }


def review(result: Any) -> Dict[str, Any]:
    """The invariant result, re-sorted into what a person does with it.

    IT REPORTS; IT DOES NOT RULE. The engine's job is to give an estimator the BOM, the route
    and the prices, and to say where each one came from. Whether that is enough to quote from
    is the estimator's judgement, made with the job in front of them and everything else they
    know about the customer — none of which is in here.

    So there is no verdict on these lines any more. There was: every finding carried a
    "blocks a firm quote" flag and the block opened by announcing the estimate was not a firm
    price. It was also empty in practice — thirty-four separate findings set it, three of them
    fired on every job because no supplier feed is integrated yet, and a warning that is
    always on is one an estimator learns to scroll past. Removing it costs nothing that was
    working and takes the engine out of a decision that was never its to make.

    What remains is the part that has value: the finding, why it matters, and the lever.
    """
    violations = (result or {}).get("violations") if isinstance(result, dict) else None
    lines = [_line(v) for v in (violations or []) if isinstance(v, dict)]
    buckets: Dict[str, List[Dict[str, Any]]] = {b: [] for b in ORDER}
    for ln in lines:
        buckets[ln["bucket"]].append(ln)
    # Stable within a bucket, so the same job reads the same way twice and a line does not
    # move between runs for a reason nobody can see.
    for b in buckets:
        buckets[b].sort(key=lambda l: l["code"])
    return {
        "schema": SCHEMA,
        "buckets": [{"title": b, "lines": buckets[b]} for b in ORDER if buckets[b]],
        "counts": {b: len(buckets[b]) for b in ORDER},
        "metric": engine_discoveries.count(violations or []),
    }


def format_review(rev: Dict[str, Any]) -> str:
    """The block that goes on the console, in the report, and beside the outstanding inputs."""
    if not isinstance(rev, dict) or not rev.get("buckets"):
        return "[estimating review] nothing outstanding"
    out: List[str] = ["", "══ ESTIMATING REVIEW ══════════════════════════════════════════"]
    for group in rev["buckets"]:
        out.append("")
        out.append(f"   {group['title'].upper()}  ({len(group['lines'])})")
        for ln in group["lines"]:
            # One marker, because there is no longer a tier. A line either wanted saying or
            # it did not, and the bucket already says whose work it is.
            out.append(f"     · {ln['what']}")
            out.append(f"       -> {ln['what_to_do']}")
    m = rev.get("metric") or {}
    out.append("")
    out.append(f"   [engine] {engine_discoveries.one_line(m)}")
    return "\n".join(out)
