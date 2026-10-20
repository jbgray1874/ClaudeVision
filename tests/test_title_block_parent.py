"""Which drawing this page IS — the fact every BOM row on it depends on.

A BOM row whose parent is unknown cannot join a hierarchy. It is not attached to the
wrong place; it is attached to nowhere, and a forest assembled from rows that could not
say who owned them is what has been read as "the family tree is broken" on job after job.

The reader's title-block regex required THREE hyphenated segments — the 12120 house
style. Two-segment numbers are the common case at SDI (1282-GA, 12392-04, 3886-GA) and
matched nothing at all. It also tested one word at a time, so a title block printing
"1282 - GA" with real spaces yielded three words and no drawing number.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import _bom_words_reader as wr  # noqa: E402
import part_code_conventions as pcc  # noqa: E402
import route_compiler  # noqa: E402


# ---------------------------------------------------------------------------
# The shape rule
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("code", [
    "12120-01-001",   # the three-segment house style the old regex was written for
    "1282-GA",        # two segments — matched nothing before
    "12392-04",
    "12392-02-GA",
    "3886-GA-C",
    "2085-01",
    "1455-C-GA",
    "11350-01-01M",
])
def test_real_sdi_drawing_numbers_are_recognised(code):
    assert pcc.looks_like_a_drawing_number(code) is True


@pytest.mark.parametrize("text", [
    "PANEL",          # a description
    "SCALE",
    "M6",             # a fastener size, no leading multi-digit run + hyphen segment
    "",
    "-GA",            # must open with a digit
    "A1",             # a sheet size: no hyphen segment at all
    "1282",           # a bare number is not a drawing number
])
def test_things_that_are_not_drawing_numbers_are_refused(text):
    assert pcc.looks_like_a_drawing_number(text) is False


def test_the_compiler_and_the_reader_share_one_definition():
    """Two spellings of "what a drawing number looks like" is how the reader finds no
    parent while the compiler waits for one."""
    for code in ("1282-GA", "12392-04", "12120-01-001"):
        assert (route_compiler._looks_like_a_drawing_number(code)
                is pcc.looks_like_a_drawing_number(code) is True)


def test_the_old_three_segment_regex_is_gone():
    source = (SRC / "_bom_words_reader.py").read_text(encoding="utf-8")
    assert r"^\d{3,}-\d+-[A-Z0-9]+$" not in source, (
        "the 12120-shaped title-block regex is back; the shape rule belongs to "
        "part_code_conventions")


# ---------------------------------------------------------------------------
# Reading it off the page
# ---------------------------------------------------------------------------
def _w(text, x0, top):
    return {"text": text, "x0": float(x0), "x1": float(x0) + 8.0 * len(text),
            "top": float(top), "bottom": float(top) + 8.0}


def _sheet(title_block_words, body_words=()):
    """A page: some body content up top, a title block low down."""
    words = [_w(t, x, 60) for t, x in body_words]
    words += [_w(t, x, 780) for t, x in title_block_words]
    return words


def test_a_two_segment_number_is_read():
    assert wr._title_block_dwg_no(_sheet([("1282-GA", 600)])) == "1282-GA"


def test_a_spaced_number_is_read_as_one_code():
    """CAD title blocks print "1282 - GA" with real spaces. pdfplumber returns three
    words and none of them is a drawing number on its own.

    The x positions are spaced as REAL spaces — about two points at this text height.
    They were originally 8 and 20 points apart, which is a cell border rather than a
    space, and the test only passed because the reader would join across any distance
    at all. That is the same permissiveness that read a whole description as a code."""
    got = wr._title_block_dwg_no(_sheet([("1282", 600), ("-", 634), ("GA", 644)]))
    assert got == "1282-GA"


def test_the_three_segment_house_style_still_reads():
    assert wr._title_block_dwg_no(_sheet([("12120-01-001", 600)])) == "12120-01-001"


def test_the_longest_run_wins_over_its_own_prefix():
    """"12392-02" and "12392-02-GA" are both drawing-number shaped. The specific one
    is this sheet's; the prefix is its parent's, and taking it would silently reparent
    every row on the page."""
    got = wr._title_block_dwg_no(_sheet([("12392-02", 600), ("-", 664), ("GA", 674)]))
    assert got == "12392-02-GA"


def test_a_drawing_number_in_a_note_does_not_become_the_parent():
    """A cross-reference high on the sheet ("SEE 1450-GA FOR FIXING DETAIL") names
    another drawing, not this one.

    Written so the band cutoff is the ONLY thing that can reject it. With a drawing
    number also in the title block, "lowest on the page wins" decides the case on its
    own and the cutoff is never exercised — so this sheet deliberately has NO drawing
    number in its title block. Answering "1450-GA" here would reparent every BOM row on
    the page onto somebody else's drawing, which is worse than answering nothing.
    """
    got = wr._title_block_dwg_no(_sheet(
        title_block_words=[("DRAWN", 600), ("BY", 660)],
        body_words=[("SEE", 100), ("1450-GA", 140), ("FOR", 220), ("DETAIL", 260)],
    ))
    assert got is None


def test_the_title_block_still_wins_over_a_note_when_both_are_present():
    got = wr._title_block_dwg_no(_sheet(
        title_block_words=[("1282-GA", 600)],
        body_words=[("SEE", 100), ("1450-GA", 140), ("FOR", 220), ("DETAIL", 260)],
    ))
    assert got == "1282-GA"


def test_a_page_with_no_drawing_number_says_so():
    assert wr._title_block_dwg_no(_sheet([("DRAWN", 600), ("BY", 660)])) is None


def test_no_words_is_not_a_crash():
    assert wr._title_block_dwg_no([]) is None


# ---------------------------------------------------------------------------
# NO OFF
# ---------------------------------------------------------------------------
def test_a_header_using_no_off_for_quantity_is_recognised():
    """NO OFF is the standard UK spelling of quantity. Rejecting it rejected the whole
    header row, so the page read as having no parts list rather than one we failed on."""
    header = [_w("ITEM", 10, 100), _w("PART", 60, 100), _w("NO", 100, 100),
              _w("DESCRIPTION", 140, 100), _w("NO", 320, 100), _w("OFF", 350, 100)]

    class _Page:
        def extract_words(self, **_kw):
            return header

    v = wr.survey_page(_Page())
    assert v["header_found"] is True, "NO OFF must anchor the quantity column"


def test_the_quantity_synonyms_have_one_home():
    """Adding a spelling must fix it for the header matcher and the page-selection
    survey at once; they read the same set."""
    assert "NO OFF" in wr._HDR_QTY
    merge_source = (SRC / "merge_boms.py").read_text(encoding="utf-8")
    assert "NO OFF" not in merge_source


# ---------------------------------------------------------------------------
# The 12392 title block, as it really is
# ---------------------------------------------------------------------------
# Taken from the run: page 1 of "12392-02-GA 1-wide GC Panel_revA.pdf" produced
#   '1-WIDEGIFTCARDGATEPOSTPANELTESCOIMS1-WIDEGIFTCARDGATEPOST12392-02-GAA'
# as its parent. The description, the customer, the description again, the real drawing
# number and the revision letter, run together — and preferred because it was LONGEST.
def _title_row(tokens, top=780.0, x=40.0, gap=8.0):
    """Words spaced like separate title-block cells (a wide gap between each)."""
    out = []
    for tok in tokens:
        out.append(_w(tok, x, top))
        x += 8.0 * len(tok) + gap
    return out


_REAL_12392_TITLE_ROW = [
    "1-WIDE", "GIFT", "CARD", "GATE", "POST", "PANEL", "TESCO", "IMS",
    "1-WIDE", "GIFT", "CARD", "GATE", "POST", "12392-02-GA", "A",
]


def test_the_real_12392_title_block_yields_the_drawing_number():
    words = _title_row(_REAL_12392_TITLE_ROW)
    assert wr._title_block_dwg_no(words) == "12392-02-GA"


def test_a_description_cannot_be_read_as_a_drawing_number():
    """"1-WIDE GIFT CARD GATE POST" joined up opens with a digit and carries hyphens.
    A job number is not one digit long, and that is what refuses it."""
    from part_code_conventions import looks_like_a_drawing_number as ok

    assert ok("1-WIDEGIFTCARDGATEPOSTPANEL") is False
    assert ok("1-WIDE") is False
    assert ok("2-OFF") is False
    assert ok("4-WAY") is False


def test_the_revision_letter_is_not_absorbed_into_the_code():
    """"12392-02-GA" and "A" sit in adjacent title-block cells. Joined they make
    "12392-02-GAA", which is drawing-number shaped and is not this drawing."""
    words = _title_row(["12392-02-GA", "A"])
    assert wr._title_block_dwg_no(words) == "12392-02-GA"


def test_a_spaced_code_still_joins_across_real_spaces():
    """The exception joining exists for: "1282 - GA" printed with actual spaces, which
    are a couple of points wide rather than a cell border."""
    words = [_w("1282", 600, 780), _w("-", 626, 780), _w("GA", 632, 780)]
    assert wr._title_block_dwg_no(words) == "1282-GA"


def test_a_bom_row_code_above_the_title_block_does_not_win():
    """Codes quoted higher up the sheet are the BOM's own rows. The title block is at
    the bottom, so the lowest match is this drawing."""
    words = [_w("12392-02-01M", 520, 520), _w("12392-02-17G", 520, 560)]
    words += _title_row(["12392-02-GA", "A"])
    assert wr._title_block_dwg_no(words) == "12392-02-GA"
