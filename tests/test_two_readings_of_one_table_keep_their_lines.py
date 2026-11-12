"""Two readers that number a parts table differently must not splice two lines into one.

12312-01-GA Rev B prints its fixings as unnumbered FIXING rows. The deterministic reader and
vision numbered them differently, so "item 6" was the M6 washer on one reading and the 06M
side bracket on the other. The row contest kept vision's code and precedence kept the text
layer's description: the sheet carried "M6 WASHER" on 12312-01-06M, the star washers landed
on FIXING320, and the washers themselves were lost.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import merge_boms  # noqa: E402


def _row(item, code, desc, qty=1):
    return {"item_number": str(item), "part_ref": code, "description": desc, "quantity": qty}


def _lines(rows):
    return {(r.get("part_ref") or "", r.get("description"), r.get("quantity")) for r in rows}


def test_a_shifted_numbering_keeps_every_line_whole():
    # Vision numbered one row ahead of the text layer from item 6 on.
    a = {"rows": [_row(5, "12312-01-05M", "ROUTER MOUNT PLATE"),
                  _row(6, "FIXING", "M6 WASHER", 4),
                  _row(7, "12312-01-06M", "SIDE BRACKET"),
                  _row(8, "12312-01-06M-H", "SIDE BRACKET HANDED")]}
    b = {"rows": [_row(5, "12312-01-05M", "ROUTER MOUNT PLATE"),
                  _row(6, "12312-01-06M", "SIDE BRACKET"),
                  _row(7, "12312-01-06M-H", "SIDE BRACKET HANDED"),
                  _row(8, "FIXING", "M6 NYLOC NUT", 4)]}
    rows, _ = merge_boms.reconcile_page(a, b, "12312-01")
    got = _lines(rows)
    assert ("12312-01-06M", "SIDE BRACKET", 1) in got
    assert ("12312-01-06M-H", "SIDE BRACKET HANDED", 1) in got
    assert ("FIXING", "M6 WASHER", 4) in got, "the washers vision did not number are kept"
    assert ("FIXING", "M6 NYLOC NUT", 4) in got
    for r in rows:
        if r.get("part_ref", "").startswith("12312-01-06M"):
            assert "WASHER" not in r["description"] and "NUT" not in r["description"]
    # Each article once: the brackets vision read at other numbers are not doubled.
    assert sum(1 for r in rows if r.get("part_ref") == "12312-01-06M") == 1


def test_two_uncoded_fixings_under_one_number_are_two_lines():
    a = {"rows": [_row(9, "FIXING", "M5 EXTERNALLY SERRATED WASHER", 8)]}
    b = {"rows": [_row(9, "FIXING", "M6 STAR WASHER", 8)]}
    rows, _ = merge_boms.reconcile_page(a, b, "P")
    descs = {r["description"] for r in rows}
    assert descs == {"M5 EXTERNALLY SERRATED WASHER", "M6 STAR WASHER"}


def test_the_same_article_read_two_ways_is_still_one_line():
    a = {"rows": [_row(3, "BI-BOLT", "M6 X 10 BUTTON HEAD BOLT", 4)]}
    b = {"rows": [_row(3, "BI-BOLTBZP", "M6X10 BUTTON HEAD BOLT BZP", 8)]}
    rows, _ = merge_boms.reconcile_page(a, b, "P")
    assert len(rows) == 1 and rows[0]["source"] == "B_OVERRIDE"


def test_the_parent_merge_does_not_fold_two_uncoded_lines():
    pages = [{"label": "12312-01", "parent_known": True, "sheet": "s1", "rows": [
        _row(6, "FIXING", "M6 WASHER", 4), _row(6, "FIXING", "M6 NYLOC NUT", 4)]}]
    parents, _ = merge_boms.merge_pages_into_parents(pages)
    descs = sorted(r["description"] for p in parents for r in p["rows"])
    assert descs == ["M6 NYLOC NUT", "M6 WASHER"]
