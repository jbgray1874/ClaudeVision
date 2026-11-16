"""A blocking flag must name a part the estimator can go and find — never "None".

file_scan rejects a part_number that reads as boilerplate/finish text and sets it to None, KEEPING
the record. When such a part also carries an impossible blank-vs-cut-path, the blocking
blank_and_cut_path_disagree flag fired reading 'None is 12 x 11 mm with a 10,016 mm cut path' —
it stopped the quote and pointed the estimator at nothing. The flag now falls back through the
part's description and source file, so there is always a handle to check.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import invariants  # noqa: E402


def _impossible_part(**extra):
    """A 12 x 11 mm blank carrying a 10,016 mm cut path — the 8352 case, priced from the blank."""
    part = {"part_number": None, "normalized_material": "MILD_STEEL",
            "normalized_thickness_mm": 3.0, "quantity": 1,
            "material_estimate": {"blank_length_mm": 12.0, "blank_width_mm": 11.0},
            "cut_length_mm": 10016.0}
    part.update(extra)
    return part


def _flag(part):
    out = invariants.check_a_blank_and_its_cut_path_can_both_be_true({"parts": [part]})
    assert out, "the impossible blank should still block"
    return out[0]


def test_the_label_falls_back_to_the_description_not_None():
    flag = _flag(_impossible_part(description="TIMBER BACK PANEL"))
    assert "TIMBER BACK PANEL" in flag["message"]
    assert "None is" not in flag["message"]


def test_the_label_falls_back_to_the_source_filename():
    flag = _flag(_impossible_part(dxf_source_file="C:/jobs/8352/8352-03-01.dxf"))
    assert "8352-03-01.dxf" in flag["message"]
    assert "None is" not in flag["message"]


def test_a_part_with_no_identity_at_all_says_so_plainly():
    flag = _flag(_impossible_part())
    assert "None is" not in flag["message"]
    assert "unidentified part" in flag["message"]


def test_a_real_part_number_is_used_verbatim():
    flag = _flag(_impossible_part(part_number="8352-99-99", description="ignored"))
    assert "8352-99-99 is" in flag["message"]


def test_the_flag_still_blocks_and_still_prices_from_the_blank():
    """Naming the part changes nothing about the verdict — the impossible geometry still blocks."""
    flag = _flag(_impossible_part(description="X"))
    assert flag["severity"] == invariants.BLOCKING
    assert "priced from the blank" in flag["message"] or "priced" in flag["message"].lower()
