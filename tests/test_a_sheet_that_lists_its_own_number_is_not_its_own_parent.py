"""A SHEET THAT LISTS ITS OWN NUMBER IS NOT ITS OWN PARENT (6364-01 18:24, 12 Nov 2026).

The rear castor plate's sheet is an assembly: item 1 is the plate, under the sheet's own
number, and item 2 is a hank bush, 2 off. The top bill calls for 2 plates. The bill tree
counted the plate as a child of itself and reached 26 plates and 52 bushes; a safety cap
then reset the bushes to 1. The drawing says 2 plates and 4 bushes.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import bom_tree as B  # noqa: E402


def _row(pn, qty, parent, **more):
    r = {"part_number": pn, "description": pn, "quantity": qty, "source_pdf": parent,
         "bom_parent": parent, "bom_parent_known": True}
    r.update(more)
    return r


def _bill(self_row=True, plates=2):
    rows = [_row("T-005", plates, "T-000 - BOM"), _row("T-013", 2, "T-000 - BOM"),
            _row("T-010", 1, "T-000 - BOM"),
            _row("FIXING-BUSH", 2, "T-005"),
            _row("T-011", 3, "T-010")]
    if self_row:
        rows.insert(3, _row("T-005", 1, "T-005"))
    return rows


def test_the_plate_and_its_bushes_are_counted_as_the_drawing_says():
    eff = B.resolve_effective_quantities(_bill())["effective"]
    assert eff["T-005"] == 2 and eff["FIXING-BUSH"] == 4


def test_the_count_follows_the_top_bill():
    eff = B.resolve_effective_quantities(_bill(plates=3))["effective"]
    assert eff["T-005"] == 3 and eff["FIXING-BUSH"] == 6


def test_a_sheet_without_a_self_row_counts_the_same():
    with_row = B.resolve_effective_quantities(_bill(self_row=True))["effective"]
    without = B.resolve_effective_quantities(_bill(self_row=False))["effective"]
    assert with_row["FIXING-BUSH"] == without["FIXING-BUSH"] == 4
    assert with_row["T-011"] == without["T-011"] == 3 and with_row["T-013"] == 2
