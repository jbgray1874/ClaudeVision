"""A table row that is not as wide as its header silently shifts every column after it.

§3 of the covering email (Bought-in and commercial) emitted seven cells for an eight-column
header — it built the file-list cell but not the Drawing-no. cell that the header and the
fallback path both carry. enumerate() rendered the seven in order and stopped, so the file
list landed under "Drawing no." and "Which drawing files and pages" came out blank on a
client's Harrods quote. Nothing errored; it just looked wrong.

_table now refuses a row whose width does not match the header, where it is cheap to catch,
rather than shipping a scrambled table to a customer.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import estimate_explained as ee  # noqa: E402


def test_a_row_short_of_the_header_is_refused():
    with pytest.raises(ValueError):
        ee._table(["Line", "What it is", "Drawing no.", "Which files"], [["7332-01-002", "LEG", "…files…"]])


def test_a_row_wider_than_the_header_is_refused():
    with pytest.raises(ValueError):
        ee._table(["A", "B"], [["1", "2", "3"]])


def test_a_matching_row_renders():
    html = ee._table(["A", "B", "C"], [["1", "2", "3"], ["x", "y", "z"]])
    assert html.count("<th ") == 3           # three headers
    assert html.count("<td ") == 6           # two rows x three cells, no shift
    assert "<table" in html and "</table>" in html
