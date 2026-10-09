"""A parts-list row whose code cell holds a word, with a part's description, is a line (D-436).

8188-08-SA04's table prints "Strengthener | EXTRUSION 92: LENGTH =100mm | 24". The code cell
is a word, so the validity gate — written for finish and title-block text, and demanding a
digit — rejected it; the record lost its identity, and the 17:37 book said "STRENGTHENER x24
is on the bill the product reaches and has no line on the sheet".
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import file_scan as fs                                                # noqa: E402


def test_a_word_with_a_parts_description_is_kept():
    assert fs.word_coded_row_is_a_purchase("Strengthener", "EXTRUSION 92: LENGTH =100mm")


def test_finish_and_boilerplate_words_are_still_rejected():
    assert not fs.word_coded_row_is_a_purchase("POWDER COATED", "RAL 9005 JET BLACK")
    assert not fs.word_coded_row_is_a_purchase("MATT", "EXTRUSION 92")
    assert not fs.word_coded_row_is_a_purchase("Strengthener", "")


def test_a_category_word_or_a_placeholder_is_not_an_identity():
    """FIXING and P/P are shared rows the engine already mints under the article's words."""
    assert not fs.word_coded_row_is_a_purchase("FIXING", "M6 x 12 BUTTON HEAD SCREW")
    assert not fs.word_coded_row_is_a_purchase("TBC", "EXTRUSION 92")


def test_a_word_with_a_note_or_a_material_for_a_description_is_not_a_part():
    assert not fs.word_coded_row_is_a_purchase("Strengthener", "SEE NOTE 3")
    assert not fs.word_coded_row_is_a_purchase("Strengthener", "3mm MILD STEEL")


def test_a_code_with_a_digit_is_not_this_rules_business():
    assert not fs.word_coded_row_is_a_purchase("8188-08-004", "WIRE WORK MESH FRAME")
