"""A sheet whose lettering is outlines is read as a drawing; a round body is its parts (D-599).

The HPP fixture pack: 18 CAD sheets printed to PDF with every word drawn as paths, 3,927 to
27,993 paths a page and no text layer. No page role could be found, so the vision read took
them under the render prompt and sized parts "from human-scale cues"; the round base came back
as one 38 mm disc, the halo as one folded strip, and the column as one flat panel.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import concept_scan  # noqa: E402
import department_codes  # noqa: E402
import file_scan  # noqa: E402

SCAN = (ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")


def _page(n, text, paths, saved=False):
    drawn = {"raw_vector_paths": paths} if saved else [{"items": []}] * paths
    return {"page_number": n, "source_pdf_path": "C:\\jobs\\HPP unit Design.pdf",
            "pdfplumber_text": text, "vision_extraction": {"drawings": drawn}}


def test_a_page_with_no_text_and_cad_line_work_is_an_outlined_sheet():
    s = {"pages": [_page(1, "", 12943), _page(2, "", 3927, saved=True),
                   _page(3, "", 12),                       # a scan, a photo, a render
                   _page(4, "SAMSUNG QM50C INSTALLATION", 4000)]}  # it has words: readers read it
    assert file_scan.outlined_drawing_pages(s) == ["HPP unit Design.pdf page 1",
                                                   "HPP unit Design.pdf page 2"]
    assert file_scan.outlined_drawing_pages({}) == []


def test_the_vision_read_takes_outlined_sheets_as_drawings():
    assert "_sheet_read = bool(_design_intent_pages) or bool(_outlined)" in SCAN
    assert "_outlined = outlined_drawing_pages(summary)" in SCAN
    assert "READ AS DRAWING SHEETS" in SCAN


def test_the_sheet_prompt_says_the_lettering_may_be_outlines():
    assert "it may be drawn as outlines and turned on its side" in concept_scan._SHEET_PREAMBLE
    assert concept_scan.SHEET_PROMPT_VERSION == "s5"


def test_a_round_body_is_its_skin_rims_and_formers():
    p = concept_scan._PROMPT
    assert "A ROUND BODY IS NOT ONE PART EITHER" in p
    assert "pi x its diameter" in p and "formers, blocking or ribs" in p
    assert "names rolling" in p
    assert "A frame that carries or hangs a part" in p
    assert concept_scan.CONCEPT_PROMPT_VERSION in ("c7", "c8")


def test_rolling_is_work_the_read_may_name_and_it_reaches_the_roll_department():
    assert "rolling" in concept_scan.SIGHTABLE_OPERATIONS
    assert department_codes.code_for("rolling") == "ROLL"


def test_a_curved_flat_part_is_blanked_by_its_box_not_its_arc():
    """D-599b: the HPP shelves' quarter segments came back 1571 x 700 (arc by depth) where each
    is cut from 1000 x 1000, about twice the board."""
    p = concept_scan._PROMPT
    assert "A CURVED FLAT PART IS BLANKED BY ITS BOX, NOT ITS ARC" in p
    assert "a quarter of a ring of\n  outer radius R is R x R" in p
    assert concept_scan.CONCEPT_PROMPT_VERSION == "c8"
