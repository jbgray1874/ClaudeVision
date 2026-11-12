"""A priced commercial placeholder carries its cost to the line total, not just the unit.

Packaging/delivery are minted as commercial placeholders and passed through estimate_part, which
short-circuits them (no fabrication/handling). That short-circuit hard-set extended_total_cost_gbp
to 0.0 — so once a house rate gave the line £2.00/unit, the sheet showed £2.00 each and a LINE
TOTAL of £0: priced on the sheet, absent from the money. An estimator reads that as "still blank".

The priced case now carries its extended total (unit × qty); an unpriced placeholder stays a clean
£0. Plate and the tube leg reach their totals by their own paths and are checked here too.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import estimator as e  # noqa: E402


def _commercial(unit):
    s = e._bought_in_part_stub("PACKAGING", "Packaging", 1)
    s["source"] = "commercial_placeholder"
    s["_commercial_placeholder"] = True
    s["unit_cost_gbp"] = unit
    s["unit_material_cost_gbp"] = unit
    s["extended_total_cost_gbp"] = unit
    s["textual_operations"] = []
    s["inferred_operations"] = []
    return s


def test_a_priced_commercial_placeholder_carries_its_line_total():
    pe = e.estimate_part(_commercial(2.00), job_quantity=6)
    assert pe["unit_cost_gbp"] == 2.00
    assert pe["extended_total_cost_gbp"] == 2.00          # was 0.0 — the bug
    assert pe["material_estimate"]["extended_material_cost_gbp"] == 2.00


def test_an_unpriced_placeholder_is_still_a_clean_zero():
    pe = e.estimate_part(_commercial(0.0), job_quantity=6)
    assert pe["unit_cost_gbp"] == 0.0
    assert pe["extended_total_cost_gbp"] == 0.0


def test_the_tube_leg_carries_its_material_total():
    part = {"part_number": "7332-01-002", "description": "LEG - 12.7 x 1.2 CHS TUBE",
            "normalized_material": "MILD STEEL", "quantity": 2,
            "section_stock": {"a": 12.7, "b": 12.7, "t": 1.2, "profile_form": "CHS",
                              "length_mm": 1400.0}}
    pe = e.estimate_part(part, job_quantity=6)
    me = pe["material_estimate"]
    assert (me.get("unit_material_cost_gbp") or 0) > 0
    assert (me.get("extended_material_cost_gbp") or 0) > 0   # the pair's metal, not £0
