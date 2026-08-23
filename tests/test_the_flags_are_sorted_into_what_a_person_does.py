"""Twenty-one flags in one list is a research project, even when every number is right.

An estimator opening 11650-04 got BLOCKING and warning interleaved: a missing catalogue rate
reading the same as an invented BOM node, and a declared powder assumption sitting between
them. All true, all in the wrong order, and the honest response to that list is to close it.

SEVERITY IS NOT THE SORT. Severity says how bad; it does not say WHOSE. A BLOCKING "this
material has no rate" is a decision waiting for a person and is perfectly ordinary work. A
WARNING "this part was invented downstream of the drawing read" is the engine confessing.
Ordering by severity puts those next to each other and asks the reader to tell them apart.

SO IT SORTS BY WHAT TO DO — confirm or overwrite, missing or broken, for information — and
each line carries one action, because a flag somebody has to interpret is a flag they will
skip on the fourth job.

NAMED FOR THE FUNCTION, NOT THE PERSON. "Estimating review" survives Tim being on holiday.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import estimating_review as er  # noqa: E402

RUN = {"blocking": 2, "warnings": 2, "unverified": 0, "may_quote_firm": False, "violations": [
    {"code": "price_not_reproducible", "severity": "blocking",
     "message": "1 priced line was costed by an AI market estimate."},
    {"code": "canonical_route_bom_node_disconnected", "severity": "blocking",
     "message": "11650-04-02M has no defensible owner in the job hierarchy."},
    {"code": "short_run_pays_for_sheet_it_does_not_use", "severity": "warning",
     "message": "At 5 off, PETG 2.0mm is charged 0.04 sheet(s)."},
    {"code": "throughput_floor_applied", "severity": "warning",
     "message": "Laser (Acrylic) derived 16.28/hr; using default 252/hr."},
]}


def _bucket(rev, title):
    return next((g for g in rev["buckets"] if g["title"] == title), None)


# ── the sort ─────────────────────────────────────────────────────────────────────────

def test_a_decision_and_a_confession_do_not_sit_together():
    """THE DEFECT, STATED AS THE TEST. Both are BLOCKING; only one is estimating work."""
    rev = er.review(RUN)
    confirm = {l["code"] for l in _bucket(rev, er.CONFIRM)["lines"]}
    broken = {l["code"] for l in _bucket(rev, er.BROKEN)["lines"]}
    assert "price_not_reproducible" in confirm
    assert "canonical_route_bom_node_disconnected" in broken
    assert not (confirm & broken)


def test_a_declared_assumption_is_not_presented_as_a_problem():
    """A number the engine chose, said so, and named the lever for. Listing it beside an
    invented part teaches an estimator to skim past both."""
    rev = er.review(RUN)
    assert [l["code"] for l in _bucket(rev, er.INFORMATION)["lines"]] == \
        ["throughput_floor_applied"]


def test_decisions_come_first_because_they_stop_the_quote():
    """The order a person works, not the order the checks ran."""
    assert er.ORDER[0] == er.CONFIRM
    assert [g["title"] for g in er.review(RUN)["buckets"]][0] == er.CONFIRM


def test_inside_a_bucket_the_order_is_stable():
    """Stable, so the same job reads the same way twice.

    This used to lead with the findings that stopped a firm quote. There is no such tier any
    more — the engine reports and the estimator decides — so the only property left worth
    holding is that a line does not move between runs for a reason nobody can see.
    """
    rev = er.review(RUN)
    codes = [l["code"] for l in _bucket(rev, er.CONFIRM)["lines"]]
    assert codes == sorted(codes)
    assert codes == [l["code"] for l in _bucket(er.review(RUN), er.CONFIRM)["lines"]]


def test_an_empty_bucket_is_not_shown():
    """A heading with nothing under it reads as something missing."""
    rev = er.review({"violations": [{"code": "throughput_floor_applied",
                                     "severity": "warning", "message": "x"}]})
    assert [g["title"] for g in rev["buckets"]] == [er.INFORMATION]


# ── each line is actionable ──────────────────────────────────────────────────────────

def test_every_line_says_what_to_do():
    """A flag somebody has to interpret is a flag they will skip on the fourth job."""
    for g in er.review(RUN)["buckets"]:
        for l in g["lines"]:
            assert l["what_to_do"] and len(l["what_to_do"]) > 15, l


def test_a_known_code_gets_its_own_action_not_the_generic_one():
    line = next(l for g in er.review(RUN)["buckets"] for l in g["lines"]
                if l["code"] == "short_run_pays_for_sheet_it_does_not_use")
    assert "offcut" in line["what_to_do"]


def test_a_broken_join_is_priced_and_the_line_says_so():
    """WE PRICE WHAT WE CAN AND SAY WHAT WAS WRONG. A broken join is a fault in the drawing
    pack's structure, not a reason to leave the work off the estimate. 11650-04-02M is costed
    in the Sheet Steel block and carries P.Coat labour — the earlier wording told an estimator
    to "raise it rather than working around it", which reads as stop on a line that is already
    priced, and contradicts the policy applied everywhere else on the sheet.

    What the broken join actually puts in doubt is the QUANTITY, and that is one cell."""
    line = next(l for g in er.review(RUN)["buckets"] for l in g["lines"]
                if l["code"] == "canonical_route_bom_node_disconnected")
    assert "priced from what was read" in line["what_to_do"].lower()
    assert "quantity" in line["what_to_do"].lower()
    assert "raise it rather than" not in line["what_to_do"]


def test_the_broken_bucket_does_not_tell_anyone_to_stop():
    """Everything that could be priced has been. This bucket says which numbers to CHECK
    FIRST, not that the job waits for an engineer."""
    action = er._BUCKET_ACTION[er.BROKEN]
    assert "change anything you disagree with" in action.lower()
    assert "raise it rather than" not in action


def test_an_unknown_code_falls_back_rather_than_inventing_advice():
    """A made-up action is worse than none, because it gets followed."""
    rev = er.review({"violations": [{"code": "something_new", "severity": "warning",
                                     "message": "x"}]})
    action = rev["buckets"][0]["lines"][0]["what_to_do"]
    assert action == er._BUCKET_ACTION[er.BROKEN]


def test_the_engines_own_words_are_kept():
    """These messages were written to be read. A summary of a summary loses the part an
    estimator needs — the part number, the quantity, the two figures that disagree."""
    line = next(l for g in er.review(RUN)["buckets"] for l in g["lines"]
                if l["code"] == "canonical_route_bom_node_disconnected")
    assert "11650-04-02M" in line["what"]


# ── it reports, it does not rule ──────────────────────────────────────────────────────

def test_the_review_passes_no_verdict():
    """The engine gives the BOM, the route, the prices and where each came from. Whether that
    is enough to quote from is the estimator's judgement, made with the job in front of them.

    This previously carried a verdict: every line held a "blocks a firm quote" flag and the
    block opened by announcing the estimate was not a firm price. It was also empty in
    practice — thirty-four findings set it and three fired on every job, so it was always on,
    and a warning that is always on is one people learn to scroll past.
    """
    rev = er.review(RUN)
    assert "may_quote_firm" not in rev, "no verdict in the payload"
    for g in rev["buckets"]:
        for l in g["lines"]:
            assert "blocks_a_firm_quote" not in l, "and none on a line"
    text = er.format_review(rev).lower()
    assert "not a firm price" not in text
    assert "blocking" not in text


def test_every_finding_still_appears_and_still_names_its_lever():
    """Removing the verdict must not remove the information. Nothing is hidden; what changed
    is that the engine no longer grades it."""
    rev = er.review(RUN)
    codes = {l["code"] for g in rev["buckets"] for l in g["lines"]}
    assert len(codes) == len([v for v in RUN["violations"]]), "every finding is still reported"
    for g in rev["buckets"]:
        for l in g["lines"]:
            assert l["what"], "the finding is stated"
            assert l["what_to_do"], "and the lever is named"


def test_the_metric_travels_with_the_review():
    """Whose fault the list is, beside the list. One is the day's work; the other is whether
    the next pack will be quieter."""
    assert er.review(RUN)["metric"]["engine_discoveries"] == 1


# ── named for the function, and wired ────────────────────────────────────────────────

def test_it_is_named_for_the_job_not_the_person():
    """A tab called Tim goes stale the first day somebody else estimates, and reads as a
    personal to-do rather than a step in the process."""
    import re
    text = er.format_review(er.review(RUN))
    assert "ESTIMATING REVIEW" in text
    # A WHOLE WORD. "esTIMating" contains the substring, and my first version of this failed
    # on the very heading it was asserting — the same naive-substring shape that let ABS match
    # inside ABSORBER and PET inside PETG.
    assert not re.search(r"(?<![a-z])tim(?![a-z])", text.lower()), text


def test_the_report_an_estimator_reads_carries_it():
    """BUILT IS NOT WIRED. A sorted list nothing prints is the raw twenty-one lines."""
    import invariants
    out = invariants.format_report(RUN)
    assert "ESTIMATING REVIEW" in out
    assert "CONFIRM OR OVERWRITE" in out
    # The raw list stays too: it is the record, and a developer reading a log wants it whole
    # and in check order.
    assert "canonical_route_bom_node_disconnected:" in out


def test_a_broken_review_does_not_take_the_report_with_it():
    """The console block is the last thing between a finished run and a person. It must never
    be the reason they see nothing."""
    import invariants
    real = er.format_review
    er.format_review = lambda rev: (_ for _ in ()).throw(RuntimeError("boom"))
    try:
        out = invariants.format_report(RUN)
        assert "price_not_reproducible" in out
    finally:
        er.format_review = real
