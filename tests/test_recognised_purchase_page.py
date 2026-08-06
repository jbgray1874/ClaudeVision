"""
A recognised purchase with no page can never be given an owner.

BI-BOLTBZP is a real GBP 0.83 bolt. The prose recogniser found the words "Bolt Bzp" in a
drawing's notes, priced it from history, and emitted it — with `source`, `page_roles` and
`review_flag`, and no record of which sheet said so. It then blocked job 12392 as a
"disconnected node" for exactly that reason: the compiler had an owner to offer it and no way
to know which.

The caller reads the notes PAGE BY PAGE and joins them one line before calling
(estimator.py, _note_chunks -> _note_text). The page was known and thrown away — the same
defect, and the same fix, as the BOM rows: attribute AFTER the match, so which phrases are
recognised does not change at all.

Two things this deliberately does not do. It does not refuse to emit a part whose page it
cannot find — that would delete a real purchase to satisfy a checker. And it does not make
the page an owner: the compiler still requires an ASSEMBLY page of a drawing the job already
knows before any edge is made.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from bought_in_recogniser import _page_that_says


PAGES = [
    {"page_number": 1, "region_text": {"notes": "GENERAL ARRANGEMENT. ALL WELDS DRESSED."}},
    {"page_number": 2, "region_text": {"notes": "FIXINGS: 4 OFF BOLT BZP M6 x 25"}},
    {"page_number": 3, "pdfplumber_text": "DETAIL SHEET - PANEL STIFFENER"},
]


def test_the_page_that_named_the_purchase_is_found():
    assert _page_that_says("Bolt Bzp", PAGES) == 2
    assert _page_that_says("BOLT BZP", PAGES) == 2


def test_it_reads_every_text_variant_a_page_carries():
    """_note_text is built from notes AND four different text extractions of the same page.
    Reading fewer of them here than the recogniser reads there would attribute a hit to no
    page while the phrase plainly matched — deterministically losing the owner."""
    assert _page_that_says("PANEL STIFFENER", PAGES) == 3
    assert _page_that_says("welds dressed", PAGES) == 1


def test_a_phrase_no_page_carries_lands_on_no_page():
    """A phrase spanning a page break still MATCHES in the joined text — it simply belongs to
    no single sheet, and saying so is the honest answer. The part is still emitted."""
    assert _page_that_says("KNURLED KNOB", PAGES) is None


def test_absence_is_not_an_error():
    assert _page_that_says("Bolt Bzp", None) is None
    assert _page_that_says("Bolt Bzp", []) is None
    assert _page_that_says("", PAGES) is None
    assert _page_that_says(None, PAGES) is None
    assert _page_that_says("Bolt Bzp", [None, "not a page"]) is None


def test_a_page_with_no_number_is_not_guessed_at():
    assert _page_that_says("BOLT BZP", [{"region_text": {"notes": "BOLT BZP"}}]) is None


def test_the_recogniser_accepts_pages_and_the_caller_supplies_them():
    """A parameter nothing passes is the defect it was added to fix."""
    import inspect
    import bought_in_recogniser, estimator
    assert "pages" in inspect.signature(
        bought_in_recogniser.recognise_bought_in_in_prose).parameters
    assert "pages=(summary.get(\"pages\") or [])" in inspect.getsource(estimator)
