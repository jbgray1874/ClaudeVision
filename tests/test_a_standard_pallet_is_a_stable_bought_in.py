"""A standard pallet (and its kin) prices from a stable config provisional, not a per-run guess.

Dyson 10575-02 BOM item 6 is "STD PART / PALLET" — the 1200x1000 pallet the display is built on.
It carries no SDI part code, so the purchasing DB has nothing to match, and it reached the web/AI
fallback — a per-run market number that changes every run (the 8352 castor moved £4.54 -> £8.54)
or a £0. A named standard commodity now returns a fixed config provisional BEFORE that guess:
reproducible (so it clears price_not_reproducible), flagged for review, and only on the fallback
path so a real DB catalogue rate still wins.

The component pallet is deliberately distinct from PACKAGING_CONFIG["pallet"] (the per-order
SHIPPING pallet share) — this is a BOM component the unit is assembled onto.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import config  # noqa: E402
import pricing_service  # noqa: E402


def _svc():
    # Construct without __init__ so no DB connection is attempted.
    return pricing_service.PricingService.__new__(pricing_service.PricingService)


def test_a_pallet_line_prices_from_the_config_provisional():
    out = _svc()._standard_commodity_price({"description": "PALLET", "part_number": "STD PART"})
    assert out is not None
    assert out["unit_price_gbp"] == 12.0
    assert out["source_type"] == "standard_commodity_provisional"


def test_the_provisional_is_reproducible_so_it_does_not_block():
    """The whole point over the market guess: the same number every run, which clears the
    price_not_reproducible invariant while still pricing the line."""
    out = _svc()._standard_commodity_price({"description": "PALLET 1200 x 1000"})
    assert out["price_is_reproducible"] is True
    assert out["review_flag"] is True            # reproducible is not firm — still flagged


def test_a_non_commodity_is_untouched():
    """A real fixing must fall through to the existing DB/market path, not be captured here."""
    assert _svc()._standard_commodity_price(
        {"description": "M6x10mm C/SUNK BOLT", "part_number": "FIXING6"}) is None


def test_an_empty_description_is_safe():
    assert _svc()._standard_commodity_price({"description": None, "part_number": None}) is None


def test_the_config_carries_the_pallet_and_documents_the_distinction():
    table = config.STANDARD_COMMODITY_PRICE_GBP
    assert "PALLET" in table and table["PALLET"]["price_gbp"] > 0
    # the component pallet is a separate figure from the shipping-pallet share
    assert config.PACKAGING_CONFIG["pallet"]["price_gbp"] != table["PALLET"]["price_gbp"]
