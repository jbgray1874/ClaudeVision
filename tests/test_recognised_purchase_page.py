"""A purchase recognised in a drawing note has to be able to say which sheet said so.

A part with no page can never be given an owner, and an unowned part blocks the job as a
disconnected node. BI-BOLTBZP is a real GBP 0.83 bolt that blocked 12392 for exactly that
reason — not because the sheet was unknown, but because the phrase was compared against an
un-normalised copy of the very page it was read from.
"""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import bought_in_recogniser as bir  # noqa: E402


def _page(text, number=3, key="text"):
    return [{"page_number": number, key: text}]


def test_a_phrase_split_across_a_line_break_is_still_found():
    """The case that mattered. Drawing notes wrap, so a line break inside a two-word
    phrase is the normal case rather than an edge one."""
    assert bir._page_that_says("BOLT BZP",
                               _page("NOTE: FIX WITH M6 BOLT\nBZP AND WASHER")) == 3


def test_double_spacing_and_tabs_are_found():
    assert bir._page_that_says("BOLT BZP", _page("M6 BOLT  BZP")) == 3
    assert bir._page_that_says("BOLT BZP", _page("M6\tBOLT\tBZP")) == 3


def test_a_plain_match_still_works():
    assert bir._page_that_says("BOLT BZP", _page("M6 BOLT BZP")) == 3


def test_a_phrase_that_is_not_there_is_not_invented():
    """Mutation guard. Normalising both sides must not make everything match — an owner
    offered on a page that never said it is worse than no owner at all."""
    assert bir._page_that_says("BOLT BZP", _page("M6 SCREW AND WASHER ONLY")) is None


def test_the_notes_region_is_read_as_well_as_the_page_text():
    pages = [{"page_number": 7, "region_text": {"notes": "ASSEMBLE WITH\nBOLT BZP"}}]
    assert bir._page_that_says("BOLT BZP", pages) == 7


def test_the_first_page_that_says_it_wins():
    pages = [{"page_number": 2, "text": "GENERAL NOTES"},
             {"page_number": 4, "text": "USE BOLT BZP"},
             {"page_number": 5, "text": "ALSO BOLT BZP"}]
    assert bir._page_that_says("BOLT BZP", pages) == 4


def test_no_pages_and_no_phrase_are_answered_honestly():
    assert bir._page_that_says("BOLT BZP", []) is None
    assert bir._page_that_says("BOLT BZP", None) is None
    assert bir._page_that_says("", _page("BOLT BZP")) is None
    assert bir._page_that_says(None, _page("BOLT BZP")) is None


def test_a_page_with_no_number_does_not_pretend_to_have_one():
    assert bir._page_that_says("BOLT BZP", [{"text": "USE BOLT BZP"}]) is None
