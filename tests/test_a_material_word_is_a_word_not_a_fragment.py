"""A material word is a word, not a fragment of another (D-600).

The lexicon was matched as a substring: GLASS and BRASS read as stainless ("SS"), CARPET as a
plastic ("PET"), WASHER and SPINE as timber ("ASH", "PINE"), and PETG was renamed acrylic. The
material that was read now survives: a key matches only as a word, the approved run-together
spellings are keys of their own, and PETG keeps its name, priced at acrylic's rate meanwhile with
the grade asked.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import estimator  # noqa: E402
import json_normaliser as jn  # noqa: E402


@pytest.mark.parametrize("text", ["GLASS", "6MM TOUGHENED GLASS", "BRASS", "CARPET", "WASHER",
                                  "SPINE", "13045"])
def test_a_fragment_inside_another_word_is_not_a_material(text):
    assert jn.normalise_material(text) is None


@pytest.mark.parametrize("text, code", [
    ("MRMDF", "MDF"), ("MR MDF", "MDF"), ("18MM MDF", "MDF"), ("18MDF", "MDF"),
    ("2MM MS", "MILD_STEEL"), ("MILDSTEEL", "MILD_STEEL"), ("CR4", "MILD_STEEL"),
    ("Steel, Mild 2mm", "MILD_STEEL"), ("16MM MFC", "MFC"), ("MELAMINE FACED MDF", "MFMDF"),
    ("304 STAINLESS", "STAINLESS_STEEL"), ("FSC PINE", "TIMBER"), ("ASH", "TIMBER"),
    ("OAK VENEER MDF", "OAK_VENEER_MDF"), ("BIRCH PLY", "BIRCH_PLYWOOD"),
])
def test_the_approved_spellings_still_read(text, code):
    assert jn.normalise_material(text) == code


def test_petg_keeps_its_name():
    assert jn.normalise_material("2MM PETG") == "PETG"
    assert jn.normalise_material("PET") == "PET"


def test_a_petg_part_keeps_petg_and_is_never_priced_as_acrylic(monkeypatch):
    """The 22 Sep 2026 decision on 11650: PETG has no invented rate. Kept as PETG, it takes the
    researched rung with its evidence, or stays unpriced and visible; never acrylic's rate."""
    monkeypatch.setattr(estimator, "_researched_board_rate_m2", lambda *a, **k: None)
    part = {"part_number": "P1", "description": "SIDE PANEL", "quantity": 1,
            "normalized_material": "PETG", "normalized_thickness_mm": 2.0,
            "blank_length_mm": 1250.0, "blank_width_mm": 525.0,
            "blank_length_mm_source": "dxf_flat_pattern", "blank_width_mm_source": "dxf_flat_pattern"}
    got = estimator.estimate_material(part)
    assert got["material"] == "PETG", "the part keeps the material that was read"
    assert not got.get("unit_material_cost_gbp"), "no evidence, no figure"
    assert "acrylic" not in str(got.get("cost_method") or "").lower()
