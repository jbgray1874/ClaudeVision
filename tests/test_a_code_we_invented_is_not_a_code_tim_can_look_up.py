"""An unpriced bought line says WHICH of the two reasons it is, because they differ.

TIM, 11350-02, 9 SEP 2026:

    "Fixings- M4 Wing Nut/M4 x 8mm Pems - can it not take of system or internet for cost or
     is spec missing on drawing"
    "Ticket Strip- Can it not take previous cost off system or isn't drawing giving correct
     information"

Both questions are the same question, and the sheet had given him no way to answer it. All
three lines read "**NOT PRICED - needs a rate**", which says nothing about whose gap it is.

They are two different cases:

  * The wing nut and the PEM stud carry NO part number on the pack. The reconciler mints a
    placeholder from the description -- BI-NUT, BI-PEMSTUD -- so the line can be carried and
    counted, and that placeholder then appears in the code column looking exactly like a part
    number. Nothing can be looked up against a code we wrote ourselves. The answer is a code
    on the drawing, or a hand price.

  * DBR60 is a REAL code. It was asked, by code, and came back with nothing. The answer is on
    our side -- the catalogue row or its supplier price list -- and the drawing is fine.

Telling him which one it is turns an unanswerable line into an action with an owner. That is
the whole of this file.

WHY IT IS TESTED HERE AND NOT ON 11350-02. The rule fires on the shape of the code, so it
fires on every job with a bought line and no part number -- the synthetic rows below carry no
job number at all. If it only worked on Tim's wing nut it would not be worth shipping.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from estimate_explained import _price_source              # noqa: E402
from part_code_conventions import is_category_not_a_code  # noqa: E402
from part_identity import is_engine_minted_code           # noqa: E402


def _unpriced_row(code: str, desc: str) -> dict:
    """A BOM row as the explainer receives one: a code, a description and no price."""
    return {"code": code, "description": desc, "text": desc, "price": 0.0}


def _explain(code: str, desc: str) -> str:
    return _price_source(_unpriced_row(code, desc), provenance={}, steel_index={}, record={})


# ── the predicate itself ──────────────────────────────────────────────────────

@pytest.mark.parametrize("code", [
    "BI-NUT",            # Tim's M4 wing nut
    "BI-PEMSTUD",        # Tim's M4 x 8mm pem stud
    "BI-SELFCLINCHNUT",
    "BI-BUTTONSCREW",
    "bi-washer",         # a reader may hand it back in any case
])
def test_the_engines_own_placeholder_is_recognised_as_ours(code):
    assert is_engine_minted_code(code), f"{code} is a code the engine minted, not one from a pack"


@pytest.mark.parametrize("code", [
    "DBR60",             # Tim's ticket strip -- a real code
    "11350-02-01",
    "BI-123",            # digits after the prefix: somebody's real code, not our family
    "BIN",
    "",
    None,
])
def test_a_real_code_is_never_called_an_invention(code):
    """The false positive that matters: a purchased code refused as ours would send an
    estimator looking for a drawing change that is not needed."""
    assert not is_engine_minted_code(code)


def test_the_two_predicates_do_not_overlap():
    """A class word printed BY THE DRAWING and a placeholder minted BY US are different
    failures with different answers, and a line must not be told it is both."""
    for code in ("BI-NUT", "BI-PEMSTUD", "BI-RIVET"):
        assert is_engine_minted_code(code)
        assert not is_category_not_a_code(code)
    for code in ("FIXING", "STD PART", "P/P"):
        assert is_category_not_a_code(code)
        assert not is_engine_minted_code(code)


# ── what the estimator actually reads ─────────────────────────────────────────

def test_a_minted_code_line_says_the_code_is_ours_and_the_drawing_is_not_at_fault():
    """THE ASSERTION for Tim's first question. He asked whether the spec was missing from the
    drawing; the line must answer that without him having to ask."""
    said = _explain("BI-PEMSTUD", "M4X8 PEM STUD")
    assert "NOT PRICED" in said
    assert "BI-PEMSTUD" in said, "name the placeholder, so he can see which line this is"
    assert "ours" in said.lower() or "we wrote" in said.lower(), (
        "the line must own the placeholder -- an estimator reading 'BI-PEMSTUD' in a code "
        "column has no way to know the engine wrote it")
    assert "drawing" in said.lower(), "answer the question he asked: is the spec missing?"
    assert said != "**NOT PRICED — needs a rate**"


def test_a_real_code_line_says_it_was_asked_and_the_gap_is_ours():
    """THE ASSERTION for Tim's second question, about DBR60 -- a code that exists."""
    said = _explain("DBR60", "TICKET STRIP (LENGHT: 758MM)")
    assert "NOT PRICED" in said
    assert "DBR60" in said
    assert "asked" in said.lower(), "say the lookup happened -- he asked whether it could"
    assert "catalogue" in said.lower()
    assert said != "**NOT PRICED — needs a rate**"


def test_the_two_lines_do_not_read_the_same():
    """If both cases produce the same sentence the estimator is no better off than before."""
    minted = _explain("BI-NUT", "M4 WING NUT")
    real = _explain("DBR60", "TICKET STRIP (LENGHT: 758MM)")
    assert minted != real


def test_a_class_word_keeps_its_own_answer():
    """The pre-existing case must not be swallowed by the new branches: a class word printed
    on the drawing is answered by a code, and that wording is already right."""
    said = _explain("FIXING", "M4x10mm FLANGE BUTTON HEAD SCREW, BLACK")
    assert "CLASS" in said, said


def test_a_priced_line_is_not_given_any_of_these_answers():
    """The branch is asked only of a line with no money on it. A bought line that IS priced
    must never be described as unpriced because of how its code is spelled."""
    row = {"code": "BI-NUT", "description": "M4 WING NUT", "text": "M4 WING NUT", "price": 0.42}
    said = _price_source(row, provenance={}, steel_index={}, record={})
    assert "NOT PRICED" not in said
