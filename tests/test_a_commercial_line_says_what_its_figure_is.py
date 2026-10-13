"""A packaging or delivery row says what its figure is (D-424).

Tim Wilkes, 12173-02, 9 Oct 2026: "It is adding a small packaging/delivery cost when it says
estimator to cost." The 4 Oct book carried £85 packaging and £65 delivery at one off — AI market
figures — on rows still worded "estimator to price": a figure, and a disclaimer that nobody had
priced it, on one line. £0 keeps the words; a market figure is named as one; a house rate says so.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

from estimator import commercial_line_wording  # noqa: E402

PACK = "Packaging (box / pallet — per-unit share, estimator to price)"
DELIV = "Delivery (per-unit share of order haulage — estimator to price)"


def test_a_market_figure_is_named_as_one():
    said = commercial_line_wording(PACK, 85.0, False)
    assert "estimator to price" not in said
    assert "AI market figure" in said and "confirm" in said


def test_a_zero_line_still_asks_to_be_priced():
    assert commercial_line_wording(DELIV, 0.0, False) == DELIV


def test_a_house_rate_says_it_is_one():
    said = commercial_line_wording(DELIV, 9.5, True)
    assert "house rate" in said and "estimator to price" not in said


def test_a_label_without_the_words_is_annotated_not_lost():
    assert commercial_line_wording("Delivery", 12.0, False) == \
        "Delivery (AI market figure — estimator to confirm)"


def test_the_minting_code_uses_it():
    src = (ROOT / "src" / "estimator.py").read_text(encoding="utf-8")
    assert "commercial_line_wording(\n                    _desc, float(_unit or 0.0), _from_hold)" in src
