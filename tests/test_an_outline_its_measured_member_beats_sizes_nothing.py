"""An outline its own measured member already exceeds does not resize another member (D-684).

12693-01-GA, 4 Nov 2026. The worktop 12693-01-102 holds a weldment 104, whose skin 03M has a
DXF measuring 1250.4 x 1250.4 mm flat, and an MDF insert 04J read 1145 x 1145 mm off its own
sheet and its own parts table. The worktop's outline was read as 1161 x 500. D-508's check
saw 04J larger than that outline and costed it on 1145 x 500: half the board, on a reading the
job's own measurement had already disproved, since no 500 mm wide worktop holds a 1250 mm
square skin even after its folds.

D-508 stays for what it was written for: a member read larger than an outline nothing
contradicts is still costed on the assembly and asked. What changes is only this: when a
MEASURED member of the same assembly, at any depth, cannot fit the outline at the usual flange
allowance, the outline is the figure in doubt, said so on the parent, and the member's read
stands.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import detail_page_geometry as dpg  # noqa: E402
import source_precedence as sp  # noqa: E402


def _worktop(skin_mm=(1250.4, 1250.4), skin_folds=8, outline=(1161.0, 500.0)):
    worktop = {"part_number": "12999-01-102", "description": "WORKTOP ASM",
               "_sheet_envelope_mm": {"length": outline[0], "width": outline[1]}}
    weldment = {"part_number": "12999-01-104", "description": "WORKTOP WELDMENT",
                "bom_parent": "12999-01-102", "is_assembly_parent": True}
    skin = {"part_number": "12999-01-03M", "description": "TOP SKIN",
            "bom_parent": "12999-01-104", "normalized_material": "MILD_STEEL",
            "normalized_thickness_mm": 1.5, "dxf_augmented": True,
            "flat_pattern_detected": True, "bend_count_dxf": skin_folds,
            "normalized_geometry": {"blank_length_mm": skin_mm[0],
                                    "blank_width_mm": skin_mm[1],
                                    "geometry_source": "dxf_flat_pattern"}}
    sp.apply_field(skin, "blank_length_mm", skin_mm[0], "dxf")
    sp.apply_field(skin, "blank_width_mm", skin_mm[1], "dxf")
    insert = {"part_number": "12999-01-04J", "description": "TOP INSERT",
              "bom_parent": "12999-01-102", "normalized_material": "MDF",
              "normalized_thickness_mm": 18.0}
    sp.apply_field(insert, "blank_length_mm", 1145.0, dpg.PROVISIONAL_SOURCE)
    sp.apply_field(insert, "blank_width_mm", 1145.0, dpg.PROVISIONAL_SOURCE)
    summary = {"document_analysis": {"bom_rows": [
        {"part_number": "12999-01-104", "bom_parent": "12999-01-102"},
        {"part_number": "12999-01-04J", "bom_parent": "12999-01-102"},
        {"part_number": "12999-01-03M", "bom_parent": "12999-01-104"}]}}
    return [worktop, weldment, skin, insert], summary


def _by(parts, pn):
    return next(p for p in parts if p["part_number"] == pn)


def test_the_insert_keeps_its_own_size_when_the_skin_proves_the_outline_wrong():
    parts, summary = _worktop()
    assert dpg.check_parts_against_their_assembly(parts, summary) == []
    insert = _by(parts, "12999-01-04J")
    assert (insert["blank_length_mm"], insert["blank_width_mm"]) == (1145.0, 1145.0)
    assert not insert.get("_blank_capped_to_assembly")
    assert not insert.get("manufacturing_questions")
    kept = insert["_blank_kept_over_assembly"]
    assert kept["assembly"] == "12999-01-102"
    assert "12999-01-03M" in kept["measured_member"]


def test_the_outline_is_said_to_be_in_doubt_once():
    parts, summary = _worktop()
    dpg.check_parts_against_their_assembly(parts, summary)
    dpg.check_parts_against_their_assembly(parts, summary)
    worktop = _by(parts, "12999-01-102")
    doubt = [f for f in worktop.get("review_flags") or [] if "OUTLINE IN DOUBT" in f]
    assert len(doubt) == 1
    assert "1161 x 500 mm" in doubt[0] and "12999-01-03M" in doubt[0]


def test_a_measured_member_that_fits_the_outline_proves_nothing():
    """A skin that fits leaves D-508 exactly as it was: the misread insert is capped."""
    parts, summary = _worktop(skin_mm=(480.0, 300.0), skin_folds=0)
    assert dpg.check_parts_against_their_assembly(parts, summary) == ["12999-01-04J"]
    insert = _by(parts, "12999-01-04J")
    assert insert["_blank_capped_to_assembly"]["costed_mm"] == [1145.0, 500.0]


def test_folds_are_allowed_before_the_member_is_said_to_exceed():
    """A developed flat is bigger than the part it folds into; 4 folds at 25 mm is 100 mm."""
    parts, summary = _worktop(skin_mm=(1200.0, 590.0), skin_folds=4, outline=(1161.0, 500.0))
    assert dpg.check_parts_against_their_assembly(parts, summary) == ["12999-01-04J"]


def test_a_measured_part_outside_the_assembly_proves_nothing_about_it():
    parts, summary = _worktop()
    summary["document_analysis"]["bom_rows"][2]["bom_parent"] = "12999-01-999"
    _by(parts, "12999-01-03M")["bom_parent"] = "12999-01-999"
    assert dpg.check_parts_against_their_assembly(parts, summary) == ["12999-01-04J"]


def test_a_loop_in_the_tree_does_not_hang_the_check():
    parts, summary = _worktop()
    summary["document_analysis"]["bom_rows"].append(
        {"part_number": "12999-01-102", "bom_parent": "12999-01-104"})
    dpg.check_parts_against_their_assembly(parts, summary)
