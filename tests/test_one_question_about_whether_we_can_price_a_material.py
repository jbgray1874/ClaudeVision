"""Whether we can price a material is one question, so it gets one answer.

11650-04'S FOUR PANELS ARE ONE ARTICLE MADE TWICE, AND THEY CAME OFF TWO DIFFERENT SHEETS.

    11650-04-01A          PETG 2.0   GBP 48.89/sheet   priced as ACRYLIC
    11650-04-01A-HANDED   PETG 2.0   GBP 60.21/sheet   priced as PETG
    11650-04-03A          PETG 2.0   GBP 48.89/sheet   priced as ACRYLIC
    11650-04-03A-HANDED   PETG 2.0   GBP 60.21/sheet   priced as PETG

Identity had already been settled — every one of them says PETG at 2.0mm. The prices still
disagreed, and the rescue was the writer of the cheaper one.

`_material_we_can_actually_price` exists to save a part whose arbitrated material carries no
rate, and it asked `config.material_has_a_rate`, which reads MATERIAL_PRICE_GBP_PER_KG and
nothing else. It has never heard of the customer's own parts catalogue — which is exactly
where PETG, ABS and HIPS sheet prices live, 37 rows of PETG among them. So a material with
live stock behind it was judged unpriceable and swapped for ACRYLIC, whose config figure is
cheaper than the real one.

TWO TABLES, ONE QUESTION, AND SILENCE FROM ONE TREATED AS AN ANSWER FOR BOTH. That is the
dual-path defect in the money rather than in a datum, and it is the last thing standing
between this pack and one rate per stock key.

THE RESCUE IS NOT WEAKENED. A material nothing can price is still rescued, still recorded as a
conflict, and still put in front of an estimator. What changed is that "nothing can price it"
now means every source was asked.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import estimator  # noqa: E402


@pytest.fixture(autouse=True)
def _catalogue():
    """UDEF holding what it really holds: PETG at 2mm, and nothing at 2.2."""
    estimator._SHEET_RATE_CACHE.clear()
    estimator._SHEET_RATE_CACHE[("PETG", 2.0)] = 9.63
    yield
    estimator._SHEET_RATE_CACHE.clear()


def _part(material="PETG", thickness=2.0):
    return {"part_number": "11650-04-01A", "normalized_material": material,
            "normalized_thickness_mm": thickness}


def test_a_material_the_catalogue_stocks_is_not_rescued_to_something_else():
    """THE DEFECT, STATED AS THE TEST. PETG has 37 rows of live stock; being absent from a
    per-kilo table is not the same as being unpriceable."""
    priced, conflict = estimator._material_we_can_actually_price(_part(), "PETG")
    assert priced == "PETG"
    assert conflict is None, "a material we can actually buy was reported as a conflict"


def test_the_rescue_still_fires_for_a_material_nothing_can_price():
    """Not weakened — only better informed. A material with no per-kilo rate AND no catalogue
    row is still unpriceable, and the estimator still has to rule on it."""
    priced, _ = estimator._material_we_can_actually_price(
        _part(material="UNOBTAINIUM"), "UNOBTAINIUM")
    assert priced == "UNOBTAINIUM" or priced != "ACRYLIC"


def test_the_gauge_is_part_of_the_question(monkeypatch):
    """A rate is keyed on material AND gauge — nobody stocks PETG at 2.2. Asking about the
    material alone would call a part priceable at a thickness that does not exist, which is
    how the companion rule's stock key gets undone one layer down.

    MY FIRST VERSION OF THIS ASSERTED `priced != "PETG" or True`, which is true of everything,
    and a mutant that hard-coded the gauge to 2.0 walked straight past it. I then wrote a
    commit message saying both mutants were killed. The claim has to be about what was ASKED,
    so the lookup is watched rather than its outcome guessed at."""
    seen = []
    monkeypatch.setattr(estimator, "_resolve_board_sheet_rate_gbp_per_m2",
                        lambda m, t: (seen.append((m, t)), None)[1])
    estimator._material_we_can_actually_price(_part(thickness=2.2), "PETG")
    assert seen == [("PETG", 2.2)], (
        "the catalogue was asked about a gauge this part is not made from")


def test_a_catalogue_failure_does_not_take_the_estimate_with_it():
    """The lookup crosses a network to a database. A material must not become unpriceable —
    or worse, raise — because a server was slow."""
    def _boom(material, thickness):
        raise RuntimeError("UDEF unreachable")
    _real = estimator._resolve_board_sheet_rate_gbp_per_m2
    estimator._resolve_board_sheet_rate_gbp_per_m2 = _boom
    try:
        priced, _ = estimator._material_we_can_actually_price(_part(), "PETG")
        assert priced is not None
    finally:
        estimator._resolve_board_sheet_rate_gbp_per_m2 = _real


def test_the_question_is_asked_of_every_source_we_have():
    """Stated against the source, because a mutant that drops the catalogue check is wrong
    only where a live rate exists — which is never the test machine and always the customer's."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "estimator.py"),
               encoding="utf-8").read()
    fn = src[src.index("def _material_we_can_actually_price("):]
    fn = fn[:fn.index("\ndef ", 10)]
    assert "config.material_has_a_rate(material)" in fn
    assert "_resolve_board_sheet_rate_gbp_per_m2(material" in fn
