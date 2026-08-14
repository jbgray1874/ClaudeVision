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


def test_inside_a_bucket_the_blocking_ones_lead():
    """Severity is the wrong TOP-level sort and the right one within a group of things the
    same person is doing in the same sitting."""
    lines = _bucket(er.review(RUN), er.CONFIRM)["lines"]
    assert lines[0]["blocks_a_firm_quote"] is True
    assert lines[-1]["blocks_a_firm_quote"] is False


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


# ── the gate is unchanged ────────────────────────────────────────────────────────────

def test_resorting_does_not_soften_blocking():
    """BLOCKING still means not firm and no ERP export. Re-sorting changes the order and the
    wording, never the gate — an estimate that reads calmly and quotes firm on an unconfirmed
    AI price is worse than the list it replaced."""
    rev = er.review(RUN)
    assert rev["may_quote_firm"] is False
    assert sum(1 for g in rev["buckets"] for l in g["lines"]
               if l["blocks_a_firm_quote"]) == 2
    assert "not a firm price" in er.format_review(rev).lower()


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
