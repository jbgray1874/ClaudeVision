"""The cover page must count what the estimator is about to turn over, and name files correctly.

Both faults found by looking at a real print of 10575-02.

ONE — "1 DRAWING FOLLOWS THIS PAGE", AND THEN THREE SHEETS.

The count is `len(printed)`, which is the number of FILES. On 10575-02 one GA PDF carries three
sheets, so the cover said "1 drawing follows this page" and the estimator turned over to find
three. James read that screen and could not tell what the feature had done.

A drawing and a sheet are not the same thing and the cover was using one word for both. The
number that matters to somebody holding the paper is how many sheets are in their hand; the
number that matters for checking the pack is complete is how many files were printed. It has to
say both.

TWO — "'.slddrw' IS NOT A DRAWING", WHICH IS SIMPLY UNTRUE.

`KNOWN_UNPRINTABLE` lists `.sldprt` and `.sldasm` but not `.slddrw`, so a SolidWorks drawing file
fell through to the catch-all branch and was reported as:

    not printed — '.slddrw' is not a drawing

It is the SolidWorks DRAWING file. It is the most drawing-like thing in the pack, and it is the
one file whose absence from the paper an estimator would most want explained properly. The
catch-all message exists for things nobody recognises, and telling somebody their drawing is not
a drawing is how a warning stops being believed.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

_spec = importlib.util.spec_from_file_location("dp", _ROOT / "src" / "drawings_print.py")
dp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dp)


# ── The SolidWorks drawing file ────────────────────────────────────────────────

def test_a_solidworks_drawing_is_a_known_file_type():
    assert ".slddrw" in dp.KNOWN_UNPRINTABLE, (
        "a .slddrw fell to the catch-all branch and was reported as 'not a drawing'")


@pytest.mark.parametrize("suffix", [".sldprt", ".sldasm", ".slddrw"])
def test_the_solidworks_family_is_complete(suffix):
    """Part, assembly and drawing. Two were listed and the third was not, which is the shape of
    mistake that only shows up on a pack that happens to carry one."""
    assert suffix in dp.KNOWN_UNPRINTABLE


def test_the_reason_given_for_a_slddrw_does_not_deny_it_is_a_drawing(tmp_path):
    f = tmp_path / "10575-02-GA.SLDDRW"
    f.write_bytes(b"")
    _, skipped = dp.collect([str(f)])
    assert len(skipped) == 1
    reason = skipped[0][1].lower()
    assert "is not a drawing" not in reason, f"got {skipped[0][1]!r}"
    assert "printable" in reason or "model" in reason or "geometry" in reason


# ── Sheets versus files ────────────────────────────────────────────────────────

def test_the_cover_reports_sheets_as_well_as_files():
    """One file of three sheets must not read as one page of paper."""
    line = dp._cover_count_line(printed_files=1, pages=3)
    assert "3" in line, f"the sheet count is missing: {line!r}"
    assert "1" in line, f"the file count is missing: {line!r}"


def test_a_single_sheet_from_a_single_file_does_not_say_it_twice():
    """When the two numbers agree, saying both is noise. One drawing, one sheet, one sentence."""
    line = dp._cover_count_line(printed_files=1, pages=1)
    assert line.count("1") == 1, f"said it twice: {line!r}"


@pytest.mark.parametrize("files,pages", [(1, 3), (4, 12), (2, 2), (1, 1), (12, 40)])
def test_the_grammar_holds_for_every_combination(files, pages):
    line = dp._cover_count_line(printed_files=files, pages=pages)
    assert " 1 sheets" not in line and " 1 files" not in line, f"plural on one: {line!r}"
    for n in (files, pages):
        if n != 1:
            assert f"{n} sheet " not in line and f"{n} file " not in line, line


def test_the_unknown_page_count_still_produces_a_sentence():
    """_page_count returns None when the merged file cannot be read back. The cover must still
    say something true rather than printing 'None drawings follow'."""
    line = dp._cover_count_line(printed_files=2, pages=None)
    assert "None" not in line
    assert "2" in line


# ── End to end, because the off-by-one only showed up in a real merge ──────────
#
# _cover_count_line was right and the cover still lied. `_cover` inserts its own page at index 0
# BEFORE reading doc.page_count, so the count included the cover itself and a three-sheet pack
# announced four. Unit-testing the sentence could never have caught that; only building a real
# document does.

def _pdf(path, pages):
    import pymupdf
    d = pymupdf.open()
    for _ in range(pages):
        d.new_page()
    d.save(str(path))
    d.close()


def test_the_cover_does_not_count_itself(tmp_path):
    import pymupdf
    _pdf(tmp_path / "10575-02-GA.PDF", 3)
    (tmp_path / "10575-02-009_DIBOND.DXF").write_bytes(b"")     # forces the cover to appear
    out = tmp_path / "merged.pdf"
    dp.build([str(tmp_path)], out, job="10575-02")

    doc = pymupdf.open(str(out))
    try:
        assert doc.page_count == 4, "1 cover + 3 sheets"
        cover = doc[0].get_text()
        assert "3 sheets follow this page" in cover, (
            f"the cover counted itself; it says: {cover.splitlines()[1]!r}")
        assert "4 sheets" not in cover
    finally:
        doc.close()


def test_a_one_sheet_pack_reads_naturally(tmp_path):
    import pymupdf
    _pdf(tmp_path / "GA.PDF", 1)
    (tmp_path / "GA-DETAIL.DXF").write_bytes(b"")
    out = tmp_path / "merged.pdf"
    dp.build([str(tmp_path)], out, job="J1")
    doc = pymupdf.open(str(out))
    try:
        cover = doc[0].get_text()
        assert "1 sheet follows this page" in cover, cover.splitlines()[1]
    finally:
        doc.close()


def test_a_solidworks_drawing_beside_its_pdf_is_not_a_gap(tmp_path):
    """The 10575-02 case: the .slddrw shares a stem with the printed PDF, so its drawing IS on
    the paper. It belongs under 'already on the paper', not under NOT PRINTED."""
    import pymupdf
    _pdf(tmp_path / "10575-02-GA.PDF", 2)
    (tmp_path / "10575-02-GA.SLDDRW").write_bytes(b"")
    out = tmp_path / "merged.pdf"
    dp.build([str(tmp_path)], out, job="10575-02")
    doc = pymupdf.open(str(out))
    try:
        cover = doc[0].get_text()
        assert "ALSO IN THE PACK" in cover
        assert "NOT PRINTED" not in cover, "a drawing already on the paper was called a gap"
    finally:
        doc.close()
