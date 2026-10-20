"""A subtotal of exactly zero is an answer, not an absence.

11650-05 hit this the moment the phantom powder line was removed. Every material row on
that job is estimator-to-price, so the sheet's Total Material Cost computed 0.00 -- the
correct answer. The readback's label scan skipped it (`f is not None and f != 0`), stamped
material=None, and two reconciliation checks then reported "verified nothing" about a job
whose material total was sitting on the sheet in front of them.

Zero and missing are different facts everywhere else in this codebase -- it is what the
MISSING sentinel exists for -- and they must not resolve the same way here. Excel makes the
distinction available at the source: an EMPTY cell reads as None, a cell holding zero reads
as 0.0. The scan now keeps them apart.

WHY THE ZERO IS PREFERRED LAST. A label row carries the label, some blanks, and the value.
Taking the last non-zero number is right when there is one; the zero fallback only applies
when the row has no non-zero number at all, which is exactly the nil-subtotal case.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wep_readback_from_xlsx import _scan_total_cell                 # noqa: E402


class _Cell:
    def __init__(self, value):
        self.Value = value


class _Sheet:
    """Enough of the Excel COM surface for the label scan: 1-indexed Cells(r, c).Value."""

    def __init__(self, rows):
        self._rows = rows

    def Cells(self, r, c):
        try:
            return _Cell(self._rows[r - 1][c - 1])
        except IndexError:
            return _Cell(None)


def _scan(rows, needles=("total material cost",)):
    ws = _Sheet(rows)
    return _scan_total_cell(ws, needles, max_row=len(rows),
                            max_col=max(len(r) for r in rows))


# ── the live failure ────────────────────────────────────────────────────────────────
def test_a_zero_subtotal_is_found():
    """The 11650-05 case: every material row estimator-to-price, subtotal 0.00."""
    hit = _scan([["Total Material Cost", None, None, 0.0]])
    assert hit == (1, 4), "a genuinely nil subtotal was read back as an absence"


def test_a_normal_subtotal_is_still_found():
    assert _scan([["Total Material Cost", None, None, 8.2767]]) == (1, 4)


def test_a_non_zero_value_is_preferred_over_a_zero_on_the_same_row():
    """A label row carries blanks and sometimes a stray zero. The real total is the last
    non-zero number; the zero fallback must not steal from it."""
    assert _scan([["Total Material Cost", 0.0, None, 12.5]]) == (1, 4)
    assert _scan([["Total Material Cost", 0.0, 12.5, 0.0]]) == (1, 3)


@pytest.mark.parametrize("blank", [None, "", "   ", "-"])
def test_an_empty_row_is_still_no_answer(blank):
    """An EMPTY cell is not a zero, and must not be reported as one -- that would turn a
    block the adapter could not read into a confident nil.

    Parametrised over the shapes a blank actually arrives in, because the distinction is
    carried by _safe_float rejecting them, not by a separate guard: a mutation showed the
    guard I first wrote could only agree with _safe_float and never fired."""
    assert _scan([["Total Material Cost", blank, blank, blank]]) is None


def test_a_row_without_the_label_is_ignored():
    assert _scan([["Something Else", 99.0]]) is None


def test_the_label_is_matched_case_insensitively_and_within_a_longer_string():
    """The template writes 'Total Labour Cost (Including Downtime)'."""
    hit = _scan([["  Total Labour Cost (Including  Downtime) ", None, 0.0]],
                needles=("total labour cost",))
    assert hit == (1, 3)


def test_a_zero_and_an_empty_cell_do_not_resolve_the_same_way():
    """Stated as its own case because it is the whole point: one is the sheet's answer and
    the other is the sheet not having been read."""
    assert _scan([["Total Material Cost", 0.0]]) is not None
    assert _scan([["Total Material Cost", None]]) is None


if __name__ == "__main__":                                          # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
