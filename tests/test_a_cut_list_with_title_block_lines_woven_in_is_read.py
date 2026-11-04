"""A cut list with title-block lines woven into it is read, not called unread (D-691).

12693-01-01M's text layer prints its cut list with two title-block lines between the rows:

    ITEM DESCRIPTION LENGTH QTY
    STATUS:
    1 25.00 x 25.00 x 1.50mm TUBE 1000 1
    PROTOTYPE RELEASED
    2 25.00 x 25.00 x 1.50mm TUBE 775.4 4
    ...

The costing read all five rows and priced 7,051.6 mm. The section coverage check stopped at
"STATUS:", found no rows, and the book reported the list as unread: one fact, two answers.
A non-row line is now stepped over only where the table's next numbered row follows within a
few lines; anything after the last row still ends the table, and a line that starts like a
row but cannot be read is still a finding.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from section_coverage_contract import parse_table  # noqa: E402

WOVEN = """ITEM DESCRIPTION LENGTH QTY
STATUS:
1 25.00 x 25.00 x 1.50mm TUBE 1000 1
PROTOTYPE RELEASED
2 25.00 x 25.00 x 1.50mm TUBE 775.4 4
3 25.00 x 25.00 x 1.50mm TUBE 487.5 2
4 25.00 x 25.00 x 1.50mm TUBE 1000 1
5 25.00 x 25.00 x 1.50mm TUBE 487.5 2
4 x 13 THRU
MAX LOADING:
WEIGHT: 7.26kg"""


def test_the_woven_list_reads_all_five_rows():
    got = parse_table(WOVEN)
    assert "error" not in got
    rows = got["rows"]
    assert [r["item"] for r in rows] == [1, 2, 3, 4, 5]
    assert sum(r["length_mm"] * r["quantity"] for r in rows) == 7051.6


def test_a_line_after_the_last_row_still_ends_the_table():
    rows = parse_table(WOVEN)["rows"]
    assert len(rows) == 5


def test_a_stray_line_with_no_next_row_ends_the_table():
    text = "ITEM DESCRIPTION LENGTH QTY\nSTATUS:\nPROTOTYPE RELEASED\nMAX LOADING:\n"
    assert parse_table(text) == {"error": "headed cut list has no readable rows"}


def test_a_row_out_of_sequence_is_not_reached_by_stepping():
    text = ("ITEM DESCRIPTION LENGTH QTY\nSTATUS:\n"
            "2 25.00 x 25.00 x 1.50mm TUBE 1000 1\n")
    assert parse_table(text) == {"error": "headed cut list has no readable rows"}


def test_an_unreadable_row_is_still_a_finding():
    text = ("ITEM DESCRIPTION LENGTH QTY\n1 25.00 x 25.00 x 1.50mm TUBE 1000 1\n"
            "2 25 x 25 x TUBE ??? 4\n")
    assert parse_table(text)["error"] == "unread section row"
