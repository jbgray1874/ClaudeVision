"""A material priced by the SHEET is not reported as having no rate.

Dyson 10575-02-009 is DIBOND, which prices off config.BOARD_SHEET_PRICE_GBP (per full sheet). But
material_has_a_rate only checked MATERIAL_PRICE_GBP_PER_KG and the plastic set — not the board
table — so the Dyson sheet showed a real Dibond price AND a BLOCKING 'material_has_no_rate' at the
same time. The two messages fought each other and read as a broken estimate.

material_has_a_rate now also consults BOARD_SHEET_PRICE_GBP (which fixes MFC/chipboard too — they
had the same gap), so a board material the engine CAN price by sheet is no longer flagged as one
it cannot price. A material with no rate anywhere is still, correctly, reported.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import config  # noqa: E402


def test_dibond_has_a_rate():
    assert config.material_has_a_rate("DIBOND") is True
    assert config.material_has_a_rate("DIBOND 3.0MM") is True   # a gauge on the name still resolves
    assert config.material_has_a_rate("ALUPANEL") is True


def test_the_other_board_families_priced_by_sheet_also_resolve():
    assert config.material_has_a_rate("MFC") is True
    assert config.material_has_a_rate("CHIPBOARD") is True


def test_steel_and_priced_plastics_still_resolve():
    assert config.material_has_a_rate("MILD STEEL") is True
    assert config.material_has_a_rate("ACRYLIC") is True


def test_a_material_with_no_rate_anywhere_is_still_reported():
    assert config.material_has_a_rate("ABS") is False          # recognised, deliberately unpriced
    assert config.material_has_a_rate("FLUBBERGLASS") is False
    assert config.material_has_a_rate("") is False
