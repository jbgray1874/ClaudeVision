"""ONE BILL ROW IS ONE RECORD (6364-01 18:24, 12 Nov 2026).

A cam lock was charged twice: once bought (3 off, under its supplier code) and once "made"
(3 off, no part number, a borrowed 829 x 639 blank and another sheet's drilling). The second
was the reader's record of the same row, whose supplier code had been rejected as text.
Reviewer: "resolve aliases consistently without losing or duplicating components."
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import detail_page_geometry as G  # noqa: E402

ROW = {"part_number": "SUPPLIER NAME:", "description": "324250 Square Cam Lock", "quantity": 3,
       "bom_parent": "T-010"}


def _nameless(rejected):
    p = {"part_number": None, "description": "324250 Square Cam Lock", "quantity": 3,
         "normalized_geometry": {"blank_length_mm": 829.0, "blank_width_mm": 639.0},
         "textual_operations": ["hole_machining", "diamond_polish"]}
    if rejected:
        p["part_number_rejected"] = rejected
    return p


def _panel():
    return {"part_number": "T-018", "description": "MID PANEL", "quantity": 1,
            "normalized_geometry": {"blank_length_mm": 829.0, "blank_width_mm": 639.0}}


def test_the_readers_nameless_record_of_the_row_is_withdrawn():
    parts = [_panel(), _nameless("SUPPLIER NAME:")]
    minted = G.mint_missing_hand_records(parts, [ROW])
    assert minted == ["SUPPLIER NAME:"]
    locks = [p for p in parts if "Cam Lock" in str(p.get("description"))]
    assert len(locks) == 1 and locks[0]["part_number"] == "SUPPLIER NAME:" and locks[0]["quantity"] == 3
    assert locks[0]["withdrew_nameless_records"] == 1 and not locks[0].get("textual_operations")
    assert any(p.get("part_number") == "T-018" for p in parts), "the panel is untouched"


def test_spacing_and_case_in_the_code_do_not_keep_the_duplicate():
    parts = [_panel(), _nameless("supplier  name:")]
    G.mint_missing_hand_records(parts, [ROW])
    assert sum(1 for p in parts if "Cam Lock" in str(p.get("description"))) == 1


def test_a_nameless_record_of_some_other_row_is_kept():
    parts = [_panel(), _nameless("ANOTHER CODE")]
    G.mint_missing_hand_records(parts, [ROW])
    assert sum(1 for p in parts if not p.get("part_number")) == 1
    assert sum(1 for p in parts if p.get("part_number") == "SUPPLIER NAME:") == 1


def test_a_nameless_record_with_no_rejected_code_is_kept():
    parts = [_panel(), _nameless("")]
    G.mint_missing_hand_records(parts, [ROW])
    assert sum(1 for p in parts if not p.get("part_number")) == 1


def test_the_scan_keeps_the_code_it_rejected():
    scan = (ROOT / "src" / "file_scan.py").read_text(encoding="utf-8")
    at = scan.index('_p["part_number_rejected"] = str(_bad)')
    assert scan.index('_p["part_number"] = None', at - 200) < at
