r"""
test_a_page_number_names_the_drawing_it_is_printed_on.py

A PACK OF FOUR DRAWINGS HAS FOUR PAGE ONES.

file_scan renumbers every page across the whole job so `page_number` is unique — 1..N — and
keeps the document's own number as `source_page_number`, which its comment describes as "the
per-PDF original for display". Nothing displayed it.

So "where did you see that" was answered with the job-wide number and, unless the pack held
exactly one PDF, no file name at all:

    01A    not recorded · p.4

There is no p.4 an estimator can turn to. The part is on page 2 of the second document, and
they are not told which of the documents to open. Both halves of the answer were missing at
once, and the fallback that filled the file in — "if the pack has one PDF it must be that
one" — was correct exactly when the question was easy.

The page record carries `source_pdf_name` and `source_page_number`. Asking it gives a
four-PDF job the same precision as a one-PDF job:

    01A    12349-02-69_Details_RevA.PDF · p.2

James raised this against the HTML report first ("it states the part ... but not the actual
drawing file name"). The report, the workbook tab and the covering note all render through
_where, so all three were wrong together and are right together.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import estimate_explained as ee                                     # noqa: E402

GA = "12349-02-69-GA_Gravity Feeders_RevA.PDF"
DETAILS = "12349-02-69_Details_RevA.PDF"

# Two documents, renumbered job-wide exactly as file_scan renumbers them.
DOC = {
    "job_source_pdfs": [{"name": GA}, {"name": DETAILS}],
    "pages": [
        {"job_page_number": 1, "page_number": 1, "source_page_number": 1, "source_pdf_name": GA},
        {"job_page_number": 2, "page_number": 2, "source_page_number": 2, "source_pdf_name": GA},
        {"job_page_number": 3, "page_number": 3, "source_page_number": 1, "source_pdf_name": DETAILS},
        {"job_page_number": 4, "page_number": 4, "source_page_number": 2, "source_pdf_name": DETAILS},
    ],
}


@pytest.fixture(scope="module")
def ctx():
    return ee._pack_files(DOC), ee._page_index(DOC)


def _where(pages, ctx, **extra):
    pack, index = ctx
    return ee._where({"part_number": "X", "pages": pages, **extra}, pack, index)


# ── the case that was broken ───────────────────────────────────────────────────

def test_the_file_is_named_on_a_pack_of_more_than_one_drawing(ctx):
    assert _where([4], ctx).startswith(DETAILS)


def test_the_page_number_is_the_one_printed_on_that_drawing(ctx):
    """Job page 4 is page 2 of the second document. p.4 is a number on nothing."""
    assert _where([4], ctx) == f"{DETAILS} · p.2"


def test_two_documents_do_not_collide_on_their_own_page_two(ctx):
    assert _where([2], ctx) == f"{GA} · p.2"
    assert _where([4], ctx) == f"{DETAILS} · p.2"


def test_a_part_in_two_documents_pairs_each_page_with_its_own_file(ctx):
    """"GA.PDF, Details.PDF · p.2, p.1" leaves the reader to pair them, and a part listed on
    the GA and drawn on its detail is the ordinary case, not the exception."""
    got = _where([2, 3], ctx)
    assert got == f"{GA} p.2, {DETAILS} p.1"


# ── what already worked, unchanged ─────────────────────────────────────────────

def test_a_single_document_pack_still_names_itself():
    one = {"job_source_pdfs": [{"name": GA}],
           "pages": [{"job_page_number": 6, "page_number": 6, "source_page_number": 6,
                      "source_pdf_name": GA}]}
    pack, index = ee._pack_files(one), ee._page_index(one)
    assert ee._where({"pages": [6]}, pack, index) == f"{GA} · p.6"


def test_a_dxf_still_answers_with_its_own_filename(ctx):
    """The best answer available: the flat the part was actually measured off."""
    got = _where([4], ctx, dxf_source_file="K:\\jobs\\12349-02-69-01A_1.2MM_MS.DXF")
    assert got.startswith("12349-02-69-01A_1.2MM_MS.DXF")


def test_page_roles_are_still_carried(ctx):
    assert "(detail)" in _where([4], ctx, page_roles=["detail"])


def test_a_part_with_no_sheet_says_so(ctx):
    assert "no sheet of its own" in _where([], ctx)


def test_an_extract_with_no_page_records_degrades_to_the_old_answer():
    """A trimmed extract carries no pages list. It must still say what it can."""
    pack = ee._pack_files({"job_source_pdfs": [{"name": GA}]})
    assert ee._where({"pages": [6]}, pack, ee._page_index({})) == f"{GA} · p.6"
