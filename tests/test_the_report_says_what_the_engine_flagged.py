r"""The report says what the engine flagged, instead of the opposite.

401912-02's book of 18 September 2026, 07:31 -- the first complete run on that job. The
workbook's own footer:

    OUTSTANDING ESTIMATOR INPUTS (5) - this sheet is NOT a price until these are filled

and section 3 of the report beside it, in full:

    No provisional or low-confidence items flagged for this job.

TWO DELIVERABLES FROM ONE RUN, DISAGREEING ABOUT WHETHER ANYTHING NEEDED CHECKING. The cause
is a two-names fault of the kind this month has spent itself on: `_render_review_items` builds
from `estimate_review_signals.parts_flagged` -- a structured signal with a fixed vocabulary --
and NEVER from `part["review_flags"]`, which is where every sentence the costing rules write
actually lands.

So the mass check's "the line is light by 0.91 kg", the fold's "counted by
dxf_bendlines_layer -- measured, not inferred", the steel rate's refusal note, and every other
rule written this month reached the record, reached the workbook, and stopped one page short
of the estimator. The page did not merely omit them: it stated the opposite, which is worse
than saying nothing, because a reader who checks section 3 and finds it empty has been told
there is nothing to check.
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import job_report_html as J  # noqa: E402

_EMPTY = {"flagged_parts": [], "risk_flag_tally": {}, "provisional": [], "part_notes": []}


def _text(review) -> str:
    return re.sub(r"<[^>]+>", " ", J._render_review_items(review))


def _with(notes):
    return dict(_EMPTY, part_notes=notes)


_MASS = ("MASS: the blank measures 2.575 kg and the title block states 1.66 kg "
         "— the line is light by 0.91 kg")
_FOLD = "1 fold(s) charged, counted by dxf_bendlines_layer — measured, not inferred."


def test_a_flag_the_engine_wrote_reaches_the_page():
    said = _text(_with([{"note": _MASS, "parts": ["401912-02-01M"]}]))
    assert "light by 0.91 kg" in said
    assert "No provisional or low-confidence items" not in said


def test_the_part_it_was_written_about_is_named():
    """A sentence about a job of forty parts, with no part on it, cannot be checked."""
    said = _text(_with([{"note": _MASS, "parts": ["401912-02-01M"]}]))
    assert "401912-02-01M" in said


def test_one_rule_firing_on_forty_parts_is_one_row():
    """A per-part rule would otherwise print forty times and be scrolled past -- which is how
    a warning stops being read, the lesson three other flags in this engine have paid for."""
    parts = [f"P-{n:02d}" for n in range(40)]
    said = _text(_with([{"note": _FOLD, "parts": parts}]))
    assert said.count("measured, not inferred") == 1
    assert "+34 more" in said


def test_the_decisions_items_are_not_printed_twice():
    """NOT PRICED lines are the Decisions-required section's subject, and that section is the
    one that gates sending. The same item in two places on one page reads as two problems."""
    review = J.part_review_notes([
        {"part_number": "PACKAGING",
         "review_flags": ["PACKAGING: NOT PRICED — enter the per-unit figure"]},
        {"part_number": "401912-02-01M", "review_flags": [_MASS]},
    ])
    notes = " ".join(n["note"] for n in review)
    assert "NOT PRICED" not in notes
    assert "light by 0.91 kg" in notes


def test_a_job_with_nothing_to_say_still_says_nothing():
    """The control. The empty sentence is correct when it is true, and it must stay reachable
    -- a section that always has rows is a section nobody believes."""
    assert "No provisional or low-confidence items flagged" in _text(_EMPTY)


def test_the_flags_are_gathered_from_the_parts_own_record():
    """The point of the fix: the list that was never read."""
    notes = J.part_review_notes([
        {"part_number": "A-01", "review_flags": [_FOLD]},
        {"part_number": "A-02", "review_flags": [_FOLD, _MASS]},
    ])
    by_note = {n["note"]: n["parts"] for n in notes}
    assert by_note[_FOLD] == ["A-01", "A-02"]
    assert by_note[_MASS] == ["A-02"]


def test_a_part_with_no_flags_contributes_nothing():
    assert J.part_review_notes([{"part_number": "A-01"}]) == []
    assert J.part_review_notes([{"part_number": "A-01", "review_flags": []}]) == []


def test_blank_and_non_string_flags_are_not_rendered_as_rows():
    notes = J.part_review_notes(
        [{"part_number": "A-01", "review_flags": ["", "   ", None]}])
    assert notes == []
