r"""
test_a_weldment_is_more_than_one_piece.py

Disagreeing about stock proves pieces, and 01A proved it three times over: 2mm, 3mm and 5mm.
A WELDMENT is the case that test cannot see. 12349-02's 03M holder is a tap and two channels,
all 1.5mm mild steel, so the stock keys agree and the pieces read as revisions of each other.
Tim splits them — TAP 1145x358 and CHANNELS 145x23 x2. We costed the tap alone.

The suffix is the tell, and it is SDI's own export convention. A revision is marked as one —
"11908-21-01J_9mm MDF+ LAM_REV[A].dxf" — while the members of a fabrication are numbered
"_-01", "_-02", "_-07". Two files for one part number carrying DIFFERENT member numbers are
different members; that is what the numbers are for. A stale revision does not acquire one.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from drawing_job_merge import (_member_suffix_of_flat as member,               # noqa: E402
                               flats_are_different_pieces as different)


def _p(*names):
    return [Path(n) for n in names]


def test_a_weldment_of_one_gauge_is_still_two_pieces():
    """THE FAULT ITSELF. Both 1.5mm mild steel, so the stock test says 'revisions'."""
    assert different(_p("12349-02-69-03M_-01_1.5MM_MILD STEEL.dxf",
                        "12349-02-69-03M_-02_1.5MM_MILD STEEL.dxf"))


def test_the_bonded_box_still_works_the_way_it_did():
    """01A passes on the stock test alone and must keep passing on it — this is a second
    test, not a replacement."""
    assert different(_p("12349-02-69-01A_-01_2MM_ACRYLIC.dxf",
                        "12349-02-69-01A_-02_3MM_ACRYLIC.dxf",
                        "12349-02-69-01A_-07_5MM_ACRYLIC.dxf"))


def test_a_stale_revision_is_still_one_part():
    """The behaviour the original branch exists for, and the one thing this must not break: a
    superseded file left in the folder must not become a phantom part on every job."""
    assert not different(_p("11908-21-01J_9mm MDF+ LAM_REV[A].dxf",
                            "11908-21-01J_9mm MDF+ LAM_REV[B].dxf"))


def test_one_file_is_one_part():
    assert not different(_p("11908-21-01J_9mm MDF+ LAM_REV[A].dxf"))


def test_the_same_member_twice_is_not_two_members():
    """A duplicated download — "(1)" — is one piece, not two."""
    assert not different(_p("12349-02-69-03M_-01_1.5MM_MILD STEEL.dxf",
                            "12349-02-69-03M_-01_1.5MM_MILD STEEL (1).dxf"))


@pytest.mark.parametrize("name,expect", [
    ("12349-02-69-01A_-07_5MM_ACRYLIC.dxf", "07"),
    ("12349-02-69-03M_-01_1.5MM_MILD STEEL.dxf", "01"),
    # A part number full of hyphens must not supply one — that is the whole reason the
    # pattern is anchored on the underscore-hyphen pair.
    ("12349-02-69-01A_5MM_ACRYLIC.dxf", None),
    ("11908-21-01J_9mm MDF+ LAM_REV[A].dxf", None),
    ("12349-02-69-100.dxf", None),
])
def test_only_the_export_suffix_counts_as_a_member_number(name, expect):
    assert member(Path(name)) == expect
