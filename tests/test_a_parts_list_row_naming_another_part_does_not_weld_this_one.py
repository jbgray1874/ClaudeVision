"""A parts-list row naming another drawing says that drawing is welded, not this one.

11896-08-02-GA and 11896-01-00-GA, 14 Nov 2026. Each top sheet's table lists its
sub-assemblies by name: "T-101 LHS UPRIGHT - WELDED ASSEMBLY 1". Every WELDED printed on the
sheet is in one of those rows. The top assembly, which is bolted together, was stamped
"WELDED per its own sheet's note" and charged a weld of its own on top of each
sub-assembly's: Estimate row 160, £39.27 a unit on 11896-08-02-GA.

The codes and words here are this test's own; the row shape is the drawings'.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import weld_symbols as ws  # noqa: E402

TOP, LEG, RAIL, BAR = "T-08-02-GA", "T-08-02-101", "T-08-02-104", "T-08-02-10M"
TABLE = (f"ITEM DWG NO. DESCRIPTION QTY 1 {LEG} LHS UPRIGHT - WELDED ASSEMBLY 1 "
         f"2 {RAIL} CROSS RAIL - WELDED ASSEMBLY 2 3 {BAR} UNIT FIXED Z-BAR 12")


def _parts():
    return [{"part_number": TOP, "is_assembly_parent": True},
            {"part_number": LEG, "is_assembly_parent": True},
            {"part_number": RAIL, "is_assembly_parent": True},
            {"part_number": BAR}]


def _stated(notes_by_code):
    parts = _parts()
    got = ws.apply_sheet_weld_notes(parts, {ws._clean_pn(k): {"notes": v, "text": v}
                                            for k, v in notes_by_code.items()})
    return got, {p["part_number"]: p for p in parts}


def test_a_top_sheet_that_only_lists_welded_sub_assemblies_is_not_itself_welded():
    got, parts = _stated({TOP: TABLE})
    assert got == [], "the top assembly was stamped welded from its parts list"
    assert "welding" not in (parts[TOP].get("textual_operations") or [])
    assert not parts[TOP].get("weld_stated_by_note")


def test_a_sub_assemblys_own_sheet_title_still_states_its_weld():
    got, parts = _stated({LEG: "LHS UPRIGHT - WELDED ASSEMBLY TITLE MATERIAL MILD STEEL"})
    assert got == [LEG] and "welding" in parts[LEG]["textual_operations"]


def test_a_note_in_the_top_sheets_own_words_still_states_its_weld():
    got, parts = _stated({TOP: TABLE + " NOTE: FRAME TO BE WELDED ON SITE JIG"})
    assert got == [TOP] and "welding" in parts[TOP]["textual_operations"]
    assert "TO BE WELDED" in parts[TOP]["weld_stated_by_note"] or "WELDED" in parts[TOP]["weld_stated_by_note"]


def test_weld_and_dress_beside_a_table_is_still_read_with_its_dressing():
    got, parts = _stated({TOP: TABLE + " WELD & DRESS ALL CORNERS"})
    assert got == [TOP]
    assert {"welding", "dress_welds"} <= set(parts[TOP]["textual_operations"])


def test_only_the_rows_are_removed_and_the_rest_of_the_sheet_is_left():
    left = ws._without_rows_naming_other_parts(TABLE + " FINISH: POWDER COATED", [LEG, RAIL, BAR])
    assert "WELDED" not in left and "POWDER COATED" in left and "ITEM DWG NO" in left


def test_a_row_naming_this_sheets_own_part_is_not_removed():
    left = ws._without_rows_naming_other_parts(f"{LEG} LHS UPRIGHT - WELDED ASSEMBLY 1", [RAIL])
    assert "WELDED" in left
