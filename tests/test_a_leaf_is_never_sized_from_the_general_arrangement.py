r"""
test_a_leaf_is_never_sized_from_the_general_arrangement.py

THE BIGGEST NUMBER IN A DRAWING PACK IS THE ONE NUMBER THAT IS CERTAINLY NOT THIS PART'S.

A general arrangement prints the size of the finished unit. Every leaf inside it is smaller,
by definition. So a last-resort sizing pass that scans "the whole document" for the two
largest numbers does not merely RISK taking the assembly's envelope -- on any pack where the
GA prints its overall, it PREFERS it.

12349-02-69-01A is what that cost. Its seven acrylic flats had resolved to the wrong parent
(the filename parser capped a part number at three dash-segments; see
test_a_flat_finds_the_part_it_belongs_to), so 01A arrived at this fallback with no blank of
its own and took 2120 x 2120 off the GA -- 4.5 square metres of high-impact acrylic, on a
drawer front. James, reading the quote: "2120x2120 is not a feeder."

There were two defects stacked here, and the square is the tell for the second:

  1. the GA's page was in the pool at all; and
  2. `_nums` is a sorted list of every OCCURRENCE, so one dimension printed on two views
     arrives as two entries. 2120 x 2120 was 2120 seen twice -- one observation counted as
     two, which is the same defect source_precedence names in its own comments.

A perfect square is what a pack produces when it has exactly one big number in it, and it is
never what a real fabricated blank looks like.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

pytest.importorskip("document_builder", reason="the builder under test")
from document_builder import _apply_post_build_fixes            # noqa: E402


GA_TEXT = (
    "GENERAL ARRANGEMENT. GRAVITY FEEDER UNIT. OVERALL 2120 x 1450. "
    "HEIGHT 2120 OVER FEET. SCALE 1:10."
)
DETAIL_TEXT = (
    "DRAWER FRONT. MATERIAL: HIGH IMPACT ACRYLIC 5mm. "
    "OVERALL 480 x 295. DEBURR ALL EDGES."
)


def _summary(pages):
    return {"pages": [
        {"page_number": n, "pdfplumber_text": t, "text_preview": t,
         "page_role": {"primary_role": r}}
        for n, t, r in pages
    ]}


def _unsized_acrylic_leaf(page):
    """01A as it reached this pass: a real non-metal part with a material and a thickness,
    no blank, and no overall dims of its own."""
    return {
        "part_number": "12349-02-69-01A",
        "description": "DRAWER FRONT",
        "pages": [page],
        "page_roles": ["detail"],
        "materials": ["HIGH IMPACT ACRYLIC"],
        "normalized_material": "ACRYLIC",
        "normalized_thickness_mm": 5.0,
        "surface_finishes": [],
        "textual_operations": [],
        "geometry_rollup": {"confidence": {"geometry_reliability": 0.0}},
    }


def _sized(part):
    return part.get("blank_length_mm"), part.get("blank_width_mm")


# ── the case that was broken ───────────────────────────────────────────────────

def test_the_general_arrangements_overall_never_becomes_a_leafs_blank():
    part = _unsized_acrylic_leaf(page=2)
    _apply_post_build_fixes([part], _summary([
        (1, GA_TEXT, "assembly"),
        (2, DETAIL_TEXT, "detail"),
    ]))
    length, width = _sized(part)
    assert length != 2120, "the GA's overall is on a leaf again"
    assert (length or 0) <= 480, (
        f"a drawer front sized at {length} mm came off the assembly sheet, not its own detail")


def test_the_leaf_is_sized_from_its_own_detail_instead():
    part = _unsized_acrylic_leaf(page=2)
    _apply_post_build_fixes([part], _summary([
        (1, GA_TEXT, "assembly"),
        (2, DETAIL_TEXT, "detail"),
    ]))
    assert _sized(part) == (480.0, 295.0)


def test_a_perfect_square_is_not_produced_from_one_number_seen_twice():
    """The tell. A dimension printed on two views is one dimension, not a length and a
    width -- and a pack with exactly one big number in it must size nothing, not a square."""
    part = _unsized_acrylic_leaf(page=1)
    _apply_post_build_fixes([part], _summary([
        (1, "DRAWER FRONT. 2120 OVERALL. SEE VIEW B: 2120.", "detail"),
    ]))
    length, width = _sized(part)
    assert not (length and width and length == width), (
        f"{length} x {width} is one reading counted twice, not a blank")


# ── the fallback still works where it is the only thing left ───────────────────

def test_a_pack_of_details_still_sizes_a_part_that_has_no_blank():
    """This pass exists because a part with no measured flat is otherwise not priced at
    all. Narrowing where it reads must not stop it reading."""
    part = _unsized_acrylic_leaf(page=1)
    _apply_post_build_fixes([part], _summary([
        (1, "DRAWER FRONT. OVERALL 480 x 295. MATERIAL: ACRYLIC 5mm.", "detail"),
    ]))
    assert _sized(part) == (480.0, 295.0)


def test_the_guessed_blank_is_still_stamped_as_a_guess():
    """A blank from this source is a guess wearing a measurement's clothes, and only the
    stamp tells them apart."""
    part = _unsized_acrylic_leaf(page=1)
    _apply_post_build_fixes([part], _summary([
        (1, "DRAWER FRONT. OVERALL 480 x 295. MATERIAL: ACRYLIC 5mm.", "detail"),
    ]))
    assert part.get("blank_length_mm_source") == "document_text_largest_numbers"


def test_a_part_that_already_has_a_blank_is_not_touched():
    part = _unsized_acrylic_leaf(page=2)
    part["blank_length_mm"], part["blank_width_mm"] = 512.0, 300.0
    _apply_post_build_fixes([part], _summary([
        (1, GA_TEXT, "assembly"),
        (2, DETAIL_TEXT, "detail"),
    ]))
    assert _sized(part) == (512.0, 300.0)


def test_a_pack_with_nothing_but_assembly_sheets_sizes_nothing():
    """The honest outcome: there is no drawing of this part to size it from. A blank
    invented off the assembly's envelope is worse than no blank, because it prices."""
    part = _unsized_acrylic_leaf(page=1)
    _apply_post_build_fixes([part], _summary([(1, GA_TEXT, "assembly")]))
    assert _sized(part) == (None, None)
