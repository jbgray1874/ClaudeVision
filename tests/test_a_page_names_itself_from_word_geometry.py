"""One title-block reader, so a page cannot name itself to one caller and not another.

Job 12392 reported, on a pack whose sheets plainly carry title blocks:

    [bom] 4/4 row(s) traced to a sheet; 0 carry the drawing that owns them

Rows placed on the right pages, every one of them an orphan, and two bought-in nodes
disconnected downstream because no page could own anything.

There were two readers of one thing. file_scan._page_drawing_number read
region_text["title_block"] — a crop taken by _zone_boxes and flattened to a string.
_bom_words_reader._title_block_dwg_no reads the same title block from WORD POSITIONS,
with its own band cutoff and its own run-joining, and it had been corrected twice while
the other had not. tools/diagnose_title_block.py, which uses the word reader, finds
12392-04-GA on a sheet where the region reader returns "".

A flattened crop has thrown away the y-positions that tell a title block from a revision
table, and the crop and the band do not agree about where a title block is. The words are
already on the page dict, so the reader that works can simply be asked.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import file_scan                                                    # noqa: E402
import _bom_words_reader as wr                                      # noqa: E402


def _w(text, top, x0=400.0, width=None):
    """A pdfplumber word. WIDTH IS PROPORTIONAL TO THE TEXT, and that matters here.

    The reader joins two words only when the gap between them is smaller than a fraction
    of the text height — a real space, not a title-block cell border. The first version of
    this fixture gave every word the same 40pt box and spaced them 45pt apart, so every
    gap was 5.0 against a 4.8 threshold and NOTHING joined. Three tests failed and the
    reader was correct: a fixture that mis-states the geometry tests the geometry, not the
    rule built on it.
    """
    w = 6.0 * len(text) if width is None else width
    return {"text": text, "top": top, "bottom": top + 8.0, "x0": x0, "x1": x0 + w}


def _sheet(code_words, *, region_text="", extra=()):
    """A page as the scan builds it: raw words, plus whatever the region crop caught."""
    words = [_w("GENERAL", 40.0, 60.0), _w("ARRANGEMENT", 40.0, 115.0)]
    words += list(extra)
    # The title block sits low on the sheet — below the 60% band cutoff.
    x = 400.0
    for t in code_words:
        word = _w(t, 520.0, x)
        words.append(word)
        x = word["x1"] + 3.0                       # a printed space, not a cell border
    return {"page_number": 1, "words": words,
            "region_text": {"title_block": region_text}}


def test_a_page_names_its_drawing_from_the_words_when_the_crop_missed_it():
    """The live failure: the crop caught nothing, the words carry the number."""
    page = _sheet(["12392-04-GA"], region_text="")
    assert file_scan._page_drawing_number(page) == "12392-04-GA"


def test_a_spaced_code_reads_as_one_code():
    """CAD title blocks print '1282 - GA' with real spaces, so pdfplumber returns three
    words and no single one of them is a drawing number."""
    page = _sheet(["1282", "-", "GA"], region_text="")
    assert file_scan._page_drawing_number(page) == "1282-GA"


def test_the_sheets_own_number_beats_its_parents_prefix():
    """'12392-02 - GA' reads as '12392-02' if single tokens simply win — and that is the
    sheet's PARENT. Every row on the page would be reparented one level up."""
    page = _sheet(["12392-02", "-", "GA"], region_text="")
    assert file_scan._page_drawing_number(page) == "12392-02-GA"


def test_a_number_high_on_the_sheet_is_not_this_sheets_name():
    """A drawing number in a note or a revision table is a reference to another sheet.
    Taking one would make a detail claim to own the assembly that references it — which
    is precisely what a flattened crop cannot rule out, having lost the positions."""
    # A real sheet has words all the way down it, which is what puts a note at the TOP of
    # the band rather than inside it. A fixture with nothing below the note makes the band
    # relative to the note itself, and then tests nothing.
    page = _sheet(["PANEL", "ASSEMBLY"], region_text="",
                  extra=[_w("SEE", 60.0, 300.0), _w("12392-99-GA", 60.0, 340.0)])
    assert file_scan._page_drawing_number(page) == "", \
        "a drawing number quoted in a note is a reference to another sheet"


def test_the_region_text_still_answers_when_there_are_no_words():
    """A page whose words were never captured — a vision-read raster sheet — must keep
    working exactly as it did."""
    page = {"page_number": 1, "words": [],
            "region_text": {"title_block": "DWG NO: 12392-02-201 REVISION: A"}}
    assert file_scan._page_drawing_number(page) == "12392-02-201"


def test_both_callers_get_the_same_answer_from_the_same_sheet():
    """The property that failed. The diagnostic and the pipeline must not disagree about
    whether a sheet names itself — a tool that finds what the run cannot is worse than no
    tool, because it says the data is there and the run is fine."""
    page = _sheet(["12392-04-GA"], region_text="")
    assert wr._title_block_dwg_no(page["words"]) == "12392-04-GA"
    assert file_scan._page_drawing_number(page) == "12392-04-GA"


def test_rows_gain_an_owner_once_the_page_can_name_itself():
    """End to end through the attribution that reported 0 owners on a real job."""
    rows = [{"part_number": "12392-04-01M", "description": "BACK MOUNTING BRACKET"},
            {"part_number": "12392-04-02M", "description": "FRONT MOUNTING BRACKET"}]
    page = _sheet(["12392-04-GA"], region_text="")
    page["region_text"]["bom"] = ("ITEM DWG NO. DESCRIPTION QTY "
                                 "3 12392-04-01M BACK MOUNTING BRACKET 2 "
                                 "4 12392-04-02M FRONT MOUNTING BRACKET 2")
    page["region_text"]["notes"] = ""

    placed = file_scan.attribute_bom_rows_to_source_pages(rows, [page])

    assert placed == 2
    assert [r.get("bom_parent") for r in rows] == ["12392-04-GA", "12392-04-GA"], \
        "rows were placed on the right sheet and still state no hierarchy"


if __name__ == "__main__":                                          # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
