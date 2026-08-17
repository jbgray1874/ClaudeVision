"""A drawing-named powder is priced from the engine's coated mass, not withheld at £0.

8352 names its powder on the BOM as POWDER197. The engine already computes the coated mass
(coated area x POWDER_KG_PER_M2) and holds a reproducible rate (config.POWDER_COST_PER_KG =
9.73 £/kg), so qty x rate is fully derivable — the exact shape of the board £/kg fix. Yet the
line shipped at £0, "price WITHHELD (quantity not on the drawing)". The cause: a NAMED powder is
read straight off the BOM and never passes through the generic-row branch that stamps
_catalogue_rate_gbp, so it reached the consumable pricer rate-less; the pricer needs a rate to
fire, found none, and withheld — while the kilos sat unused in the calculator.

Now a powder consumable line resolves its rate from config when it carries none of its own
(_powder_consumable_rate), so a named powder is priced exactly like the generic one: qty = the
engine's coated mass, price = the SDI £/kg. Keyed on the powder class (the word POWDER), not on
'POWDER197' or any code, so every powder job inherits it. A non-powder consumable gets nothing
here, and a powder with no rate available stays an honest gap (None), never a guess.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import wb_populate as wb  # noqa: E402
import config  # noqa: E402


def test_a_named_powder_with_no_rate_inherits_the_config_rate():
    """THE 8352 CASE. POWDER197 carries no rate of its own -> the SDI £/kg, not £0."""
    rate = wb._powder_consumable_rate({"part_number": "POWDER197",
                                       "description": "POWDER197"}, config.POWDER_COST_PER_KG)
    assert rate == config.POWDER_COST_PER_KG
    assert rate and rate > 0


def test_the_generic_powder_row_keeps_its_own_stamped_rate():
    """The engine's generic 'POWDER' row already stamps _catalogue_rate_gbp; that own rate is
    used unchanged — the fallback only fills a gap, never overrides."""
    assert wb._powder_consumable_rate(
        {"part_number": "POWDER", "_catalogue_rate_gbp": 11.0}, 9.73) == 11.0


def test_a_line_own_rate_beats_the_config_fallback():
    assert wb._powder_consumable_rate(
        {"part_number": "POWDER197", "_catalogue_rate_gbp": 12.5}, 9.73) == 12.5


def test_a_non_powder_consumable_gets_no_powder_rate():
    """A sealant or adhesive with an unknown quantity must NOT be handed the powder rate —
    the fallback is powder-only, keyed on the word, so it cannot leak onto other consumables."""
    assert wb._powder_consumable_rate(
        {"part_number": "SEALANT", "_consumable_qty_unknown": True}, 9.73) is None


def test_a_powder_with_no_rate_available_is_an_honest_gap():
    """No config rate to fall back to -> None, so the line stays withheld rather than priced
    from a guessed number."""
    assert wb._powder_consumable_rate({"part_number": "POWDER197"}, None) is None
    assert wb._powder_consumable_rate({"part_number": "POWDER197"}, 0) is None


def test_a_powder_named_only_in_the_description_is_recognised():
    """Some packs put the word in the description, not the code — still a powder line."""
    assert wb._is_powder_consumable({"part_number": "X", "description": "Powder coat"}) is True
    assert wb._powder_consumable_rate(
        {"part_number": "X", "description": "Powder coat consumable"}, 9.73) == 9.73


def test_the_powder_classifier_does_not_match_unrelated_lines():
    assert wb._is_powder_consumable({"part_number": "POWDER197"}) is True
    assert wb._is_powder_consumable({"part_number": "8352-01-09", "description": "HOOK"}) is False
    assert wb._is_powder_consumable({}) is False


def test_the_config_rate_is_reproducible_by_construction():
    """The whole point: the price is a config constant x an engine-derived mass, so it repeats
    every run — this is why a named powder can enter the total without tripping
    price_not_reproducible, where an AI market figure could not."""
    assert isinstance(config.POWDER_COST_PER_KG, (int, float))
    assert config.POWDER_COST_PER_KG > 0


def test_the_consumable_branch_resolves_the_rate_before_pricing():
    """Wired, not merely defined: the pricing branch calls the resolver and the powder
    classifier, so a named powder reaches the qty=kg x rate path instead of the withhold path."""
    src = open(os.path.join(os.path.dirname(__file__), "..", "src", "wb_populate.py"),
               encoding="utf-8").read()
    assert "_cat_rate = _powder_consumable_rate(pe, _POWDER_COST_PER_KG)" in src
    assert "_is_consumable_line = bool(pe.get(\"_consumable_qty_unknown\")) or \\\n" \
           "                                  _is_powder_consumable(pe)" in src
