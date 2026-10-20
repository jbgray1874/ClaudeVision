"""A page that cannot name itself cannot own anything.

Job 12392's bolt had everything it needed and stayed disconnected: page 6 is an assembly
page, and the record carried source_page=6 into both pools the compiler builds its
population from. The only thing missing was the page's own name.

DRAWING_NUMBER_PATTERN requires a literal "DWG NO" or "DRAWING NO" immediately before the
code, so a title block whose label does not survive text extraction next to its number
yields nothing — and assembly_page_owners then falls back to the file stem, which matches
no part the job knows.

Meanwhile _bom_words_reader's own title-block read finds 12392-04-GA on that very sheet.
Two functions answering "which drawing is this page", and the ownership chain used the
weaker one.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import file_scan  # noqa: E402


def _page(title_block):
    return {"region_text": {"title_block": title_block}}


@pytest.mark.parametrize("title_block,expected", [
    ("DWG NO 12392-04-GA", "12392-04-GA"),          # the labelled path, unchanged
    ("12392-04-GA", "12392-04-GA"),                 # no label — the case that broke it
    ("12392-02-01M", "12392-02-01M"),
    ("1282 - GA", "1282-GA"),                       # the spaced form a drawing prints
    ("12392-02 - GA", "12392-02-GA"),
])
def test_a_title_block_names_its_drawing_with_or_without_a_label(title_block, expected):
    assert file_scan._page_drawing_number(_page(title_block)) == expected


def test_the_description_is_not_swallowed():
    """Joining greedily made "12392-04-GA MOD BRACKET SET" into one long token that passes
    the shape test, because every word in it is alphanumeric."""
    assert file_scan._page_drawing_number(
        _page("12392-04-GA MOD BRACKET SET")) == "12392-04-GA"


def test_the_prefix_is_not_taken_for_the_whole():
    """"12392-02 - GA" read as "12392-02" is the sheet's PARENT. Every row on the page
    would be reparented one level up — silently, and plausibly."""
    assert file_scan._page_drawing_number(_page("12392-02 - GA")) == "12392-02-GA"


def test_two_drawing_numbers_name_neither():
    """A region holding two has caught a cross-reference as well as its own, and naming
    the wrong one gives every row on the page the wrong owner. The labelled path has
    always refused this; the unlabelled one must too."""
    assert file_scan._page_drawing_number(_page("12392-04-GA SEE 1450-GA")) == ""


@pytest.mark.parametrize("title_block", [
    "MOD BRACKET SET",
    "DRAWN BY JS SCALE 1:2",
    "",
])
def test_a_title_block_that_names_no_drawing_says_so(title_block):
    assert file_scan._page_drawing_number(_page(title_block)) == ""


def test_the_shape_rule_is_the_shared_one():
    """Not a third private opinion about what a drawing number looks like. The BOM
    reader's title-block read and the route compiler already ask part_code_conventions."""
    source = (SRC / "file_scan.py").read_text(encoding="utf-8")
    assert "_pcc.looks_like_a_drawing_number" in source
