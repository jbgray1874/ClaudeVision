"""A row of a part's own table that is not a size is said, not skipped (D-694).

12693-01-04J's own parts table lists three sized rows (1145 x 1145 x 18 x1, 1145 x 210 x 12
x2, 725 x 210 x 12 x1) and a fourth line, count 1, whose words the text layer did not carry.
D-688 costs the three sized rows as the part's four physical pieces; the fourth row went
nowhere. A reviewer: "with the unresolved cutting-table entry checked before declaring
completeness". The part now says the row is not costed and asks for it to be read.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

sys.path.insert(0, str(ROOT / "tests"))
import test_a_board_part_is_the_pieces_its_own_table_lists as base  # noqa: E402


def _flags(part):
    return [f for f in part.get("review_flags") or [] if f.startswith("TABLE ROW NOT COSTED")]


def test_the_blank_row_is_said_and_asked():
    _done, parts, _rows = base._minted()
    part = parts[base.CODE]
    flags = _flags(part)
    assert len(flags) == 1
    assert "a row with no description x1" in flags[0] and "NOT costed" in flags[0]
    qs = [q for q in part.get("manufacturing_questions") or []
          if "not costed" in str(q.get("issue") or "")]
    assert len(qs) == 1


def test_the_four_physical_pieces_are_one_two_one():
    _done, parts, _rows = base._minted()
    qty = {pn: p.get("quantity") for pn, p in parts.items() if pn != base.CODE}
    assert sorted(qty.values()) == [1, 1, 2]
    assert sum(qty.values()) == 4


def test_a_table_of_sizes_only_says_nothing_more():
    rows = [r for r in base._rows() if r["description"]]
    _done, parts, _rows = base._minted(rows=rows)
    assert _flags(parts[base.CODE]) == []


def test_a_coded_row_is_an_item_and_is_not_said_here():
    rows = base._rows()[:3] + [base._row("4", "M6 WOOD INSERT", 8, code="FIX99")]
    _done, parts, _rows = base._minted(rows=rows)
    assert _flags(parts[base.CODE]) == []
