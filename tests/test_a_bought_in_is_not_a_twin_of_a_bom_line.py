"""A bought-in the BOM already carries is not re-minted as a BI- twin.

8352 listed the Tente castor on the BOM as part number 'TENTE LINEA CASTOR 5925UAP050L51_10'
with the description 'Black'. The prose recogniser read 'Tente Linea Castor' from the drawing
notes and minted BI-TENTELINEACASTOR — a second copy of a part already on the sheet — which the
canonical route then flagged as a disconnected node with no owner. It happened because the dedup
overlapped DESCRIPTIONS (here 'Black' — no overlap) and matched part numbers EXACTLY
(BI-TENTELINEACASTOR is not the castor's number), and never overlapped the phrase against the
part NUMBER, where the castor's identity actually lives.

The identity check now reads a part's whole identity — description AND part number. A worded PN
dedups a worded phrase; a numeric code cannot false-match one.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import bought_in_recogniser as bir  # noqa: E402


def test_a_phrase_in_the_part_number_is_recognised_as_already_present():
    """THE CASTOR. The identity is in the code, not the description."""
    assert bir._phrase_already_in_bom(
        "Tente Linea Castor", ["TENTE LINEA CASTOR 5925UAP050L51_10"]) is True


def test_the_old_description_only_check_would_have_missed_it():
    """The castor's description is 'Black'. Overlapping only descriptions is why the twin was
    minted — proven here so the regression cannot quietly return."""
    assert bir._phrase_already_in_bom("Tente Linea Castor", ["Black"]) is False


def test_a_numeric_part_number_does_not_false_match_a_worded_phrase():
    """'8352-01-08' carries no descriptive tokens, so it cannot swallow 'Foot Plate' — the guard
    only fires when the identity genuinely names the same thing."""
    assert bir._phrase_already_in_bom("Foot Plate", ["8352-01-08"]) is False


def test_an_unrelated_part_is_not_deduped():
    assert bir._phrase_already_in_bom("Self Tapping Screw", ["8352-01-05 SHELF"]) is False


def test_a_worded_part_number_dedups_its_phrase():
    """A foot plate whose code spells it out IS caught — the general case the castor is one of."""
    assert bir._phrase_already_in_bom("Foot Plate", ["8352-FOOT-PLATE-08"]) is True


def test_an_empty_phrase_is_not_a_match():
    assert bir._phrase_already_in_bom("", ["TENTE LINEA CASTOR"]) is False


def test_the_recogniser_uses_the_identity_check():
    """Wired, not merely defined: the dedup in the recogniser loop calls the helper against BOTH
    descriptions and part numbers."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "bought_in_recogniser.py"),
               encoding="utf-8").read()
    assert "_phrase_already_in_bom(desc, list(existing_descriptions) + list(existing_pns))" in src
