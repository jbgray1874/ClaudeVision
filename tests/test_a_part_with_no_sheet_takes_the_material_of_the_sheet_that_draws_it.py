"""A part with no sheet of its own takes the material of the sheet that draws it (D-426).

8188-08 M&S Hero Header, the live run of 9 Oct 14:50: wave layers 014 and 015 are drawn on wave
layer 013's sheet, whose title block states ACRYLIC, and have no title block of their own. The
pack states several materials, so it hands down none (D-421), and the SolidWorks model's library
appearance — MILD_STEEL, the default the same sheet overruled on 013 — was the only reading. Both
layers went on the Sheet Steel block, the metal laser, the brake and the powder line.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import file_scan as fs                                                # noqa: E402
from source_precedence import apply_field, source_of                  # noqa: E402


def _page(n, numbers, materials):
    return {"page_number": str(n),
            "page_analysis": {"title_block": {"drawing_numbers": numbers,
                                              "materials": materials}}}


def _pages():
    return [
        _page(2, ["8188-08_GA"], ["TIMBER"]),
        _page(3, ["8188-08-SA05"], ["MILD STEEL"]),
        _page(6, ["8188-08-013"], ["ACRYLIC"]),
        _page(9, ["8188-08-010"], ["MDF"]),
    ]


def _layer(code, pages=(6,), role="assembly"):
    return {"part_number": code, "description": "WAVE LAYER", "pages": list(pages),
            "page_roles": [role]}


def test_a_layer_drawn_on_anothers_sheet_takes_that_sheets_material_over_the_appearance():
    part = _layer("8188-08-014")
    apply_field(part, "normalized_material", "MILD_STEEL", "solidworks_applied_material")
    fs._inherit_sheet_material_to_parts([part], _pages())
    assert part["normalized_material"] == "ACRYLIC"
    assert source_of(part, "normalized_material") == "drawn_on_sheet"
    flags = " ".join(part.get("review_flags") or [])
    assert "no sheet of its own" in flags and "library appearance" in flags, flags


def test_a_part_with_nothing_read_takes_its_sheets_material_without_a_question():
    part = _layer("8188-08-004", pages=(3,))
    fs._inherit_sheet_material_to_parts([part], _pages())
    assert part["normalized_material"].replace("_", " ") == "MILD STEEL"
    assert not [f for f in part.get("review_flags") or [] if "no sheet of its own" in f]


def test_a_parts_own_sheet_is_never_overruled_by_this():
    """013 is the sheet's own title block: what the drawing readers took off it stands."""
    part = _layer("8188-08-013", role="detail")
    apply_field(part, "normalized_material", "ACRYLIC", "drawing_deterministic")
    fs._inherit_sheet_material_to_parts([part], _pages())
    assert source_of(part, "normalized_material") == "drawing_deterministic"


def test_the_parts_own_reading_outranks_the_sheet_that_draws_it():
    part = _layer("8188-08-014")
    apply_field(part, "normalized_material", "MILD STEEL", "drawing_deterministic")
    fs._inherit_sheet_material_to_parts([part], _pages())
    assert part["normalized_material"] == "MILD STEEL"


def test_sheets_of_two_families_hand_down_nothing():
    part = _layer("X-1", pages=(3, 6))
    fs._inherit_sheet_material_to_parts([part], _pages())
    assert not part.get("normalized_material")


def test_bought_in_and_assemblies_take_nothing():
    bought = dict(_layer("PSA1999C", pages=(2,)), is_bought_in=True)
    sub = dict(_layer("8188-08-SA04", pages=(6,)), is_sub_assembly=True)
    fs._inherit_sheet_material_to_parts([bought, sub], _pages())
    assert not bought.get("normalized_material") and not sub.get("normalized_material")
