"""A labour row with a stated time charges every member's time, each times its pieces (D-428).

Tim Wilkes on 12173-02 Card Spinner, 9 Oct 2026: weld and dress "very low". The Weld (CO2) row
grouped 12173-05-01M x4, 12173-05-101 x4 and 12173-06-201 x7 — fifteen pieces a spinner — and
the stated-time branch read the FIRST member's 6 minutes as the whole row's: 15 pieces at
150/hr, six minutes for fifteen welded pieces. The grouping had already summed them (1.355 h).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import wb_populate as wp                                              # noqa: E402


def _group(once=False):
    return {
        "wb_op": "Weld (CO2)", "qty": 15.0, "engine_ops": ["welding"],
        "parts": ["12173-05-01M", "12173-05-101", "12173-06-201"],
        "run_hours_per_unit": 0.0638 * 4 + 0.1 * 4 + 0.1 * 7,
        "hours_by_part": {"12173-05-01M": {"bh": 0.11, "qty_per_unit": 4.0},
                          "12173-05-101": {"bh": 0.15, "qty_per_unit": 4.0},
                          "12173-06-201": {"bh": 0.15, "qty_per_unit": 7.0}},
        "stated_once_per_finished_unit": once,
    }


def _records(claimed=("12173-05-01M", "12173-05-101", "12173-06-201")):
    hours = {"12173-05-01M": {"welding": 0.0638}, "12173-05-101": {"welding": 0.1},
             "12173-06-201": {"welding": 0.1}}
    claims = {pn: "the welding department's model" for pn in claimed}
    ops = {pn: {"welding", "dress_welds"} for pn in claimed}
    return claims, hours, ops


def test_the_row_charges_every_member_times_its_pieces():
    claims, hours, ops = _records()
    h, who = wp.stated_row_hours(_group(), claims, hours, ops)
    assert abs(h - 1.3552) < 1e-3, h
    assert set(who) == {"12173-05-01M", "12173-05-101", "12173-06-201"}
    assert 15 / h < 12, "fifteen welded pieces cannot run at 150 an hour"


def test_an_unclaimed_member_keeps_its_computed_share():
    """Only 06-201 is stated; 05-01M and 05-101 still weld, and their time stays on the row."""
    claims, hours, ops = _records(claimed=("12173-06-201",))
    h, who = wp.stated_row_hours(_group(), claims, hours, ops)
    assert who == ["12173-06-201"]
    assert abs(h - 1.3552) < 1e-3, h


def test_a_member_stated_under_the_departments_other_name_adds_its_pieces():
    """Its hours are filed under the department's other name, so the grouping summed nothing
    for it; the stated figure is added, times its pieces."""
    g = _group()
    g["engine_ops"] = ["assembly"]
    g["run_hours_per_unit"] = 0.0
    hours = {"12173-06-201": {"handling": 0.05}}
    claims = {"12173-06-201": "stated"}
    ops = {"12173-06-201": {"assembly", "handling"}}
    h, who = wp.stated_row_hours(g, claims, hours, ops)
    assert who == ["12173-06-201"] and abs(h - 0.05 * 7) < 1e-9, h


def test_no_claim_leaves_the_row_to_the_chain():
    _, hours, _ = _records()
    assert wp.stated_row_hours(_group(), {}, hours, {}) == (0.0, [])


def test_a_time_stated_once_per_finished_unit_is_booked_once():
    claims, hours, ops = _records()
    h, _ = wp.stated_row_hours(_group(once=True), claims, hours, ops)
    assert abs(h - 0.1) < 1e-9, h
