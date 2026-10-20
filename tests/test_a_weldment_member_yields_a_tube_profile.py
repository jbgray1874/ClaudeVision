"""A weldment cut-list member description yields a tube profile — the missing frame reader.

8352's frame is a SolidWorks WELDMENT. Its tube sizes live in the weldment cut-list member
descriptions ('TUBE, SQUARE 30 X 30 X 2.6') and the member LENGTH — data the analyser detects
(cutlist_kind = 'unknown_or_weldment') but never parses, because it only reads the sheet-metal
cut-list keys. So the frame arrived at the estimate with an empty Wire block and no structural
money at all — the largest missing figure on a metal-stand pack.

parse_weldment_profile is the core the reader was missing: it turns a member description into the
{a, b, t, profile_form} the estimator's tube costing already consumes. It is PURE — a string in,
a profile out — so it is proven here without a SolidWorks seat. The COM read that supplies the
description and LENGTH still needs a seat and is wired separately; this is the piece that was
wrongly said to need one.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools", "solidworks"))

import sw_native_analyse as sw  # noqa: E402


def test_a_square_tube_is_read_as_shs():
    assert sw.parse_weldment_profile("TUBE, SQUARE 30 X 30 X 2.6") == \
        {"a": 30.0, "b": 30.0, "t": 2.6, "profile_form": "SHS"}


def test_a_rectangular_tube_is_read_as_rhs_smallest_is_the_wall():
    """The three numbers order so the smallest is the wall; unequal sides make it RHS."""
    assert sw.parse_weldment_profile("RHS 60 X 40 X 3") == \
        {"a": 40.0, "b": 60.0, "t": 3.0, "profile_form": "RHS"}
    assert sw.parse_weldment_profile("TUBE, RECTANGULAR 50 X 25 X 2") == \
        {"a": 25.0, "b": 50.0, "t": 2.0, "profile_form": "RHS"}


def test_a_section_keyword_anywhere_in_the_description_is_enough():
    assert sw.parse_weldment_profile("SB EN10219 S235JRH 40 X 40 X 3 SHS")["profile_form"] == "SHS"


def test_a_part_with_no_section_keyword_is_not_a_tube():
    """A plate/bracket with an a×b×t-looking size must not be read as a tube — the keyword gate
    is what separates a hollow section from a solid part."""
    assert sw.parse_weldment_profile("BRACKET 30 X 30 X 3 PLATE") is None
    assert sw.parse_weldment_profile("SCREW PLATE") is None


def test_an_implausible_wall_is_refused():
    """A 'wall' that is not credibly less than half each side is not a hollow section — refuse it
    rather than cost a solid bar as a tube."""
    assert sw.parse_weldment_profile("TUBE, SQUARE 30 X 30 X 20") is None


def test_two_dimensions_are_not_a_profile():
    assert sw.parse_weldment_profile("TUBE 30 X 30") is None


def test_empty_or_garbled_is_an_honest_none():
    assert sw.parse_weldment_profile("") is None
    assert sw.parse_weldment_profile(None) is None


def test_the_form_agrees_with_the_estimator_reader():
    """SHS/RHS naming matches document_builder's own section detector, so the weldment path and
    the drawing-text path cost the same profile the same way."""
    import os as _os
    _root = _os.path.join(_os.path.dirname(__file__), "..", "src")
    sys.path.insert(0, _root)
    import document_builder as db  # noqa: E402
    # Both call an equal-sides section SHS and unequal RHS.
    assert sw.parse_weldment_profile("TUBE 40 X 40 X 3")["profile_form"] == "SHS"
    assert "SHS" in db._SECTION_HOLLOW_KW and "RHS" in db._SECTION_HOLLOW_KW
