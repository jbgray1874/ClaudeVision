"""Dave Wright, 28 Sep 2026, on 12645 DRS External Shelter: "material can be just standard mild
steel – not the 'PLAIN CARBON STEEL' stated on the drawings". SolidWorks' default library steel
resolved to no material at all (D-309)."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import json_normaliser as jn  # noqa: E402


def test_the_solidworks_default_steel_is_mild_steel():
    for s in ("PLAIN CARBON STEEL", "Plain Carbon Steel", "Material: Plain Carbon Steel 2mm"):
        assert jn.normalise_material(s) == "MILD_STEEL", s


def test_other_steels_are_unchanged():
    assert jn.normalise_material("STAINLESS STEEL 304") != "MILD_STEEL"
    assert jn.normalise_material("MILD STEEL") == "MILD_STEEL"
