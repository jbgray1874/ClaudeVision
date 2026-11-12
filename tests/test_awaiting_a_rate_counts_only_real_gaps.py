""""Awaiting your rate" counts only lines a person actually owns, not correctly-nil ones.

The Provenance footer said "5 awaiting your rate" on 7332-01 while the honest gap list is two
(PACKAGING, DELIVERY). It counted every row whose material-price field read UNKNOWN — which
swept in the nest pointers (a fabricated leaf costed in the Sheet Steel block), the assembly
parent (£0, its material is its children's) and any duplicate. Those are correctly nil, owned by
NOBODY. The count now uses the same canonical classifier the row already carries: a positive
price is priced; a blank is pending only when an estimator or the engine owns it.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import estimation_report as er  # noqa: E402
import price_provenance as pp  # noqa: E402


def _row(unit=0.0, owner_category=None):
    r = {"unit_cost": unit, "extended_cost": unit, "fields": []}
    if owner_category is not None:
        r["unpriced_reason"] = pp.unpriced_reason(owner_category)
    return r


def test_a_correctly_nil_pointer_or_assembly_is_not_awaiting_a_rate():
    rows = [
        _row(unit=7.65),                              # priced nest line
        _row(unit=0.0, owner_category=pp.NOT_APPLICABLE),   # nest pointer / assembly £0
        _row(unit=0.0, owner_category=pp.NOT_APPLICABLE),   # duplicate
        _row(unit=0.0, owner_category=pp.NO_PRICE_SOURCE),  # PACKAGING — estimator owns it
        _row(unit=0.0, owner_category=pp.ORDER_LEVEL),      # DELIVERY — estimator owns it
    ]
    out = er.reading_and_pricing_counts(rows)
    assert out["pending"] == 2      # only the two real gaps, not the three nil rows
    assert out["priced"] == 1


def test_an_indicative_priced_line_counts_as_priced_not_awaiting():
    # the felt pad / plate line now carry an INDICATIVE figure — a rate to verify, not awaited
    out = er.reading_and_pricing_counts([_row(unit=0.20), _row(unit=20.0)])
    assert out["pending"] == 0 and out["priced"] == 2


def test_an_engine_gap_still_counts():
    # a measured blank with no rate in the engine is a real gap (undercharging) — still pending
    out = er.reading_and_pricing_counts([_row(unit=0.0, owner_category=pp.NO_VOCABULARY)])
    assert out["pending"] == 1
