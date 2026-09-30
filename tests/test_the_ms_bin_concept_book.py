"""M&S clothing-bin concept run (PNG render), 30 Sep 2026 09:38, engine 60a7421.

D-352  18 mm MFMDF noted "GBP 14.00 a square metre, researched" and charged GBP 105.63 a
       2800 x 2070 sheet: the MDF per-kg config rate (1.35 x 750 kg/m3), GBP 18.22 a m2.
D-353  "CNC Joinery … each: CPT01 7/hr …" on a row charging the department's 12/hr.
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("SDI_OFFLINE", "1")

import estimator as E  # noqa: E402


def test_the_researched_rate_prices_the_whole_sheet():
    # CPT01 header panel 620 x 380: 0.2356 m2 x GBP 14.00 = GBP 3.2984
    se = {"candidate_sheet_size_mm": [2800, 2070], "parts_per_sheet": 20}
    t = E._researched_sheet_terms({"price_gbp": 3.2984}, 0.2356, se)
    assert t["researched_rate_gbp_per_m2"] == 14.0
    assert t["sheet_price_gbp"] == round(14.0 * 2.8 * 2.07, 2) == 81.14
    assert t["parts_per_sheet"] == 20


def test_unreadable_terms_leave_the_old_path():
    assert E._researched_sheet_terms({"price_gbp": 3.3}, 0, {}) == {}
    assert E._researched_sheet_terms({}, 0.2, {"candidate_sheet_size_mm": [2800, 2070]}) == {}


def test_both_researched_board_branches_carry_the_sheet_terms():
    src = open(os.path.join(ROOT, "src", "estimator.py"), encoding="utf-8").read()
    assert src.count("**_researched_sheet_terms(") == 2


def test_a_grouped_row_says_which_rate_it_charges():
    src = open(os.path.join(ROOT, "src", "wb_populate.py"), encoding="utf-8").read()
    assert '(engine estimate; "' in src and 'f"charged at {throughput:g}/hr)"' in src
