"""A tube is not folded — folding is a flat-sheet operation.

7332-01's square-tube leg carried a folding charge. A tube is bent on a tube bender (its own op)
or cut and welded, never put through a press brake. Cutting stays valid (a tube is sawn /
laser-tube-cut), and punching a wall stays impossible, as before.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import stock_form_rules as sfr  # noqa: E402


def test_fold_is_impossible_on_a_tube():
    assert sfr.impossibility_reason("fold", "tube") is not None
    assert sfr.impossibility_reason("folding", "tube") is not None
    assert sfr.impossibility_reason("linebend", "tube") is not None


def test_cutting_a_tube_is_still_allowed():
    # a tube is sawn / laser-tube-cut — cutting must NOT be ruled impossible
    assert sfr.impossibility_reason("laser_cutting", "tube") is None
    assert sfr.impossibility_reason("saw", "tube") is None
    assert sfr.impossibility_reason("tube_cut", "tube") is None


def test_punch_stays_impossible_and_tubebend_is_fine():
    assert sfr.impossibility_reason("punch", "tube") is not None
    assert sfr.impossibility_reason("tubebend", "tube") is None
    assert sfr.impossibility_reason("drill", "tube") is None
