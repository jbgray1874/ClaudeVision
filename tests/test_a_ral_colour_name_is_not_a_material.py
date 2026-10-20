"""RAL 9006 is called "White Aluminium". A mild steel cover was costed as aluminium.

12552's 02-09M is 1.5 mm MILD STEEL, powder coated RAL9006. Its title block extracts as
labels-then-values — the label column first, then the value column, and not even in the same
order:

    MATERIAL:                       RAL9006 WHITE ALUMINIUM
    COLOUR:            ->           MILD STEEL
    SURFACE FINISH:                 POWDER COATED

So the labelled "MATERIAL:" read finds "COLOUR:" immediately after the label and returns
nothing. The whole-page keyword fallback then scans the sheet, finds ALUMINIUM — inside the
colour name — before it reaches MILD STEEL, and _first_or_none takes the first one.

A THIRD OF THE DENSITY AND A DIFFERENT RATE. Aluminium is 2.7 g/cm3 against steel's 7.85, comes
off a different price list and from a different supplier. Nothing about the resulting figure
looks wrong on the page: it is a plausible number for a part made of something else.

RAL'S PALETTE IS FULL OF THESE. 9006 White Aluminium, 9007 Grey Aluminium, 8004 Copper Brown,
9022 Pearl Light Grey. Every one lands a metal word on a sheet whose part is made of something
else, and the more carefully a drawing office names its colour, the worse the misread.

BLANKED AS A PHRASE, NOT AS A WORD. "ALUMINIUM" on its own is a perfectly good material
callout, and a part genuinely made of aluminium and coated RAL9006 still reads correctly.

AND THE FILLER HAD TO BE GUARDED, which the first version of this fix got wrong. Allowing any
words between the RAL code and the metal word made the match greedy: on "RAL9006 WHITE
ALUMINIUM MILD STEEL" it swallowed "WHITE ALUMINIUM MILD " to reach STEEL and blanked the
part's real material along with the colour name. That turns a misread into a blank, which is
worse — a wrong material is at least visible in the report, and an absent one reads as a
drawing that never stated it.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from extractor_patterns import extract_title_block_fields               # noqa: E402


def _mat(text: str):
    return extract_title_block_fields(text)["normalized"]["primary_material"]


# 02-09M's title block, in the order the PDF actually extracts it.
SHEET_02_09M = (
    "1.5 THK\n"
    "MATERIAL:\nCOLOUR:\nSURFACE FINISH:\n"
    "RAL9006 WHITE ALUMINIUM\nMILD STEEL\nPOWDER COATED\n"
    "WEIGHT:\n0.3kg\n"
)


def test_the_steel_cover_is_not_costed_as_aluminium():
    assert _mat(SHEET_02_09M) == "MILD STEEL"


def test_the_real_material_survives_the_strip():
    """THE FIRST ATTEMPT AT THIS FIX BLANKED IT. A greedy filler ran from the RAL code
    through the colour name and the word MILD to reach STEEL, taking the part's own material
    with it. A blank is worse than a wrong value: the wrong one is visible in the report, the
    blank reads as a drawing that never stated its material."""
    assert _mat(SHEET_02_09M) is not None


@pytest.mark.parametrize("colour", [
    "RAL9006 WHITE ALUMINIUM",
    "RAL 9007 GREY ALUMINIUM",
    "RAL8004 COPPER BROWN",
    "RAL 9006 - WHITE ALUMINIUM",
])
def test_every_metal_named_in_a_ral_colour_is_ignored(colour):
    assert _mat(f"MATERIAL:\nCOLOUR:\n{colour}\nMILD STEEL\n") == "MILD STEEL"


def test_a_part_genuinely_made_of_aluminium_still_reads_as_aluminium():
    """THE THING THIS MUST NOT BREAK. The strip removes a colour PHRASE, not the word. A
    part that really is aluminium — and may well be coated RAL9006 — reads correctly from its
    own material callout."""
    assert _mat("MATERIAL: ALUMINIUM\nCOLOUR:\nRAL9006 WHITE ALUMINIUM\n") == "ALUMINIUM"
    assert _mat("MATERIAL:\nCOLOUR:\nRAL9006 WHITE ALUMINIUM\nALUMINIUM\n") == "ALUMINIUM"


def test_a_colour_with_no_ral_code_is_left_alone():
    """The RAL code is the evidence that this is a colour name. Stripping metal words after
    any colourish phrase would start guessing."""
    assert _mat("MATERIAL:\nCOLOUR:\nWHITE ALUMINIUM\n") == "ALUMINIUM"


def test_every_detail_sheet_in_12552_reads_as_mild_steel():
    """Every fabricated part in 12552 is mild steel — James's table says so for all fifteen —
    and each has its own detail sheet. Run against the real GA rather than a fixture, because
    the failure was a property of how that title block extracts and no invented sample would
    have reproduced it."""
    pymupdf = pytest.importorskip("pymupdf")
    pdf = Path("/root/.claude/uploads/09b98f42-bd9e-534a-8993-f8eb3975326c/"
               "cd0141e6-1255200GA_Infinity_Drawer_Rev_C.PDF")
    if not pdf.exists():
        pytest.skip("the 12552 GA is not on this machine")
    doc = pymupdf.open(str(pdf))
    # Detail sheets: one part each, 4-11 and 14-25. Sheets 1-3 and 12-13 are GA/BOM pages.
    detail = [3, 4, 5, 6, 7, 8, 13, 14, 16, 17, 20, 21, 22, 23, 24]
    bad = {i + 1: extract_title_block_fields(doc[i].get_text())["normalized"]["primary_material"]
           for i in detail}
    wrong = {k: v for k, v in bad.items() if v and "ALUMIN" in str(v).upper()}
    assert not wrong, wrong


def test_a_bom_line_naming_a_metal_still_leaks_onto_an_assembly_sheet():
    """A SECOND, DIFFERENT LEAK — RECORDED HERE AND NOT FIXED, so it is not rediscovered as a
    surprise.

    12552's sheets 2 and 19 carry the BOM line "2.4x6mm DOME RIVET, ALU" — a bought-in
    aluminium rivet — and the whole-page keyword scan makes ALU the SHEET's material. Those are
    GA and assembly pages rather than detail sheets, so no fabricated part takes its gauge or
    its rate from them, which is why this is not being changed in the same pass as the RAL fix.

    It is a real defect all the same, and the general question behind it is bigger than the
    colour one: what a BOM line's material has to do with the sheet's own. Deciding that
    belongs in its own change, with its own run to check it against.

    This test asserts the CURRENT behaviour. When it is fixed, this test should fail and be
    replaced — that is the point of writing it down."""
    assert _mat("MATERIAL:\nCOLOUR:\nFIXING 2.4x6mm DOME RIVET, ALU 3\n") == "ALUMINIUM"
