"""A flat DXF has to resolve to the part it is a flat OF.

On 12349-02 every flat resolved to the top-level `12349-02-69` instead of to `…-01A` or
`…-03M`, because the filename parser capped a part number at three dash-segments and SDI
numbers a fabrication with four. The consequences all followed from that one truncation:

  * seven acrylic flats arrived at a parent they were not children of, could bind to nothing
    there, and were promoted as standalone parts with invented numbers (`…-DXF12349026903`);
  * `01A` kept a 2120 x 2120 mm bounding box as its blank, because nothing replaced it;
  * `03M`'s own strap was costed twice — once as `03M`, once as an orphan with the same blank
    to a hundredth of a millimetre.

The cap was there for a reason — `9233-12-GA-UK-MW` must still become `9233-12-GA` — so the
fix is to decide the cut by what a segment LOOKS like rather than by how many there are.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

ezdxf = pytest.importorskip("ezdxf", reason="dxf_reader needs it at import")
from dxf_reader import _parse_filename                                  # noqa: E402


def _pn(name: str):
    return _parse_filename(Path(name)).get("part_number")


# ── the case that was broken ─────────────────────────────────────────────────

@pytest.mark.parametrize("name,expected", [
    ("12349-02-69-01A_-01_2MM_High Impact Acrylic_RevA.DXF", "12349-02-69-01A"),
    ("12349-02-69-01A_-07_5MM_High Impact Acrylic_RevA.DXF", "12349-02-69-01A"),
    ("12349-02-69-03M_-01_1.5mm_MS_RevA.DXF", "12349-02-69-03M"),
    ("12349-02-69-03M_-02_1.5mm_MS_RevA.DXF", "12349-02-69-03M"),
    ("12349-02-69-04M_1.2MM_MS_RevA.DXF", "12349-02-69-04M"),
    ("12349-02-69-06A_5MM_High Impact Acrylic_RevA.DXF", "12349-02-69-06A"),
    ("12349-02-69-08J_6mm_MDF_RevA.DXF", "12349-02-69-08J"),
])
def test_a_four_segment_sdi_number_survives(name, expected):
    """All seven 01A flats must reach 01A, or they become somebody else's children."""
    assert _pn(name) == expected


def test_the_seven_flats_of_one_fabrication_agree_on_their_parent():
    parents = {_pn(f"12349-02-69-01A_-0{i}_5MM_High Impact Acrylic_RevA.DXF")
               for i in range(1, 8)}
    assert parents == {"12349-02-69-01A"}, (
        "if they disagree they cluster under different parents and are costed as strangers")


# ── what the cap was there for, still working ────────────────────────────────

@pytest.mark.parametrize("name,expected", [
    ("9233-12-GA_UK_MW_Dressing_Kit_2020.DXF", "9233-12-GA"),
    ("9376-01-001_MS_1_5mm_revL.DXF", "9376-01-001"),
    ("12242-01-01M_MS_1_5mm_revD.DXF", "12242-01-01M"),
    ("4002-00 Ambient Produce Unit_4002-01.dxf", "4002-01"),
    ("4083-555_4083-557.dxf", "4083-557"),
])
def test_every_example_the_parser_documents_is_unchanged(name, expected):
    """The docstring's own cases. A fix that quietly rewrites these is not a fix."""
    assert _pn(name) == expected


def test_a_word_after_the_number_still_stops_it():
    """That is what the three-segment cap was doing, and it must keep doing it."""
    assert _pn("9233-12-GA-UK-MW-DRESSING.DXF") == "9233-12-GA"


@pytest.mark.parametrize("tail", ["2MM", "5MM", "REVA", "MS", "ACRYLIC"])
def test_a_material_or_thickness_is_never_taken_for_a_part_segment(tail):
    """MM is two letters, REVA is not digits — neither looks like an identifier, and the
    test is what a segment looks like rather than a list of words to exclude."""
    assert _pn(f"12349-02-69-01A-{tail}.DXF") == "12349-02-69-01A"


def test_a_three_segment_number_is_not_lengthened_by_the_change():
    assert _pn("12552-01-01M_1.5mm_MS_RevA.DXF") == "12552-01-01M"


# ── the promoted child, once the parent is right ─────────────────────────────

def test_a_promoted_flat_is_named_as_a_child_of_its_parent():
    """It has to be, or _stamp_assembly_parents cannot see it.

    That function makes a part an assembly parent — carrying neither its own sheet material
    nor geometry-derived labour — when >=2 other part numbers start with "<pn>-". A promoted
    flat named after the WRONG parent leaves the right one looking like a leaf, which is
    exactly how 01A came to keep a bounding box and be costed on it.
    """
    sys.path.insert(0, str(SRC))
    from drawing_job_merge import _orphan_child_pn
    parent = {"part_number": "12349-02-69-01A"}
    pn = _orphan_child_pn(parent, Path("12349-02-69-01A_-03_5MM_High Impact Acrylic.DXF"), 3)
    assert pn.startswith("12349-02-69-01A-"), (
        "the child's number has to begin with its parent's, or the parent is never stamped")
    assert pn[-1].isdigit(), (
        "ending in a digit keeps SDI's single-letter material conventions from reading the "
        "synthesised suffix — a trailing -T routed an acrylic panel to timber once")
